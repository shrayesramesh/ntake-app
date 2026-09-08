"""Pure normalization and scoring for prompt-optimizer outputs."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from app.assistant.actions.registry import REGISTRY
from app.routing.engine import DataType

from .models import ActionCall, LinkLabels, Score

# MVP evaluation judges whether the model selected the right action and supplied
# machine-actionable time/date or identifier values. Titles, descriptions,
# locations, tags, and display-name strings remain free-text payloads and do not
# affect action recall/precision.
_SCORABLE_PARAM_TYPES = frozenset(
    {DataType.DATE, DataType.DATETIME, DataType.INTEGER, DataType.ARRAY_INTEGER}
)


def action_key(action: ActionCall) -> tuple[str, str]:
    """Canonical full identity used for source-benchmark validation only."""
    return action.name, json.dumps(action.params, sort_keys=True, separators=(",", ":"))


def scoring_action_key(name: str, params: dict[str, Any]) -> tuple[str, str]:
    """Return MVP action identity without free-text payload values.

    The action name always participates. When the action is registered, only
    date/time and identifier parameters participate; every free-text value is
    deliberately ignored. Unknown actions retain their supplied params for a
    stable diagnostic key, though their unknown name already prevents a match.
    """
    spec = REGISTRY.get(name)
    if spec is None:
        retained = params
    else:
        retained = {
            param.name: params[param.name]
            for param in spec.params
            if param.datatype in _SCORABLE_PARAM_TYPES and param.name in params
        }
    return name, json.dumps(retained, sort_keys=True, separators=(",", ":"))


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
    """Score PROPOSE actions by name plus time/date and identifier params.

    Action order and duplicate calls are preserved by the multiset comparison.
    Free-text payload values intentionally do not influence the MVP metric.
    """
    actual_counter: Counter[tuple[str, str]] = Counter()
    for raw in actual:
        name = raw.get("name")
        params = raw.get("params", {})
        if isinstance(name, str) and isinstance(params, dict):
            actual_counter[scoring_action_key(name, params)] += 1
        else:
            actual_counter[
                ("<malformed>", json.dumps(raw, sort_keys=True, default=str))
            ] += 1
    required_counter = Counter(
        scoring_action_key(action.name, action.params) for action in required
    )
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
