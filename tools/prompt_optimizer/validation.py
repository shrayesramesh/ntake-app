"""Deterministic validation for generated synthetic prompt cases."""

from __future__ import annotations

import re
from datetime import UTC
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.assistant.actions.registry import REGISTRY

from .models import LinkLabels, PromptCase
from .scoring import action_key

_ENTITY_TOKEN = re.compile(r"\[(?:[mwe])\d+\]")


def validate_case(case: PromptCase) -> list[str]:
    """Return deterministic validation errors for one generated case."""
    errors: list[str] = []
    errors.extend(_validate_timezone(case))
    errors.extend(_validate_ids(case))
    errors.extend(_validate_actions(case))
    errors.extend(_validate_capture(case))
    return errors


def validate_batch(cases: list[PromptCase]) -> list[str]:
    """Return batch-level errors, including duplicate semantic fingerprints."""
    errors: list[str] = []
    fingerprints: set[tuple[str, str, str]] = set()
    for case in cases:
        errors.extend(f"{case.case_id}: {error}" for error in validate_case(case))
        fingerprint = (case.stage, case.capture.casefold(), case.world_view)
        if fingerprint in fingerprints:
            errors.append(f"duplicate case fingerprint: {case.case_id}")
        fingerprints.add(fingerprint)
    return errors


def _validate_timezone(case: PromptCase) -> list[str]:
    errors: list[str] = []
    if case.now.tzinfo is None or case.now.utcoffset() != UTC.utcoffset(case.now):
        errors.append("now must be an ISO-8601 UTC timestamp")
    try:
        ZoneInfo(case.timezone)
    except ZoneInfoNotFoundError:
        errors.append(f"timezone is not an IANA zone: {case.timezone}")
    return errors


def _validate_ids(case: PromptCase) -> list[str]:
    errors: list[str] = []
    known = {
        "work_item": {entity.id for entity in case.world.work_items},
        "event": {entity.id for entity in case.world.events},
        "member": {entity.id for entity in case.world.members},
    }
    labels = (("required", case.required_links), ("forbidden", case.forbidden_links))
    for label_name, labels_for_kind in labels:
        for kind, ids in _link_label_items(labels_for_kind):
            for entity_id in ids:
                if entity_id not in known[kind]:
                    errors.append(f"{label_name} {kind} id {entity_id} is not in world")
                token = _token(kind, entity_id)
                if token not in case.world_view:
                    errors.append(f"world_view does not contain {token}")
    for kind, required_ids in _link_label_items(case.required_links):
        forbidden_ids = dict(_link_label_items(case.forbidden_links))[kind]
        overlap = sorted(set(required_ids) & set(forbidden_ids))
        if overlap:
            errors.append(f"required and forbidden {kind} ids overlap: {overlap}")
    return errors


def _validate_actions(case: PromptCase) -> list[str]:
    errors: list[str] = []
    required_keys: set[tuple[str, str]] = set()
    forbidden_keys: set[tuple[str, str]] = set()
    required_names: set[str] = set()
    for action in case.required_actions:
        spec = REGISTRY.get(action.name)
        if spec is None:
            errors.append(f"required action {action.name} is not in REGISTRY")
            continue
        if not spec.accepts(action.params):
            errors.append(f"required action {action.name} does not satisfy ActionSpec")
        key = action_key(action)
        if key in required_keys:
            errors.append(f"duplicate required action {action.name}")
        required_keys.add(key)
        required_names.add(action.name)
    for action in case.forbidden_actions:
        spec = REGISTRY.get(action.name)
        if spec is None:
            errors.append(f"forbidden action {action.name} is not in REGISTRY")
            continue
        key = action_key(action)
        forbidden_keys.add(key)
        if action.params and not spec.accepts(action.params):
            errors.append(f"forbidden action {action.name} does not satisfy ActionSpec")
        if not action.params and action.name in required_names:
            errors.append(f"required and forbidden action names overlap: {action.name}")
    overlap = required_keys & forbidden_keys
    if overlap:
        errors.append("required and forbidden actions overlap")
    return errors


def _validate_capture(case: PromptCase) -> list[str]:
    errors: list[str] = []
    if _ENTITY_TOKEN.search(case.capture):
        errors.append("capture contains internal entity token")
    capture_lower = case.capture.casefold()
    for spec in REGISTRY.all():
        action_name = spec.name
        if action_name.casefold() in capture_lower:
            errors.append(f"capture contains action/tool name {action_name}")
    if not case.tags:
        errors.append("case has no coverage tags")
    return errors


def _link_label_items(labels: LinkLabels) -> list[tuple[str, list[int]]]:
    return [
        ("work_item", labels.work_item_ids),
        ("event", labels.event_ids),
        ("member", labels.member_ids),
    ]


def _token(kind: str, entity_id: int) -> str:
    prefix = {"work_item": "w", "event": "e", "member": "m"}[kind]
    return f"[{prefix}{entity_id}]"
