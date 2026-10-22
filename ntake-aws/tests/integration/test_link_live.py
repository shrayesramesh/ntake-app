"""Tier-2: a live LINK call against the real Anthropic API (AWS_PLAN Session 4).

Runs ONLY under ``make integration`` (the Tier-1 gate ignores ``tests/integration``).
Proves the cloud-only truths Tier 1 structurally cannot: the Secrets Manager
``{api_key, workspace_id}`` read, egress to ``api.anthropic.com``, the real
Messages forced-tool response shape, and that the real model grounds a note to
the right in-family id. Uses an in-memory repo for the world view (LINK needs a
world + a model, not DynamoDB), so this isolates the Anthropic seam.

Self-skips cleanly if the Anthropic secret isn't set (never a false pass): the
``make integration`` creds self-check runs first; this skips if the key is
absent, recording it as a [HUMAN] follow-up.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import boto3
import pytest

from adapters.anthropic_http import HttpAnthropicClient
from core.assistant.anthropic_link import AnthropicCaptureResolver
from core.assistant.capture import CaptureRequest
from core.repository_memory import InMemoryRepository
from core.schemas import Family, Member, WorkItem

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TZ = "America/New_York"
MODEL = os.environ.get("NTAKE_ANTHROPIC_MODEL", "claude-haiku-4-5")


def _secret_id() -> str:
    stage = os.environ.get("NTAKE_STAGE", "dev")
    return os.environ.get(
        "NTAKE_ANTHROPIC_SECRET_ID", f"ntake-{stage}/anthropic-api-key"
    )


def _region() -> str:
    return os.environ.get("NTAKE_REGION") or os.environ.get("AWS_REGION", "us-east-1")


@pytest.fixture(scope="module")
def _require_anthropic_secret() -> None:
    """Skip (don't fail) if the Anthropic secret has no usable value yet."""
    try:
        raw = boto3.client("secretsmanager", region_name=_region()).get_secret_value(
            SecretId=_secret_id()
        )["SecretString"]
        data = json.loads(raw)
        assert data.get("api_key") and data.get("workspace_id")
    except Exception as e:  # noqa: BLE001
        pytest.skip(
            f"Anthropic secret {_secret_id()!r} not usable ({type(e).__name__}); "
            f"run `make secrets-anthropic` — [HUMAN] follow-up."
        )


def _seeded_repo() -> tuple[InMemoryRepository, Member]:
    repo = InMemoryRepository()
    alex = Member(
        id="m1", family_id="fam1", display_name="Alex", role="adult", created_at=NOW
    )
    repo.seed_family(Family(id="fam1", name="T", timezone=TZ, created_at=NOW), [alex])
    repo.put_work_item(
        WorkItem(
            id="w2",
            family_id="fam1",
            title="call plumber",
            status="doing",
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return repo, alex


@pytest.mark.usefixtures("_require_anthropic_secret")
def test_live_link_grounds_note_to_in_family_item() -> None:
    repo, alex = _seeded_repo()
    client = HttpAnthropicClient(model=MODEL, region_name=_region())
    resolver = AnthropicCaptureResolver(client)

    fc = resolver.focus(
        CaptureRequest(text="the plumber is coming friday", timezone=TZ, now=NOW),
        repo,
        alex,
    )

    # The real model should ground "the plumber" to the in-family work item w2.
    assert fc.resolved_work_item_ids == ["w2"]
    assert "call plumber" in fc.deep_context


@pytest.mark.usefixtures("_require_anthropic_secret")
def test_live_link_resolves_nothing_for_unrelated_note() -> None:
    repo, alex = _seeded_repo()
    client = HttpAnthropicClient(model=MODEL, region_name=_region())
    resolver = AnthropicCaptureResolver(client)

    fc = resolver.focus(
        CaptureRequest(text="buy stamps at the post office", timezone=TZ, now=NOW),
        repo,
        alex,
    )

    # Nothing existing matches → no linked work items (a brand-new task).
    assert fc.resolved_work_item_ids == []
