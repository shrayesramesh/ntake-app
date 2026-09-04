"""The LLM protocol — the one injected effect the local-LLM backend depends on.

Task 7 Track A step 1 (spec/NEXT_SESSION.md): pin the ``LLM`` contract
(``complete(system, user, schema) -> dict``) and the ``ScriptedLLM`` test double
that every step below tests against. ``ScriptedLLM`` returns canned JSON keyed
off the call (a substring of the ``user`` message), so link/propose tests can
drive deterministic model output with no transport and no model.

Nothing here (or above the protocol) imports httpx — that lives only in
``client.py`` (step 3). This test guards that boundary too.
"""

from __future__ import annotations

import pytest

from app.assistant.local_llm.protocol import LLM, ScriptedLLM


def test_scripted_llm_satisfies_the_llm_protocol():
    # The double IS an LLM (structural conformance — the protocol is a Protocol
    # so the httpx client can satisfy it later without inheriting anything).
    scripted = ScriptedLLM(default={"actions": []})
    assert isinstance(scripted, LLM)


def test_complete_returns_the_default_when_no_keys_match():
    scripted = ScriptedLLM(default={"work_item_ids": [], "event_ids": []})
    out = scripted.complete(
        system="link things", user="a note about nothing in particular", schema={}
    )
    assert out == {"work_item_ids": [], "event_ids": []}


def test_complete_selects_the_response_keyed_off_the_user_message():
    # Canned JSON is keyed off a substring of the user prompt (the note/world
    # text), so different captures deterministically yield different output.
    scripted = ScriptedLLM(
        responses={
            "plumber": {"work_item_ids": [3], "event_ids": []},
            "dentist": {"work_item_ids": [], "event_ids": [8]},
        },
    )
    plumber = scripted.complete(
        system="link", user="the plumber is coming friday", schema={}
    )
    dentist = scripted.complete(
        system="link", user="my dentist appointment moved", schema={}
    )
    assert plumber == {"work_item_ids": [3], "event_ids": []}
    assert dentist == {"work_item_ids": [], "event_ids": [8]}


def test_complete_returns_a_fresh_dict_each_call():
    # Guard against a caller mutating a shared canned object and poisoning the
    # next call's result (the protocol hands back JSON-like dicts that parsing
    # code may edit in place).
    scripted = ScriptedLLM(default={"actions": []})
    first = scripted.complete(system="s", user="u", schema={})
    first["actions"].append("mutated")
    second = scripted.complete(system="s", user="u", schema={})
    assert second == {"actions": []}


def test_complete_raises_on_a_miss_when_no_default_is_set():
    # A miss must be loud: an unkeyed call with no default is a test-authoring
    # bug, not a silent empty proposal. Deterministic doubles fail fast.
    scripted = ScriptedLLM(responses={"plumber": {"work_item_ids": [3]}})
    with pytest.raises(KeyError):
        scripted.complete(system="link", user="unrelated note", schema={})


def test_first_matching_key_wins_in_insertion_order():
    # When several keys match, the earliest-inserted wins — deterministic and
    # explainable (dicts preserve insertion order in 3.12).
    scripted = ScriptedLLM(
        responses={
            "friday": {"which": "friday"},
            "plumber friday": {"which": "both"},
        },
    )
    out = scripted.complete(system="s", user="the plumber friday", schema={})
    assert out == {"which": "friday"}


def test_calls_are_recorded_for_assertions():
    # The double records each (system, user, schema) so a test can assert the
    # backend built the prompt/schema it expected before ever hitting a model.
    scripted = ScriptedLLM(default={"actions": []})
    scripted.complete(system="SYS", user="USER", schema={"type": "object"})
    assert scripted.calls == [("SYS", "USER", {"type": "object"})]


def test_protocol_module_does_not_import_httpx():
    # The boundary the whole backend rests on: nothing above client.py may import
    # the transport. If this fails, an httpx dependency leaked into the protocol.
    import sys

    import app.assistant.local_llm.protocol as protocol_mod

    assert "httpx" not in protocol_mod.__dict__
    # And importing the protocol must not have pulled httpx into the process on
    # its account (defensive: the file has no transport import at all).
    assert "app.assistant.local_llm.client" not in sys.modules
