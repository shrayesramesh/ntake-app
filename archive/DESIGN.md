# Family Calendar + Todo Board — Design

> **Status:** Draft, in progress. Split from the original combined DESIGN.md on
> 2026-08-30; requirements moved to [REQUIREMENTS.md](./REQUIREMENTS.md).
>
> This document describes **how** the system is built: architecture, hosting
> topology, providers, data model, data flows, and front-end implementation. It
> **references requirement IDs** (`R-*`, `F-*`, `NFR-*`) from REQUIREMENTS.md
> rather than restating what/for-whom.
>
> **Rule of thumb for what belongs here:** anything that could reasonably change
> during implementation without changing what the product *is*. If a statement
> would change the product itself, it belongs in REQUIREMENTS.md.
>
> **Lower-level design (LLD) research and decisions** made after this HLD settled
> live in **[`research/`](./research/)**, to keep this document stable.

---

## 1. Architecture Overview & Hosting Topology

> **Resolved (launch):** self-hosted on a **single always-on home PC**, reached
> privately over **Tailscale**, with a **local self-hosted parsing model** on the
> same machine (leveraging its GPU). PWA-first (no public webhook needed at
> launch). This satisfies NFR-PRIVACY (nothing leaves owned hardware) and
> NFR-COST (no cloud/LLM fees) and is the simplest thing that ships. See
> "Deferred" below for the planned availability hardening.

### 1.1 Components & stack

**Stack (decided):** **FastAPI (Python)** backend — keeps all TDD-heavy logic
(CRUD, auth, the change-event seam, parse orchestration) in the owner's strong
language and co-locates the local model's Python ecosystem. **SQLite** to start
(§1.5). Frontend is a **light HTMX + minimal-JS** layer over server-rendered
HTML — sufficient for the **read-mostly** display/PWA (F-DISP-05), with HTMX's
built-in SSE handling for live updates. The backend is kept a clean **JSON/SSE
API** underneath the HTML so a richer TS/React view is a later view-swap, not a
rewrite (the escape hatch if board interactivity ever outgrows read-mostly).

- **Backend** — authenticate → parse (if needed) → CRUD → persist → **emit change
  event** → respond.
- **Datastore** — family DB (SQLite to start; engine detail §1.5).
- **Parsing/classification engine** — **local model on the home PC's GPU** (§3),
  used for free-text capture; structured PWA input bypasses it.
- **PWA serving** — HTML/HTMX assets for the shared display (§6) and phone
  capture/management (same artifact); PWA manifest + service worker for kiosk /
  home-screen behavior.
- **Sync path** — SSE; pushes change events to connected clients/display (§5.4,
  satisfies NFR-SYNC / F-DISP-02).

### 1.2 Launch topology — single always-on home PC + Tailscale

```
   Family phones (PWA)          Wall display (PWA, kiosk)
          │                            │
          └────────────┬───────────────┘
                       │  HTTPS over Tailscale (private mesh; no public exposure)
                       ▼
        ┌─────────────────────────────────────────┐
        │        Home PC (always on, for now)       │
        │  • PWA static serving                     │
        │  • Backend API (auth, CRUD, sync)         │
        │  • Database (family data)                 │
        │  • Local LLM parse service (GPU)          │
        └─────────────────────────────────────────┘
```

- **Reachability: Tailscale, not public ingress.** Family devices join the
  owner's tailnet and reach the PC directly. **No port-forwarding, no public
  hostname, no exposed endpoint** — the strongest privacy/security posture and
  the least setup (NFR-EFFORT). Because the launch capture channel is the PWA
  (not an SMS webhook), there is **no third party that needs to POST to us**, so
  private-mesh reachability is sufficient.
- **TLS:** HTTPS (required for the PWA service worker) is provided by
  **`tailscale serve`**, which fronts the local app with an auto-renewing
  Let's Encrypt cert for `<machine>.<tailnet>.ts.net`. See the research note
  §1.6 for the concrete mechanism and caveats.
- **Local model on the same box:** the PC's GPU runs the parse model resident, so
  free-text captures parse fast with no external call.

### 1.3 Accepted launch simplifications & deferred hardening

- **Availability = home-PC uptime (NFR-UPTIME / OQ-AVAIL).** For launch the PC is
  assumed always on. Sleep/reboot/outage takes the system down; accepted at
  family scale to ship. Home internet/power outage downtime is likewise accepted.
