"""Meta action behavior."""

from __future__ import annotations

from app.assistant.actions.registry import apply_action
from app.persistence.models import Event, WorkItemUpdate


def test_no_action_does_nothing(session, fam_member_item):
    fam, m, wi = fam_member_item

    apply_action(session, m, "no_action", wi.id, {})

    session.expire_all()
    assert session.query(WorkItemUpdate).count() == 0  # no update appended
    assert session.query(Event).count() == 0
