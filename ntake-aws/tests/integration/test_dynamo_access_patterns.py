"""Tier-2: the irreducible DynamoDB-only contracts (AWS_LLD §1).

Trimmed to the single-table mechanics that **only the real table can tell the
truth about** — the properties where the in-memory double and DynamoDB can
genuinely disagree, which is the entire reason Tier 2 exists. Everything that is
repository *semantics* (archived-exclusion, board grouping/ordering, family
scoping, calendar unify/range, the due-bridge, all-day timezone math, the
co-created pair's observable outcome) is pinned exactly and instantly at Tier 1
in ``tests/data/test_repository_flows.py`` via the backend-agnostic ``repo``
fixture — re-running those bodies against the real table only duplicates logic
and adds latency/flake, so they are not repeated here.

What remains is irreducible:

* **Write primitives.** The ``TransactWriteItems`` co-created pair and the
  single-``Put`` standalone create — asserted via call-spies. In-memory has no
  transaction/serializer, so the double-serialization + ``list_append``
  operand-type bugs (both found at Tier 2) can only surface here.
* **Raw GSI key shape + sparse drop-out.** The literal ``STATUS#…#POS#…`` /
  ``TS#…`` sort keys in the actual index, and their removal on archive/clear —
  in-memory has no GSI, and a happy-path flow never asserts a key *disappeared*.
* **GSI eventual consistency.** One representative drop-out read through the repo
  (archive → leaves the calendar) exercised with ``poll_until`` — a behavior the
  synchronous in-memory double cannot even exhibit.

Seeds carry the ``itest-`` prefix (integration conftest) so the cleanup sweep
removes every row this suite writes.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from unittest import mock

from adapters.dynamo_repository import DynamoRepository
from core.schemas import EventProvenance
from tests.harness.factories import (
    make_family,
    make_member,
    make_timed_event,
    make_update,
    make_work_item,
    seed_family,
)


def _titles(rows: Any) -> list[str]:
    return [r.title for r in rows]


# --- write primitives: the one transaction vs. the single Put --------------


def test_co_created_event_transact_writes_both_sides(
    dynamo_repo: DynamoRepository,
) -> None:
    """create_event_from_update is one TransactWriteItems: the event Put and the
    work-item log append both land (base-table reads → strongly consistent, no
    poll needed). The double-serialization + list_append operand-type bugs lived
    in this transaction path; only the real table surfaces them."""
    repo = dynamo_repo
    fam = make_family()
    mem = make_member(fam.id, display_name="Alex")
    seed_family(repo, fam, [mem])
    wi = make_work_item(fam.id, title="plan party")
    repo.put_work_item(wi)

    log_entry = make_update(
        author_id=mem.id, source="assistant", body="Created calendar event: Party"
    )
    ev = make_timed_event(
        fam.id,
        title="Party",
        source_update_id=log_entry.update_id,
        provenance=EventProvenance(
            work_item_id=wi.id,
            member_id=mem.id,
            member_name=mem.display_name,
            note_snippet="plan party",
            at=datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        ),
    )
    repo.create_event_from_update(ev, log_entry)

    got_ev = repo.get_event(fam.id, ev.id)
    assert got_ev is not None and got_ev.source_update_id == log_entry.update_id
    got_wi = repo.get_work_item(fam.id, wi.id)
    assert got_wi is not None
    assert [u.body for u in got_wi.updates] == ["Created calendar event: Party"]


def test_standalone_event_create_is_a_single_put(
    dynamo_repo: DynamoRepository,
) -> None:
    """A standalone event create goes through one ``put_item`` and NO
    ``transact_write_items`` (the co-created path is the only transaction)."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])

    with (
        mock.patch.object(
            repo._table, "put_item", wraps=repo._table.put_item
        ) as put_spy,
        mock.patch.object(
            repo._ddb,
            "transact_write_items",
            wraps=repo._ddb.transact_write_items,
        ) as transact_spy,
    ):
        repo.put_event(make_timed_event(fam.id, title="standalone"))

    assert put_spy.call_count == 1
    assert transact_spy.call_count == 0


# --- raw GSI assertions: verify the INDEX directly + sparse drop-out --------


