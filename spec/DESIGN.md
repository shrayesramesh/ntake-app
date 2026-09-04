# Family Calendar + Work Items — Design

> Clean, reconciled technical design (supersedes the earlier DESIGN.md and the
> research notes it draws from). Describes **how** the system is built.
> References requirement IDs from REQUIREMENTS.md. Implementation phasing is in
> PLAN.md; the deferred SMS/text channel is in DESIGN-sms-deferred.md.

---

## 1. Architecture & hosting

**Launch topology: a single always-on home PC (Pop!_OS), reached privately over
Tailscale, running a local assistant model on its GPU. PWA-first. No public
webhook.**

```
   Family phones (PWA)          Wall display (PWA kiosk, e.g. iPad)
          │                            │
          └────────────┬───────────────┘
                       │  HTTPS over Tailscale (private mesh; no public exposure)
                       ▼
        ┌─────────────────────────────────────────┐
        │            Home PC (always on)            │
        │  • PWA serving (HTMX + light JS)          │
        │  • Backend API (FastAPI)                  │
        │  • Database (SQLite)                      │
        │  • Local assistant model (GPU)            │
        └─────────────────────────────────────────┘
```

**Stack:** FastAPI (Python) backend · SQLite via SQLAlchemy 2.0 (+ Alembic) ·
HTMX + light JS frontend · Server-Sent Events for live updates · local
GPU-hosted model for the assistant. Rationale: keeps all TDD-heavy logic in
Python, co-locates the model, minimal frontend for a read-mostly display, clean
JSON/SSE API underneath so a richer TS/React view is a later view-swap if ever
needed.

**Reachability (satisfies NFR-PRIVACY):** family devices join the owner's
Tailscale tailnet; `tailscale serve` fronts the local app with an auto-renewing
Let's Encrypt cert for `<machine>.<tailnet>.ts.net` (HTTPS is required for the
PWA service worker). No port-forwarding, no public endpoint. Every device runs
Tailscale. *(Setup + the CT-ledger naming caveat: see research/Tailscale notes.)*

**Availability (NFR-UPTIME):** launch availability = the home PC's uptime
(accepted). A future two-tier split — a cheap always-on box for the API/DB/PWA +
the GPU PC as an on-demand parse tier with a rules fallback — is documented but
**not built**.

---

## 2. Identity & authentication (ACCESS, SAFE)

Two independent layers:

1. **Transport = Tailscale (the perimeter).** Only tailnet devices can reach the
   API at all.
2. **Identity = per-device credentialed token.** Each device is enrolled by an
   admin and given a long random token; the server stores only its **hash** and
   maps it → member → role. Every request carries the token. Tailscale is the
   perimeter; the token's job is **intra-family identity/role** (adult vs. child,
   attribution), not gatekeeping — but it is a real secret so one member can't
   impersonate another.

- **Enrollment (v1: config + CLI, no admin UI).** Members are defined in an
  out-of-repo config (`family.toml`; default `~/.config/ntake/family.toml`, env
  `NTAKE_CONFIG`) and seeded into the DB on startup (idempotent upsert). Device
  tokens are minted by an operator CLI — `python -m app.manage gen-token
  "<member>" --label "<device>"` — which generates a random token, stores only
  `hash(token)` (HMAC-SHA256 over `NTAKE_TOKEN_SECRET`), and prints the plaintext
  **once** for delivery to the device (QR / tailnet link / copy-paste, operator's
  choice). `list-tokens` / `revoke <id>` manage them. *(This replaces the
  originally-designed in-app admin enrollment + first-admin bootstrap flow;
  chosen for simplicity given the single-household trust model. An admin UI /
  bootstrap remains a possible future addition. See PLAN Phase 2.)*
- **Display** is a low-privilege (`child`-role) member with its own token (same
  CLI). Re-enroll on reset/replace = `revoke` old + `gen-token` new.
- **Config holds no secrets.** The hand-edited `family.toml` carries household +
  members only; token hashes live in the DB, plaintext is never persisted. The
  real config + `NTAKE_TOKEN_SECRET` stay off the (public) repo.

---

## 3. Data model (SQLAlchemy 2.0, minimal)

Typed `Mapped[...]`. Timestamps stored **UTC**; `families.timezone` required
day-one (NFR-TIME). Representation: SQLAlchemy ORM classes for persistence +
separate Pydantic DTOs at the API edge (no dataclasses, no SQLModel — the owner
prefers transparent SQL; ORM never hides it, Core/`select()` available for tuned
queries).

