"""ScriptedAnthropicClient — the deterministic Anthropic Messages double.

The deterministic double for the Anthropic Messages seam (AWS_LLD §3.4). Both
LINK (forced-tool constrained JSON) and PROPOSE (tool-use) sit behind the
``core.assistant.anthropic_client.AnthropicClient`` protocol; this double lets
those flows run with **no network and no key**, canned responses keyed off the
user text. Shaped like the real Messages response verified by
``scripts/spike/link_probe.py``:

* the top-level ``content`` is a list of blocks;
* a tool call is ``{"type": "tool_use", "id", "name", "input": {...}}``;
* ``stop_reason`` is ``"tool_use"`` (a forced/used tool) or ``"end_turn"``.

(This is the real seam's double; the Converse-shaped Bedrock double it succeeded
was removed with the throwaway tracer in Session 5, since the project is on the
Anthropic Messages API.)
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

LINK_TOOL_NAME = "record_links"


def link_response(ids: dict[str, list[str]]) -> dict[str, Any]:
    """A canned LINK response: one forced ``record_links`` ``tool_use`` block.

    LINK uses a forced tool whose ``input`` IS the
    ``{work_item_ids, event_ids, member_ids}`` object (AWS_LLD §3.1); ``ids`` is
    merged over empty-list defaults so a caller supplies only what matters.
    """
    payload = {"work_item_ids": [], "event_ids": [], "member_ids": [], **ids}
    return {
        "stop_reason": "tool_use",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_link",
                "name": LINK_TOOL_NAME,
                "input": payload,
            }
        ],
    }


def propose_response(tool_uses: list[dict[str, Any]]) -> dict[str, Any]:
    """A canned PROPOSE response: one ``tool_use`` block per tool call.

    Each item is ``{"name": <action>, "input": {...}}`` (``input`` defaults to
    ``{}``; an ``id`` is filled if omitted). Returns the Messages shape with one
    block per call and ``stop_reason="tool_use"``, so a handler consuming a
    *list* of blocks (parallel tool use, AWS_LLD §3.5) works for one or many.
    """
    content = [
        {
            "type": "tool_use",
            "id": tu.get("id", f"toolu_{i}"),
            "name": tu["name"],
            "input": tu.get("input", {}),
        }
        for i, tu in enumerate(tool_uses)
    ]
    return {"stop_reason": "tool_use", "content": content}


@dataclass(frozen=True)
class RecordedCall:
    """One recorded ``create_message`` call (for prompt/schema assertions)."""

    system: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None
    tool_choice: dict[str, Any] | None


class ScriptedAnthropicClient:
    """A deterministic ``AnthropicClient`` — canned responses keyed off text.

    Seed with ``responses``: an ordered ``{key: response}`` map. ``create_message``
    returns the first response whose ``key`` is a **substring of the concatenated
    user text** (insertion order breaks ties). ``default`` is the fallback; a miss
    with no default raises ``KeyError`` (a miss is a test-authoring bug — fail
    loudly). Each call returns a **deep copy** (a caller mutating the result can't
    poison a later call) and is recorded in :attr:`calls`.
    """

    def __init__(
        self,
        responses: dict[str, dict[str, Any]] | None = None,
        *,
        default: dict[str, Any] | None = None,
    ) -> None:
        self._responses: dict[str, dict[str, Any]] = responses or {}
        self._default = default
        self.calls: list[RecordedCall] = []

    def create_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(RecordedCall(system, messages, tools, tool_choice))
        user_text = _user_text(messages)
        for key, response in self._responses.items():
            if key in user_text:
                return copy.deepcopy(response)
        if self._default is not None:
            return copy.deepcopy(self._default)
        raise KeyError(
            f"ScriptedAnthropicClient: no canned response matched user text "
            f"{user_text!r} and no default was set"
        )


def _user_text(messages: list[dict[str, Any]]) -> str:
    """Concatenate the text of all user-role message blocks (Messages shape)."""
    parts: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        content = msg.get("content", [])
        if isinstance(content, str):  # Messages allows a bare string too
            parts.append(content)
            continue
        for block in content:
            text = block.get("text") if isinstance(block, dict) else None
            if text:
                parts.append(text)
    return "\n".join(parts)