- **Deferred: two-tier always-on split.** The known future mitigation is to move
  the *always-on tier* (PWA + backend + DB + Tailscale) onto a **cheap low-power
  box** (Raspberry Pi / N100 mini PC, ~$120–250 one-time, a few $/yr power) and
  keep the **GPU PC as an on-demand parse tier**, woken via Wake-on-LAN /
  suspend-resume, with a **rules-based / small-CPU-model fallback** on the
  always-on tier for when the GPU box is unavailable. This removes the "must
  never sleep the GPU PC" constraint without changing the app architecture — the
  parse engine is already a separable service (§3). **Not built at launch.**
- **Deferred: public ingress for a text channel.** If the SMS/Telegram channel
  (§2) is later added, it needs the provider to reach the backend — via a tunnel
  (e.g. Cloudflare Tunnel) rather than raw home-IP exposure. Out of scope for
  launch since there is no webhook yet.

### 1.4 Identity & authentication — per-device credentialed token (decided)

> Resolves the identity/auth HLD in **G0** and underpins **F-MEMBER**,
> **F-SETUP**, roles (REQUIREMENTS §2), `created_by`/`assigned_to`, and the
> login-free display (F-DISP-03).

**Two independent layers of trust:**

1. **Transport trust — Tailscale (§1.2), the perimeter.** Only devices on the
   owner's tailnet can reach the API at all. This is what actually gates access.
2. **Intra-family identity — per-device credentialed token.** *Which* family
   member (and role) is behind a request, established by a **long, unguessable
   random token** provisioned to each device at enrollment. The server stores
   only a **hash** of the token and maps it → `member` → `role`. Every API call
   carries the token (e.g. bearer header).

**What the token is *for* (and what it is *not*).** On a 2–4 person tailnet,
**Tailscale is the security perimeter** — network membership already gates who
can reach the API at all. The token is therefore **not** the perimeter; its real
job is **intra-family role and attribution**: distinguishing adult from child
(role enforcement), stamping `created_by`/`assigned_to`, and giving the display a
low-privilege identity. Framing it as "the security boundary" would overstate it.

**Why a credential (secret), not a plain claim.** Given that job, the token still
needs to be an unguessable secret rather than a self-asserted `member_id`,
because the one threat network-membership does *not* stop is **one family member
impersonating another inside the tailnet** — e.g. a child editing a client value
to grant themselves adult rights. A hashed random token closes that at near-zero
cost (generate at enrollment, store hashed, compare per request). There is **no
login UI / password** — enrollment *is* authentication.

*Alternative considered (deferred):* since children are a deferred persona, a
launch could skip the credential and use network-trust + self-asserted member,
adding credentials when the child role actually ships. We keep the credential now
because it's cheap and avoids re-opening this later — but the intra-family threat
is its *only* justification, so this is the piece to revisit if it ever adds
friction.

**Enrollment (the sensitive moment; admin-only, satisfies F-MEMBER-02).**

```
Admin (adult) in PWA
   │  create member (name, role)
   ▼
Backend mints a random device token ──► stores hash(token) against the member/device
   │
   ▼
Token delivered onto the device  (QR code / one-time link on the tailnet / copy-paste)
   │
   ▼
Device stores token locally; sends it on every API call
```

- **The display is just another enrolled identity** — a low-privilege "kiosk"
  member/token (read-mostly). This cleanly resolves the F-DISP-03 tension:
  display and phones authenticate by the *same* mechanism, they just hold tokens
  with different roles.
- **Display re-enrollment lifecycle.** The wall tablet is the device most likely
  to be factory-reset, re-imaged, or replaced. Treat this as normal revocation +
  re-enroll: an admin revokes the old kiosk token and issues a new one to the
  fresh device. No special path needed — just called out because it *will*
  happen.
