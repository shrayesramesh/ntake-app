# Family Calendar + Work Items — Implementation Plan

> Phased plan reconciled to the v2 architecture (REQUIREMENTS.md + DESIGN.md).
> Method: **TDD** — write tests first; **`make check`** (lint + types + tests)
> must be clean before any checkpoint is done. Rule: TDD your own code; smoke-test
> the environment you don't own (Tailscale, TLS, browser).

## Current state (already built & passing)

Phases 0–3 and the fake-first Phase 4 are built and green (`make check` → 208
tests pass, ≥95% cov). What exists:
- FastAPI app; `GET /health`, `GET /events`, the work-item/board read + append
  paths, `/capture` (propose-only) and `/actions/confirm`.
- SQLAlchemy 2.0 + SQLite: `Family`, `Event`, `Member`, `device_tokens`,
  `work_items`, `work_item_updates`, `checklist_items`. Pydantic DTOs at the edge.
- Change-event seam → in-process emitter → SSE endpoint (live sync), with a
  real-socket integration test.
- Config-seeded identity (`family.toml`) + token CLI (`python -m app.manage`);
  auth on every request.
- The assistant: reusable engine (`app/routing/`) + ntake plugin
  (`app/assistant/`) with the two swappable seams (`CaptureResolver`,
  `AssistantClient`) and the `fake/` backend. Skinny calendar render + SSE.
- Makefile, setup.sh, pinned requirements, ruff + mypy config.

**Not yet built:** Phase-4 **task 7** (the live Ollama backend — see the Phase 4
status note below) and all of Phase 5. Alembic migration wiring is still deferred
(tests/app use `create_all`).

## Phasing

Vertical slices; each proves the architecture end-to-end and defers LLD to the
phase that forces it.

### Phase 0 — scaffold ✅ (done)
Buildable, tested skeleton; `make check` green.

### Phase 1 — events slice + live sync
- **1a** health endpoint ✅
- **1b** DB + `Family`/`Event` + round-trip test ✅ *(Alembic migration still to
  wire — currently `create_all` in tests)*
- **1c** `GET /events` read path ✅
- **1d** change-event seam (unit): on a write, publish `{entity, id, op}` to an
  in-process emitter. The HLD "writes emit change events" made a tested unit.
- **1e** SSE endpoint (`sse-starlette` server, `httpx-sse` test): write → event
  arrives on the stream.
- **1f** reachability over Tailscale + TLS (manual smoke; human-only). See the
  Tailscale research/shovel-ready notes.

**Exit:** an event added on one device renders live on another over Tailscale.

### Phase 2 — identity, setup & enrollment (ACCESS) ✅ (built)
- `members`, `device_tokens` tables; per-device credentialed token (hashed);
  auth on every request; Tailscale = perimeter.
- ~~First-admin bootstrap; admin enrolls/revokes devices~~ → **DIVERGENCE (v1):**
  no in-app admin UI or bootstrap flow. Identity is **config-seeded** — an
  out-of-repo `family.toml` (default `~/.config/ntake/family.toml`, env
  `NTAKE_CONFIG`) defines household + members and is seeded into the DB on
  startup (keeps the members table populated for the Phase 3 `author` FK). Device
  tokens are minted by a CLI (`python -m app.manage gen-token`), which stores only
  the hash and prints the plaintext once; `revoke`/`list-tokens` manage them. The
  display gets a low-priv (`child`) token. Chosen for simplicity given the
  single-household trust model; an admin UI/bootstrap remains a possible future.
- **Adds `families.timezone` usage**, role gating (adult vs. non-adult).

**Exit:** no request succeeds without a valid token ✅; devices enrolled/revoked
via config + CLI ✅.

### Phase 3 — work items + update log + board (the core product)
- `work_items`, `work_item_updates` (with `source: human|assistant`, `author →
  members`), `checklist_items`; fixed status enum (todo/on_deck/doing/done);
  `tags`; `due_at` nullable.
- CRUD + **append-update** flow (the primary daily interaction); each write emits
  a change event (reuse 1d) → SSE.