### Tables

**`families`** — `id, name, timezone, created_at`. (Also holds the tag→color map,
SETTINGS-1 — see §3.2.)

**`members`** — `id, family_id, display_name, role (adult|child), phone_number
(contact only, not auth), created_at`.

**`device_tokens`** — `id, member_id, token_hash (unique), label, created_at,
revoked_at (NULL = active)`.

**`events`** — deliberately small (EVENT-3):
- `id, family_id, title, description?, location?`
- `all_day` — timing split to avoid the all-day off-by-one bug:
  - timed: `start_at`, `end_at` (UTC datetimes)
  - all-day: `start_date`, `end_date` (plain dates, rendered in family tz)
- `source_update_id?` → `work_item_updates.id` (ON DELETE SET NULL) — the update
  record that drove this event; person/why come via that record (ACCESS-4,
  EVENT-7). NULL for directly-created/imported events.
- `tags` — list of strings, shared vocabulary (EVENT-6)
- `participants` — list of `{member_id?, name}` (EVENT-5): a linked member or a
  free-text name
- `created_at, updated_at`
- **No** uid / sequence / status / recurrence_rule. (`.ics` export synthesizes
  UID/DTSTAMP; recurrence is assistant-from-log, not a column — EVENT-4.)

**`work_items`** — the loose item (WORKITEM):
- `id, family_id, assigned_to?, title, description? (free text)`
- `status` — fixed enum `todo | on_deck | doing | done` (stored as codes; display
  labels Todo / On deck / Doing / Done are UI-layer)
- `position` — order within a `(family_id, status)` column
- `due_at?` — assistant-inferred + confirmed (WORKITEM-8), not human-core
- `tags` — list of strings, same shared vocabulary as events (WORKITEM-9)
- `created_at, updated_at, completed_at?, archived_at?`

**`work_item_updates`** — append-only log, the primary daily object & source of
truth (WORKITEM-2/3):
- `id, work_item_id (ON DELETE CASCADE), author? → members, source (human |
  assistant), body (free text), created_at`
