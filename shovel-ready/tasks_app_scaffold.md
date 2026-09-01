# Task: Scaffold the app (FastAPI + pytest) — PLAN Phase 0 / checkpoint 1a

> **Run on:** the **home PC** (the always-on host). Gets a minimal, tested app
> running so there's something for `tailscale serve` to front later.
>
> **Verify versions at install time** — pin whatever is current; the names below
> are the intended libraries, not fixed versions.

## Intended stack (from DESIGN §1.1; pinned baseline in `../research/03-stack-libraries.md`)

- **Backend:** FastAPI (`fastapi[standard]`) + Uvicorn (ASGI server).
- **Tests:** pytest + FastAPI `TestClient` (via `httpx`); `pytest-asyncio` +
  `httpx-sse` for the SSE stream test (checkpoint 1e).
- **DB (next task/phase):** SQLite to start; SQLAlchemy **2.0** + Alembic
  migrations. *(SQLModel vs. plain SQLAlchemy = decide at 1b — see research note.)*
- **SSE (Phase 1e):** `sse-starlette` (`EventSourceResponse`) on the server;
  `httpx-sse` to consume it in tests.
- **Frontend (Phase 3):** HTMX + minimal JS; HTMX SSE extension.

> Current versions (2026-08) are in `../research/03-stack-libraries.md` —
> **re-confirm latest and pin exactly at install** (FastAPI ships frequently).

## Steps

- [ ] **(Pop!_OS)** Ensure venv support: `sudo apt install python3-venv`
      (Pop!_OS ships Python 3 but `venv` may need this). Then create the project
      dir + virtualenv:
      ```
      python3 -m venv .venv && source .venv/bin/activate
      ```
      Python 3.12+ (Pop!_OS 22.04+ is fine; check `python3 --version`).
- [ ] `pip install "fastapi[standard]" "uvicorn[standard]" pytest httpx`
      (then freeze exact versions in `requirements.txt` / `pyproject.toml`).
- [ ] Create a minimal app with a health endpoint:
      ```python
      # app/main.py
      from fastapi import FastAPI
      app = FastAPI()

      @app.get("/health")
      def health():
          return {"status": "ok", "version": "0.0.1"}
      ```
- [ ] Write the first tests (checkpoint 1a):
      ```python
      # tests/test_health.py
      from fastapi.testclient import TestClient
      from app.main import app

      client = TestClient(app)

      def test_health_ok():
          r = client.get("/health")
          assert r.status_code == 200
          assert r.json()["status"] == "ok"
      ```
- [ ] Run the app: `uvicorn app.main:app --reload --port 8000`.
- [ ] Run tests: `pytest`.

## Done when (checkpoint 1a)

- [ ] `pytest` is green.
- [ ] `http://127.0.0.1:8000/health` returns 200 in a browser on the host.

## Next

- DB + migrations (checkpoint 1b) — forces the SQLite-vs-Postgres call
  (default SQLite). Then `tasks_tailscale_host_serve.md` once there's an app to
  serve.
