"""Stage 1 — CaptureResolver.focus(): CaptureRequest -> FocusedContext (DB lookups).

The ``CaptureResolver`` seam is the app-coupled resolver: it queries the DB and
produces the *focused world* stage 2 reasons over. Post-reshape (WORKPLAN-A2) the
``FocusedContext`` carries the resolved entity ids + the ``deep_context`` string
(NOT the legacy ``calendar_window``). ``FakeCaptureResolver`` runs the real
two-call *shape* with a deterministic, model-free LINK.

``render_focus`` and the FocusedContext shape are pinned in ``test_context.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.assistant.base import CaptureResolver
from app.assistant.context import CaptureRequest, FocusedContext
from app.assistant.fake import FakeCaptureResolver

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _req(text="hello") -> CaptureRequest:
    return CaptureRequest(text=text, timezone="America/New_York", now=NOW)


def test_focus_returns_focused_context_passing_through_raw_fields(session, fam_member):
    fam, m = fam_member
    ctx = FakeCaptureResolver().focus(_req("call plumber"), session, m)
    assert isinstance(ctx, FocusedContext)
    assert ctx.text == "call plumber"
    assert ctx.timezone == "America/New_York"
    assert ctx.now == NOW


def test_focus_deep_context_includes_the_member_header(session, fam_member):
    fam, m = fam_member
    ctx = FakeCaptureResolver().focus(_req("call plumber"), session, m)
    # deep_context always renders at least the member header (their footprint).
    assert isinstance(ctx.deep_context, str)
    assert m.display_name in ctx.deep_context


# --- the CaptureResolver seam contract ------------------------------------


def test_fake_capture_resolver_is_a_capture_resolver():
    assert isinstance(FakeCaptureResolver(), CaptureResolver)


def test_capture_resolver_abc_cannot_be_instantiated():
    with pytest.raises(TypeError):
        CaptureResolver()  # type: ignore[abstract]