def _gsi_sks(repo: DynamoRepository, index: str, pk_attr: str, pk_value: str) -> Any:
    """All sort-key values currently in ``index`` under ``pk_value`` (raw query)."""
    from boto3.dynamodb.conditions import Key

    sk_attr = "GSI1SK" if index == "GSI1" else "GSI2SK"
    resp = repo._table.query(
        IndexName=index, KeyConditionExpression=Key(pk_attr).eq(pk_value)
    )
    return sorted(i[sk_attr] for i in resp.get("Items", []))


def test_gsi1_index_holds_board_keys_and_drops_on_archive(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """GSI1 itself carries ``STATUS#…#POS#…`` for an unarchived item and loses it
    on archive — asserted by querying the index directly."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    wi = make_work_item(fam.id, title="x", status="doing", position=3)
    repo.put_work_item(wi)
    gsi1pk = f"FAM#{fam.id}#BOARD"

    keys = poll_until(
        lambda: _gsi_sks(repo, "GSI1", "GSI1PK", gsi1pk),
        expected=["STATUS#doing#POS#000003"],
    )
    assert keys == ["STATUS#doing#POS#000003"]  # exact sort-key shape in the index

    repo.archive_work_item(fam.id, wi.id)
    keys = poll_until(lambda: _gsi_sks(repo, "GSI1", "GSI1PK", gsi1pk), expected=[])
    assert keys == []  # the sparse key is gone from the index entirely


def test_gsi2_index_holds_event_and_due_keys_and_drops_them(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """GSI2 itself carries a ``TS#…#EV#`` key for an event and a ``TS#…#WI#`` key
    for a due-dated item; deleting the event and clearing the due date remove
    them — asserted by querying the index directly."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    ev = make_timed_event(
        fam.id, title="ev", start_at=datetime(2026, 2, 1, 9, 0, tzinfo=UTC)
    )
    due = make_work_item(
        fam.id, title="due", due_at=datetime(2026, 2, 5, 12, 0, tzinfo=UTC)
    )
    repo.put_event(ev)
    repo.put_work_item(due)
    gsi2pk = f"FAM#{fam.id}#CAL"

    keys = poll_until(
        lambda: _gsi_sks(repo, "GSI2", "GSI2PK", gsi2pk),
        expected=[
            f"TS#2026-02-01T09:00:00.000000Z#EV#{ev.id}",
            f"TS#2026-02-05T12:00:00.000000Z#WI#{due.id}",
        ],
    )
    assert keys == [
        f"TS#2026-02-01T09:00:00.000000Z#EV#{ev.id}",
        f"TS#2026-02-05T12:00:00.000000Z#WI#{due.id}",
    ]

    repo.delete_event(fam.id, ev.id)
    repo.update_work_item(fam.id, due.id, {"due_at": None})
    keys = poll_until(lambda: _gsi_sks(repo, "GSI2", "GSI2PK", gsi2pk), expected=[])
    assert keys == []  # both sparse calendar keys removed from the index


# --- GSI eventual consistency: one representative drop-out through the repo --


def test_archive_drops_due_item_from_calendar(
    dynamo_repo: DynamoRepository, poll_until: Callable[..., Any]
) -> None:
    """Archiving a due-dated item drops it from the calendar (GSI2 sparse), read
    back through ``list_calendar`` — the representative eventual-consistency
    drop-out the synchronous in-memory double cannot exhibit."""
    repo = dynamo_repo
    fam = make_family()
    seed_family(repo, fam, [])
    due = make_work_item(
        fam.id, title="due", status="done", due_at=datetime(2026, 2, 5, tzinfo=UTC)
    )
    repo.put_work_item(due)
    window = (datetime(2026, 2, 1, tzinfo=UTC), datetime(2026, 3, 1, tzinfo=UTC))
    poll_until(
        lambda: repo.list_calendar(fam.id, *window), expected=["due"], key=_titles
    )

    repo.archive_work_item(fam.id, due.id)
    rows = poll_until(
        lambda: repo.list_calendar(fam.id, *window), expected=[], key=_titles
    )
    assert _titles(rows) == []
