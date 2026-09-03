#!/usr/bin/env python
"""Host integration smoke — run the real stack end-to-end on this machine.

NOT part of `make check` (that's the fast unit/integration suite). This is a
manual, operator-facing smoke: it stands up a real uvicorn server against an
*isolated temp DB*, seeds a member, mints a real device token via the CLI path,
then drives real HTTP — health, the shell page, an authenticated create, the
board fragment, and one real SSE change frame after a write. Every wait is
bounded so it fails loudly instead of hanging.

Usage:
    make smoke                 # run checks, print PASS/FAIL, tear down
    python scripts/integration_smoke_on_host.py --serve
                               # run checks, then KEEP the server up and print
                               # the URL + token so you can poke it in a browser
    python scripts/integration_smoke_on_host.py --serve --host 0.0.0.0
                               # bind the LAN too (for a phone smoke; no TLS/auth
                               # perimeter — use only on a network you control)

Exit code 0 = all checks passed.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

# Isolated temp DB + throwaway secret BEFORE importing the app (engine binds at
# import from CALENDAR_DB_URL).
_TMP = Path(tempfile.mkdtemp(prefix="ntake_smoke_"))
os.environ["CALENDAR_DB_URL"] = f"sqlite:///{_TMP / 'smoke.db'}"
os.environ.setdefault("NTAKE_TOKEN_SECRET", "host-smoke-secret")

# Make the repo root importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

from app.db import SessionLocal, engine, init_schema  # noqa: E402
from app.main import app  # noqa: E402
from app.manage import gen_token_for, seed_sample_events  # noqa: E402
from app.models import Family, Member  # noqa: E402
from app.tokens import token_secret  # noqa: E402

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed_and_mint() -> str:
    """Create schema + a family/member, mint a device token; return plaintext."""
    init_schema(engine)
    now = datetime.now(UTC)
    s = SessionLocal()
    try:
        fam = Family(name="Smoke Household", timezone="America/New_York")
        s.add(fam)
        s.commit()
        s.add(
            Member(
                family_id=fam.id,
                display_name="Smoke Tester",
                role="adult",
                created_at=now,
            )
        )
        s.commit()
        return gen_token_for(
            s, "Smoke Tester", label="host-smoke", secret=token_secret()
        )
    finally:
        s.close()


def _start_server(host: str, port: int) -> uvicorn.Server:
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        raise RuntimeError("uvicorn did not start within 15s")
    return server


def _get(url: str, token: str | None = None, timeout: float = 5.0):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(req, timeout=timeout)


def _post_json(url: str, payload: dict, token: str, timeout: float = 5.0):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST"
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    return urllib.request.urlopen(req, timeout=timeout)


def _check(name: str, fn) -> bool:
    try:
        fn()
        print(f"  {PASS}  {name}")
        return True
    except Exception as e:  # noqa: BLE001 — smoke: report any failure
        print(f"  {FAIL}  {name}: {e!r}")
        return False


def run_checks(base: str, token: str) -> bool:
    ok = True

    def health():
        r = _get(f"{base}/health")
        assert r.status == 200
        assert json.loads(r.read())["status"] == "ok"

    def shell():
        r = _get(f"{base}/")
        body = r.read().decode()
        assert r.status == 200 and "board-container" in body

    def auth_required():
        try:
            _get(f"{base}/board/view")  # no token
            raise AssertionError("expected 401 without token")
        except urllib.error.HTTPError as e:
            assert e.code == 401

    created_title = f"smoke-{int(time.time())}"

    def create_item():
        r = _post_json(f"{base}/work-items", {"title": created_title}, token)
        assert r.status == 201
        assert json.loads(r.read())["title"] == created_title

    def board_shows_item():
        r = _get(f"{base}/board/view", token=token)
        assert r.status == 200 and created_title in r.read().decode()

    def sse_delivers_change():
        # Open the stream, then trigger a write, then read one change frame.
        result: dict[str, object] = {}

        def reader():
            try:
                resp = _get(f"{base}/events/stream?token={token}", timeout=10)
                for raw in resp:
                    line = raw.decode().strip()
                    if line.startswith("data:"):
                        result["frame"] = json.loads(line[len("data:") :].strip())
                        break
            except Exception as e:  # noqa: BLE001
                result["error"] = repr(e)

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        time.sleep(1.0)  # ensure subscribed
        _post_json(f"{base}/work-items", {"title": f"{created_title}-sse"}, token)
        t.join(timeout=10)
        assert "error" not in result, result.get("error")
        assert result.get("frame"), "no SSE frame received"

    def assistant_capture_propose_confirm():
        # Capture free text -> proposals (fake: 'friday' -> set_due_date).
        r = _post_json(f"{base}/capture", {"text": "call plumber friday"}, token)
        assert r.status == 201
        data = json.loads(r.read())
        item_id = data["item"]["id"]
        names = [p["name"] for p in data["proposals"]]
        assert "set_due_date" in names, names
        due = next(p for p in data["proposals"] if p["name"] == "set_due_date")
        # Confirm the proposed action -> applies it.
        c = _post_json(
            f"{base}/actions/confirm",
            {"name": "set_due_date", "params": due["params"], "target_id": item_id},
            token,
        )
        assert c.status == 200, c.status

    def seed_events_show_in_calendar():
        # Seed sample events directly (no assistant) and confirm GET /events
        # returns them — the manual-testing seed path (task 9).
        s = SessionLocal()
        try:
            seeded = seed_sample_events(s)
        finally:
            s.close()
        assert len(seeded) >= 2
        r = _get(f"{base}/events", token=token)
        assert r.status == 200
        titles = [e["title"] for e in json.loads(r.read())]
        for ev in seeded:
            assert ev.title in titles, titles

    for name, fn in [
        ("health is ok", health),
        ("shell page renders", shell),
        ("board requires auth (401)", auth_required),
        ("authenticated create (201)", create_item),
        ("board fragment shows created item", board_shows_item),
        ("SSE delivers a change frame", sse_delivers_change),
        ("assistant capture->propose->confirm", assistant_capture_propose_confirm),
        ("seed-events show in calendar", seed_events_show_in_calendar),
    ]:
        ok = _check(name, fn) and ok
    return ok


def _cleanup(server: uvicorn.Server | None) -> None:
    """Stop the server and remove the throwaway temp DB. Safe to call twice."""
    import shutil

    if server is not None:
        server.should_exit = True
        time.sleep(0.3)
    # Drop engine connections so the temp file isn't held open, then remove it.
    try:
        engine.dispose()
    except Exception:  # noqa: BLE001 — best-effort teardown
        pass
    shutil.rmtree(_TMP, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Host integration smoke.")
    parser.add_argument("--serve", action="store_true", help="keep server up after")
    parser.add_argument("--host", default="127.0.0.1", help="bind host")
    parser.add_argument("--port", type=int, default=0, help="bind port (0=random)")
    args = parser.parse_args(argv)

    server: uvicorn.Server | None = None
    # atexit safety net: guarantees cleanup even on an unexpected hard exit.
    import atexit
    import signal

    atexit.register(lambda: _cleanup(server))

    # Trap SIGTERM/SIGINT so `--serve` (which blocks) still runs the finally
    # cleanup when killed, not only on Ctrl-C. Convert the signal into a normal
    # KeyboardInterrupt that the serve loop already handles.
    def _on_signal(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    try:
        token = _seed_and_mint()
        port = args.port or _free_port()
        server = _start_server(args.host, port)
        base = f"http://127.0.0.1:{port}"

        print(f"\nHost smoke against {base} (temp DB: {_TMP})\n")
        ok = run_checks(base, token)
        print(f"\n{'All checks passed.' if ok else 'SOME CHECKS FAILED.'}\n")

        if args.serve:
            shown = args.host if args.host != "0.0.0.0" else "<this-machine-LAN-IP>"
            print("Server is up. Open in a browser and paste the token:")
            print(f"    URL:   http://{shown}:{port}/")
            print(f"    token: {token}\n")
            print("Ctrl-C to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

        return 0 if ok else 1
    finally:
        # Runs on success, failure (assertion/return), exception, or Ctrl-C.
        _cleanup(server)
        print(f"Cleaned up temp DB ({_TMP}).")


if __name__ == "__main__":
    raise SystemExit(main())
