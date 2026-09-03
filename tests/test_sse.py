"""SSE / change-emitter subsystem — the write → publish → stream path.

Consolidates three checkpoint-era files (the emitter unit, the subscribe wiring,
and the real-socket integration) into one module for the SSE feature:

* **Emitter unit** — ``InProcessEmitter.emit`` fans out to listeners.
* **Subscribe wiring (1e)** — a published change lands on a subscriber's queue,
  formatted as the SSE message; unsubscribe detaches. Unit-tested directly
  against ``app.main.subscribe`` (the endpoint's ``while True`` never completes,
  so we test the wiring, not the ASGI stream).
* **Real-socket integration (1e, option B)** — a real uvicorn server + real TCP
  client prove actual ``text/event-stream`` bytes travel write → 1d seam →
  app_emitter → SSE frame on the wire.

The 1d commit→publish seam itself is proven in test_write_seam.py.
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
from app.event_emitter import InProcessEmitter
from app.main import _format_change, app, subscribe
from app.models import Family

# --- emitter unit ---------------------------------------------------------


@pytest.mark.asyncio
async def test_emit():
    emitter = InProcessEmitter()
    received = []

    async def listener(entity, id, op):
        received.append((entity, id, op))

    emitter.add_listener(listener)

    await emitter.emit("event", 123, "create")

    assert received == [("event", 123, "create")]


# --- subscribe wiring (1e) ------------------------------------------------


def test_format_change_shape():
    msg = _format_change("events", 7, "create")
    assert msg["event"] == "change"
    assert json.loads(msg["data"]) == {"entity": "events", "id": 7, "op": "create"}


@pytest.mark.asyncio
async def test_subscribe_receives_emitted_change():
    emitter = InProcessEmitter()
    queue, unsubscribe = subscribe(emitter)

    await emitter.emit("families", 3, "update")

    assert queue.get_nowait() == ("families", 3, "update")

    # Unsubscribing detaches the listener so later emits are not received.
    unsubscribe()
    await emitter.emit("families", 4, "create")
    assert queue.empty()


# --- real-socket integration (1e, option B) -------------------------------


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
