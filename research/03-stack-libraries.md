# Stack libraries — pinned baseline (Phase 0/1)

> **Type: research / reference.** Current library baseline so `shovel-ready/
> tasks_app_scaffold.md` is copy-paste rather than "verify at install." Versions
> are **as of 2026-08** from PyPI/official release notes — **re-confirm the exact
> latest at install time and pin** (FastAPI in particular ships very frequently).

## Versions found (2026-08)

| Library | Role | Version seen | Notes |
|---|---|---|---|
| `fastapi[standard]` | web framework | **0.136.1** (Apr 2026); >0.141 by mid-2026 | 0.x — pin exactly; releases often. |
| `uvicorn[standard]` | ASGI server | ~**0.51–0.52** | dev: `--reload`. |
| `pytest` | test runner | **9.1.x** | |
| `pytest-asyncio` | async tests | current | needed once async SSE/DB tests appear. |
| `httpx` | test client dep | current | FastAPI `TestClient` uses it. |
| `sse-starlette` | **SSE server** | current on PyPI | `EventSourceResponse` for the push endpoint (§5.4). |
| `httpx-sse` | **SSE client (tests)** | current (Oct 2025) | `connect_sse` / `.iter_sse()` — consume the stream in checkpoint **1e** without a browser. |
| `sqlalchemy` | ORM/core | **2.0.52** (Aug 2026) | stay on the **2.0** line; 2.1 is beta — avoid for now. |
| `alembic` | migrations | **1.19.1** | pairs with SQLAlchemy 2.0 (checkpoint 1b). |

## SQLModel vs. plain SQLAlchemy 2.0 — DECIDED

**Chosen: plain SQLAlchemy 2.0 ORM** (SQLModel rejected). Rationale — the owner
prefers transparent SQL and does query optimization; SQLModel is the least
transparent option and lags releases. Full decision + the table→model mapping and
"SQLAlchemy models + Pydantic DTOs, no dataclasses" representation pattern are in
**`04-data-layer.md`**.

## Suggested initial install (pin real versions at install)

```
# core
pip install "fastapi[standard]" "uvicorn[standard]"
# tests
pip install pytest pytest-asyncio httpx httpx-sse
# sse (Phase 1e)
pip install sse-starlette
# data (Phase 1b)
pip install "sqlalchemy>=2.0,<2.1" alembic
```

Then freeze exact versions into `requirements.txt` / `pyproject.toml`.

## Frontend (Phase 3 — not pip)

- **HTMX** via CDN or vendored JS; add the **HTMX SSE extension** for
  live-updating views over the same SSE endpoint. Pin the HTMX version too
  (check the current release when Phase 3 starts).

## Caveats

- FastAPI/Starlette/Pydantic move fast and are interdependent — install together
  and pin as a set; let `fastapi[standard]` pull compatible Starlette/Pydantic
  rather than pinning those independently.
- SQLAlchemy **2.1** was in beta as of mid-2026 — stay on 2.0 until it's stable
  and Alembic/ecosystem catch up.
- Versions above are point-in-time; the **pinning discipline** matters more than
  the specific numbers.
