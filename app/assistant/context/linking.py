"""Deterministic rules that enrich LINK-stage member resolution."""

from __future__ import annotations

import re

_FIRST_PERSON = re.compile(r"\b(?:i|me|my|mine)\b", re.IGNORECASE)


def add_capturing_member_for_first_person(
    text: str, member_ids: list[int], capturing_member_id: int
) -> list[int]:
    """Return resolved member ids with the author linked for first-person notes.

    LINK remains free to resolve any named people. This deterministic rule adds
    the capturing member when the note uses first-person language, with the
    author first and duplicate ids removed in original relative order.
    """
    if not _FIRST_PERSON.search(text):
        return member_ids

    result = [capturing_member_id]
    result.extend(
        member_id for member_id in member_ids if member_id != capturing_member_id
    )
    return result
