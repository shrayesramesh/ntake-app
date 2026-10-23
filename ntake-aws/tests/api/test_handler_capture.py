"""Capture handler logic — LINK→PROPOSE, propose-only, writes nothing (§3).

Drives the capture route's core (``handlers._support.run_capture``) over the
in-memory repo + the scripted Anthropic double. Asserts the observable contract:
proposals come back as ``ProposalRead`` with the registry's ground-truth
``action_summary`` and the resolved ``target_label``; and **nothing is persisted**
(v1 capture is propose-only).
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.repository_memory import InMemoryRepository
from core.schemas import CaptureResponse, Family, Member, WorkItem
from handlers._support import run_capture
from tests.harness.anthropic_double import (
    ScriptedAnthropicClient,
    link_response,
    propose_response,
)

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TZ = "America/New_York"


def _seed() -> tuple[InMemoryRepository, Member, WorkItem]:
    repo = InMemoryRepository()
    alex = Member(
        id="m1", family_id="fam1", display_name="Alex", role="adult", created_at=NOW
    )
    repo.seed_family(Family(id="fam1", name="T", timezone=TZ, created_at=NOW), [alex])
    plumber = WorkItem(
        id="w2",
        family_id="fam1",
        title="call plumber",
        status="doing",
        created_at=NOW,
        updated_at=NOW,
    )
    repo.put_work_item(plumber)
    return repo, alex, plumber


def test_capture_returns_proposals_and_writes_nothing() -> None:
    repo, alex, plumber = _seed()
    # Key off structural markers unique to each stage's user message: LINK's
    # user text carries "THE NOTE"; PROPOSE's carries "CONTEXT:". (Both contain
    # the note word "plumber", so key on the stage markers, not the note.)
    client = ScriptedAnthropicClient(
        responses={
            "THE NOTE": link_response({"work_item_ids": ["w2"]}),
            "CONTEXT:": propose_response([{"name": "complete_work_item", "input": {}}]),
        }
    )

    resp = run_capture(repo, client, alex, "the plumber came, it's done")

    assert isinstance(resp, CaptureResponse)
    assert resp.item is None  # propose-only: nothing persisted
    assert [p.name for p in resp.proposals] == ["complete_work_item"]
    card = resp.proposals[0]
    # action_summary is the registry's ground truth, not model narration.
    assert card.action_summary == "Mark the work item done"
    # target attached + labelled from the resolved id.
    assert card.target_id == "w2" and card.target_type == "work_item"
    assert card.target_label == "call plumber"
    # Nothing written.
    got = repo.get_work_item("fam1", "w2")
    assert got is not None and got.status == "doing"


def test_capture_no_action_yields_an_empty_proposal_list_item() -> None:
    repo, alex, _ = _seed()
    client = ScriptedAnthropicClient(
        default=propose_response([{"name": "no_action", "input": {}}])
    )
    resp = run_capture(repo, client, alex, "just musing, nothing to do")
    assert [p.name for p in resp.proposals] == ["no_action"]
    assert resp.item is None


def test_capture_degrades_to_no_proposals_when_model_fails() -> None:
    repo, alex, _ = _seed()

    class _Boom:
        def create_message(self, *a: object, **k: object) -> dict:
            raise RuntimeError("api down")

    resp = run_capture(repo, _Boom(), alex, "anything")
    assert resp.proposals == [] and resp.item is None
