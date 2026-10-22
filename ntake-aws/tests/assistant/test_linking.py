"""First-person member linking — behaviour-faithful to the reference.

``add_capturing_member_for_first_person`` (git show
main:app/assistant/context/linking.py): a deterministic rule that adds the
capturing member to the resolved member ids when the note uses first-person
language (author first, duplicates removed, original relative order otherwise).
Pure — no repo, no model. Port changes only the id type (int → ULID str).
"""

from __future__ import annotations

import pytest

from core.assistant.linking import add_capturing_member_for_first_person


@pytest.mark.parametrize("word", ["I", "me", "my", "mine", "I'm", "remind me"])
def test_first_person_prepends_capturing_member(word: str) -> None:
    out = add_capturing_member_for_first_person(f"{word} need milk", [], "mem_self")
    assert out == ["mem_self"]


def test_no_first_person_leaves_member_ids_untouched() -> None:
    out = add_capturing_member_for_first_person(
        "Sam needs milk", ["mem_sam"], "mem_self"
    )
    assert out == ["mem_sam"]


def test_first_person_with_others_author_first_no_dup() -> None:
    out = add_capturing_member_for_first_person(
        "remind me and Sam", ["mem_sam", "mem_self"], "mem_self"
    )
    assert out == ["mem_self", "mem_sam"]  # author first, author dedup'd


def test_first_person_is_whole_word_only() -> None:
    # "paint" contains "i" but not the word "I" — must NOT trigger.
    out = add_capturing_member_for_first_person("buy paint", [], "mem_self")
    assert out == []
