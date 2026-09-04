"""LocalLlmClient — the httpx transport implementing the LLM seam (step 3).

The ONE place the runtime is visible: an OpenAI-style
``POST {base_url}/v1/chat/completions`` with the constrained-output schema
attached, holding ``base_url`` / ``model`` / ``timeout``. Tested against a
**stubbed** ``httpx`` transport (``httpx.MockTransport``) — a real HTTP round trip
through httpx's stack, but no live model and no socket. The client implements the
same ``LLM`` protocol as ``ScriptedLLM``, so everything above the seam is
oblivious to which is wired in.

Adversarial/timeout hardening (malformed JSON, unknown tools, wrong types,
timeouts → degrade) is step 6; here we pin the transport shape + the happy path +
the minimal "don't raise on a junk body" posture.
"""

from __future__ import annotations

import json

import httpx

from app.assistant.local_llm.client import LocalLlmClient
from app.assistant.local_llm.protocol import LLM


def _client_with_handler(handler, **kw) -> LocalLlmClient:
    """A LocalLlmClient whose httpx transport is a stub calling ``handler``."""
    transport = httpx.MockTransport(handler)
    return LocalLlmClient(
        base_url=kw.get("base_url", "http://localhost:8080"),
        model=kw.get("model", "llama3.1:8b"),
        timeout=kw.get("timeout", 30.0),
        transport=transport,
    )


def _ok(body: dict) -> httpx.Response:
    """An OpenAI-style chat-completions response whose content is ``body`` JSON."""
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": json.dumps(body)}}]},
    )


def test_client_is_an_llm():
    client = _client_with_handler(lambda req: _ok({"actions": []}))
    assert isinstance(client, LLM)


def test_complete_posts_openai_shape_and_returns_parsed_content():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["method"] = request.method
        seen["body"] = json.loads(request.content)
        return _ok({"work_item_ids": [3], "event_ids": []})

    client = _client_with_handler(handler, model="qwen2.5:14b")
    schema = {"type": "object", "properties": {"work_item_ids": {"type": "array"}}}
    out = client.complete(system="SYS", user="the plumber note", schema=schema)

    # The parsed model JSON is handed back as a dict.
    assert out == {"work_item_ids": [3], "event_ids": []}

    # OpenAI-style POST to the chat-completions path.
    assert seen["method"] == "POST"
    assert seen["url"] == "http://localhost:8080/v1/chat/completions"
    body = seen["body"]
    assert body["model"] == "qwen2.5:14b"
    assert body["messages"] == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "the plumber note"},
    ]
    # The schema is attached as constrained output. llama.cpp/llamafile shape:
    # response_format.schema directly (no json_schema wrapper, no strict/name).
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["schema"] == schema
    assert "json_schema" not in body["response_format"]
    assert "strict" not in body["response_format"]


def test_base_url_trailing_slash_is_normalized():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return _ok({"actions": []})

    client = _client_with_handler(handler, base_url="http://localhost:8080/")
    client.complete(system="s", user="u", schema={})
    # No doubled slash regardless of a trailing slash on base_url.
    assert seen["url"] == "http://localhost:8080/v1/chat/completions"


def test_complete_returns_empty_dict_on_non_json_content():
    # Minimal "don't raise" posture: a model that returns junk (not JSON) yields
    # {} — the parse layer above treats that as "no actions". Full adversarial
    # coverage is step 6.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "not json at all"}}]}
        )

    client = _client_with_handler(handler)
    assert client.complete(system="s", user="u", schema={}) == {}


def test_complete_returns_empty_dict_on_unexpected_response_shape():
    # A response missing choices/message/content must not raise either.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    client = _client_with_handler(handler)
    assert client.complete(system="s", user="u", schema={}) == {}
