"""REST write routes — create a work item, append a human update (§4).

The two direct (non-assistant) writes the reference app exposed:
``POST /work-items`` (201 → ``WorkItemRead``) and
``POST /work-items/{id}/updates`` (201 → ``WorkItemUpdateRead``). Driven over the
in-memory repo + a fake poster. Each write lands via the repository and is
announced **once** to the family's live connections (the same publish boundary
confirm uses); a missing work item is a ``KeyError`` the shell maps to 404, and a
malformed body is a ``ValueError`` it maps to 400.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from core.repository_memory import InMemoryRepository
from core.schemas import Family, Member, WorkItem
from handlers._support import append_human_update, create_work_item

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TZ = "America/New_York"


def _seed() -> tuple[InMemoryRepository, Member]:
    repo = InMemoryRepository()
    alex = Member(
        id="m1", family_id="fam1", display_name="Alex", role="adult", created_at=NOW
    )
    repo.seed_family(Family(id="fam1", name="T", timezone=TZ, created_at=NOW), [alex])
    repo.put_connection("fam1", "c1", "m1")
    return repo, alex


def _poster(sink: list[dict]):
    def poster(connection_id: str, data: str) -> bool:
        sink.append(json.loads(data))
        return True

    return poster


# --- POST /work-items ------------------------------------------------------


def test_create_work_item_persists_and_announces_once() -> None:
    repo, alex = _seed()
    posted: list[dict] = []

    read = create_work_item(
        repo, alex, {"title": "Buy milk", "tags": ["home"]}, poster=_poster(posted)
    )

    stored = repo.get_work_item("fam1", read.id)
    assert stored is not None
    assert stored.title == "Buy milk" and stored.tags == ["home"]
    assert stored.status == "todo" and stored.updates == []  # no assistant log
    assert read.title == "Buy milk" and read.family_id == "fam1"
    assert posted == [{"entity": "work_item", "id": read.id, "op": "create"}]


@pytest.mark.parametrize(
    "body", [{}, {"title": ""}, {"title": 3}, {"title": "x", "tags": "a"}]
)
def test_create_work_item_rejects_malformed_body(body: dict) -> None:
    repo, alex = _seed()
    posted: list[dict] = []
    with pytest.raises(ValueError):
        create_work_item(repo, alex, body, poster=_poster(posted))
    assert posted == []  # nothing written, nothing announced


def _taxes() -> WorkItem:
    return WorkItem(
        id="w2", family_id="fam1", title="Taxes", created_at=NOW, updated_at=NOW
    )


# --- POST /work-items/{id}/updates -----------------------------------------


def test_append_human_update_logs_and_announces_once() -> None:
    repo, alex = _seed()
    repo.put_work_item(_taxes())
    posted: list[dict] = []

    read = append_human_update(
        repo, alex, "w2", {"body": "found the W-2"}, poster=_poster(posted)
    )

    stored = repo.get_work_item("fam1", "w2")
    assert stored is not None
    assert [(u.source, u.author_id, u.body) for u in stored.updates] == [
        ("human", "m1", "found the W-2")
    ]
    assert read.work_item_id == "w2" and read.source == "human"
    assert read.id == stored.updates[0].update_id
    assert posted == [{"entity": "work_item", "id": "w2", "op": "update"}]


def test_append_human_update_missing_item_raises_key_error() -> None:
    repo, alex = _seed()
    posted: list[dict] = []
    with pytest.raises(KeyError):
        append_human_update(repo, alex, "nope", {"body": "x"}, poster=_poster(posted))
    assert posted == []


@pytest.mark.parametrize("body", [{}, {"body": ""}, {"body": 7}])
def test_append_human_update_rejects_malformed_body(body: dict) -> None:
    repo, alex = _seed()
    repo.put_work_item(_taxes())
    posted: list[dict] = []
    with pytest.raises(ValueError):
        append_human_update(repo, alex, "w2", body, poster=_poster(posted))
    assert posted == []
