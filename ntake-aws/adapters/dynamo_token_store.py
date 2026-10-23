"""The real-table ``TokenStore`` — device tokens + pairing codes (AWS_LLD §5).

The DynamoDB twin of :class:`core.token_store_memory.InMemoryTokenStore`,
satisfying the same :class:`core.token_store.TokenStore` ``Protocol``. Identity
items are top-level (not family-scoped): ``TOK#<hash>`` / ``#META`` and
``PAIR#<code>`` / ``#META`` on the one ``ntake-<stage>`` table. Key composition
reuses the pure composers in :mod:`core.token_store` (``token_pk``/``pairing_pk``)
byte-for-byte — the single source of identity-key knowledge.

Items are stored as the DTO's ``model_dump(mode="json")`` payload plus ``PK``/
``SK``; reads strip the key attrs and ``model_validate`` the DTO back. Each method
is one atomic op (``PutItem``/``GetItem``/``UpdateItem``). ``boto3`` lives only in
this adapters layer (the engine boundary keeps it out of ``core``).

The authorizer only ever calls ``get_device_token`` — so the authorizer Lambda's
IAM can scope to ``GetItem`` on this table alone, no family-data access.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import boto3
from boto3.dynamodb.conditions import Attr

from core.schemas import DeviceToken, PairingCode
from core.token_store import pairing_pk, token_pk

if TYPE_CHECKING:
    from mypy_boto3_dynamodb.service_resource import Table

_META_SK = "#META"


class DynamoTokenStore:
    """DynamoDB-backed :class:`core.token_store.TokenStore` (Tier-2 / real app)."""

    def __init__(
        self,
        table_name: str,
        *,
        region_name: str | None = None,
        endpoint_url: str | None = None,
        table: Table | None = None,
    ) -> None:
        if table is not None:
            self._table = table
        else:
            resource = boto3.resource(
                "dynamodb", region_name=region_name, endpoint_url=endpoint_url
            )
            self._table = resource.Table(table_name)

    # --- device tokens ------------------------------------------------------

    def get_device_token(self, token_hash: str) -> DeviceToken | None:
        resp = self._table.get_item(Key={"PK": token_pk(token_hash), "SK": _META_SK})
        item = resp.get("Item")
        return DeviceToken.model_validate(_strip(item)) if item else None

    def put_device_token(self, token: DeviceToken) -> None:
        self._table.put_item(
            Item={
                "PK": token_pk(token.token_hash),
                "SK": _META_SK,
                **token.model_dump(mode="json"),
            }
        )

    def list_device_tokens_for_member(self, member_id: str) -> list[DeviceToken]:
        # Device tokens are keyed by hash (no member GSI — listing a member's
        # tokens is an admin/rare path, so a scan with a filter is acceptable at
        # household scale, AWS_LLD §5.3).
        items: list[dict[str, Any]] = []
        scan_kwargs: dict[str, Any] = {
            "FilterExpression": Attr("SK").eq(_META_SK)
            & Attr("member_id").eq(member_id)
            & Attr("token_hash").exists()
        }
        while True:
            resp = self._table.scan(**scan_kwargs)
            items.extend(resp.get("Items", []))
            lek = resp.get("LastEvaluatedKey")
            if not lek:
                break
            scan_kwargs["ExclusiveStartKey"] = lek
        return [DeviceToken.model_validate(_strip(i)) for i in items]

    def revoke_device_token(self, token_hash: str) -> None:
        self._update_tolerant(
            key={"PK": token_pk(token_hash), "SK": _META_SK},
            update_expression="SET revoked_at = :t",
            condition=Attr("PK").exists() & Attr("revoked_at").not_exists(),
            values={":t": datetime.now(UTC).isoformat()},
        )

    # --- pairing codes ------------------------------------------------------

    def get_pairing_code(self, code: str) -> PairingCode | None:
        resp = self._table.get_item(Key={"PK": pairing_pk(code), "SK": _META_SK})
        item = resp.get("Item")
        return PairingCode.model_validate(_strip(item)) if item else None

    def put_pairing_code(self, pairing: PairingCode) -> None:
        self._table.put_item(
            Item={
                "PK": pairing_pk(pairing.code),
                "SK": _META_SK,
                **pairing.model_dump(mode="json"),
            }
        )

    def consume_pairing_code(self, code: str) -> None:
        self._update_tolerant(
            key={"PK": pairing_pk(code), "SK": _META_SK},
            update_expression="SET consumed_at = :t",
            condition=Attr("PK").exists() & Attr("consumed_at").not_exists(),
            values={":t": datetime.now(UTC).isoformat()},
        )

    def record_pairing_attempt(self, code: str) -> None:
        self._update_tolerant(
            key={"PK": pairing_pk(code), "SK": _META_SK},
            update_expression="SET attempts = if_not_exists(attempts, :z) + :one",
            condition=Attr("PK").exists(),
            values={":z": 0, ":one": 1},
        )

    # --- internals ----------------------------------------------------------

    def _update_tolerant(
        self,
        *,
        key: dict[str, str],
        update_expression: str,
        condition: Any,
        values: dict[str, Any],
    ) -> None:
        """An ``UpdateItem`` whose conditional miss is a no-op (in-memory parity).

        The in-memory store treats revoke/consume/record on a missing or
        already-settled record as a silent no-op; the real table expresses the
        same guard as a ``ConditionExpression`` and swallows the resulting
        ``ConditionalCheckFailedException`` so both backends behave identically.
        """
        try:
            self._table.update_item(
                Key=key,
                UpdateExpression=update_expression,
                ConditionExpression=condition,
                ExpressionAttributeValues=values,
            )
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            return


def _strip(item: dict[str, Any]) -> dict[str, Any]:
    """Drop the key attributes so the remainder ``model_validate``s to the DTO."""
    return {k: v for k, v in item.items() if k not in ("PK", "SK")}