- **Revocation:** losing a device = delete/rotate that device's token record.
  (Only possible because it's a stored credential, not a guessable ID.)
- **Lifetime:** long-lived tokens (no expiry dance — fits family scale); rotate
  on demand.

*Consequence for the data model:* with token-based authorization, the
`members.phone_number` field is **no longer doing security work** at launch (that
allowlist existed for the deferred SMS channel). It drops to a plain contact
field until/unless SMS returns. See §4.3.

> *Research note (not a decision):* `tailscale serve` can inject verified
> `Tailscale-User-*` identity headers, which could serve as the identity layer
> instead of hand-rolled tokens. This does **not** change the decision above —
> it's a surfaced option to evaluate later; see §1.6. If ever adopted, Tailscale
> would supply *identity* and we'd still map identity → role.

### 1.5 Remaining §1 open questions

- [ ] **Datastore engine** — SQLite (simplest, single-file, easy backup — good
      fit for single-host family scale) vs. Postgres (richer, overkill?). Ties to
      NFR-DURABILITY / backup (G4).
- [~] **HTTPS/cert mechanism** — **researched** (§1.6): use `tailscale serve`
      (auto-renewing Let's Encrypt cert). No open decision; just execution.
- [ ] **Token delivery mechanism** at enrollment — QR / one-time tailnet link /
      copy-paste (LLD; the credential model itself is decided).

### 1.6 Research note — Tailscale HTTPS & Serve (setup reference)

> **Research, not a decision.** Findings from Tailscale docs (validated
> Dec 2025 / Jan 2026) to make Phase 1f execution concrete. Nothing here changes
> a resolved decision.

**HTTPS / TLS mechanism.**
- Enable once in the admin console: DNS page → enable **MagicDNS** → **Enable
  HTTPS**. Certs are real **Let's Encrypt** certs for
  `<machine>.<tailnet>.ts.net`.
- **Use `tailscale serve <port>`** to front the local FastAPI app (e.g.
  `tailscale serve 8000` → `https://<machine>.<tailnet>.ts.net` proxies to
  `http://127.0.0.1:8000`). Serve **auto-renews** the cert. Prefer this over the
  manual `tailscale cert` path, which makes the 90-day renewal our problem.

**Privacy caveat — Certificate Transparency ledger.** Enabling HTTPS publishes
the **machine name + tailnet DNS name** to the public CT ledger (no data/access
exposure, but the names are public). Free mitigations: use a **randomized tailnet
name** (e.g. `yak-bebop.ts.net`) and a **non-sensitive machine name** (avoid e.g.
`smith-family-home`).

**Surfaced option (for later evaluation, ties to §1.4).** Serve injects verified
`Tailscale-User-Login` / `Tailscale-User-Name` headers and strips client-supplied
copies (anti-spoof). This could act as the identity layer instead of hand-rolled
tokens. **Safe only if the app listens on localhost only** — otherwise anyone on
the LAN/tailnet could hit it directly and forge the headers. Not adopted; recorded
as a candidate to weigh at Phase 2.

**Account-setup checklist (doable without the host machine):**
1. Create a Tailscale account (personal plan, free; ample for 2–4 devices).
2. Admin console: enable **MagicDNS**, then **Enable HTTPS**.
3. Set a **randomized tailnet name** (avoids identifying info in the CT ledger).
4. Later, on the host + each device: install Tailscale, join the one tailnet,
   give the host a **non-sensitive machine name**, run `tailscale serve <port>`.

---

## 2. Deferred Capture Channel — SMS / Text Bot

> **Deferred; not part of the launch build.** The launch capture + management
> surface is the **PWA** (§6). The full design for a later no-install text
> channel — SMS or a bot like Telegram — lives in
> **[DESIGN-sms-deferred.md](./DESIGN-sms-deferred.md)**, kept separate so this
> document reflects only what is being built.
>
> Adding that channel reintroduces parked complexity — public ingress (§1.3),
> the stateful-conversation model (G6), free-text parsing as the primary path,
> entity resolution (G7), A2P registration, and the phone-number allowlist (which
> is why `members.phone_number` is only a contact field at launch, §4.3).

---

## 3. Parsing / Classification Engine — local model (decided)

> Implements the parsing behind **F-CAP-04** (natural phrasing, relative dates)
> and the classify/resolve steps of the triage flow (§5.1). Motivated by
> **NFR-PRIVACY** and **NFR-COST**.

**Decision:** the parser/classifier runs as a **local, self-hosted model on the
home PC's GPU** (§1), not a cloud LLM API. In the PWA-first launch, structured
input handles most captures, so the model is invoked mainly for **free-text**
entry (and becomes primary again if the deferred text channel §2 ships).

**Why it fits:**
- **Privacy (NFR-PRIVACY)** — messages never leave owned hardware.
- **No per-call cost (NFR-COST)** — unlike a metered cloud LLM API.
- **No external dependency** — no third-party AI service in the request path.
- **Hardware already on hand** — the owner's GPU runs a capable local model well.
- **Sufficient for the task** — triage is constrained (classify
  `{entity, operation}`, extract fields, resolve a target).

**Tradeoffs / consequences:**
- **Availability = home-PC uptime (NFR-UPTIME / OQ-AVAIL).** At launch the PC is
  assumed always on; the deferred two-tier split + fallback (§1.3) is what later
  decouples always-on serving from the GPU.
- **Capability ceiling.** Local models are smaller/less capable than frontier
  cloud models; fine for constrained triage, weaker on very fuzzy free text.
  Worth testing target-resolution quality specifically (§5.1, G7).
- **Keep the model separable.** Treat the parser as a distinct service behind a
  clean interface — this is what makes the future two-tier move (§1.3) and the
  fallback drop-in without touching the rest of the app.

Open questions:
- [ ] **Model & runtime** — which local model / runtime (e.g. an Ollama-served
      instruct model)? Size vs. capability given the available GPU?
- [ ] **Fallback** — rules-based parser (and/or tiny CPU model) for simple
      commands when the GPU parse is unavailable (needed for the §1.3 two-tier
      future; cheap insurance even at launch)?
- [ ] **Structured output** — constrain the model to emit strict JSON
      `{entity, op, fields, target}` for reliable downstream handling?

---

## 4. Data Model

Two core tables (`events`, `todos`), kept **separate** because they have
genuinely different shapes — events are time-*ranges* with recurrence, todos are
tasks with status/assignee/board position. A todo's `due_at` is the bridge that
lets it render on the calendar (F-TODO-05).

### 4.1 `events` — iCalendar-aligned (satisfies R1)

Field names mirror the RFC 5545 `VEVENT` model so events are ICS-compatible for
rendering/export (F-ICS).

| Column | iCalendar field | Notes |
|---|---|---|
| `id` | — | DB primary key |
| `family_id` | — | Scopes to a household |
| `created_by` | — | `members.id` |
| `uid` | `UID` | Stable, globally-unique string; survives export/import, dedupes across systems (distinct from `id`). *Open: who mints it and when — server-side at create.* |
| `title` | `SUMMARY` | |
| `description` | `DESCRIPTION` | |
| `location` | `LOCATION` | |
| `start_at` | `DTSTART` | UTC timestamp (see NFR-TIME / G5) |
| `end_at` | `DTEND` | UTC timestamp |
| `all_day` | (value type) | Date-only vs. date-time |
| `recurrence_rule` | `RRULE` | Nullable; repeating-event grammar (OQ-RECUR) |
| `status` | `STATUS` | confirmed / tentative / cancelled |
| `sequence` | `SEQUENCE` | Revision counter, bumped on edit (sync/updates) |
| `created_at` | `DTSTAMP` | |
| `updated_at` | `LAST-MODIFIED` | |

*Recurrence note (OQ-RECUR):* storing an `RRULE` is easy; **expanding** it into
occurrences and handling single-instance edits (`RECURRENCE-ID` / `EXDATE`) is
the hard part. The calendar view (§6.2) cannot render recurring events until
expansion is designed — these are coupled. Decide how much recurrence a family
needs (weekly chores, birthdays) vs. deferring per-instance exceptions.

### 4.2 `todos` — board cards

**Board model (satisfies F-TODO single-board decision):** a **single family
Kanban board** with a fixed set of columns. No multiple named lists — a card *is*
a task, and a card can hold a checklist. `todos.status` is the Kanban **column**;
`todos.position` orders cards within a column.

| Column | Notes |
|---|---|
| `id`, `family_id`, `created_by` | |
| `assigned_to` | Nullable `members.id` (F-TODO-06) |
| `title`, `notes` | |
| `status` | Kanban column — enum: `todo` / `doing` / `done` *(names TBD, OQ-COLS)* |
| `position` | Ordering of the card within its column (OQ-DISP-SORT) |
| `due_at` | Nullable — **bridge to the calendar** (F-TODO-05); UTC (NFR-TIME) |
| `created_at`, `updated_at`, `completed_at` | |

**`checklist_items`** — sub-items inside a card (how "a task can be a grocery
list" works, F-TODO-04):

| Column | Notes |
|---|---|
| `id`, `todo_id` | Belongs to a `todos` card |
| `text` | e.g. "milk" |
| `checked` | bool |
| `position` | Ordering within the card |

### 4.3 Supporting tables

- **`families`** — the household (`id`, `name`, **`timezone`**). The `timezone`
  is **required day-one**: resolving relative capture like "Tuesday 3pm"
  (F-CAP-04) is impossible without it, and it anchors recurrence/DST (G5). Store
  timestamps in UTC, convert at the edges against this timezone.
- **`members`** — people (`id`, `family_id`, `display_name`, `role`
  [adult/child], `phone_number`).
- **device tokens** — auth is by **per-device credentialed token** (§1.4): store
  a **hash** of each device's token against its member (a `device_tokens` table,
  or equivalent, with `member_id`, `token_hash`, `label`, `created_at`,
  `revoked_at`). This is what authorizes API calls; the display is just a
  low-privilege enrolled token.

*Note on `phone_number` (changed):* it **no longer functions as a security
allowlist** — that role belonged to the deferred SMS channel (§2). Under
token-based auth (§1.4) it is a **plain contact field**. If/when SMS returns, the
allowlist check can be layered back on top of it, but it authorizes nothing at
launch.

*(No `lists` table — see the single-board model, §4.2 / REQUIREMENTS §4.4.)*

### 4.4 `.ics` interoperability — future work arc

> Satisfies **F-ICS**; priority/direction are OQ-ICS-PRIORITY / OQ-ICS-DIRECTION.

Built on the iCalendar-aligned schema:
- **Export first** (high value, easier) — generate a `.ics` file or subscribable
  feed URL so the family calendar appears inside Apple/Google/Outlook.
- **Import** — accept `.ics` files/invites → create events.
- **CalDAV / two-way sync** — only if ever needed; most complex.

---

## 5. Data Flows

### 5.1 Capture → CRUD triage

> The processing behind **F-CAP / F-QRY / F-EVT / F-TODO**. At launch this serves
> the **PWA**: structured input (tap a card, pick a date) supplies most of
> `{entity, op, target}` directly, so parsing/entity-resolution is a *fallback*
> for free-text entry, not the main path. The same triage serves the deferred
> text channel (DESIGN-sms-deferred.md), where free-text parsing is primary.

Every capture resolves to a **CRUD operation on an entity** — two entities × four
operations:

|  | **Event** (`events`, §4.1) | **Todo** (`todos` / `checklist_items`, §4.2) |
|---|---|---|
| **Create** | New calendar event | New card, or append a checklist item to a card |
| **Read** | Query events ("what's on today?") | Query todos ("what's left?") |
| **Update** | Change time/title; move/reschedule | Set/clear due date, move lane, edit title, check/uncheck item |
| **Delete** | Remove/cancel an event | Remove a card or checklist item |

```
Capture (PWA structured input, or free text)
        │
        ▼
[ Authenticate ]  valid device token? ──no──► reject   (F-AUTH; §1.4)
        │ yes
        ▼
[ Resolve intent ] ──► { entity: event|todo, op: C|R|U|D, fields..., target? }
        │   PWA structured input supplies this directly;
        │   free text goes through Parse+Classify (§3)
        ├─ Create ─► insert row (event) / card or checklist item (todo)
        ├─ Read ───► query + format a reply
        ├─ Update ─► resolve target, then apply change
        └─ Delete ─► resolve target, then remove         ⚠ gated (F-SAFE-02)
        │
        ▼
[ Persist ] (syncs to all devices, §5.4)  ─►  confirm (UI / reply)

   (ambiguous free text) ──► clarification   (F-CAP-05)
```

**Two layers (only exercised by free-text capture):**
1. **Classify** — determine `{entity, operation}` (plus fields). Keyword rules or
   the local model (§3).
2. **Resolve target (R/U/D)** — identify *which* existing event/todo the input
   refers to. In the PWA the user **taps** the target, so this is trivial; over
   free text it is the hard **entity-resolution** problem (G7, detailed in
   DESIGN-sms-deferred.md §7).

### 5.2 Destructive-op gating & confirmation

> **F-SAFE-02** destructive-op gating and **F-CAP-05** disambiguation.

**Launch (PWA):** confirmation is a **UI dialog** ("Delete 'dentist'?") and
disambiguation is direct selection — no stateless-channel machinery. Gating is by
**explicit UI confirm + adult role** (OQ-DEL-POLICY).

The stateful pending-operation model (per-sender state, expiry, "reply YES"
handling) is **only** needed for the deferred text channel — it lives with that
design in **DESIGN-sms-deferred.md §6 (G6)**, not here.

### 5.3 Concurrency, idempotency & failure handling

**Concurrent edits (Gap 2 — day-one, PWA).** Two phones editing the same
card/event at once (e.g. two adults reordering the board) is realistic at launch.
**Decision: last-write-wins** at family scale — the later write by `updated_at`
wins, with `events.sequence` (§4.1) bumped on each event edit as a
revision/tiebreak. No locking, no merge/CRDT. Acceptable because the household is
tiny and low-adversarial; the cost is an occasional clobbered field, not data
corruption. (Revisit only if real conflicts prove annoying.)

**Idempotency.** A retried/double-submitted write (flaky network, double-tap)
should not create duplicates — use a client-supplied request/idempotency key on
create. (For the deferred text channel, the provider message ID serves this — see
DESIGN-sms-deferred.md §10.)

**Failure surfacing.** If a write fails, the client must **surface it**, not fail
silently (aligns with F-CAP-05/06). In the always-connected PWA (§5.4) this is a
direct request/response error the UI shows.

### 5.4 Sync to devices / display

> Satisfies **F-DISP-02** and **NFR-SYNC** (G3).

**Decided (HLD): always-connected clients, no offline write queue at launch.**
Clients (phones + display) are thin views over the backend; a capture requires
the backend reachable. On a home tailnet the backend is almost always reachable,
so this is a reasonable simplification and it **avoids** client-side local state,
conflict resolution, and reconciliation. (Concurrent edits are handled
last-write-wins, §5.3. Offline-capable capture via a service-worker queue remains
a possible future enhancement; if added it would need real conflict handling on
`events.sequence` rather than the launch last-write-wins.)

**Transport — decided: Server-Sent Events (SSE).** Live updates are
**server→client only** (server pushes changed entities; writes go over normal
request/response), which is exactly SSE's shape. SSE is chosen over the
alternatives because:
- **WebSocket is bidirectional overkill** — the client never streams data *up*
  (captures are discrete POSTs), so WS's upgrade handshake, keepalive, and
  separate connection model buy nothing here.
- **Polling is strictly worse** for an always-on display — fast polling is
  wasteful and still not truly live; slow polling is stale.
- **Least infrastructure** — SSE is plain HTTP (works over the Tailscale HTTPS
  path with no special handling), and the browser's `EventSource`
  **auto-reconnects** on drop natively, directly serving F-DISP-04 (leak-free,
  survives sleep/wake over days).

*Known SSE constraints — non-issues at family scale, recorded so they aren't
tripped over:* the ~6-connections-per-domain HTTP/1.1 cap (irrelevant for a few
devices; moot under HTTP/2) and text/UTF-8-only payloads (our change events are
JSON). **Escape hatch:** switch to WebSocket only if genuine client→server
streaming ever appears — not foreseen.

Remaining (LLD) choices:
- **Event granularity** — push the changed record (avoids a refetch round-trip,
  the likely choice) vs. a "something changed, refetch" nudge.
- **Reconnect/resume** — `EventSource` reconnects automatically; replay missed
  events via `Last-Event-ID` vs. simple refetch-on-reconnect (the latter is
  simplest and almost certainly enough on a tailnet).
- **Latency target** — OQ-SYNC-LATENCY: **live push** (resolved in direction by
  the SSE choice); exact expectation still informal.

---

## 6. Front End — Shared Display (Dashboard)

> Implements **F-DISP**. Consumption model in REQUIREMENTS §3.2.

### 6.1 Consumption pattern

A **single, browser-based visual display** (e.g. a wall-mounted tablet) — a
**kiosk / dashboard**, not a per-user app. Calendar and todo board visible at
once. Design consequences:

- **Glanceable, read-heavy (F-DISP-01).** Primary job is *displaying* legibly
  from across the room; data entry is secondary (capture is via the PWA on
  phones).
- **Always-on, long-running (F-DISP-04 / NFR-UPTIME).** Must **auto-refresh /
  live-update** (§5.4), survive sleep/wake, stay leak-free over days.
- **Single shared family view (F-DISP-03).** No per-person login; auth once at
  setup (F-SETUP-02 / G0).
- **Fixed, touch-friendly layout.** Tablet-sized, likely landscape, large fonts
  and touch targets. Split: calendar one side, board the other.
- **Browser-based / PWA.** PWA gives full-screen "Add to Home Screen" kiosk
  behavior.

*Future front ends (not now):* phones may later get a more interactive view
(ties to OQ-CAP / G2); the backend/API serves all of them.

### 6.2 Part A — Calendar view

- Renders `events` plus todos with a `due_at` (F-TODO-05) on a familiar calendar
  surface.
- Views: month / week / day / agenda. **Default TBD** (OQ-DISP-VIEW) — agenda or
  week tends to read best at a glance.
- Read-focused; **live-updates** (§5.4).
- Maps cleanly to standard rendering because events are iCalendar-aligned (R1);
  can reuse an existing calendar library.
- **Coupling:** rendering recurring events depends on RRULE expansion (§4.1,
  OQ-RECUR) — the view can't show recurrences until that's designed.

Open questions:
- [ ] **Default view** (OQ-DISP-VIEW) — agenda / week / month?
- [ ] **Time window** — "today + next N days" agenda vs. full month grid?
- [ ] **Library** — existing calendar component (e.g. FullCalendar-style) vs.
      custom?

### 6.3 Part B — Todo board view (iterative)

Renders the **single family Kanban board** (F-TODO): cards (`todos`) in fixed
columns (`todos.status`), ordered by `position`. A card may show its checklist
(`checklist_items`).

- **Interactivity (F-DISP-05 — decided read-mostly):** live-updating views with
  **simple tap/form mutations** (tick a checklist item, move a card via a
  control, add via a form). Slick drag-and-drop is **deferred** (OQ-DISP-INT);
  revisiting it is the main trigger for the TS/React view-swap escape hatch
  (§1.1).
- **Card face (OQ-DISP-CARD):** title only vs. + checklist progress ("2/5") +
  assignee + due date?
- **Completed items (OQ-DISP-DONE):** hide immediately / keep in Done / "done
  today" then archive?
- **Sort within column (OQ-DISP-SORT):** manual `position` / due date / priority?

Plan: sketch a **v1** (simplest useful board) and iterate.

---

## 7. Design Open Questions (index)

Consolidated; requirement-level questions live in REQUIREMENTS §7.

- [x] **§1 Topology** — **RESOLVED (launch):** single always-on home PC +
      Tailscale, local model, PWA-first (no public webhook). Two-tier always-on
      split deferred (§1.3).
- [ ] **§1 Datastore** — engine choice, SQLite vs. Postgres (ties to
      NFR-DURABILITY / G4).
- [~] **§1.6 HTTPS/cert** — **researched** (not a decision): `tailscale serve`
      with auto-renewing Let's Encrypt cert; CT-ledger name caveat + mitigations.
- [x] **§1.4 Identity/auth** — **RESOLVED:** per-device credentialed token
      (hashed, admin-enrolled); Tailscale for transport. G0 identity closed.
      Remaining: token *delivery* mechanism (LLD).
- [ ] **Text channel (deferred)** — see DESIGN-sms-deferred.md; SMS vs. Telegram,
      provider, number type, confirmation, query-at-launch — only when built.
- [ ] **§3 Parsing** — model/runtime given the GPU, fallback, structured output.
- [ ] **§4.1 UID minting.**
- [x] **§4.3 family timezone (G5)** — **RESOLVED day-one:** `families.timezone`
      required at launch (F-CAP-04 dependency); DST/recurrence depth still LLD.
- [ ] **§4.1 / OQ-RECUR** — recurrence depth (and its §6.2 rendering coupling).
- [x] **§5.2 Destructive-op gating (G6)** — **RESOLVED (launch):** PWA UI confirm
      + adult role; stateless "reply YES" model lives only in the deferred text
      channel (DESIGN-sms-deferred.md §6).
- [x] **§5.3 Concurrency (Gap 2)** — **RESOLVED:** last-write-wins
      (`updated_at` / `events.sequence`). Idempotency key + failure surfacing
      remain LLD.
- [x] **§5.4 Sync (G3)** — **RESOLVED:** always-connected clients + **SSE**
      transport (server→client push, auto-reconnect). Remaining: event
      granularity + reconnect-replay (LLD); latency direction is live
      (OQ-SYNC-LATENCY).
- [ ] **Entity resolution (G7)** — parked with the deferred text channel
      (DESIGN-sms-deferred.md §7); PWA structured input avoids it at launch.
- [~] **§6 Display** — interactivity **RESOLVED: read-mostly** (F-DISP-05).
      Remaining LLD: view default, card face, done-handling, sort (OQ-DISP-*).
- [ ] **§4.4 .ics** — export/import priority and direction (OQ-ICS-*).

---

## Change Log

- **2026-08-30** — **Split into Requirements + Design.** This doc is now
  implementation-only; the what/for-whom content moved to REQUIREMENTS.md.
  Reorganized around architecture/topology (§1), the SMS capture arc (§2),
  parsing engine (§3), data model (§4), **data flows (§5)** — pulling the CRUD
  triage, the **stateful confirmation/disambiguation model (§5.2, G6)**,
  **idempotency/failure handling (§5.3)**, and **sync (§5.4, G3)** into explicit
  flows — and the dashboard front end (§6). Added requirement-ID cross-references
  throughout and a design open-questions index (§7). Content prior to the split
  is preserved in git history.
- **2026-08-30** — **Resolved §1 hosting topology and made the capture channel
  PWA-first.** Launch topology = **single always-on home PC + Tailscale + local
  GPU model**, PWA-first with **no public webhook** (§1.2); rewrote §1 with
  components, the private-mesh reachability rationale, and accepted
  simplifications. Documented the **deferred two-tier always-on split** (cheap
  low-power always-on box + on-demand GPU parse tier with Wake-on-LAN and a
  rules-based/small-model fallback) as the future NFR-UPTIME mitigation (§1.3).
  **Demoted the SMS bot to a deferred §2 text channel** (SMS vs. Telegram noted).
  Updated §3 parsing from "leaning" to **decided (local GPU model)**, removed the
  now-resolved reachability wrinkle, and kept the parser separable for the future
  two-tier move + fallback. Updated the §7 index.
- **2026-08-30** — **Resolved the identity/auth HLD (G0):** per-device
  **credentialed token** (long random secret, stored hashed, admin-enrolled),
  with Tailscale providing transport trust — two independent layers (§1.4).
  Chose the credential variant over a self-asserted `member_id` to remove
  in-family impersonation/self-promotion. The display is a low-privilege enrolled
  token (resolves F-DISP-03). Added `device_tokens` to the data model and
  **demoted `members.phone_number` to a plain contact field** (its allowlist role
  belonged to the deferred SMS channel) — §4.3. Resolved the **G3 sync HLD** to
  **always-connected, no offline queue at launch** (§5.4), leaving transport as
  LLD. Updated the §7 index.
- **2026-08-30** — **Review pass: tightened, de-duplicated, and closed remaining
  day-one hooks.** (1) **Extracted the deferred SMS/text channel to
  DESIGN-sms-deferred.md**, leaving a short pointer at §2, so the launch design is
  what a reader sees first; folded the stateful-conversation (G6) and
  entity-resolution (G7) notes into that file. (2) **Reframed auth (§1.4):**
  Tailscale is the perimeter; the device token's real job is **intra-family role
  + attribution**, not gatekeeping — kept as a credential solely to stop
  intra-family impersonation, with the network-trust-only alternative noted.
  Added the **display re-enrollment lifecycle**. (3) **Concurrent edits (§5.3):**
  decided **last-write-wins** (`updated_at`/`sequence`) for the day-one PWA
  multi-editor case. (4) **Timezone (§4.3):** promoted `families.timezone` to a
  **required day-one** field (F-CAP-04 dependency). (5) Reframed §5.1 triage as
  PWA-first (structured input primary; parsing/resolution a free-text fallback).
  De-duplicated the single-board model and two-tier-split narration down to
  pointers. Updated the §7 index.
- **2026-08-30** — **Chose the sync transport: SSE (§5.4).** Server→client push
  fits the one-directional live-update job; picked over WebSocket (bidirectional
  overkill) and polling (wasteful/stale), and it is the least infrastructure over
  the Tailscale HTTPS path with native `EventSource` auto-reconnect. Recorded the
  HTTP/1.1 connection-cap and text-only caveats (non-issues at family scale) and
  a WebSocket escape hatch. Event granularity and reconnect-replay left as LLD.
- **2026-08-30** — **Chose the stack and resolved display interactivity.**
  Frontend interactivity decided **read-mostly** (F-DISP-05; drag-and-drop
  deferred), which settles the stack: **FastAPI (Python) backend + HTMX/light-JS
  frontend + SQLite to start**, local model in Python (§1.1). Backend kept a
  clean JSON/SSE API so a TS/React view is a later view-swap escape hatch, not a
  rewrite. Updated §6.3 and the §7 index.
- **2026-08-30** — **Research (not a decision): Tailscale HTTPS & Serve.** Added
  §1.6 capturing the concrete cert mechanism (`tailscale serve` + auto-renewing
  Let's Encrypt), the Certificate-Transparency name caveat with free mitigations
  (randomized tailnet name, non-sensitive machine name), an account-setup
  checklist doable without the host, and a **surfaced option** — Serve identity
  headers as a possible identity layer — recorded against §1.4 to evaluate at
  Phase 2 **without** changing the resolved device-token decision.

### Pre-split history (from the original combined doc)

- **2026-08-29** — Initial draft: Overview, Users & Personas, Input & Capture
  scaffolding. Open questions seeded.
- **2026-08-29** — Added Alexa integration options; later deferred.
- **2026-08-29** — Pivoted primary capture to an **SMS bot**; added the dedicated
  SMS Bot work arc.
- **2026-08-29** — Added Requirements block (R1–R3) and §5 Data Model.
- **2026-08-29** — Added Front End shared-dashboard section (Part A calendar,
  Part B todo board).
- **2026-08-29** — Decided board model: single family Kanban board; dropped
  `lists`, added `checklist_items`.
- **2026-08-29** — Added Core User Flows; generalized User Flow 1 to full CRUD on
  both entities; added destructive-op safety gating.
- **2026-08-29** — Noted parsing engine leaning toward a local self-hosted model
  with tradeoffs and the webhook↔backend↔local-model reachability wrinkle.
