# AGENT — START HERE

You are a coding agent working on a **self-hosted family calendar + work-item
app** on the owner's home machine (Pop!_OS). This folder is the clean, current
source of truth. Read this fully before doing anything.

## Read these first (the whole design, no cruft)

1. **REQUIREMENTS.md** — what the system does and for whom (solution-neutral).
2. **DESIGN.md** — how it's built: architecture, data model, flows, front end.
3. **PLAN.md** — phased checkpoints, current priorities, and what is deferred.
4. **SKILL.md** *(at repo root, with the code)* — how to work in this repo (the
   check gate, conventions).

Use these only when the task makes them relevant:

- Before changing assistant behavior, read `app/assistant/` and the focused
  `tests/assistant/` coverage; the action contract is implementation-owned.
- **BUGLIST.md** — reproducible correctness issues and their evidence.
- **UI_TESTING_BACKLOG.md** — product, interaction, and visual follow-ups.
- **HOST_SETUP_GUIDE.md** *(at repo root)* — operator-only local-LLM and host
  setup; do not perform those steps as an agent.
- SMS/text capture is deferred; do not revive it without a new scoped decision.
  The `research/` notes are reference material only.

## The code (already exists, at repo root — not in this folder)

`app/`, `tests/`, `Makefile`, `setup.sh`, `requirements.txt`, `pyproject.toml`.

### Package map

- `app/persistence/` — database engine/session setup, ORM models, and Alembic
  wrapper. The repository-root `alembic/` directory holds scripts and revision
  history.
- `app/identity/` — device-token cryptography and FastAPI authentication
  dependencies. `Member` and `DeviceToken` remain persistence models.
- `app/assistant/` — fake and local-LLM backends plus the explicit
  world → LINK → deep-context → PROPOSE pipeline.
- `app/schemas.py` — Pydantic API DTOs; it is an API boundary, not persistence.
- `tests/<feature>/` — feature-owned tests: `assistant`, `identity`,
  `persistence`, `api`, `web`, and `operations`. Shared fixtures stay in
  `tests/conftest.py`; prompt snapshots stay in `tests/expectations/`.
Current state: phases 0–3 and **Phase 4 including the live local-LLM backend
(task 7)** are built and green (`make check` green, ≥95% coverage; + `make smoke`,
12 real-stack checks). Events + work-item/board + live SSE + config-seeded
identity are in; the assistant runs as a two-stage pipeline (`CaptureResolver` →
`AssistantClient`) over a reusable engine, with both a deterministic `fake/`
backend and the **`local_llm/` backend (llamafile / any OpenAI-style localhost
endpoint), verified end-to-end against Llama 3.1 8B on `localhost:8080` — no
Tailscale**. The live pipeline links work items, events, **and members**
(`{work_item_ids, event_ids, member_ids}`) and folds each linked member's
workload into the PROPOSE context. The calendar is now a locally served
**EventCalendar** grid (month default; week/day optional; authenticated `/events`,
SSE `refetchEvents()`, stable kiosk region, title-first event metadata); it stays
read-only so mutations remain propose-and-confirm. FullCalendar remains the
fallback if on-device validation exposes a blocking EventCalendar limitation.
Live-surface foundations are done (WAL, `manage backup`, SSE reconnect re-sync,
and the PWA manifest/service worker). Dev bring-up for safe live UI testing is
**`make llm-up` then `make ui-demo`** (fresh Alex/Sam demo DB + live model + debug
trace). `make ui-live` remains the separate persistent local sandbox mode.

**Current MVP sequence — follow this unless a user assigns narrower work:**

1. Implement privacy-preserving capture-to-confirm observability: local logs and
   actionable UI feedback for capture, assistant, proposal, Confirm, and response
   failures. Do not log device tokens or raw household note text by default.
2. Resolve the kiosk access boundary. The current `/` PWA shell is shared by all
   authenticated devices; its board/calendar are read-only, but it still exposes
   capture and Confirm. Do not describe the wall display as technically read-only
   until a kiosk surface or mutation denial is implemented.
3. Stop for the owner to install phone/tablet PWAs and perform the documented
   Tailscale HTTPS smoke. Then the owner runs the days-long kiosk soak and
   schedules weekly backups.

**Validated assistant behavior:** the former BUG-001 through BUG-008 captures and
the family-local temporal contract are fixed and validated. Treat further prompt
work as regression-driven, not open-ended tuning. **Follow-on scope:** the labor
view, on-demand grooming assist, and manual board-grooming UI (the
`archive_work_item`/`delete_event` *actions* exist; no manual UI).

## How to work

- **One checkpoint at a time** (PLAN.md). Stop after each; show real output.
- **TDD:** test first, then code. Never claim a test passes without running it.
- **Before finishing any checkpoint, run `make check`** (ruff + mypy + pytest) and
  fix everything until clean. Paste the output.
- **Environment setup:** `make setup` (creates venv, installs, verifies). On
  Pop!_OS, if venv errors: `sudo apt install python3-venv`.
- **Do NOT** do Tailscale / browser / device / deploy steps — those are
  **human-only** (checkpoint 1f and setup). If a task needs them, stop and say so.
- **Do NOT** invent APIs; don't run destructive/networked commands; don't
  `git push`.
- **Stay in scope:** build the assigned checkpoint only — don't try to implement
  all of DESIGN.md at once.

## Key facts (treat as given; details in the docs)

- **Stack:** FastAPI + SQLite (SQLAlchemy 2.0, NOT SQLModel) + HTMX + SSE; local
  GPU assistant. App binds **127.0.0.1** (Tailscale fronts it — human concern).
- **Data model:** minimal events; work items = free-text item + **append-only
  `work_item_updates`** log (with `source: human|assistant`, `author → members`);
  fixed board columns; tags on both events and work items.
- **Assistant:** inline **propose-and-confirm** (never auto-applies); synchronous
  in v1.
- **Backup:** weekly consistent snapshot (`VACUUM INTO`), same-disk v1.

## Definition of done for a checkpoint
Code + tests written; `make check` clean (output shown); only in-scope files
changed; deps pinned if added; report files changed + the `make check` output +
anything you were unsure about.
