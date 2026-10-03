"""Input-validation error paths across the ported handlers (AWS_LLD §2).

The handlers normalize/validate model-supplied params and raise
:class:`ActionError` on malformed input (dropped by the propose seam rather than
failing the request). These negative-path tests pin those branches — the
counterpart to the happy-path flows in ``test_action_handlers.py``.
"""

from __future__ import annotations

import pytest

from core.actions.registry import apply_action
from core.engine.engine import ActionError
from core.repository_memory import InMemoryRepository
from core.schemas import Member, TargetType
from tests.harness.factories import make_family, make_member, make_timed_event


def _seeded() -> tuple[InMemoryRepository, str, Member]:
    repo = InMemoryRepository()
    fam = make_family()
    member = make_member(fam.id, display_name="Alex")
    repo.seed_family(fam, [member])
    return repo, fam.id, member


def test_event_location_must_be_non_empty() -> None:
    repo, fam_id, member = _seeded()
    ev = make_timed_event(fam_id, title="meet")
    repo.put_event(ev)
    with pytest.raises(ActionError, match="location must be a non-empty string"):
        apply_action(
            repo,
            member,
            "set_event_location",
            ev.id,
            {"location": "  "},
            TargetType.EVENT,
        )


def test_event_participants_must_be_a_non_empty_list() -> None:
    repo, fam_id, member = _seeded()
    ev = make_timed_event(fam_id, title="meet")
    repo.put_event(ev)
    with pytest.raises(ActionError, match="participants must be a non-empty list"):
        apply_action(
            repo,
            member,
            "add_event_participants",
            ev.id,
            {"participants": []},
            TargetType.EVENT,
        )


def test_event_participant_entries_must_be_non_empty_names() -> None:
    repo, fam_id, member = _seeded()
    ev = make_timed_event(fam_id, title="meet")
    repo.put_event(ev)
    with pytest.raises(ActionError, match="each participant must be a non-empty name"):
        apply_action(
            repo,
            member,
            "add_event_participants",
            ev.id,
            {"participants": [" "]},
            TargetType.EVENT,
        )


def test_event_tags_entries_must_be_non_empty_strings() -> None:
    repo, fam_id, member = _seeded()
    ev = make_timed_event(fam_id, title="meet")
    repo.put_event(ev)
    with pytest.raises(ActionError, match="each tag must be a non-empty string"):
        apply_action(
            repo, member, "set_event_tags", ev.id, {"tags": [""]}, TargetType.EVENT
        )


def test_create_work_item_rejects_empty_checklist_entries() -> None:
    repo, fam_id, member = _seeded()
    with pytest.raises(ActionError, match="items must be a non-empty list of strings"):
        apply_action(
            repo,
            member,
            "create_work_item",
            None,
            {"title": "x", "checklist_items": [" "]},
        )
