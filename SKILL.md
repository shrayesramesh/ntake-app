# SKILL: Coding agent conventions for this repo

> **Purpose:** how any coding agent (local or cloud) should work in the family
> calendar codebase. Read this before writing code. It encodes the guardrails
> that keep changes correct — especially important for smaller local models.

## Golden rules

1. **Work in small, verified steps.** One checkpoint/task at a time. After each,
   run the check gate and report real output. Do not batch many changes then
   hope.
2. **Never claim success without running the command.** Paste actual output of
   `make check` (or the relevant target). "It should pass" is not acceptable.
3. **The check gate is mandatory before finishing any task:**
   ```
   make check      # = lint (ruff) + typecheck (mypy) + tests (pytest)
   ```
   Fix every finding and re-run until it is clean. Do NOT declare a task done
   with failing lint, type, or test output.
4. **Do not invent APIs.** If unsure of a library's function/signature, check the
   installed package or ask — never guess. If lint/mypy flags an undefined name,
   that is a real error, fix it.
5. **Don't loop blindly.** If the same fix fails twice, stop and report the full
   error rather than trying random variations.
6. **Stay in scope.** Change only what the task requires. Do not refactor
   unrelated code or add dependencies without reason.

## The environment

- **Python 3.12+**, everything in a `.venv`. Never install into system Python.
- **One-time setup / after dependency changes:** `make setup` (creates venv,
  installs pinned `requirements.txt`, runs tests). On Pop!_OS, if it complains
  about venv, run `sudo apt install python3-venv`.
- Config lives in `pyproject.toml` (ruff, mypy, pytest) — standard Python, no
  Amazon/BuilderTools tooling involved.

## Make targets (use these, not raw commands)

| Command | Does |
|---|---|
| `make setup` | venv + install + verify (run once / after deps change) |
| `make test` | run pytest |
| `make lint` | ruff check + format-check (no changes) |
| `make format` | ruff auto-fix + format (mutates files) |
| `make typecheck` | mypy |
| `make check` | **lint + typecheck + test — the gate before finishing** |
| `make run` | dev server on 127.0.0.1:8000 |
| `make clean` | remove venv/caches/db |

Typical loop while coding: write test → write code → `make format` → `make check`
→ fix findings → repeat until `make check` is clean.

## Conventions

- **TDD:** write the test first, then the code to pass it. Tests live in `tests/`
  and use the in-memory-SQLite fixtures in `tests/conftest.py` (each test gets an
  isolated DB — do not write to the real `calendar.db`).
- **Data layer:** SQLAlchemy 2.0 ORM (typed `Mapped[...]`), NOT SQLModel. Schema
  per `research/04-data-layer.md`. Pydantic models are separate DTOs at the API
  edge (`app/schemas.py`) — do not merge them into the ORM classes.
- **Timestamps are UTC**; `families.timezone` is required. Use `datetime.UTC`
  (not the older `timezone.utc`).
- **App binds to 127.0.0.1 only.** A Tailscale reverse proxy fronts it in
  production — that is a human-run concern, not the agent's.
- **Formatting** is Black-compatible via ruff; let `make format` handle it, don't
  hand-format.
- The one cosmetic `StarletteDeprecationWarning` (httpx/httpx2) from pytest is
  **expected and harmless** — do NOT install `httpx2` to silence it.

## Out of scope for the agent

- Tailscale / networking / TLS / device enrollment — **human-only**
  (`shovel-ready/tasks_tailscale_*.md`).
- Do not `git push`, force-push, or run destructive/network commands.
- Do not implement everything in `DESIGN.md` / `REQUIREMENTS.md` — those are
  context. Build only the assigned checkpoint(s) (see `PLAN.md`,
  `AGENT_START_HERE.md`).

## Definition of done for a checkpoint

- Code + tests written; `make check` is **clean** (lint, types, tests all pass),
  with output shown.
- Only in-scope files changed; dependencies pinned in `requirements.txt` if added.
- Report: files changed, the `make check` output, and anything you were unsure of.