- `author` is always a **member** — the human who **wrote** the note (human
  entries) or **confirmed** the change (assistant entries). The LLM is never an
  author (it isn't a member).
- `source` distinguishes a **human-written note** from a **confirmed
  assistant-driven outcome**. This is why the labor view (§4.2) can credit human
  effort without conflating it with changes the assistant proposed and a human
  merely rubber-stamped. `body` narrates the content either way.
- No further type/metadata — minimal by design.

**`checklist_items`** — `id, work_item_id (CASCADE), text, checked, position`
(WORKITEM-6).

*Indexes:* none day-one — unnecessary at family scale (hundreds–low-thousands of
rows). Add one (e.g. on the calendar range query) via a migration only if a query
ever proves slow.

### 3.1 Integrity notes
- FKs: `family_id` CASCADE; `checklist_items`/`work_item_updates` → work_item
  CASCADE; `assigned_to`/`author`/`source_update_id` → SET NULL (removing a
  member/work item doesn't delete related rows, just unlinks).
- **App-level invariants** (enforced in mutations, not schema): only a `done`
  card may be archived (GROOM-4); exactly one timing pair populated per event
  keyed by `all_day`.
- **Concurrency (last-write-wins):** two devices editing the same row → later
  `updated_at` wins. No locking/CRDT (family scale). *(No `sequence` column —
  `updated_at` suffices; dropped as bloat.)*
- **SQLite:** enable `PRAGMA foreign_keys=ON` per connection; enums/lists via
  SQLAlchemy types (portable to Postgres later).

### 3.1a Persistence & resiliency (NFR-DURABILITY, NFR-UPTIME)

SQLite is a **single file on disk** on the home PC; the FastAPI process opens it
directly (no DB server to run/crash). Failure modes, by severity:

- **Graceful shutdown / reboot / app restart:** nothing lost — committed writes
  are on disk; the app reopens the same file.
- **Sudden power loss mid-write:** use **WAL mode (`journal_mode=WAL`) +
  `synchronous=NORMAL`** — the standard crash-safe home config. An interrupted
  write rolls back cleanly on next open; no corruption. (Realistic worst case on
  power loss = **zero** data loss.)
- **Disk failure / file loss:** the backup is the recovery — see below.

**Backup (v1): weekly, on-machine, consistent snapshot.**
- **Cadence:** weekly (accepted RPO — on file loss, lose ≤ 1 week; fine at family
  scale).
- **Method:** a **consistent SQLite snapshot** via `VACUUM INTO` / the online
  backup API — **not** a raw `cp` (a plain copy of a WAL-mode DB can capture an
  inconsistent state). Safe to run while the app is live.
- **Destination (v1):** another file **on the same disk**. This protects against
  app/logic corruption and accidental deletion of the live DB.
- **⚠ Accepted limitation:** same-disk backup does **NOT** protect against
  **physical disk failure** (live DB + backup die together). This is the one
  residual "total loss" risk, accepted for v1. **Real fix (future, one-line
  destination change):** write the snapshot **off-machine** (second drive / NAS /
  a tailnet destination) — the snapshot mechanism is identical, only the target
  changes.
- **Scheduling:** the backup is the **one periodic job** in the system (a systemd
  timer / cron on the Pop!_OS box). Everything else — assistant, archive,
  grooming — is on-demand, not scheduled.

### 3.2 Tags & color (EVENT-6/WORKITEM-9/DISP-6/SETTINGS-1)
Tags are plain strings on events and work items from one **shared family
vocabulary** (consistent vocab lets "Kid1" mean the same thing on calendar +
board and lets
the assistant reason about it). Color is a **separate render-time concern**: a
small **tag→color map** in family settings; changing a color updates everything
with that tag. Not stored on rows; not a tag-management subsystem.

---

## 4. Data flows

### 4.1 Capture / update → assistant → confirm (ASSIST)

The daily loop, and the most important flow in the product. The assistant runs
**inline, synchronously in the request path** — parsing input **and** proposing,
in one round trip.

#### Two-stage pipeline: focus → propose

Capture is split into **two stages**, each with its own swappable client
(deterministic fakes in v1; local-model implementations on the host, task 7):

```
CaptureRequest {text, timezone, now}          ← raw input from the endpoint
        │
        ▼  [ STAGE 1 — CaptureResolver.focus() ]  app-coupled: DB lookups, entity
        │                         resolution, param grounding. Seam in base.py;
        │                         v1 impl FakeCaptureResolver in fake/resolver.py.
FocusedContext {text, timezone, now,
                resolved_work_item_ids, resolved_event_ids,  ← LINK-resolved ids
                deep_context: str}             ← full records for those ids
        │
        ▼  [ STAGE 2 — AssistantClient.propose() ]  engine-clean: no Session, no
        │                         ORM. Pure reasoning over the focused context.
[ ProposedAction, … ]  executable by construction: real target ids + grounded
                       params (stage 1 already resolved them)
```

- **Stage 1 = `CaptureResolver.focus()`** turns raw text into the *focused world*
  the action will operate on. It runs the two-call *shape*: a LINK step resolves
  which existing entities the note refers to (their **real ids**, validated to the
  family) into `resolved_work_item_ids` / `resolved_event_ids`, then a
  deterministic deep-fetch renders their full records — the target item(s) with
  full update history + linked/participated events — into the `deep_context`
  string stage 2 reasons over. Stage 2 needs the real ids to emit an *executable*
  action; it attaches the target from the resolved ids (`primary_work_item_id` /
  `primary_event_id`). `CaptureResolver` is app-coupled (its `focus()` takes a
  `Session`); the abstract seam lives in `app/assistant/base.py` and the v1
  `FakeCaptureResolver` in `app/assistant/fake/resolver.py`.
- **Stage 2 = `propose()`** reasons over the `FocusedContext` and emits
  `ProposedAction`s. It is **engine-clean** (no `Session`/ORM/app imports) — the
  reusable piece. Because stage 1 resolved the entities/params, every proposal
  fully defines its operation and is confirmable as-is.
- **v1 scope:** stage-1 resolution is **deterministic**, not yet an LLM call —
  `FakeCaptureResolver` uses a model-free LINK (`fake/link.py`, significant-word
  title matching) to resolve ids, then the real `resolve.deep_context`. The
  LLM-backed `OllamaCaptureResolver` (task 7) swaps in a real LINK call (which also
  builds `build_world_view` for its prompt) behind the same seam. The fake's LINK
  is deterministic (title matching), so the fake now resolves existing-item
  targets too — the note-append / set-due-date paths are reachable in v1, not
  dormant.
- Both stages sit behind config-selected seams for TDD: a `FakeAssistant`
  (stage 2) reasons over a hand-built `FocusedContext` with zero DB, and the
  `FakeCaptureResolver` (stage 1) produces focused contexts from seeded rows.
  Both are chosen by `NTAKE_ASSISTANT` via `app/assistant/factory.py`
  (`get_assistant()` / `get_capture_resolver()`); the Ollama implementations
  (task 7) drop into the same seams behind the same switch.

The rest of this section describes the confirm half of the loop.


```
Member enters an event capture or a work-item update (free text) in the PWA
        │
        ▼
[ Authenticate ]  valid device token? ──no──► reject
        │ yes
        ▼
[ Save (existing item only) ]  a capture onto an EXISTING work item appends a
        source=human note to its log immediately (WORKITEM-2). A NEW-item
        capture saves NOTHING — bare text does not auto-create a work item; it
        becomes a create_work_item / create_event proposal to confirm.
        │
        ▼
[ Assistant (local GPU), same request ]  parse + interpret in context (this
        work item's log + the calendar) → recommendation(s):
        blocker / needs-help / partial / propose due-date / calendar-event impact
        │
        ▼
[ Response returns: the saved item + the proposal(s) ]
        │
        ▼
[ PWA renders each proposal as an inline card under the saved item,
  on the AUTHOR'S device only — Confirm / Dismiss each ]
        │
   ├─ Dismiss ─► nothing applied (raw input stays saved). To correct a wrong
   │            proposal, the member writes another update ("actually 4pm") →
   │            a fresh proposal comes back. (Lightweight conversational
   │            refinement via the existing capture loop.)
   │
   └─ Confirm ─► apply the change (set status/due_at, create/update event) AND
                append a work_item_updates entry (source=assistant, author=confirmer)
                narrating the outcome
```

**Behaviors (v1):**
- **Propose-and-confirm (ASSIST-2):** never auto-applies. Calendar mutations
  happen only on explicit Confirm.
- **Inline cards, per proposal:** multiple proposals (e.g. a blocker flag *and* a
  due date) render as separate cards, each independently Confirm/Dismiss.
- **Author's device only:** proposals surface to the person who wrote the update,
  not the shared wall display. The **raw input** still SSE-pushes everywhere
  immediately (§4.3); only the proposal prompt is scoped to the author.
- **Correcting a wrong proposal = Dismiss + restate**, which yields a new
  proposal. **No GUI edit form** — that would break the prose-first model.
- **Structured JSON out** (`{recommendations, proposed_due_at?, proposed_event?}`)
  for reliable handling.
- **No suggestions table:** unconfirmed proposals live only in the request/
  response; **unacted proposals vanish with the session** (accepted — no
  persistence). Only confirmed **outcomes** persist (a log entry + the field
  change).
- **Capture is always a NEW propose-only capture (v1).** It takes only free text
  (no `work_item_id`): bare text saves nothing until the human confirms a
  `create_work_item` / `create_event` proposal. Appending a `source=human` note
  to a *specific* existing item is a separate, explicit action —
  `POST /work-items/{id}/updates` — not the capture path. (Resolving a target
  work item *from the text* is a v2/Ollama focuser capability; see §4.1a.)
- **The assistant describes what it understood.** Each proposal carries, in its
  `llm_rationale`, the model's account of what it focused on / why it proposed
  this (rendered as the card's secondary line). In v1 the fake passes the focused
  context through verbatim (`render_focus`); a real model writes a genuine
  description. The ground-truth "what this will do" line is separate and
  registry-derived (`action_summary`), so a wrong rationale can't misstate the
  action.

**Accepted v1 limitations (deliberate, to ship; clean to refactor later):**
- **Synchronous latency:** the save blocks on the local GPU model (seconds) before
  the response returns with proposals. Accepted for v1. **Future refactor:** save
  the raw input instantly and deliver proposals **asynchronously** over the SSE
  channel — reversible without a data-model change (raw-save and proposal are
  already separable).
- **Calendar correction is Dismiss+restate, not conversational.** **Future
  direction:** in-place **conversational refinement** — correct a proposal by
  telling the assistant what's wrong ("make it 4pm at the downtown office") and it
  re-proposes in the same thread, still writing the calendar only on Confirm.
  Multi-turn refinement is a v2 build; the v1 Dismiss+restate loop is its seed.

### 4.1a Assistant architecture: two stages + a reusable engine

The assistant is built as **two stages behind a reusable, domain-agnostic
engine**, so the machinery (propose → validate → dispatch) is separable from the
ntake-specific actions.

**Two stages (focus → propose).**

```
CaptureRequest {text, timezone, now}
      │  [ STAGE 1 — CaptureResolver.focus() ]  app-coupled: DB lookups, entity
      ▼             resolution, param grounding.  (seam: base.py; v1: fake/resolver.py)
FocusedContext {text, tz, now, work_item_id, item_log,
                calendar_window: [EventSummary]}   ← resolved entities, WITH ids
      │  [ STAGE 2 — AssistantClient.propose() ]  engine-clean: no Session/ORM
      ▼
[ ProposedAction, … ]  executable by construction (real ids + grounded params)
```

- **Stage 1 `CaptureResolver.focus()`** turns raw text into the *focused world*
  the action will operate on — resolving relevant entities *with real ids* and
  grounding params. App-coupled (`focus()` takes a `Session`). `calendar_window`
  is a typed `EventSummary` list carrying ids precisely because stage 2 needs a
  real id to emit an executable action (e.g. `deconflict_events` targeting
  `event_id=8`). **v1:** resolution is deterministic (`FakeCaptureResolver`) — no
  target resolved from text, so `work_item_id` is always `None` (every capture is
  new). The second **LLM** call (stage 1 as a query-planner reading the text to
  decide what to fetch / which item to target) is the `OllamaCaptureResolver`
  (task 7) behind the same seam.
- **Stage 2 `propose()`** reasons over the `FocusedContext` and emits
  `ProposedAction`s. Engine-clean; the reusable piece.

**The two swappable seams + the reusable engine.**

- **Contracts — `app/assistant/base.py`**: the two seams a backend implements —
  `CaptureResolver` (stage 1) and the re-exported `AssistantClient` (stage 2) —
  plus the shared value types. `app/assistant/factory.py` selects a backend per
  the `NTAKE_ASSISTANT` switch: `get_capture_resolver()` (stage 1) and
  `get_assistant()` (stage 2), one switch driving both.
- **Backends (parallel packages):** `app/assistant/fake/` (`FakeCaptureResolver`
  + `FakeAssistant` — dev/tests, deterministic) and `app/assistant/ollama/`
  (`OllamaCaptureResolver` + `OllamaAssistant` — host, task 7). They are mirror
  images swapped by config.
- **Engine — `app/routing/engine.py`** (imports NOTHING app-specific: no
  `app.models`, no `sqlalchemy`, no `fastapi`; enforced by a boundary test):
  `ProposedAction`, `AssistantClient`/`NullAssistant` (the propose contract);
  `ActionRegistry`/`ActionSpec` (register name → `{required, describe, handler,
  needs_target, logs}`; `dispatch(name, params, context)` validates + calls the
  handler; `describe(name, params)` derives the ground-truth `action_summary`);
  `ActionError`, `require_params`, `propose_bounded` (bounded-timeout +
  graceful-degrade). The opaque context is a **bounded type parameter**
  (`ContextT` bound to `ActionContext`, PEP 695 generics): the engine never
  inspects it; each plugin binds its own (`ActionRegistry[NtakeActionContext]`,
  `AssistantClient[FocusedContext]`). No `Any`.
- **Plugin — `app/assistant/`**: registers ntake's actions into an engine
  `ActionRegistry` — a **13-action** v1 set spanning create/modify/status/assign/
  archive/checklist across work-item, event, and no-target actions (e.g.
  `set_due_date`, `create_event`, `complete_work_item`, the status-lifecycle verbs,
  `assign_work_item`, `reschedule_event`, `archive_work_item`, `add_checklist_items`,
  `deconflict_events`, `no_action`; see `spec/ASSISTANT_ACTIONS.md` for the full
  registry + scope tiers). Each handler receives the opaque
  `NtakeActionContext(session, member, target_id, target_type)` and does the ORM
  mutation plus — only when it targets a work item — the `source=assistant`
  update append (WORKITEM-3; conditional per the generalized target). The
  `FakeAssistant`, the per-action `describe` text, and the `CaptureResolver`
  implementations live here.

**Why the split:** the propose-confirm pattern is generic and reusable; the split
keeps the engine extractable into its own package by a directory move (only if a
second consumer appears — package-shape now, not a published package). See PLAN
"reusable propose-confirm engine".

### 4.2 Views over the same data
- **Calendar:** events + due work items in a date range (filter by `family_id` +
  `start_at`; the due-date bridge). Read-mostly; live via SSE. Colored by tag
  (DISP-6).
- **Board (~monthly grooming, GROOM):** fixed 4 columns; prioritize / review
  workload / celebrate + manually archive Done.
- **Labor view (on demand, R-labor / ASSIST-4):** the assistant reads the **raw
  update log by author over time** and surfaces who's carrying/coordinating what
  — recognition & fairness, **not** scoring. Uses `source` to weight
  **human-authored notes** as effort and not conflate them with
  **assistant-driven, human-confirmed** entries. Computed live each time (no
  stored metrics — deliberate, anti-surveillance and anti-bloat).

### 4.3 Live sync — SSE (NFR-SYNC, DISP-2)
- **Always-connected clients** (no offline write queue at launch). A capture
  needs the backend reachable; fine on a home tailnet.
- **Transport: Server-Sent Events.** On any write, the backend publishes a change
  event to an in-process emitter; the SSE endpoint streams it to connected
  clients (server→client only fits the one-directional live-update need; WS would
  be overkill, polling wasteful). `EventSource` auto-reconnects.
- Remaining LLD: event granularity (push changed record vs. "refetch" nudge),
  reconnect replay — decided at build.

---

## 5. Front end (DISP)

One browser-based PWA artifact, serving **two surfaces** with different roles.
Both are read-mostly views over the same data; the backend stays a clean JSON/SSE
API so a richer TS/React view is a later view-swap, not a rewrite. Frontend is
HTMX + light JS.

### 5.1 Phone surface (the everyday interaction)
The primary place capture and updates happen (§4.1).
- **Capture / update:** a free-text input to add an event or append a work-item
  update. On submit, the response returns the saved item **plus** the assistant's
  proposal(s).
- **Suggestion cards:** each proposal renders as an **inline card** beneath the
  saved item — **Confirm / Dismiss**, independently. Calendar-event proposals are
  confirmed as-is or dismissed; correcting one = **restate in a new update**
  (§4.1), not an edit form.
- **Scoping:** proposals appear on the **author's device only**. The raw item
  still live-updates on every device via SSE.
- **Browsing:** read the calendar and the work-item board/threads; append updates;
  simple tap/form actions (tick a checklist item, mark done). No drag-and-drop
  day-one (DISP-4).

### 5.2 Wall display (the shared kiosk)
- Kiosk PWA (manifest + service worker, full-screen), always-on, **single shared
  view**, no per-user login (DISP-3/5).
- Shows **calendar + board side by side**, colored by tag (DISP-6), live via SSE.
- **Read-only in practice** — it does **not** show suggestion cards (those are
  author-scoped, §5.1); it reflects committed state.
- **Hardware:** prototype on the existing iPad (current Safari → PWA renders;
  Guided Access kiosk); upgrade to a larger 24–27" display later (verify
  open-Android + Chrome + Tailscale before buying a smart-calendar device). See
  research/dashboard-hardware.

### 5.3 Shared behavior
- Live-updating via SSE (§4.3); survives sleep/wake for days (DISP-5).
- Tag→color applied at render time from the family settings map (§3.2 / DISP-6).

---

## 6. Calendar interoperability (INTEROP — deferred)

`.ics` export/import to Google/Apple/Outlook is a **later arc**. Because the event
model is minimal, export is a translation function that **synthesizes** the
iCalendar fields (UID, DTSTAMP, VEVENT shape) on the fly. Import maps `.ics` →
events; an imported event may be modeled as its own `work_item_updates` entry
(import-as-action) so it still traces to an update record. **Not** two-way CalDAV
sync.

---

## 7. Deferred / out of scope

- **SMS / text capture channel** — full design parked in
  DESIGN-sms-deferred.md (reintroduces public ingress, stateful confirmation,
  free-text parsing as primary).
- **Two-tier availability split** (§1) — future NFR-UPTIME mitigation.
- **`.ics` interop** (§6), **recurrence** (assistant-from-log evolution),
  **automatic archiving**, **background/scheduled assistant passes**,
  **persisted labor metrics** — all explicitly not built.

---

## 8. Open design questions (LLD, non-blocking)

- Assistant prompt contract (structured JSON) + latency in the request path on
  the local GPU (perf-validate; rules/fast-path fallback available).
- Labor-view output shape (a summary, not scores — R-labor guardrail).
- SSE event granularity + reconnect replay.
- Datastore stays SQLite unless a reason to move to Postgres appears.
- `.ics` timing (OQ-INTEROP-WHEN) and calendar default view (OQ-DISP-VIEW).