- Concurrency: last-write-wins (`updated_at`).
- Board view (grooming): 4 columns; **manual archive** of Done (+ "archive all
  Done"); unarchive. App-invariant: only Done archivable.
- `events.source_update_id` now a real FK → `work_item_updates`.
- Read-mostly HTMX views: calendar (events + due work items, tag-colored) + board;
  simple tap/form actions.

**Exit:** family members add/update work items and events from phones; every
device (incl. wall display) reflects it live.

### Phase 4 — the assistant (inline propose-and-confirm)
- Local GPU model behind a separable interface; **structured JSON out**
  (`{recommendations, proposed_due_at?, proposed_event?}`).
- Inline flow (DESIGN §4.1): save raw input → assistant parses + proposes
  (synchronous, v1) → **inline Confirm/Dismiss cards on the author's device** →
  confirm applies change + appends a `source=assistant` update entry.
- Recommendation types: blocker / needs-help / partial / due-date /
  calendar-event impact. Correct-by-restate (no edit form).
- Timezone-correct relative dates (uses `families.timezone`).

**Exit:** free-text capture/updates yield correct, confirmable suggestions;
calendar mutations only on confirm.

> **Status:** the fake-first v1 is built as a **two-stage `focus()` → `propose()`
> pipeline over a reusable engine** — see DESIGN §4.1a. `app/routing/` is the
> domain-agnostic engine (registry/dispatch/`propose_bounded`, generic
> `ActionContext`); `app/assistant/` is the ntake plugin. **Both stages sit behind
> config-selected, swappable seams** (one `NTAKE_ASSISTANT` switch): stage 1 is
> the `CaptureResolver` seam (`base.py`) with `get_capture_resolver()`; stage 2 is
> `AssistantClient` with `get_assistant()`. The two backends are **parallel
> packages** — `app/assistant/fake/` (`FakeCaptureResolver` + `FakeAssistant`,
> built) and `app/assistant/ollama/` (task 7, not yet built). v1 action set:
> `set_due_date`, `create_event` (standalone or work-item-linked),
> `complete_work_item`, `create_work_item`, `deconflict_events` (calendar-context
> placeholder), `no_action`. Capture is propose-only and always new (`work_item_id`
> stays `None`); proposals carry a registry-derived `action_summary` + the model's
> `llm_rationale`. **Remaining (task 7):** the **`OllamaCaptureResolver` (stage 1)
> + `OllamaAssistant` (stage 2)** — host-only live model. The real stage-1
> text→target resolution and stage-2 reasoning drop into the seams above with no
> architecture change.

### Phase 5 — labor view, grooming assist, hardening
- **Labor view** (on demand): assistant reads the raw update log by author over
  time, using `source` to credit human effort vs. assistant-confirmed — surfaced
  as recognition, **not** scores (R-labor guardrail).
- **On-demand grooming** assist for the ~monthly review.
- **Persistence/resiliency:** WAL mode + `synchronous=NORMAL`; the **one scheduled
  job** — weekly consistent snapshot (`VACUUM INTO`, same-disk v1).
- Kiosk hardening: PWA manifest + service worker, always-on, SSE reconnect.
- Failure surfacing in the UI; basic logging.

**Exit:** data is backed up weekly; wall display survives days of uptime; labor
view works; failures are visible.

## Deferred (explicitly not built)
- SMS/text capture channel (DESIGN-sms-deferred.md).
- `.ics` import/export (INTEROP), recurrence (assistant-from-log evolution).
- Async assistant delivery (v1 is synchronous); conversational refinement of
  proposals (v1 is restate-loop).
- Two-tier availability split; off-machine backup; Postgres.
- Persisted labor metrics; drag-and-drop board; multi-household.

## Deferred / future refactor — reusable propose-confirm engine  ✅ DONE

> **Done — lives in `app/routing/`** (the domain-agnostic engine), with the
> ntake plugin in `app/assistant/`. `app/routing/` holds `ProposedAction`,
> `AssistantClient`/`NullAssistant` (contract.py), the generic `ActionRegistry`
> + `ActionSpec` + `ActionError` + `require_params` (registry.py), and
> `propose_bounded` (propose.py). Handlers receive an **opaque context** the app
> injects (ntake's is `NtakeActionContext(session, member, target_id,
> target_type)` in `app/assistant/actions.py`). The import boundary — engine
> imports no `app.models` / `sqlalchemy` / `fastapi` — is enforced by
> `tests/test_engine.py::test_engine_does_not_import_app_specific_modules`.
> Still package-shape inside this repo (extractable by a directory move); the
> Ollama `format`-constrained client (below) is the remaining piece, arriving
> with task 7.

The Phase 4 assistant (capture → propose `{name,params}` → human confirm →
dispatch to a handler) is built modular **within the app**, but its engine is
worth extracting into a **domain-agnostic, reusable module** ("propose-confirm" /
action-router) that other projects can consume. The split:

- **Engine (reusable, imports nothing app-specific):** `AssistantClient` /
  `ProposedAction` / a generic `CaptureContext`; a generic `ActionRegistry`
  (register name → param spec + handler); validate/dispatch with a uniform error;
  the bounded-timeout + graceful-degrade wrapper; the `{actions:[{name,params}]}`
  contract + an Ollama `format`-constrained client that builds its JSON schema
  from the registered actions. No `Session`, no `Member`, no ORM models.
- **Plugin (this app):** registers ntake's actions (`set_due_date`,
  `create_event`, …); each handler receives an **opaque context** the app injects
  (here `(session, member, target_id)`) and does the ORM mutation +
  `source=assistant` append. The engine never sees SQLAlchemy.

**Approach (agreed):** *package-shape now, not a separate package.* Structure as a
self-contained sub-package with a strict "engine imports nothing app-specific"
rule, enforced by isolated engine tests (fake handler + fake context). Extractable
into its own installable package later by a directory move — only if a concrete
second consumer appears (don't pay packaging cost pre-emptively). Do this as a
dedicated refactor task **after** the Phase 4 v1 flow lands, since it touches the
task 2/4/5 code and is cleaner as its own focused, well-tested change.

## Deferred-decision ledger (decide at the forcing phase)
| Decision | At |
|---|---|
| Alembic migration wiring | 1b (finish) |
| SSE event granularity + reconnect replay | 1e / 5 |
| Token delivery mechanism (QR / link / paste) | 2 → **resolved:** CLI prints plaintext once; operator delivers (paste/link/QR) |
| Board labels / calendar default view / card face | 3 |
| Assistant model + runtime; prompt contract; latency validation | 4 |
| Labor-view output shape (summary, not scores) | 5 |
| Backup destination → off-machine | future |

## Change log
- Reconciled to v2: work-item/update-log model, inline assistant, `source` field,
  persistence/resiliency, minimal events. Supersedes the pre-reframe plan.
