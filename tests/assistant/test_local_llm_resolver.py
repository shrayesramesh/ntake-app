"""LocalLlmCaptureResolver — the LINK call (LLM call 1), step 5.

Stage-1 sibling of ``FakeCaptureResolver``, model-backed: it renders the shallow
``build_world_view`` + the note into the LINK prompt, calls the injected ``LLM``
seam for the ids the note refers to, then runs the shared deterministic tail
(``parse_ids`` → ``deep_context``) to produce the ``FocusedContext`` stage 2
reasons over. Tested with a ``ScriptedLLM`` (canned LINK JSON) + real DB fixtures
— no model — so these pin compose + parse + whitelist, not model quality.

Validate-don't-trust: ``deep_context`` whitelists the linked ids to the
capturing member's family, so a hallucinated/foreign id is dropped even though
the model returned it.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.assistant.base import CaptureRequest, CaptureResolver, FocusedContext
from app.assistant.local_llm.link import LocalLlmCaptureResolver
from app.assistant.local_llm.protocol import ScriptedLLM

NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _req(text: str = "hello") -> CaptureRequest:
    return CaptureRequest(text=text, timezone="America/New_York", now=NOW)


def _resolver(link_json: dict) -> LocalLlmCaptureResolver:
    return LocalLlmCaptureResolver(ScriptedLLM(default=link_json))


def test_is_a_capture_resolver():
    assert isinstance(_resolver({}), CaptureResolver)


def test_focus_returns_focused_context_with_raw_fields(session, fam_member):
    _fam, m = fam_member
    ctx = _resolver({"work_item_ids": [], "event_ids": []}).focus(
        _req("buy milk"), session, m
    )
    assert isinstance(ctx, FocusedContext)
    assert ctx.text == "buy milk"
    assert ctx.timezone == "America/New_York"
    assert ctx.now == NOW


def test_link_resolves_a_work_item_id_into_the_context(
    session, fam_member, work_item_factory
):
    _fam, m = fam_member
    wi = work_item_factory(m.family_id, title="call plumber")
    ctx = _resolver({"work_item_ids": [wi.id], "event_ids": []}).focus(
        _req("the plumber is coming"), session, m
    )
    assert ctx.resolved_work_item_ids == [wi.id]
    assert ctx.primary_work_item_id == wi.id
    # deep_context renders the linked item so PROPOSE can reason over it.
    assert "call plumber" in ctx.deep_context


def test_link_resolves_an_event_id_into_the_context(session, fam_member, event_factory):
    _fam, m = fam_member
    ev = event_factory(m.family_id, title="Soccer practice")
    ctx = _resolver({"work_item_ids": [], "event_ids": [ev.id]}).focus(
        _req("about soccer"), session, m
    )
    assert ctx.resolved_event_ids == [ev.id]
    assert ctx.primary_event_id == ev.id


def test_foreign_or_hallucinated_ids_are_dropped_by_the_whitelist(session, fam_member):
    # The model returns ids that don't belong to the family; deep_context's
    # family whitelist drops them (validate-don't-trust).
    _fam, m = fam_member
    ctx = _resolver({"work_item_ids": [9999], "event_ids": [8888]}).focus(
        _req("nonsense"), session, m
    )
    assert ctx.resolved_work_item_ids == []
    assert ctx.resolved_event_ids == []


def test_focus_sends_world_view_and_note_to_the_llm(session, fam_member):
    _fam, m = fam_member
    llm = ScriptedLLM(default={"work_item_ids": [], "event_ids": []})
    LocalLlmCaptureResolver(llm).focus(_req("walk the dog"), session, m)
    assert len(llm.calls) == 1
    system, user, schema = llm.calls[0]
    # The LINK prompt carries the world view (member header) + the note.
    assert "FAMILY MEMBERS:" in user
    assert "walk the dog" in user
    assert "link" in system.lower()
    # The constrained-output schema names the three id lists.
    assert set(schema["properties"]) == {"work_item_ids", "event_ids", "member_ids"}


def test_malformed_link_json_degrades_to_no_ids(session, fam_member):
    # A reply that isn't the expected shape → parse_ids yields empty → a context
    # with only the member footprint, never a raise.
    _fam, m = fam_member
    ctx = _resolver({"garbage": True}).focus(_req("whatever"), session, m)
    assert ctx.resolved_work_item_ids == []
    assert ctx.resolved_event_ids == []
    assert isinstance(ctx.deep_context, str)


def test_first_person_capture_links_the_author_even_when_llm_returns_no_members(
    session, fam_member
):
    _family, member = fam_member
    ctx = _resolver({"work_item_ids": [], "event_ids": [], "member_ids": []}).focus(
        _req("my dentist appointment"), session, member
    )

    assert ctx.resolved_member_ids == [member.id]
    assert ctx.primary_member_id == member.id
