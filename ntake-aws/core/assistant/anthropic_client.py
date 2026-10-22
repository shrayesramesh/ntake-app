"""The ``AnthropicClient`` seam — the injected effect LINK/PROPOSE depend on.

A deliberately thin, **generic** protocol over the Anthropic Messages API
(``POST /v1/messages``): one ``create_message(system, messages, tools?,
tool_choice?)`` round trip returning the raw response dict. Structural typing
(``Protocol``) lets both the real HTTP client (``adapters/``, Session 4 Tier-2)
and the scripted test double (``tests/harness``) satisfy it with no shared base.

Kept generic on purpose (AWS_LLD §3.6): "call a model with a system/messages +
optional tools, get the raw typed response back" — not hard-named to LINK or
capture — so PROPOSE and any future decision/insight surface reuse the same seam.
The LINK/PROPOSE-specific request shaping (the forced ``record_links`` tool for
LINK, the registry→tools projection for PROPOSE) lives in those callers, not here.

Response shape is the real Messages shape (verified via
``scripts/spike/link_probe.py``): a top-level ``content`` list of blocks, where a
tool call is ``{"type": "tool_use", "id", "name", "input": {...}}`` and
``stop_reason`` is ``"tool_use"`` / ``"end_turn"``. Callers parse defensively and
ignore unknown fields (the live API carries extras like ``caller``, ``usage``).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AnthropicClient(Protocol):
    """One Messages round trip; the only place the Anthropic API is reached."""

    def create_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send a Messages request; return the raw response dict (unparsed)."""
        ...
