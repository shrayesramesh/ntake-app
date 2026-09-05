"""Deterministic LINK-stage rules shared by fake and local resolvers."""

from __future__ import annotations

import pytest

from app.assistant.context.linking import add_capturing_member_for_first_person


@pytest.mark.parametrize("text", ["I need a dentist", "remind me", "my task", "mine"])
def test_first_person_adds_capturing_member(text):
    assert add_capturing_member_for_first_person(text, [], 7) == [7]


def test_first_person_preserves_existing_member_order_after_the_author():
    assert add_capturing_member_for_first_person("I and Sam", [2, 7, 3], 7) == [7, 2, 3]


@pytest.mark.parametrize("text", ["time to go", "email Sam", "family dinner"])
def test_non_first_person_does_not_add_capturing_member(text):
    assert add_capturing_member_for_first_person(text, [2], 7) == [2]
