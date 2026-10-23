"""Live-sync publish — fan-out, the message contract, pruning (AWS_LLD §4.2).

Tier-1 unit tests for ``publish_change`` over the in-memory repo with a fake
poster. Pin: the ``{entity, id, op}`` JSON contract, fan-out to every live
connection, gone-connection pruning, and best-effort error swallowing (a dead
socket never fails the write). The single-call-site invariant is asserted
separately as a boundary test.
"""

from __future__ import annotations

import json

from core.live_sync import publish_change
from core.repository_memory import InMemoryRepository


def _repo_with_connections(*connection_ids: str) -> InMemoryRepository:
    repo = InMemoryRepository()
    for cid in connection_ids:
        repo.put_connection("fam1", cid, "m1")
    return repo


def test_publishes_entity_id_op_to_every_connection() -> None:
    repo = _repo_with_connections("c1", "c2")
    posted: list[tuple[str, str]] = []

    def poster(connection_id: str, data: str) -> bool:
        posted.append((connection_id, data))
        return True

    publish_change(repo, "fam1", "work_item", "w9", "update", poster=poster)

    assert {cid for cid, _ in posted} == {"c1", "c2"}
    # Every message is the exact {entity, id, op} contract.
    for _cid, data in posted:
        assert json.loads(data) == {"entity": "work_item", "id": "w9", "op": "update"}


def test_no_connections_is_a_noop() -> None:
    repo = InMemoryRepository()
    calls = 0

    def poster(connection_id: str, data: str) -> bool:
        nonlocal calls
        calls += 1
        return True

    publish_change(repo, "fam1", "event", "e1", "create", poster=poster)
    assert calls == 0


def test_gone_connection_is_pruned() -> None:
    repo = _repo_with_connections("live", "dead")

    def poster(connection_id: str, data: str) -> bool:
        return connection_id != "dead"  # "dead" reports gone (410)

    publish_change(repo, "fam1", "event", "e1", "create", poster=poster)

    # The dead socket is pruned; the live one remains.
    assert repo.list_connections("fam1") == ["live"]


def test_poster_error_is_swallowed_and_does_not_prune() -> None:
    repo = _repo_with_connections("c1", "c2")

    def poster(connection_id: str, data: str) -> bool:
        if connection_id == "c1":
            raise RuntimeError("transient transport error")
        return True

    # Must not raise; a transient error is swallowed (not treated as gone).
    publish_change(repo, "fam1", "work_item", "w1", "delete", poster=poster)
    # c1 is NOT pruned (error != gone); both connections remain.
    assert set(repo.list_connections("fam1")) == {"c1", "c2"}
