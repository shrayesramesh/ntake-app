"""``LocalLlmClient`` — the httpx transport implementing the :class:`LLM` seam.

The ONE place the model runtime is visible. It turns a
``complete(system, user, schema)`` call into an OpenAI-style
``POST {base_url}/v1/chat/completions`` (llamafile is the reference runtime;
Ollama / LM Studio / llama-server expose the same endpoint and differ only in the
``base_url``/``model`` knobs here), attaches the constrained-output ``schema`` at
``response_format.schema`` (the llama.cpp/llamafile shape — verified against its
server README; the OpenAI-cloud ``json_schema``+``strict`` nesting is rejected by
llama.cpp, see issues #11847/#11988), and JSON-decodes the model's reply into the
``dict`` the seam returns. It holds ``base_url`` / ``model`` / ``timeout`` and NO
prompt or domain logic — building the prompt + schema is the caller's job
(``assistant.py`` / ``resolver.py``), which depend on the :class:`LLM` protocol,
never on this module.

This is the only file in the backend that imports ``httpx``; the boundary test in
``tests/test_local_llm_protocol.py`` guards that nothing above the seam does.

Error posture (v1, minimal): a junk/unexpected model reply decodes to ``{}`` (the
parse layer above reads that as "no actions") rather than raising. Full
adversarial + timeout hardening — the deliberate degrade-to-``[]`` contract — is
step 6; the engine's ``propose_bounded`` additionally bounds the wall-clock.
"""

from __future__ import annotations

import json

import httpx

_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"


class LocalLlmClient:
    """An :class:`LLM` backed by a localhost OpenAI-style chat-completions server.

    ``transport`` is an injection seam for tests (pass an ``httpx.MockTransport``);
    in production it is ``None`` and httpx opens real localhost connections.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        timeout: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._transport = transport

    def complete(self, system: str, user: str, schema: dict) -> dict:
        """One constrained-JSON completion: POST the messages + schema, return the
        parsed content dict (``{}`` on a non-JSON / unexpected reply)."""
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # llama.cpp/llamafile shape: the schema sits directly under
            # response_format.schema (NOT nested in a json_schema object, and no
            # `strict`/`name` — those are the OpenAI-cloud form that the llama.cpp
            # server rejects; see ggml-org/llama.cpp#11847, #11988). Verified
            # against tools/server/README.md.
            "response_format": {
                "type": "json_schema",
                "schema": schema,
            },
        }
        with httpx.Client(timeout=self._timeout, transport=self._transport) as http:
            response = http.post(self._base_url + _CHAT_COMPLETIONS_PATH, json=payload)
            response.raise_for_status()
            data = response.json()
        return _parse_content(data)


def _parse_content(data: dict) -> dict:
    """Extract + JSON-decode the model's message content; ``{}`` if unusable.

    Isolated so step-6 hardening can grow here without touching the transport.
    """
    try:
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
