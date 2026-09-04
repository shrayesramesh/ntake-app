"""``infra.py`` — the in-app operational surface over an *already-running* model.

Task 7 step 10. This does NOT provision, start, or stop the model — acquiring the
llamafile binary + weights and serving them (foreground / systemd) is the
operator's job (HOST_SETUP_GUIDE §7). Here we only *observe* and *prime* a running
endpoint:

* :func:`check_health` — GET ``/v1/models``: is ``base_url`` reachable, and is the
  expected ``model`` among those served?
* :func:`warm` — send a tiny priming ``/v1/chat/completions`` so the model loads
  into memory before the first real capture (the pipeline is two sequential calls
  and a cold first call can take tens of seconds → a timed-out cold miss). Called
  by the ``manage llm warm`` CLI and a startup hook.

Both are **non-raising** (same posture as the request path): a down/slow/garbled
server yields ``reachable=False`` / ``warm() is False`` rather than an exception,
so a CLI or startup hook degrades cleanly. Only this module + ``client.py`` import
httpx. ``transport`` is an injection seam for tests (``httpx.MockTransport``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

_MODELS_PATH = "/v1/models"
_CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
_HEALTH_TIMEOUT = 5.0
_WARM_TIMEOUT = 120.0  # a cold first load can take tens of seconds


@dataclass(frozen=True)
class HealthResult:
    """Outcome of a health probe. ``reachable`` = the endpoint answered
    ``/v1/models`` with 200; ``served_models`` = the ids it reported (empty if
    unreachable or the body was unparseable); ``model_ok`` = the expected model is
    among them. ``detail`` is a short human line for the CLI."""

    reachable: bool
    model_ok: bool
    served_models: list[str] = field(default_factory=list)
    detail: str = ""


def check_health(
    base_url: str, model: str, transport: httpx.BaseTransport | None = None
) -> HealthResult:
    """Probe ``base_url``'s ``/v1/models``; report reachability + model presence.

    Never raises: any transport error, non-200, or unparseable body → an
    unreachable/not-ok result.
    """
    url = base_url.rstrip("/") + _MODELS_PATH
    try:
        with httpx.Client(timeout=_HEALTH_TIMEOUT, transport=transport) as http:
            response = http.get(url)
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return HealthResult(
            reachable=False,
            model_ok=False,
            detail=f"unreachable at {url}",
        )
    served = _served_models(data)
    model_ok = model in served
    detail = (
        f"serving {model!r}"
        if model_ok
        else f"reachable, but {model!r} not in served models {served}"
    )
    return HealthResult(
        reachable=True, model_ok=model_ok, served_models=served, detail=detail
    )


def _served_models(data: object) -> list[str]:
    """Extract model ids from an OpenAI-style ``/v1/models`` body; [] if unusable."""
    if not isinstance(data, dict):
        return []
    entries = data.get("data")
    if not isinstance(entries, list):
        return []
    return [
        e["id"] for e in entries if isinstance(e, dict) and isinstance(e.get("id"), str)
    ]


def warm(
    base_url: str, model: str, transport: httpx.BaseTransport | None = None
) -> bool:
    """Send a tiny priming completion so the model loads into memory.

    Returns True if the server answered a completion (2xx), False on any
    transport/timeout/status error. A large timeout tolerates the cold-load wait.
    """
    url = base_url.rstrip("/") + _CHAT_COMPLETIONS_PATH
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        with httpx.Client(timeout=_WARM_TIMEOUT, transport=transport) as http:
            response = http.post(url, json=payload)
            response.raise_for_status()
    except httpx.HTTPError:
        return False
    return True
