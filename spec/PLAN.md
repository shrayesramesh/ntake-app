# Family Calendar + Work Items — Implementation Plan

> Phased plan reconciled to the v2 architecture (REQUIREMENTS.md + DESIGN.md).
> Method: **TDD** — write tests first; **`make check`** (lint + types + tests)
> must be clean before any checkpoint is done. Rule: TDD your own code; smoke-test
> the environment you don't own (Tailscale, TLS, browser).

## Current state (already built & passing)

Events vertical slice + tooling exist and are green (`make check` → 5 tests
pass):
- FastAPI app, `GET /health`, `GET /events`
- SQLAlchemy 2.0 + SQLite; minimal `Family` + `Event` models (v2-shrunk: no
  uid/status/sequence/recurrence; all-day-as-date; nullable `source_update_id`)
- Pydantic `EventRead` DTO; isolated in-memory-DB test fixtures
- Makefile, setup.sh, pinned requirements, ruff + mypy config

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
