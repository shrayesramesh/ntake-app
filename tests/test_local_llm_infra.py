"""Step 10 — the in-app operational surface over an already-running model server.

``infra.py`` does NOT start/stop the model (that's the operator's llamafile /
systemd job, HOST_SETUP_GUIDE §7). It only *observes* and *primes* a running
endpoint: **health** (is ``base_url`` up and serving the expected model?),
**warm** (send a tiny priming completion so the first real capture isn't a
cold-load miss), and a **status** summary. Tested against stubbed httpx
(``httpx.MockTransport``) — no live model, like the client tests.

Like the request path, these never raise on a down/slow server — health reports
``reachable=False`` and warm reports ``False`` rather than blowing up a CLI or a
startup hook.
"""

from __future__ import annotations

import httpx

from app.assistant.local_llm.infra import HealthResult, check_health, warm


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _models_response(*names: str) -> httpx.Response:
    return httpx.Response(200, json={"data": [{"id": n} for n in names]})


# --- health ----------------------------------------------------------------


def test_health_reachable_and_model_present():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return _models_response("llama3.1:8b", "qwen2.5:14b")

    result = check_health(
        base_url="http://localhost:8080",
        model="llama3.1:8b",
        transport=_transport(handler),
    )
    assert isinstance(result, HealthResult)
    assert result.reachable is True
    assert result.model_ok is True
    assert "llama3.1:8b" in result.served_models


def test_health_reachable_but_model_missing():
    result = check_health(
        base_url="http://localhost:8080",
        model="llama3.1:8b",
        transport=_transport(lambda req: _models_response("some-other-model")),
    )
    assert result.reachable is True
    assert result.model_ok is False
    assert result.served_models == ["some-other-model"]


def test_health_unreachable_when_transport_errors():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    result = check_health(
        base_url="http://localhost:8080",
        model="llama3.1:8b",
        transport=_transport(boom),
    )
    assert result.reachable is False
    assert result.model_ok is False
    assert result.served_models == []


def test_health_unreachable_on_error_status():
    result = check_health(
        base_url="http://localhost:8080",
        model="m",
        transport=_transport(lambda req: httpx.Response(500)),
    )
    assert result.reachable is False


def test_health_tolerates_a_malformed_models_body():
    # 200 but not the expected shape → reachable, no models parsed, model not ok.
    result = check_health(
        base_url="http://localhost:8080",
        model="m",
        transport=_transport(lambda req: httpx.Response(200, json={"weird": 1})),
    )
    assert result.reachable is True
    assert result.served_models == []
    assert result.model_ok is False


# --- warm ------------------------------------------------------------------


def test_warm_returns_true_when_the_model_answers():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    assert (
        warm(
            base_url="http://localhost:8080",
            model="llama3.1:8b",
            transport=_transport(handler),
        )
        is True
    )


def test_warm_returns_false_when_the_server_is_down():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    assert (
        warm(base_url="http://localhost:8080", model="m", transport=_transport(boom))
        is False
    )


# --- _served_models branch coverage ---------------------------------------


def test_served_models_parses_ids_and_tolerates_junk():
    from app.assistant.local_llm.infra import _served_models

    assert _served_models({"data": [{"id": "a"}, {"id": "b"}]}) == ["a", "b"]
    # non-dict body, dict without a list `data`, and non-dict/id-less entries:
    assert _served_models("not a dict") == []
    assert _served_models({"data": "not a list"}) == []
    assert _served_models({"data": [{"no_id": 1}, "str", {"id": 5}]}) == []
