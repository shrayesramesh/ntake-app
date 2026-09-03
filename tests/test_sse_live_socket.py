"""Checkpoint 1e — real-socket SSE integration test (option B).

Proves **actual socket bytes**: a real uvicorn server, a real HTTP client reading
a real ``text/event-stream``, and a write that travels write → 1d seam →
app_emitter → SSE frame on the wire.

Key correctness point: the emit is *in-process* to the server (app_emitter is a
module singleton the seam is bound to at import via ``SessionLocal``). So the
write must happen in the **same process** as the server, through that same
``SessionLocal`` — a separate process or a separate sessionmaker would have its
own (unobserved) emitter. We therefore run uvicorn in a background **thread**
(same process) and read over a **real TCP socket** (a real client, not an
in-process ASGI transport — the latter deadlocks on an infinite SSE stream).

All waits are bounded (boot poll, socket read timeout, thread joins) so a wiring
regression fails loudly instead of hanging the suite.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn

from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Family


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def live_server(monkeypatch):
    """Run the real app under uvicorn in a background thread (same process).

    Same-process is required for correctness: the write must go through the
    app's own ``SessionLocal`` (the sessionmaker the 1d seam is bound to) so it
    reaches the module-level ``app_emitter`` the server streams from. Uses the
    app's own engine/DB; the test cleans up the rows it writes. Also enrolls a
    device token (the stream is now auth-protected). Yields (port, headers).
    """
    from datetime import UTC, datetime

    from app.models import DeviceToken, Member
    from app.tokens import generate_token, hash_token

    # Ensure schema exists on the app's own engine (the one SessionLocal uses).
    Base.metadata.create_all(engine)

    secret = "test-token-secret"
    monkeypatch.setenv("NTAKE_TOKEN_SECRET", secret)

    # Enroll a family/member/token so the auth-protected stream accepts us.
    now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    setup = SessionLocal()
    fam = Family(name="LiveFam", timezone="America/New_York")
    setup.add(fam)
    setup.commit()
    member = Member(family_id=fam.id, display_name="Live", role="adult", created_at=now)
    setup.add(member)
    setup.commit()
    token = generate_token()
    setup.add(
        DeviceToken(
            member_id=member.id,
            token_hash=hash_token(token, secret=secret),
            label="live",
            created_at=now,
        )
    )
    setup.commit()
    fam_id = fam.id
    setup.close()

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Bounded wait for readiness.
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        raise RuntimeError("uvicorn did not start in time")

    try:
        yield port, {"Authorization": f"Bearer {token}"}, fam_id
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        # This test exercises the app's real engine (calendar.db). Remove the
        # runtime file so the test leaves no repo artifact (make clean also does).
        db_path = Path("calendar.db")
        if db_path.exists():
            db_path.unlink()


def test_committed_write_delivered_over_real_socket(live_server):
    port, headers, fam_id = live_server
    result: dict[str, object] = {}

    def reader() -> None:
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/events/stream", headers=headers
            )
            resp = urllib.request.urlopen(req, timeout=10)
            assert resp.headers["content-type"].startswith("text/event-stream")
            for raw in resp:
                line = raw.decode().strip()
                if line.startswith("data:"):
                    result["frame"] = json.loads(line[len("data:") :].strip())
                    break
        except Exception as e:  # surface, don't hang
            result["error"] = repr(e)

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    # Ensure the stream is subscribed on the server before we write.
    time.sleep(1.0)

    # Write through the app's OWN SessionLocal — the sessionmaker the 1d seam is
    # registered on, so this commit publishes to the server's app_emitter.
    from datetime import UTC, datetime

    from app.models import Event

    now = datetime(2026, 9, 1, 15, 0, tzinfo=UTC)
    db = SessionLocal()
    ev = Event(
        family_id=fam_id,
        title="live-event",
        start_at=now,
        end_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(ev)
    db.commit()
    ev_id = ev.id
    db.close()

    t.join(timeout=10)

    # Clean up rows written to the shared app DB (event, member, family).
    cleanup = SessionLocal()
    for model, key in ((Event, ev_id),):
        obj = cleanup.get(model, key)
        if obj is not None:
            cleanup.delete(obj)
    cleanup.commit()
    cleanup.close()

    assert "error" not in result, f"stream reader failed: {result.get('error')}"
    frame = result.get("frame")
    assert frame is not None, "no SSE frame received over the socket"
    assert frame["entity"] == "events"
    assert frame["op"] == "create"
    assert frame["id"] == ev_id
