"""Confirm handler logic — execute → write → publish once (§4.2).

Drives ``handlers._support.run_confirm`` over the in-memory repo + a fake poster.
Asserts: a confirmed action writes via the registry; exactly one ``{entity,id,op}``
nudge is published to the family's live connections; ``no_action`` writes/publishes
nothing; and an invalid action raises ``ActionError`` (the shell maps it to 422).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.engine.engine import ActionError
from core.repository_memory import InMemoryRepository
from core.schemas import Family, Member, WorkItem
from handlers._support import run_confirm

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TZ = "America/New_York"


def _seed() -> tuple[InMemoryRepository, Member, WorkItem]:
    repo = InMemoryRepository()
    alex = Member(
        id="m1", family_id="fam1", display_name="Alex", role="adult", created_at=NOW
    )
    repo.seed_family(Family(id="fam1", name="T", timezone=TZ, created_at=NOW), [alex])
    wi = WorkItem(
        id="w2",
        family_id="fam1",
        title="call plumber",
        status="doing",
        created_at=NOW,
        updated_at=NOW,
    )
    repo.put_work_item(wi)
    return repo, alex, wi


def _poster(sink: list[tuple[str, str]]):
    def poster(connection_id: str, data: str) -> bool:
        sink.append((connection_id, data))
        return True

    return poster


def test_confirm_executes_writes_and_publishes_once() -> None:
    repo, alex, wi = _seed()
    repo.put_connection("fam1", "c1", "m1")
    posted: list[tuple[str, str]] = []

    result = run_confirm(
        repo,
        alex,
        name="complete_work_item",
        params={},
        target_id="w2",
        target_type="work_item",
        poster=_poster(posted),
    )

    assert result["applied"] == "complete_work_item"
    # The write landed.
    got = repo.get_work_item("fam1", "w2")
    assert got is not None and got.status == "done"
    # Exactly one nudge, to the one live connection, naming the target.
    assert len(posted) == 1
    assert posted[0][0] == "c1"
    import json

    assert json.loads(posted[0][1]) == {
        "entity": "work_item",
        "id": "w2",
        "op": "update",
    }


def test_confirm_no_action_writes_and_publishes_nothing() -> None:
    repo, alex, _ = _seed()
    repo.put_connection("fam1", "c1", "m1")
    posted: list[tuple[str, str]] = []

    result = run_confirm(
        repo,
        alex,
        name="no_action",
        params={},
        target_id=None,
        target_type=None,
        poster=_poster(posted),
    )

    assert result["applied"] == "no_action"
    assert posted == []  # nothing happened, nothing announced


def test_confirm_invalid_action_raises_action_error() -> None:
    repo, alex, _ = _seed()
    posted: list[tuple[str, str]] = []
    # set_due_date requires local_due_at; omitting it is an ActionError (→ 422).
    with pytest.raises(ActionError):
        run_confirm(
            repo,
            alex,
            name="set_due_date",
            params={},
            target_id="w2",
            target_type="work_item",
            poster=_poster(posted),
        )
    assert posted == []  # no publish on a failed write


def test_confirm_create_publishes_a_create_nudge() -> None:
    repo, alex, _ = _seed()
    repo.put_connection("fam1", "c1", "m1")
    posted: list[tuple[str, str]] = []

    run_confirm(
        repo,
        alex,
        name="create_work_item",
        params={"title": "New task"},
        target_id=None,
        target_type=None,
        poster=_poster(posted),
    )

    import json

    # A creator has no single target id; it nudges the entity class to refetch.
    assert len(posted) == 1
    msg = json.loads(posted[0][1])
    assert msg["entity"] == "work_item" and msg["op"] == "create"
