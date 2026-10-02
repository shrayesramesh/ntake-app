"""ScriptedBedrockClient — the deterministic Bedrock Converse double.

The Converse-shaped analog of the old ``ScriptedLLM`` (``git show
main:app/assistant/local_llm/protocol.py``). Both Bedrock seams — LINK
(constrained-JSON) and PROPOSE (tool-use) — will sit behind a small
``BedrockClient`` protocol (defined for real in Sessions 4-5, AWS_LLD §3.4); this
double lets those flows be exercised with **no network and no model**, canned
responses keyed off the user text.

Session 1 ships it so the harness is complete and self-tested; Sessions 4-5 bind
it to the real protocol. It is deliberately shaped like the Bedrock Converse API
(``output.message.content`` is a list of blocks; a ``toolUse`` block is
``{"toolUse": {"name", "input", "toolUseId"}}``) so the PROPOSE handler consumes
the double exactly as it will consume the real response.
"""

from __future__ import annotations

import copy
import json
from typing import Any


def link_response(ids: dict[str, list[str]]) -> dict[str, Any]:
    """A canned LINK (constrained-JSON) Converse response.

    LINK returns the JSON object ``{work_item_ids, event_ids, member_ids}`` as the
    model's text content; the app parses + validates it (AWS_LLD §3.1). ``ids`` is
    merged over the empty-list defaults so a caller supplies only what matters.
    """
    payload = {"work_item_ids": [], "event_ids": [], "member_ids": [], **ids}
    return {
        "output": {
            "message": {"role": "assistant", "content": [{"text": json.dumps(payload)}]}
        },
        "stopReason": "end_turn",
        "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
    }


def propose_response(tool_uses: list[dict[str, Any]]) -> dict[str, Any]:
    """A canned PROPOSE (tool-use) Converse response from a list of tool calls.

    Each item is ``{"name": <action>, "input": {...}}`` (an optional
    ``"toolUseId"`` is filled in if omitted). Returns the Converse shape with one
    ``toolUse`` content block per call and ``stopReason="tool_use"``, so a handler
    that consumes a *list* of blocks (AWS_LLD §3.5 multi-tool-call) works
    unchanged whether the list has one or many.
    """
    content = [
        {
            "toolUse": {
                "toolUseId": tu.get("toolUseId", f"tu-{i}"),
                "name": tu["name"],
                "input": tu.get("input", {}),
            }
        }
        for i, tu in enumerate(tool_uses)
    ]
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": "tool_use",
        "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
    }


class ScriptedBedrockClient:
    """A deterministic Bedrock Converse client — canned responses keyed off text.

    Seed it with ``responses``: an ordered ``{key: converse_response}`` map.
    ``converse`` returns the first response whose ``key`` is a **substring of the
    concatenated user text** (insertion order breaks ties — earliest wins), so
    different captures yield different output with no model. ``default`` is the
    fallback when nothing matches; a miss with **no default** raises ``KeyError``
    (a miss is a test-authoring bug — fail loudly, don't silently degrade).

    Build the canned values with :func:`link_response` / :func:`propose_response`.
    Each call returns a **deep copy** (so a caller mutating the result in place
    can't poison a later call) and is recorded in :attr:`calls` as
    ``(system, messages, tool_config)`` for prompt/schema assertions — mirroring
    ``ScriptedLLM.calls``.
    """

    def __init__(
        self,
        responses: dict[str, dict[str, Any]] | None = None,
        *,
        default: dict[str, Any] | None = None,
    ) -> None:
        self._responses: dict[str, dict[str, Any]] = responses or {}
        self._default = default
        self.calls: list[tuple[str, list[dict[str, Any]], dict[str, Any] | None]] = []

    def converse(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tool_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the canned Converse response for ``messages`` (keyed by substring)."""
        self.calls.append((system, messages, tool_config))
        user_text = _user_text(messages)
        for key, response in self._responses.items():
            if key in user_text:
                return copy.deepcopy(response)
        if self._default is not None:
            return copy.deepcopy(self._default)
        raise KeyError(
            f"ScriptedBedrockClient: no canned response matched user text "
            f"{user_text!r} and no default was set"
        )


def _user_text(messages: list[dict[str, Any]]) -> str:
    """Concatenate the text of all user-role message blocks (Converse message shape)."""
    parts: list[str] = []
    for msg in messages:
        if msg.get("role") != "user":
            continue
        for block in msg.get("content", []):
            text = block.get("text") if isinstance(block, dict) else None
            if text:
                parts.append(text)
    return "\n".join(parts)
