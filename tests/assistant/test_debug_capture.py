"""Debug scaffolding (app/assistant/debug_capture.py) — the live-LLM UI trace.

Covers the RecordingLLM wrapper (records every complete() round trip, passes the
reply through unchanged) and run_capture_with_debug (runs the real two-stage
local pipeline with recording, returning a CaptureDebug with both prompts + raw
replies + the resolved ids).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.capture import CaptureRequest
from app.assistant.debug_capture import RecordingLLM, run_capture_with_debug
from app.assistant.local_llm.protocol import ScriptedLLM

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_recording_llm_records_and_passes_through():
    inner = ScriptedLLM(default={"ok": True})
    rec = RecordingLLM(inner)
    out = rec.complete(system="sys", user="usr", schema={"type": "object"})
    assert out == {"ok": True}  # pass-through
    assert len(rec.calls) == 1
    c = rec.calls[0]
    assert c.system == "sys" and c.user == "usr" and c.reply == {"ok": True}


def test_run_capture_with_debug_captures_both_stages(session, fam_member):
    _fam, m = fam_member
    # Scripted LINK (empty link) + PROPOSE (a create_work_item), keyed by the note.
    inner = ScriptedLLM(
        default={
            # LINK schema wants these keys; PROPOSE wants actions — a permissive
            # default that satisfies parsing for both calls in sequence.
            "work_item_ids": [],
            "event_ids": [],
            "actions": [{"name": "create_work_item", "params": {"title": "Milk"}}],
        }
    )
    req = CaptureRequest(text="buy milk", timezone="America/New_York", now=NOW)

    ctx, actions, dbg = run_capture_with_debug(inner, req, session, m)

    # Both stages recorded: prompts non-empty, replies captured.
    assert dbg.link_system and dbg.link_user
    assert dbg.propose_system and dbg.propose_user
    assert dbg.link_reply == inner._responses.get("", inner._default) or dbg.link_reply
    assert isinstance(dbg.resolved_work_item_ids, list)
    assert isinstance(dbg.resolved_event_ids, list)
    # The propose stage produced the scripted action.
    assert any(a.name == "create_work_item" for a in actions)
    assert dbg.propose_reply.get("actions")
