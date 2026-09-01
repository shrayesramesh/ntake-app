# Family Calendar + Todo Board — Implementation Plan (High-Level)

> **Status:** Draft. Companion to [REQUIREMENTS.md](./REQUIREMENTS.md) and
> [DESIGN.md](./DESIGN.md). This plan is intentionally allowed to churn as
> implementation proceeds; requirements/design stay comparatively stable.
>
> **Shape:** phased **vertical slices**. Each phase proves the architecture
> end-to-end and ships something usable, so **deferred LLD decisions are made at
> the phase that forces them** — not up front. The scariest integration seams
> (Tailscale reachability, SSE push, token auth) are proven early rather than
> after everything is built.
>
> **Method:** TDD. The rule throughout — **TDD your own code (unit + in-process
> integration); smoke-test the environment you don't own** (Tailscale, TLS, the
> browser). Don't try to automate the network/browser; assert on your own seams.
>
> **Stack (from DESIGN §1.1):** FastAPI (Python) + `pytest`/`TestClient`;
> SQLite to start; HTMX + light JS frontend; SSE for live updates; local GPU
> model (Python) behind a separable parser interface.

---

## Phase 0 — Project scaffolding

Goal: a buildable, testable skeleton before any feature code.

- FastAPI app skeleton, dependency/venv setup, `pytest` wired and running.
- CI-less local test loop confirmed (`pytest` green on an empty test).
- Repo hygiene (this is currently plain files — init version control when ready).

**Exit:** `pytest` runs and passes a trivial test; the app boots.

---

## Phase 1 — Walking skeleton (the riskiest seams, end-to-end)

Goal: one hardcoded event travels DB → backend → SSE → a browser on another
device over Tailscale. Proves reachability, persistence, the change-event seam,
and live push before any real features exist.

TDD checkpoints (each is red→green→refactor unless marked smoke):

- **1a — Health endpoint (unit + integration).**
  - *Unit:* `GET /health` handler returns 200 + status/version body.
  - *Integration:* boot the real app, hit `/health`, assert 200.
  - *Proves:* build + HTTP serving + integration harness. No DB/network yet.

- **1b — DB connection + migration (integration).** *Forces the datastore
  decision.*
  - *Integration:* app starts, runs migrations against a test DB, a repository
    writes then reads back one row.
  - *Unit:* repository interface tested against a fake.
  - *Decision made here:* SQLite vs. Postgres (default **SQLite** unless a reason
    emerges). Ref DESIGN §1.5.
  - *Proves:* persistence end-to-end.

- **1c — First real read path: `GET /events` (unit + integration).**
  - *Unit:* service maps DB rows → API DTOs; **first UTC/timezone test lands
    here** (NFR-TIME).
  - *Integration:* seed one event → `GET /events` returns it as JSON.
  - *Proves:* the DB→API→JSON vertical cut.

- **1d — Change-event seam (unit).** *This is the HLD commitment "writes emit
  change events" (DESIGN §5.3/§5.4), made a first-class tested unit.*
  - *Unit:* on a committed write, the write path **publishes a change event** to
    an in-process emitter/bus; assert the emitter is called with the right
    payload (mock subscriber).
  - *Proves:* writes produce change events, independent of SSE.

- **1e — SSE delivery (integration).**
  - *Integration:* an in-process HTTP client subscribes to the SSE stream; a
    write is performed; assert the subscriber receives the pushed event. No
    browser needed.
  - *Proves:* the reactive push pipe (DESIGN §5.4).

- **1f — Reachability over Tailscale + TLS (smoke, manual).**
  - *Manual checklist:* a second device on the tailnet loads the page over HTTPS
    and sees the pushed event live.
  - *Explicitly not automated* — infra seam verified by hand once, then trusted.
  - *Decision touched:* TLS/cert mechanism over Tailscale (DESIGN §1.5).

**Exit:** hardcoded/seeded event renders live on a second device over Tailscale;
1a–1e green in the automated suite; 1f smoke-checked.

---

## Phase 2 — Identity, setup & member/device enrollment

Goal: real auth on every request; the bootstrap and admin enrollment flows exist.
(Satisfies F-AUTH, F-SETUP, F-MEMBER; DESIGN §1.4.)

- First-admin **bootstrap** (create household + first adult before any data).
- Admin **enrolls a device** → mint random token, store **hash**, map to member/
  role. Token delivery mechanism decided here (QR / one-time tailnet link /
  copy-paste — LLD).
- Every API call **authenticates** the token → member → role; unauthenticated
  rejected (F-SAFE-01).
- **Revocation** + display re-enrollment path (DESIGN §1.4).

*TDD focus:* token hashing/verification (unit), auth middleware allow/deny
(unit + integration), enrollment flow (integration). Role gating tested here even
though child role isn't built (adult vs. non-adult).

**Exit:** no request succeeds without a valid device token; an admin can enroll
and revoke a device; the display enrolls as a low-privilege identity.

---

## Phase 3 — Core CRUD + live board & calendar (the usable product)

Goal: the real app — events, todos, checklists — with structured PWA input and
SSE-driven live updates. (Satisfies F-CAP structured path, F-EVT, F-TODO,
F-QRY, F-DISP; read-mostly per F-DISP-05.)

- Data model built out: `events`, `todos`, `checklist_items`, `families`
  (incl. **`timezone`, day-one**), `members`, `device_tokens` (DESIGN §4).
