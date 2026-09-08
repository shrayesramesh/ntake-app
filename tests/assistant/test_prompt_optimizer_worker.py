"""Evaluation-worker tests for external prompt optimizer code."""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.local_llm import link, propose
from app.assistant.local_llm.protocol import ScriptedLLM
from tools.prompt_optimizer.models import (
    LinkLabels,
    PromptCase,
    SyntheticWorld,
    WorldEntity,
)
from tools.prompt_optimizer.worker import evaluate_cases

NOW = datetime(2026, 9, 4, 18, 25, tzinfo=UTC)


def _link_case() -> PromptCase:
    return PromptCase(
        case_id="link-001",
        stage="link",
        tags=["link.correct_event"],
        timezone="America/New_York",
        now=NOW,
        capture_author="[m1] Alex (adult)",
        world=SyntheticWorld(events=[WorldEntity(id=11, title="Piano recital")]),
        world_view="EVENTS:\n- [e11] Piano recital",
        deep_context="RELEVANT EVENTS:\n- [e11] Piano recital",
        capture="move the recital",
        required_links=LinkLabels(event_ids=[11]),
    )


def _propose_case() -> PromptCase:
    return PromptCase(
        case_id="propose-001",
        stage="propose",
        tags=["propose.no_action"],
        timezone="America/New_York",
        now=NOW,
        capture_author="[m1] Alex (adult)",
        world=SyntheticWorld(),
        world_view="EVENTS:\n- (none)",
        deep_context="RELEVANT EVENTS:\n- (none)",
        capture="nothing to change",
        required_actions=[],
    )


def test_link_worker_scores_scripted_reply_and_restores_template():
    original = link.LINK_SYSTEM
    llm = ScriptedLLM(
        default={"work_item_ids": [], "event_ids": [11], "member_ids": []}
    )

    results = evaluate_cases(
        stage="link",
        cases=[_link_case()],
        llm=llm,
        template="CUSTOM LINK {timezone} {now}",
    )

    assert results[0].score.required_recall == 1.0
    assert results[0].score.forbidden_precision == 1.0
    assert "CUSTOM LINK" in results[0].system
    assert link.LINK_SYSTEM == original


def test_propose_worker_uses_actual_tools_schema_and_scores_raw_envelope():
    llm = ScriptedLLM(default={"actions": [{"name": "no_action", "params": {}}]})

    results = evaluate_cases(stage="propose", cases=[_propose_case()], llm=llm)

    assert results[0].score.required_recall == 1.0
    assert results[0].score.forbidden_precision == 0.0
    assert results[0].raw_reply == {"actions": [{"name": "no_action", "params": {}}]}
    assert "AVAILABLE TOOLS:" in results[0].user
    assert propose.PROPOSE_SYSTEM.startswith("You are a household assistant.")
