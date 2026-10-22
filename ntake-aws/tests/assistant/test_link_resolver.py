"""LINK resolver — the end-to-end stage-1 flow (AWS_LLD §3.1).

The larger-scoped flow test for Session 4: world view → ``create_message``
(forced ``record_links`` tool) → parse ``tool_use.input`` → validate-against-
family (``resolve_ids``) + first-person linking → ``deep_context`` →
``FocusedContext``. Driven by the scripted Anthropic double (no network, no key).
Also pins the graceful-degrade contract: any failure → an empty-but-valid
``FocusedContext``, never a raise into the request path.
"""

from __future__ import annotations

from datetime import UTC, datetime

from core.assistant.anthropic_link import AnthropicCaptureResolver
from core.assistant.capture import CaptureRequest
from core.repository_memory import InMemoryRepository
from core.schemas import Family, Member, WorkItem
from tests.harness.anthropic_double import ScriptedAnthropicClient, link_response

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TZ = "America/New_York"


def _member(mid: str, name: str = "Alex", role: str = "adult") -> Member:
    return Member(
        id=mid, family_id="fam1", display_name=name, role=role, created_at=NOW
    )


def _wi(wid: str, title: str, **kw: object) -> WorkItem:
    return WorkItem(
        id=wid,
        family_id="fam1",
        title=title,
        status="doing",
        created_at=NOW,
        updated_at=NOW,
        **kw,  # type: ignore[arg-type]
    )


def _repo(members: list[Member]) -> InMemoryRepository:
    repo = InMemoryRepository()
    repo.seed_family(Family(id="fam1", name="T", timezone=TZ, created_at=NOW), members)
    return repo


def _req(text: str) -> CaptureRequest:
    return CaptureRequest(text=text, timezone=TZ, now=NOW)


def _resolve(client: ScriptedAnthropicClient, repo, member, text: str):
    return AnthropicCaptureResolver(client).focus(_req(text), repo, member)


# --- happy path ------------------------------------------------------------


def test_resolves_linked_work_item_into_focused_context() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    repo.put_work_item(_wi("w2", "call plumber"))
    client = ScriptedAnthropicClient(default=link_response({"work_item_ids": ["w2"]}))

    fc = _resolve(client, repo, alex, "the plumber is coming friday")

    assert fc.resolved_work_item_ids == ["w2"]
    assert fc.primary_work_item_id == "w2"
    assert "call plumber" in fc.deep_context  # deep-context built for the id
    assert fc.text == "the plumber is coming friday"
    assert fc.timezone == TZ


def test_world_view_and_note_are_sent_to_the_model() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    repo.put_work_item(_wi("w2", "call plumber"))
    client = ScriptedAnthropicClient(default=link_response({}))

    _resolve(client, repo, alex, "the plumber note")

    (call,) = client.calls
    # The forced record_links tool is used, and the user message carries the
    # world view (the item) + the note.
    assert call.tool_choice == {"type": "tool", "name": "record_links"}
    user_text = call.messages[0]["content"][0]["text"]
    assert "call plumber" in user_text  # world view
    assert "the plumber note" in user_text  # the note


def test_first_person_links_capturing_member() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    client = ScriptedAnthropicClient(default=link_response({}))  # model names nobody

    fc = _resolve(client, repo, alex, "remind me to buy milk")

    assert fc.resolved_member_ids == ["m1"]  # added deterministically in code


def test_foreign_id_is_dropped_validate_dont_trust() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    repo.put_work_item(_wi("w2", "real"))
    # Model hallucinates a work item that isn't in the family.
    client = ScriptedAnthropicClient(
        default=link_response({"work_item_ids": ["w2", "w_bogus"]})
    )

    fc = _resolve(client, repo, alex, "note")

    assert fc.resolved_work_item_ids == ["w2"]  # bogus dropped


# --- graceful degrade (never raise) ----------------------------------------


class _RaisingClient:
    def create_message(self, *a: object, **k: object) -> dict:
        raise RuntimeError("api down")


def test_api_failure_degrades_to_empty_context() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    fc = AnthropicCaptureResolver(_RaisingClient()).focus(_req("note"), repo, alex)
    assert fc.resolved_work_item_ids == []
    assert fc.resolved_event_ids == []
    # deep_context still renders its (empty) scaffold — "nothing linked", not a
    # crash; the context is valid-but-empty, which is what PROPOSE should see.
    assert "- (none)" in fc.deep_context
    assert fc.text == "note"  # still a usable context


def test_missing_tool_use_block_degrades_to_empty() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    # A text-only reply (no tool_use block) — degrade, don't crash.
    client = ScriptedAnthropicClient(
        default={"stop_reason": "end_turn", "content": [{"type": "text", "text": "hi"}]}
    )
    fc = _resolve(client, repo, alex, "note")
    assert fc.resolved_work_item_ids == []


def test_malformed_tool_input_degrades_to_empty() -> None:
    alex = _member("m1")
    repo = _repo([alex])
    # tool_use present but input is the wrong shape.
    client = ScriptedAnthropicClient(
        default={
            "stop_reason": "tool_use",
            "content": [
                {
                    "type": "tool_use",
                    "id": "t",
                    "name": "record_links",
                    "input": "garbage",
                }
            ],
        }
    )
    fc = _resolve(client, repo, alex, "note")
    assert fc.resolved_work_item_ids == []


def test_first_person_still_applied_even_when_model_degrades() -> None:
    # Even a non-conforming reply shouldn't lose the deterministic author link.
    alex = _member("m1")
    repo = _repo([alex])
    client = ScriptedAnthropicClient(default={"stop_reason": "end_turn", "content": []})
    fc = _resolve(client, repo, alex, "remind me about the thing")
    assert fc.resolved_member_ids == ["m1"]
