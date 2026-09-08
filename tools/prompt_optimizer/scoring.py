"""Pure normalization and scoring for prompt-optimizer outputs."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .models import ActionCall, LinkLabels, Score


def action_key(action: ActionCall) -> tuple[str, str]:
    """Canonical identity for an id-free action call."""
    return action.name, json.dumps(action.params, sort_keys=True, separators=(",", ":"))


def score_links(
    *,
    actual_work_item_ids: list[int],
    actual_event_ids: list[int],
    actual_member_ids: list[int],
    required: LinkLabels,
) -> Score:
    """Score parsed LINK IDs; every unexpected emitted ID is a false positive."""
    actual = _link_counter(actual_work_item_ids, actual_event_ids, actual_member_ids)
    expected = _link_counter(
        required.work_item_ids, required.event_ids, required.member_ids
    )
    return _score_counter(actual=actual, required=expected)


def score_actions(*, actual: list[dict[str, Any]], required: list[ActionCall]) -> Score:
    """Score id-free PROPOSE action envelopes as an order-independent multiset."""
    actual_counter: Counter[tuple[str, str]] = Counter()
    for raw in actual:
        name = raw.get("name")
        params = raw.get("params", {})
        if isinstance(name, str) and isinstance(params, dict):
            actual_counter[
                (name, json.dumps(params, sort_keys=True, separators=(",", ":")))
            ] += 1
        else:
            actual_counter[
                ("<malformed>", json.dumps(raw, sort_keys=True, default=str))
            ] += 1
    required_counter = Counter(action_key(action) for action in required)
    return _score_counter(actual=actual_counter, required=required_counter)


def _link_counter(
    work_item_ids: list[int], event_ids: list[int], member_ids: list[int]
) -> Counter[tuple[str, str]]:
    counter: Counter[tuple[str, str]] = Counter()
    for kind, ids in (
        ("work_item", work_item_ids),
        ("event", event_ids),
        ("member", member_ids),
    ):
        for entity_id in ids:
            counter[(kind, str(entity_id))] += 1
    return counter


def _score_counter(
    *, actual: Counter[tuple[str, str]], required: Counter[tuple[str, str]]
) -> Score:
    matched = sum((actual & required).values())
    required_count = sum(required.values())
    actual_count = sum(actual.values())
    recall = matched / required_count if required_count else 1.0
    if actual_count:
        precision = matched / actual_count
    else:
        precision = 1.0 if not required_count else 0.0
    unexpected: list[str] = []
    for key, count in (actual - required).items():
        unexpected.extend(_render_key(key) for _ in range(count))
    return Score(
        required_recall=recall,
        forbidden_precision=precision,
        unexpected=sorted(unexpected),
    )


def _render_key(key: tuple[str, str]) -> str:
    return f"{key[0]}:{key[1]}"
