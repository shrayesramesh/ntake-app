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
def live_server():
    """Run the real app under uvicorn in a background thread (same process).

    Same-process is required for correctness: the write must go through the
    app's own ``SessionLocal`` (the sessionmaker the 1d seam is bound to) so it
    reaches the module-level ``app_emitter`` the server streams from. Uses the
    app's own engine/DB; the test cleans up the row it writes. Yields the port.
    """
    # Ensure schema exists on the app's own engine (the one SessionLocal uses).
    Base.metadata.create_all(engine)

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
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        # This test exercises the app's real engine (calendar.db). Remove the
        # runtime file so the test leaves no repo artifact (make clean also does).
        db_path = Path("calendar.db")
        if db_path.exists():
            db_path.unlink()


def test_committed_write_delivered_over_real_socket(live_server):
    port = live_server
    result: dict[str, object] = {}

    def reader() -> None:
        try:
            req = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/events/stream", timeout=10
            )
            assert req.headers["content-type"].startswith("text/event-stream")
            for raw in req:
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
    db = SessionLocal()
    fam = Family(name="LiveFam", timezone="America/New_York")
    db.add(fam)
    db.commit()
    fam_id = fam.id
    db.close()

    t.join(timeout=10)

    # Clean up the row we wrote to the shared app DB.
    cleanup = SessionLocal()
    obj = cleanup.get(Family, fam_id)
    if obj is not None:
        cleanup.delete(obj)
        cleanup.commit()
    cleanup.close()

    assert "error" not in result, f"stream reader failed: {result.get('error')}"
    frame = result.get("frame")
    assert frame is not None, "no SSE frame received over the socket"
    assert frame["entity"] == "families"
    assert frame["op"] == "create"
    assert isinstance(frame["id"], int)
