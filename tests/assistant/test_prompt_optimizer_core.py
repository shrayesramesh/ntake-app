"""Deterministic contracts for synthetic prompt-optimizer cases and scoring."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tools.prompt_optimizer.models import (
    ActionCall,
    LinkLabels,
    PromptCase,
    SyntheticWorld,
    WorldEntity,
)
from tools.prompt_optimizer.scoring import score_actions, score_links
from tools.prompt_optimizer.validation import validate_batch, validate_case

NOW = datetime(2026, 9, 4, 18, 25, tzinfo=UTC)


def _case(**changes) -> PromptCase:
    values = {
        "case_id": "link-event-001",
        "stage": "link",
        "tags": ["link.distractor_precision"],
        "timezone": "America/New_York",
        "now": NOW,
        "capture_author": "[m1] Alex (adult)",
        "world": SyntheticWorld(
            members=[
                WorldEntity(id=1, name="Alex", role="adult"),
                WorldEntity(id=2, name="Sam", role="child"),
            ],
            events=[
                WorldEntity(id=11, title="Piano recital"),
                WorldEntity(id=12, title="Piano lesson"),
            ],
        ),
        "world_view": (
            "FAMILY MEMBERS:\n- [m1] Alex (adult)\n- [m2] Sam (child)"
            "\n\nEVENTS:\n- [e11] Piano recital\n- [e12] Piano lesson"
        ),
        "deep_context": (
            "ALSO ABOUT: [m2] Sam (child)\n\nRELEVANT EVENTS:\n- [e11] Piano recital"
        ),
        "capture": "can we move Sam's piano thing to Wed at 5?",
        "required_links": LinkLabels(event_ids=[11], member_ids=[2]),
        "forbidden_links": LinkLabels(event_ids=[12]),
        "required_actions": [],
        "forbidden_actions": [],
    }
    values.update(changes)
    return PromptCase(**values)


def test_valid_link_case_has_no_validation_errors():
    assert validate_case(_case()) == []


def test_validation_rejects_id_not_in_world():
    case = _case(required_links=LinkLabels(event_ids=[99]))
    assert "required event id 99 is not in world" in validate_case(case)


def test_validation_rejects_internal_capture_token():
    case = _case(capture="move [e11] to Wednesday")
    assert "capture contains internal entity token" in validate_case(case)


def test_validation_rejects_registered_action_name_in_capture():
    case = _case(capture="please create_timed_event for Sam")
    assert "capture contains action/tool name create_timed_event" in validate_case(case)


def test_validation_rejects_conflicting_link_labels():
    case = _case(
        required_links=LinkLabels(event_ids=[11]),
        forbidden_links=LinkLabels(event_ids=[11]),
    )
    assert "required and forbidden event ids overlap: [11]" in validate_case(case)


def test_validation_checks_required_action_registry_contract():
    case = _case(
        stage="propose",
        required_actions=[ActionCall(name="create_timed_event", params={})],
    )
    error = "required action create_timed_event does not satisfy ActionSpec"
    assert error in validate_case(case)


def test_validation_allows_name_only_forbidden_action_foil():
    case = _case(
        stage="propose",
        required_actions=[
            ActionCall(
                name="create_timed_event",
                params={
                    "title": "Piano recital",
                    "local_start_at": "2026-09-09T21:00:00",
                    "local_end_at": "2026-09-09T22:00:00",
                },
            )
        ],
        forbidden_actions=[ActionCall(name="delete_event")],
    )
    assert validate_case(case) == []


def test_validation_rejects_duplicate_case_fingerprint():
    errors = validate_batch([_case(), _case(case_id="link-event-002")])
    assert errors == ["duplicate case fingerprint: link-event-002"]


def test_link_score_tracks_required_recall_and_emitted_precision():
    score = score_links(
        actual_work_item_ids=[],
        actual_event_ids=[11, 12],
        actual_member_ids=[2],
        required=LinkLabels(event_ids=[11], member_ids=[2]),
    )
    assert score.required_recall == 1.0
    assert score.forbidden_precision == pytest.approx(2 / 3)
    assert score.unexpected == ["event:12"]


def test_link_score_empty_output_is_precise_for_no_link_case():
    score = score_links(
        actual_work_item_ids=[],
        actual_event_ids=[],
        actual_member_ids=[],
        required=LinkLabels(),
    )
    assert score.required_recall == 1.0
    assert score.forbidden_precision == 1.0


def test_action_score_is_order_independent_and_detects_extra_action():
    required = [
        ActionCall(name="complete_work_item"),
        ActionCall(name="set_due_date", params={"local_due_at": "2026-09-05T19:00:00"}),
    ]
    actual = [
        {"name": "set_due_date", "params": {"local_due_at": "2026-09-05T19:00:00"}},
        {"name": "complete_work_item", "params": {}},
        {"name": "move_to_on_deck", "params": {}},
    ]
    score = score_actions(actual=actual, required=required)
    assert score.required_recall == 1.0
    assert score.forbidden_precision == pytest.approx(2 / 3)
    assert score.unexpected == ["move_to_on_deck:{}"]


def test_action_score_tracks_missing_required_action():
    score = score_actions(
        actual=[],
        required=[ActionCall(name="no_action")],
    )
    assert score.required_recall == 0.0
    assert score.forbidden_precision == 0.0


def test_action_score_ignores_free_text_payload_values():
    required = [
        ActionCall(
            name="create_work_item",
            params={
                "title": "Field day kit",
                "description": "Pack items for Friday",
                "checklist_items": ["sunscreen", "water bottles"],
            },
        )
    ]
    actual = [
        {
            "name": "create_work_item",
            "params": {
                "title": "Field-day supplies",
                "description": "Bring supplies to school",
                "checklist_items": ["sunblock", "drinks"],
            },
        }
    ]

    score = score_actions(actual=actual, required=required)

    assert score.required_recall == 1.0
    assert score.forbidden_precision == 1.0


def test_action_score_retains_datetime_params_but_not_event_title():
    required = [
        ActionCall(
            name="create_timed_event",
            params={
                "title": "Milo school play",
                "local_start_at": "2026-09-09T21:00:00",
                "local_end_at": "2026-09-09T22:00:00",
            },
        )
    ]
    matching_time = [
        {
            "name": "create_timed_event",
            "params": {
                "title": "School play for Milo",
                "local_start_at": "2026-09-09T21:00:00",
                "local_end_at": "2026-09-09T22:00:00",
            },
        }
    ]
    wrong_time = [
        {
            "name": "create_timed_event",
            "params": {
                "title": "Milo school play",
                "local_start_at": "2026-09-09T22:00:00",
                "local_end_at": "2026-09-09T23:00:00",
            },
        }
    ]

    assert score_actions(actual=matching_time, required=required).required_recall == 1.0
    assert score_actions(actual=wrong_time, required=required).required_recall == 0.0


def test_action_score_retains_identifier_params():
    required = [ActionCall(name="assign_work_item", params={"member_id": 2})]
    actual = [{"name": "assign_work_item", "params": {"member_id": 3}}]

    score = score_actions(actual=actual, required=required)

    assert score.required_recall == 0.0
    assert score.forbidden_precision == 0.0
