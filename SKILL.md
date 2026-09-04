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
  (not the older `timezone.utc`). **Gotcha:** SQLite/SQLAlchemy returns
  **tz-naive** datetimes even when you stored tz-aware ones — they represent UTC.
  When comparing or formatting a value read back from the DB, attach UTC first
  (`dt.replace(tzinfo=UTC)`) / compare against a naive-UTC bound. See
  `app/assistant/world.py`.
- **App binds to 127.0.0.1 only.** A Tailscale reverse proxy fronts it in
  production — that is a human-run concern, not the agent's.
- **Formatting** is Black-compatible via ruff; let `make format` handle it, don't
  hand-format.
- The one cosmetic `StarletteDeprecationWarning` (httpx/httpx2) from pytest is
  **expected and harmless** — do NOT install `httpx2` to silence it.

## Design conventions (learned in this codebase)

These are the judgment calls this codebase has settled on. Follow them unless
there's a concrete reason not to; deviating is fine but call it out.

- **Prefer dumb, explicit data over clever machinery.** When something needs
  declaring (e.g. an action's params), favor a plain, verbose dataclass list over
  stringly-typed conventions, decorators, or signature introspection. "Lightest
  *engine*, verbose *authoring*" beats magic that's lighter to write but heavier
  to reason about. (See `ActionSpec.params: list[Param]`.)
- **Don't add speculative structure; earn a seam with a test.** Cut unused
  facades and abstractions (YAGNI). If you want to keep an internal helper/type as
  a "seam," write a test that uses it directly — that test is what justifies its
  existence. (We removed the `app/routing/__init__` re-export facade because it
  wrapped a single module; we kept the world-view row dataclasses only once a
  direct `_render` test used them.)
- **Cohesion: data renders/validates itself.** Put rendering next to the fields it
  renders and validation next to the contract it checks — as methods/properties on
  the type, not free functions elsewhere. (`ActionSpec.prompt_line` renders the
  action; `ActionSpec.execute` validates-then-applies; the registry just resolves
  name→spec.)
- **Snapshot the exact text an LLM will see.** For prompt-facing renderers, assert
  the *entire* output string in a test (a visible, reviewable snapshot) so drift is
  caught and the prompt context is inspectable in-repo. (`test_world_view`,
  `test_tools_view`.)
- **Keep the engine domain-agnostic.** `app/routing/` (the propose/route/confirm
  engine) must import nothing app-specific — no `app.models`, `sqlalchemy`, or
  `fastapi` (enforced by a boundary test). App-coupled work (DB, ORM) lives in
  `app/assistant/`. Vocabulary marks the boundary: **"actions" are what we execute
  (internal); "tools" are how they're presented to the LLM.**
- **Config-selected, swappable backends behind one switch.** The assistant has two
  seams (`CaptureResolver`, `AssistantClient`) chosen by `NTAKE_ASSISTANT` via
  `app/assistant/factory.py`; backends are parallel packages (`fake/`, later
  `local_llm/`). Stateless singleton strategies — request-scoped state (the DB
  `Session`) flows in as a method arg, never stored on the strategy.
- **Test fixtures for seeding, not copied helpers.** Use the `conftest.py`
  factories (`family_factory`/`member_factory`/`work_item_factory`/`event_factory`)
  and composites (`fam_member`, `fam_member_item`, `populated_family`) rather than
  re-defining local seed helpers per file.
- **Keep the docs in sync as part of the change.** Update `spec/` (and this file)
  in the same session as the code — stale status/action-lists/test-counts are a
  recurring drift source.

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