- CRUD endpoints for events and todos/checklists; each write **emits a change
  event** (reuses the 1d seam) → SSE to clients.
- **Concurrency:** last-write-wins via `updated_at`/`sequence` (DESIGN §5.3);
  idempotency key on create.
- Read-mostly frontend: HTMX views — calendar (events + due todos) and the single
  Kanban board (cards + checklists); **simple tap/form mutations** (tick item,
  move card via control, add via form); live-updating via HTMX-SSE.
- Structured input supplies `{entity, op, target}` directly (no parser yet).

*LLD decisions made here as needed:* column names (OQ-COLS), default calendar
view (OQ-DISP-VIEW), card face (OQ-DISP-CARD), done handling (OQ-DISP-DONE), sort
(OQ-DISP-SORT). Each decided when its screen is built.

*TDD focus:* CRUD services + validation (unit), timezone conversion at edges
(unit), each write emits the right change event (unit), full write→SSE→read
slice (integration).

**Exit:** a family member can add/edit/complete events and todos from a phone via
structured input, and every device (incl. the wall display) reflects it live.

---

## Phase 4 — Free-text capture + local model

Goal: natural-language capture ("dentist Tuesday 3pm") via the local GPU model,
behind the separable parser interface. (Satisfies F-CAP-04; DESIGN §3, §5.1.)

- Parser service (Ollama or similar) behind a clean interface; **structured JSON
  output** `{entity, op, fields, target}`.
- Free-text capture path routes through the parser → existing CRUD/triage.
- **Timezone-correct** relative-date resolution (uses `families.timezone`).
- Ambiguous/unparseable → clarification (F-CAP-05).

*LLD decisions:* model/runtime + size given the GPU; optional rules-based/small
fallback (also the seed for the future two-tier split); structured-output
constraint.

*TDD focus:* parser interface with a **fake** (unit — deterministic, no model);
triage mapping (unit); a small real-model integration/eval for parse quality
(not in the fast unit loop).

**Exit:** free-text captures resolve to correct CRUD ops with timezone-correct
dates; parser is swappable behind its interface.

---

## Phase 5 — Hardening & operations

Goal: make it safe to actually rely on. (NFR-DURABILITY, NFR-UPTIME, F-DISP-04.)

- **Backup (day-one durability minimum):** automated nightly off-machine DB
  copy/dump (NFR-DURABILITY). Verify a restore once.
- **Display kiosk behavior:** PWA manifest + service worker; always-on / sleep-
  wake resilience; SSE **reconnect** behavior (refetch-on-reconnect is likely
  enough).
- Failure surfacing in the UI (F-CAP-05/06); basic logging.
- Destructive-op gating: UI confirm + adult role (F-SAFE-02, OQ-DEL-POLICY).

**Exit:** data is backed up automatically; the wall display survives days of
uptime and reconnects cleanly; failures are visible, not silent.

---

## Later arcs (explicitly deferred — not in the launch build)

Parked with clear homes so they don't distort the launch plan:

- **Recurrence depth** — beyond simple RRULEs to per-instance exceptions
  (`RECURRENCE-ID`/`EXDATE`); couples to calendar rendering (OQ-RECUR).
- **`.ics` interoperability** — export/subscribe first, then import; direction
  TBD (F-ICS, DESIGN §4.4).
- **Two-tier availability split** — cheap always-on box + on-demand GPU parse
  tier with WoL + fallback (DESIGN §1.3), when home-PC-uptime chafes.
- **Text capture channel (SMS/Telegram)** — reintroduces public ingress,
  stateful confirmation (G6), entity resolution (G7); full design in
  [DESIGN-sms-deferred.md](./DESIGN-sms-deferred.md).
- **Richer frontend** — TS/React view-swap if read-mostly + tap/form outgrows
  HTMX (esp. drag-and-drop board; DESIGN §1.1 escape hatch).
- **Children role enforcement** — schema supports it; enforced access later.

---

## Deferred-decision ledger (made at the phase that forces each)

| Decision | Decide at | Ref |
|---|---|---|
| Datastore engine (SQLite vs Postgres) | Phase 1b | DESIGN §1.5 |
| TLS/cert mechanism over Tailscale | Phase 1f | DESIGN §1.5 |
| Token delivery mechanism | Phase 2 | DESIGN §1.4 |
| SSE event granularity + reconnect-replay | Phase 3 / 5 | DESIGN §5.4 |
| Column names / calendar default / card face / done / sort | Phase 3 | OQ-DISP-* |
| Local model + runtime; parser fallback; structured output | Phase 4 | DESIGN §3 |
| Confirmation policy (always vs. on-ambiguity) | Phase 3/5 | OQ-CAP-CONF |
| Recurrence depth | Later arc | OQ-RECUR |
| `.ics` priority / direction | Later arc | OQ-ICS-* |

---

## Change Log

- **2026-08-30** — Initial high-level plan. Phased vertical slices (0–5) + later
  arcs; Phase 1 walking skeleton expanded into TDD checkpoints 1a–1f (unit /
  in-process integration / manual smoke). Deferred-decision ledger added so LLD
  choices are made at the forcing phase. Reflects the resolved HLD: PWA-first,
  home-PC+Tailscale, device-token auth, SSE sync, read-mostly UI,
  FastAPI/HTMX/SQLite stack.
