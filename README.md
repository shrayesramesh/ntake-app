# Family Calendar + Work Items

A private, self-hosted family calendar + work-item app for one household. Runs on
a home PC, reached privately over Tailscale, with a shared always-on wall display
and phone access. A local assistant reads free-text updates and proposes calendar/
work-item changes (propose-and-confirm). Core purpose beyond scheduling: make
household/emotional labor **visible for recognition and fairness**.

## Start here

- **Building it? → read [`spec/AGENT_START_HERE.md`](spec/AGENT_START_HERE.md)**,
  then the rest of `spec/`. That is the current source of truth.
- **Running the code:** `make setup` (creates venv, installs, runs tests), then
  `make check` (lint + types + tests) and `make run` (dev server on 127.0.0.1).
  Needs Python 3.12+ (Pop!_OS: `sudo apt install python3-venv` if venv errors).
- **Local assistant model (optional, dev):** with a llamafile model acquired
  (see `HOST_SETUP_GUIDE.md` §7), `make llm-up` / `make llm-status` / `make llm-down`
  bring the local model server up/down on `127.0.0.1:8080`, and
  `python scripts/live_local_llm_smoke.py` drives real captures against it and
  **prints** the assistant's proposals (reasoning quality is eyeballed, not
  asserted). All localhost — no Tailscale needed to exercise the assistant.

## Repo map

| Path | What it is |
|---|---|
| **`spec/`** | **Source of truth** — requirements, design, plan, agent entry point. Read this. |
| `app/assistant/` | Propose-confirm engine plugin, context renderers, fake backend, and live local-LLM stages. |
| `app/persistence/` | SQLAlchemy database setup, ORM models, and programmatic Alembic integration. |
| `app/identity/` | Device-token cryptography and FastAPI request authentication. |
| `app/schemas.py` | Pydantic API DTOs; deliberately separate from persistence models. |
| `tests/` | Feature suites: `assistant/`, `identity/`, `persistence/`, `api/`, `web/`, and `operations/`; root holds shared fixtures and snapshots. |
| `alembic/` | Alembic script environment and immutable migration revision history. |
| `Makefile`, `setup.sh`, `requirements.txt`, `pyproject.toml` | Build/run/lint tooling. |
| `SKILL.md` | How to work in this repo (the `make check` gate, conventions). |
| `HOST_SETUP_GUIDE.md` | Operator setup (config, device tokens, Tailscale, run). |
| `USER_SETUP_GUIDE.md` | Family-facing device setup (install Tailscale, add PWA). |

## Current status

Phases 0–3 and **Phase 4 including the live local-LLM backend** are built and
passing (`make check` green, ≥95% coverage; plus a real-stack `make smoke`,
12 checks): FastAPI app; `/health`, `/events`, the work-item + board read/append
paths, `/capture` (propose-only) and `/actions/confirm`; config-seeded identity +
token CLI; change-event seam → SSE live sync; and the assistant as a reusable
engine (`app/routing/`) + ntake plugin (`app/assistant/`) with two swappable seams
(`CaptureResolver`, `AssistantClient`), **both a `fake/` and a live `local_llm/`
backend**, and the two prompt views (`build_world_view`, `build_tools_view`). The
live action registry and parameters are documented only in
`spec/ASSISTANT_ACTIONS.md`. The two-call pipeline links work items, events, **and
members** from free text (`{work_item_ids, event_ids, member_ids}`) and folds each
linked member's workload into the PROPOSE context; proposal cards render verbose,
id-resolved detail via each action's own `ActionSpec.render_card`. The calendar is
a locally served **EventCalendar** grid (month default; week/day optional) backed
by authenticated `/events`, with SSE-driven `refetchEvents()`, stable kiosk height,
and title-first compact event metadata (time, participant names, location). It
remains read-only so mutations stay propose-and-confirm; FullCalendar is the
documented fallback in `spec/calendar_design.md`.

**Live-surface hardening (done):** SQLite WAL + `synchronous=NORMAL`
(crash-safety); Alembic **migrations** as the real-DB schema path (startup runs
`upgrade head`; `python -m app.manage migrate`; tests use `create_all`); a
`VACUUM INTO` weekly-snapshot backup (`python -m app.manage backup`; scheduling is
a documented host cron/systemd step); SSE re-sync on (re)connect so the wall
display can't miss a change during a disconnect; and a PWA manifest + service
worker for add-to-home-screen.

**Live local LLM (done):** the `local_llm/` backend runs against llamafile (or any
OpenAI-style localhost endpoint) and is verified end-to-end. For hands-on browser
testing: **`make llm-up` then `make ui-demo`** starts a resettable Alex/Sam demo
DB with the live model, a demo token (retrieve it with `make ui-demo-token` while
the session is running), and the in-UI LINK/PROPOSE debug trace.
**`make ui-live`** remains the separate persistent local sandbox mode. Both bind
only localhost (see `HOST_SETUP_GUIDE` §7.4/§7.6). The backend selection stays
config-in-code (`AssistantConfig`); these targets flip it via the opt-in
`NTAKE_ASSISTANT_KIND=local` env override so the committed default (and tests)
stay on `fake`.

**Next MVP work:** finish live-assistant prompt/behavior tuning and kiosk launch
hardening (always-on soak, failure surfacing, logging). **Follow-on scope:** labor
view, on-demand grooming assist, manual board-grooming UI, and one-time backfill
from Trello / Google Calendar (`manage import`, designed in DESIGN §6a). See
`spec/PLAN.md`, `spec/BUGLIST.md`, and `spec/UI_TESTING_BACKLOG.md`.

## Key shape (details in `spec/`)

- **Stack:** FastAPI + SQLite (SQLAlchemy 2.0) + HTMX + SSE; local GPU assistant.
  Self-hosted; app binds 127.0.0.1, Tailscale fronts it.
- **Data:** minimal events; work items = free-text item + append-only update log
  (`work_item_updates`, with `source: human|assistant`); fixed board columns; tags.
- **Assistant:** inline propose-and-confirm; never auto-applies.
- **Backup:** weekly consistent snapshot (same-disk v1).
