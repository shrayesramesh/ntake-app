"""``DynamoRepository`` — the boto3 single-table persistence seam (AWS_LLD §2.2).

The real-table twin of :class:`core.repository_memory.InMemoryRepository`: it
satisfies the same :class:`core.repository.Repository` ``Protocol``, so the
exact flow tests Tier 1 runs in-memory run **unchanged** against the real
``ntake-dev`` table at Tier 2 (``make integration``). This module is the **only**
place ``boto3`` is imported for persistence, and the **only** place table-key
knowledge is *applied* — the key/sort *derivation* lives in
:mod:`core.repository` and is reused here byte-for-byte (DRY: one source of how a
key is composed; the engine boundary test keeps ``boto3`` out of ``core``).

Design (AWS_LLD §1):

* **Item shape.** Each DTO is stored as its ``model_dump(mode="json")`` payload
  (ISO strings for datetimes/dates) plus the key attributes ``PK``/``SK`` and —
  when the item participates — the sparse GSI keys. Reads strip the key/`_type`
  attributes and ``model_validate`` the DTO back, so the serialized form never
  leaks into the DTO contract.
* **Sparse GSIs.** ``GSI1`` (board) keys are written **only when ``archived_at``
  is null**, so archiving drops the item from the board with no delete.
  ``GSI2`` (calendar) keys are written on events and on **due-dated, unarchived**
  work items (the calendar/due-date bridge); clearing a due date, archiving, or
  deleting removes them.
* **Atomicity.** Intra-item writes are one ``UpdateItem``; the single cross-item
  method ``create_event_from_update`` is one ``TransactWriteItems`` (event ``Put``
  + work-item ``list_append`` ``UpdateItem``). Standalone ``put_event`` is a
  single ``Put``.
* **Configurability.** The constructor takes the table name plus optional
  ``region_name``/``endpoint_url`` (or an injected resource), so the same code
  points at the real dev table under ``make integration``.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import boto3
from boto3.dynamodb.conditions import Key
from boto3.dynamodb.types import TypeSerializer

from core.repository import (
    board_sort_key,
    calendar_sort_ts,
    connection_sk,
    event_sk,
    family_pk,
    member_sk,
    to_utc,
    work_item_due_sort_ts,
    work_item_sk,
)
from core.schemas import (
    BOARD_COLUMNS,
    CalendarKind,
    CalendarRow,
    Event,
    Family,
    Member,
    WorkItem,
    WorkItemUpdate,
)

if TYPE_CHECKING:  # boto3 resource/table types are only needed for annotations
    from mypy_boto3_dynamodb.service_resource import Table

# The GSI partition-key suffixes (AWS_LLD §1.2): FAM#<fam>#BOARD / #CAL.
_BOARD_PK_SUFFIX = "#BOARD"
_CAL_PK_SUFFIX = "#CAL"
# Internal item-type discriminator (kept out of the DTO on read).
_TYPE_ATTR = "_type"
_FAMILY_SK = "#META"


def _ts_key(instant: datetime) -> str:
    """A fixed-width ISO-8601 UTC instant so GSI2 lexical range == time range."""
    return to_utc(instant).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class DynamoRepository:
    """boto3 single-table :class:`core.repository.Repository` (real dev/prod)."""

    def __init__(
        self,
        table_name: str,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        resource: Any | None = None,
    ) -> None:
        if resource is None:
            resource = boto3.resource(
                "dynamodb", region_name=region_name, endpoint_url=endpoint_url
            )
        self._table: Table = resource.Table(table_name)
        # A PLAIN low-level client for TransactWriteItems, kept SEPARATE from the
        # resource. We must NOT serialize values ourselves and hand them to the
        # resource's client (``self._table.meta.client``): the resource attaches
        # boto3's (de)serialization transform hooks to that client, so our
        # already-serialized values get double-wrapped (``{"S": v}`` ->
        # ``{"M": {"S": v}}`` -> "Type mismatch for key PK expected: S actual:
        # M"). A standalone client has no such hooks, so one explicit
        # TypeSerializer pass is exactly right. Region defaults to the resource's.
        self._ddb = boto3.client(
            "dynamodb",
            region_name=region_name or resource.meta.client.meta.region_name,
            endpoint_url=endpoint_url,
        )

    # --- provisioning (impl-only; not part of the Repository protocol) ------

    def seed_family(self, family: Family, members: list[Member]) -> None:
        """Insert a family + its members (test/fixture provisioning, AWS_LLD §2.1).

        Families/members are provisioned out-of-band of the protocol (the
        minting/admin path), so the harness seeds them with raw ``PutItem``\\s —
        mirroring the in-memory impl's ``seed_family`` so the flow tests stay
        backend-agnostic.
        """
        self._table.put_item(
            Item={
                "PK": family_pk(family.id),
                "SK": _FAMILY_SK,
                _TYPE_ATTR: "family",
                **family.model_dump(mode="json"),
            }
        )
        for m in members:
            self._table.put_item(
                Item={
                    "PK": family_pk(m.family_id),
                    "SK": member_sk(m.id),
                    _TYPE_ATTR: "member",
                    **m.model_dump(mode="json"),
                }
            )

    # --- reads --------------------------------------------------------------

    def get_work_item(self, family_id: str, work_item_id: str) -> WorkItem | None:
        item = self._get(family_pk(family_id), work_item_sk(work_item_id))
        return WorkItem.model_validate(self._strip(item)) if item else None

    def get_member(self, family_id: str, member_id: str) -> Member | None:
        item = self._get(family_pk(family_id), member_sk(member_id))
        return Member.model_validate(self._strip(item)) if item else None

    def list_members(self, family_id: str) -> list[Member]:
        items = self._query_pk_prefix(family_pk(family_id), "MEM#")
        return [Member.model_validate(self._strip(i)) for i in items]

    def get_event(self, family_id: str, event_id: str) -> Event | None:
        item = self._get(family_pk(family_id), event_sk(event_id))
        return Event.model_validate(self._strip(item)) if item else None

    def list_board(self, family_id: str) -> dict[str, list[WorkItem]]:
        """The four columns, pre-sorted, via a single GSI1 Query (AWS_LLD §1.3).

        GSI1 is sparse (archived items carry no key), so the Query returns only
        board-visible items, already ordered by ``STATUS#…#POS#…``.
        """
        board: dict[str, list[WorkItem]] = {col: [] for col in BOARD_COLUMNS}
        board_pk = family_pk(family_id) + _BOARD_PK_SUFFIX
        resp = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(board_pk),
        )
        for item in resp.get("Items", []):
            wi = WorkItem.model_validate(self._strip(item))
            if wi.status in board:
                board[wi.status].append(wi)
        return board

    def list_calendar(
        self, family_id: str, frm: datetime, to: datetime
    ) -> list[CalendarRow]:
        """Events + due-dated items in [frm, to], time-ordered, via one GSI2 Query.

        GSI2 is sparse + unified: the range Query over ``TS#<from>``..``TS#<to>``
        returns event and due-item rows together, already in time order.
        """
        cal_pk = family_pk(family_id) + _CAL_PK_SUFFIX
        resp = self._table.query(
            IndexName="GSI2",
            KeyConditionExpression=Key("GSI2PK").eq(cal_pk)
            & Key("GSI2SK").between(f"TS#{_ts_key(frm)}", f"TS#{_ts_key(to)}#\uffff"),
        )
        rows: list[CalendarRow] = []
        for item in resp.get("Items", []):
            clean = self._strip(item)
            if item.get(_TYPE_ATTR) == "event":
                ev = Event.model_validate(clean)
                rows.append(
                    CalendarRow(
                        id=ev.id,
                        kind=CalendarKind.EVENT,
                        title=ev.title,
                        sort_ts=calendar_sort_ts(ev, self._family_timezone(family_id)),
                    )
                )
            else:
                wi = WorkItem.model_validate(clean)
                due = work_item_due_sort_ts(wi)
                if due is not None:
                    rows.append(
                        CalendarRow(
                            id=wi.id,
                            kind=CalendarKind.WORK_ITEM,
                            title=wi.title,
                            sort_ts=due,
                        )
                    )
        rows.sort(key=lambda r: r.sort_ts)
        return rows

    def list_done_work_items(self, family_id: str) -> list[WorkItem]:
        """Done, unarchived items via a GSI1 Query on the done column prefix."""
        board_pk = family_pk(family_id) + _BOARD_PK_SUFFIX
        resp = self._table.query(
            IndexName="GSI1",
            KeyConditionExpression=Key("GSI1PK").eq(board_pk)
            & Key("GSI1SK").begins_with("STATUS#done#"),
        )
        return [WorkItem.model_validate(self._strip(i)) for i in resp.get("Items", [])]

    def get_family(self, family_id: str) -> Family | None:
        item = self._get(family_pk(family_id), _FAMILY_SK)
        return Family.model_validate(self._strip(item)) if item else None

    # --- writes -------------------------------------------------------------

    def put_work_item(self, wi: WorkItem) -> None:
        self._table.put_item(Item=self._work_item_item(wi))

    def update_work_item(
        self, family_id: str, work_item_id: str, changes: dict
    ) -> None:
        """Apply field changes + re-derive the sparse GSI keys (AWS_LLD §1.2).

        Read-modify-write: load the aggregate, apply ``changes`` + bump
        ``updated_at``, and re-``put`` so the GSI1 (board) and GSI2 (due-date)
        keys are recomputed — e.g. clearing ``due_at`` drops the calendar key,
        changing ``status``/``position`` moves the board key.
        """
        wi = self._require_work_item(family_id, work_item_id)
        for key, value in changes.items():
            setattr(wi, key, value)
        wi.updated_at = datetime.now(UTC)
        self._table.put_item(Item=self._work_item_item(wi))

    def append_update(
        self, family_id: str, work_item_id: str, update: WorkItemUpdate
    ) -> None:
        """Append one log entry via an atomic ``list_append`` ``UpdateItem``."""
        self._require_work_item(family_id, work_item_id)  # miss -> KeyError
        self._table.update_item(
            Key={"PK": family_pk(family_id), "SK": work_item_sk(work_item_id)},
            UpdateExpression=(
                "SET updates = list_append(if_not_exists(updates, :empty), :u), "
                "updated_at = :now"
            ),
            ExpressionAttributeValues={
                ":u": [update.model_dump(mode="json")],
                ":empty": [],
                ":now": datetime.now(UTC).isoformat(),
            },
        )

    def put_event(self, ev: Event) -> None:
        """Standalone create — a single ``Put`` (AWS_LLD §1.2 two creation paths)."""
        self._table.put_item(Item=self._event_item(ev))

    def update_event(self, family_id: str, event_id: str, changes: dict) -> None:
        ev = self._require_event(family_id, event_id)
        for key, value in changes.items():
            setattr(ev, key, value)
        ev.updated_at = datetime.now(UTC)
        self._table.put_item(Item=self._event_item(ev))

    def create_event_from_update(self, ev: Event, wi_log_entry: WorkItemUpdate) -> None:
        """Co-created event — one ``TransactWriteItems`` (AWS_LLD §1.4).

        Event ``Put`` + work-item log ``UpdateItem``, atomic across the two
        partitions. The event's ``provenance.work_item_id`` names the work item.
        The log append is a **SET of the full ``updates`` list** (read, append in
        Python, write back) — unambiguous and atomic within the transaction.

        On a ``TransactionCanceledException`` the per-item ``CancellationReasons``
        are surfaced in the raised message (the standard way to see *which*
        operand failed and why — otherwise the error is an opaque
        ``[ValidationError, None]``).
        """
        if ev.provenance is None:
            raise ValueError("create_event_from_update requires event.provenance")
        work_item_id = ev.provenance.work_item_id
        wi = self._require_work_item(ev.family_id, work_item_id)  # miss -> KeyError
        client = self._ddb
        now_iso = datetime.now(UTC).isoformat()
        new_updates = [u.model_dump(mode="json") for u in wi.updates]
        new_updates.append(wi_log_entry.model_dump(mode="json"))
        try:
            client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self._table.name,
                            "Item": self._to_dynamo(self._event_item(ev)),
                        }
                    },
                    {
                        "Update": {
                            "TableName": self._table.name,
                            "Key": self._to_dynamo(
                                {
                                    "PK": family_pk(ev.family_id),
                                    "SK": work_item_sk(work_item_id),
                                }
                            ),
                            "UpdateExpression": "SET updates = :all, updated_at = :now",
                            "ExpressionAttributeValues": self._to_dynamo(
                                {":all": new_updates, ":now": now_iso}
                            ),
                        }
                    },
                ]
            )
        except client.exceptions.TransactionCanceledException as exc:
            reasons = exc.response.get("CancellationReasons")
            raise RuntimeError(
                f"create_event_from_update transaction cancelled: {reasons}"
            ) from exc

    def delete_event(self, family_id: str, event_id: str) -> None:
        self._table.delete_item(
            Key={"PK": family_pk(family_id), "SK": event_sk(event_id)}
        )

    def archive_work_item(self, family_id: str, work_item_id: str) -> None:
        """Set ``archived_at`` + re-put so the sparse GSI1/GSI2 keys drop off."""
        wi = self._require_work_item(family_id, work_item_id)
        now = datetime.now(UTC)
        wi.archived_at = now
        wi.updated_at = now
        self._table.put_item(Item=self._work_item_item(wi))

    # --- connections --------------------------------------------------------

    def put_connection(
        self, family_id: str, connection_id: str, member_id: str
    ) -> None:
        self._table.put_item(
            Item={
                "PK": family_pk(family_id),
                "SK": connection_sk(connection_id),
                _TYPE_ATTR: "connection",
                "member_id": member_id,
                "connected_at": datetime.now(UTC).isoformat(),
            }
        )

    def list_connections(self, family_id: str) -> list[str]:
        items = self._query_pk_prefix(family_pk(family_id), "CONN#")
        return [i["SK"][len("CONN#") :] for i in items]

    def delete_connection(self, family_id: str, connection_id: str) -> None:
        self._table.delete_item(
            Key={"PK": family_pk(family_id), "SK": connection_sk(connection_id)}
        )

    # --- item assembly (the sparse-GSI write rules) -------------------------

    def _work_item_item(self, wi: WorkItem) -> dict:
        """A work-item item + its sparse GSI keys (board when unarchived; calendar
        when due-dated + unarchived)."""
        item: dict[str, Any] = {
            "PK": family_pk(wi.family_id),
            "SK": work_item_sk(wi.id),
            _TYPE_ATTR: "work_item",
            **wi.model_dump(mode="json"),
        }
        if wi.archived_at is None:
            # GSI1 (board): sparse — present only while unarchived.
            item["GSI1PK"] = family_pk(wi.family_id) + _BOARD_PK_SUFFIX
            item["GSI1SK"] = board_sort_key(wi.status, wi.position)
            # GSI2 (calendar): the due-date bridge — only when due-dated.
            due = work_item_due_sort_ts(wi)
            if due is not None:
                item["GSI2PK"] = family_pk(wi.family_id) + _CAL_PK_SUFFIX
                item["GSI2SK"] = f"TS#{_ts_key(due)}#WI#{wi.id}"
        return item

    def _event_item(self, ev: Event) -> dict:
        """An event item + its GSI2 (calendar) key (events always participate)."""
        sort_ts = calendar_sort_ts(ev, self._family_timezone(ev.family_id))
        return {
            "PK": family_pk(ev.family_id),
            "SK": event_sk(ev.id),
            _TYPE_ATTR: "event",
            "GSI2PK": family_pk(ev.family_id) + _CAL_PK_SUFFIX,
            "GSI2SK": f"TS#{_ts_key(sort_ts)}#EV#{ev.id}",
            **ev.model_dump(mode="json"),
        }

    # --- internals ----------------------------------------------------------

    def _get(self, pk: str, sk: str) -> dict | None:
        resp = self._table.get_item(Key={"PK": pk, "SK": sk})
        return resp.get("Item")

    def _query_pk_prefix(self, pk: str, sk_prefix: str) -> list[dict]:
        resp = self._table.query(
            KeyConditionExpression=Key("PK").eq(pk) & Key("SK").begins_with(sk_prefix)
        )
        return list(resp.get("Items", []))

    def _require_work_item(self, family_id: str, work_item_id: str) -> WorkItem:
        wi = self.get_work_item(family_id, work_item_id)
        if wi is None:
            raise KeyError(f"work item not found: {family_id}/{work_item_id}")
        return wi

    def _require_event(self, family_id: str, event_id: str) -> Event:
        ev = self.get_event(family_id, event_id)
        if ev is None:
            raise KeyError(f"event not found: {family_id}/{event_id}")
        return ev

    def _family_timezone(self, family_id: str) -> str:
        fam = self.get_family(family_id)
        return fam.timezone if fam is not None else "UTC"

    @staticmethod
    def _strip(item: dict) -> dict:
        """Drop the storage-only key/`_type` attributes before DTO validation."""
        clean = copy.deepcopy(item)
        for attr in ("PK", "SK", "GSI1PK", "GSI1SK", "GSI2PK", "GSI2SK", _TYPE_ATTR):
            clean.pop(attr, None)
        return clean

    def _to_dynamo(self, obj: Any) -> Any:
        """Serialize a plain Python value to the low-level DynamoDB wire shape.

        Used only on the two ``TransactWriteItems`` operands (the low-level client
        needs ``{"S": ...}``-tagged values); the resource-level calls elsewhere do
        this automatically.
        """
        serializer = TypeSerializer()
        if isinstance(obj, dict) and not self._is_tagged(obj):
            return {k: serializer.serialize(v) for k, v in obj.items()}
        return serializer.serialize(obj)

    @staticmethod
    def _is_tagged(obj: dict) -> bool:
        return len(obj) == 1 and next(iter(obj)) in {
            "S",
            "N",
            "B",
            "SS",
            "NS",
            "BS",
            "M",
            "L",
            "NULL",
            "BOOL",
        }
