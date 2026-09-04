# AGENT — START HERE

You are a coding agent working on a **self-hosted family calendar + work-item
app** on the owner's home machine (Pop!_OS). This folder is the clean, current
source of truth. Read this fully before doing anything.

## Read these first (the whole design, no cruft)

1. **REQUIREMENTS.md** — what the system does and for whom (solution-neutral).
2. **DESIGN.md** — how it's built: architecture, data model, flows, front end.
3. **PLAN.md** — phased checkpoints; what's already built vs. next.
4. **SKILL.md** *(at repo root, with the code)* — how to work in this repo (the
   check gate, conventions).

Deferred/reference (only if relevant): **DESIGN-sms-deferred.md** (a parked text
channel), and the `research/` notes at repo root (reasoning trail + operational
setup like Tailscale/hardware/stack).

## The code (already exists, at repo root — not in this folder)

`app/`, `tests/`, `Makefile`, `setup.sh`, `requirements.txt`, `pyproject.toml`.
Current state: phases 0–3 and the **fake-first Phase 4** are built and green
(`make check` → 300 tests pass; + `make smoke`, 12 real-stack checks). Events +
work-item/board + live SSE + config-seeded identity are in; the assistant runs as
a two-stage pipeline (`CaptureResolver` → `AssistantClient`) over a reusable
engine, with a `fake/` backend that runs the real two-call shape
(`build_world_view` → `fake_link` → `deep_context` → `propose`). Live-surface
hardening is done (WAL, `manage backup`, SSE reconnect re-sync, PWA). **Not built
yet:** Phase-4 **task 7** (the live Ollama backend) and Phase 5's labor view +
grooming assist + kiosk polish (see PLAN.md).

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
