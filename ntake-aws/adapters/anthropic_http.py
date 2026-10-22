"""``HttpAnthropicClient`` — the real Anthropic Messages client (AWS_LLD §3).

The only place the Anthropic API is reached. Satisfies the generic
:class:`core.assistant.anthropic_client.AnthropicClient` protocol with one real
``POST https://api.anthropic.com/v1/messages``. The credential is read from
Secrets Manager (``{api_key, workspace_id}`` JSON, written by
``scripts/secrets-anthropic.sh``) once per client and cached; it is used only to
sign the request and is never logged.

Request shape is the real Messages shape verified by
``scripts/spike/link_probe.py``: ``x-api-key`` + ``anthropic-version`` +
``anthropic-workspace-id`` headers (the key is account-level, so the workspace
header is required), a body of ``{model, max_tokens, system, messages, tools?,
tool_choice?}``. stdlib ``urllib`` (no new dependency); ``boto3`` (already a dep)
reads the secret. Unit coverage is the Tier-2 ``make integration`` LINK call
against the real API — there is no value in stubbing a fake that can't prove the
real contract.
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

import boto3

_API_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_DEFAULT_MAX_TOKENS = 1024


def _default_secret_id() -> str:
    stage = os.environ.get("NTAKE_STAGE", "dev")
    return os.environ.get(
        "NTAKE_ANTHROPIC_SECRET_ID", f"ntake-{stage}/anthropic-api-key"
    )


def _default_region() -> str:
    return os.environ.get("NTAKE_REGION") or os.environ.get("AWS_REGION", "us-east-1")


class HttpAnthropicClient:
    """Real Anthropic Messages client; credential from Secrets Manager (cached)."""

    def __init__(
        self,
        *,
        model: str,
        secret_id: str | None = None,
        region_name: str | None = None,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._model = model
        self._secret_id = secret_id or _default_secret_id()
        self._region = region_name or _default_region()
        self._max_tokens = max_tokens
        self._creds: tuple[str, str] | None = None  # (api_key, workspace_id)

    def create_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        api_key, workspace_id = self._credentials()
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools is not None:
            body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice

        request = urllib.request.Request(
            _API_URL,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "anthropic-workspace-id": workspace_id,
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as resp:  # noqa: S310 (https literal)
            return json.loads(resp.read().decode("utf-8"))

    def _credentials(self) -> tuple[str, str]:
        if self._creds is None:
            client = boto3.client("secretsmanager", region_name=self._region)
            raw = client.get_secret_value(SecretId=self._secret_id)["SecretString"]
            data = json.loads(raw)
            self._creds = (data["api_key"], data["workspace_id"])
        return self._creds
