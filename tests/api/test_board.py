"""Phase 3, checkpoint 5 — read-only board projection.

GET /board returns non-archived work items grouped into the 4 fixed columns
(todo / on_deck / doing / done), ordered within each column. Read-only: no
archive/move actions (GROOM deferred). Auth-protected.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.persistence.models import Family, WorkItem

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
COLUMNS = ["todo", "on_deck", "doing", "done"]


def _item(session, fam_id, *, status="todo", position=0, title="X", archived=False):
    wi = WorkItem(
        family_id=fam_id,
        title=title,
        status=status,
        position=position,
        created_at=NOW,
        updated_at=NOW,
        archived_at=NOW if archived else None,
    )
    session.add(wi)
    session.commit()
    return wi


def test_board_requires_auth(client):
    assert client.get("/board").status_code == 401


def test_board_has_all_four_columns_even_when_empty(client, auth_headers):
    r = client.get("/board", headers=auth_headers)
    assert r.status_code == 200
    board = r.json()
    assert list(board.keys()) == COLUMNS
    assert all(board[c] == [] for c in COLUMNS)


def test_board_groups_items_by_status(client, session, auth_headers):
    fam = session.query(Family).first()
    if fam is None:
        fam = Family(name="F", timezone="UTC")
        session.add(fam)
        session.commit()
    _item(session, fam.id, status="todo", title="a")
    _item(session, fam.id, status="doing", title="b")
    _item(session, fam.id, status="doing", title="c")
    _item(session, fam.id, status="done", title="d")

    board = client.get("/board", headers=auth_headers).json()
    assert [wi["title"] for wi in board["todo"]] == ["a"]
    assert {wi["title"] for wi in board["doing"]} == {"b", "c"}
    assert [wi["title"] for wi in board["done"]] == ["d"]
    assert board["on_deck"] == []


def test_board_excludes_archived(client, session, auth_headers):
    fam = Family(name="F", timezone="UTC")
    session.add(fam)
    session.commit()
    _item(session, fam.id, status="done", title="visible")
    _item(session, fam.id, status="done", title="archived", archived=True)

    board = client.get("/board", headers=auth_headers).json()
    titles = [wi["title"] for wi in board["done"]]
    assert titles == ["visible"]


def test_board_orders_within_column_by_position(client, session, auth_headers):
    fam = Family(name="F", timezone="UTC")
    session.add(fam)
    session.commit()
    _item(session, fam.id, status="todo", position=2, title="second")
    _item(session, fam.id, status="todo", position=1, title="first")

    board = client.get("/board", headers=auth_headers).json()
    assert [wi["title"] for wi in board["todo"]] == ["first", "second"]
