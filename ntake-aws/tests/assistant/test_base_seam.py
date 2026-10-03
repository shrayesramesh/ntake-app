"""The assistant stage-1 contract (core/assistant/base.py) — the ``CaptureResolver``
seam, ported in Session 3 onto the ``Repository`` + DTO ``Member`` (AWS_LLD §2).

A concrete resolver (the fake/LINK backends) arrives in Session 4; here we only
pin the contract shape — the seam is an ABC that takes ``(request, repo, member)``
and returns a ``FocusedContext`` — and that the shared value types re-export from
one spot.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.assistant.base import (
    AssistantClient,
    CaptureRequest,
    CaptureResolver,
    FocusedContext,
    NullAssistant,
    ProposedAction,
)
from core.repository import Repository
from core.repository_memory import InMemoryRepository
from core.schemas import Member


class _StubResolver(CaptureResolver):
    """A trivial resolver proving the seam can be implemented over the repo."""

    def focus(
        self, request: CaptureRequest, repo: Repository, member: Member
    ) -> FocusedContext:
        return FocusedContext(
            text=request.text,
            timezone=request.timezone,
            now=request.now,
            deep_context=f"{member.display_name}: {request.text}",
        )


def test_capture_resolver_seam_takes_repo_and_member() -> None:
    resolver = _StubResolver()
    member = Member(
        id="mem1",
        family_id="fam1",
        display_name="Alex",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    request = CaptureRequest(text="buy milk", timezone="UTC", now=datetime.now(UTC))
    focused = resolver.focus(request, InMemoryRepository(), member)
    assert isinstance(focused, FocusedContext)
    assert focused.deep_context == "Alex: buy milk"


def test_base_reexports_stage2_contracts() -> None:
    # The one-spot re-export: a backend imports every contract from base.
    assert issubclass(NullAssistant, AssistantClient)
    empty_ctx = FocusedContext(text="", timezone="UTC", now=datetime.now(UTC))
    assert NullAssistant().propose(empty_ctx) == []
    assert ProposedAction(name="no_action", params={}).name == "no_action"
