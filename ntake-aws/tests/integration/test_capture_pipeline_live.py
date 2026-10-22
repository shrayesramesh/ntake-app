"""Tier-2: the joint LINK→PROPOSE assistant pipeline, over the REAL dev table.

The most end-to-end assistant test reachable before the HTTP/Lambda surface
exists (Session 6): seed a family + member + work item into the **real**
``ntake-dev`` DynamoDB table, run the **real** LINK call (its world view +
``deep_context`` are built from real base-table Queries, not a stub), then run the
**real** PROPOSE call over the ``FocusedContext`` LINK produced.

Why Dynamo, not in-memory: LINK reads the repository (``list_work_items`` /
``list_events`` / ``get_member`` — the family-partition ``begins_with(SK, …)``
Queries). Running those against the real table is the point of Tier 2 — the
in-memory double cannot surface a Dynamo-only read divergence, and this is the
only joint LINK→PROPOSE path that exercises the real data layer + the real model
together until the Session-6/8 Lambda e2e.

Scope boundaries (deliberate):
* Still **selection, not execution** — PROPOSE writes nothing; the only rows
  written are the seed, swept by the ``itest-`` prefix cleanup.
* Assertions are loose where the live model is non-deterministic (it is a real
  LLM) — they pin the *contract* (grounding to an in-family id; real deep context;
  only registered tools; target attached), not exact card text. The exact
  drop/attach/enum semantics are pinned deterministically at Tier 1.

Self-skips cleanly if the Anthropic secret isn't set (never a false pass).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import boto3
import pytest

import tests.harness.factories as factories
from adapters.anthropic_http import HttpAnthropicClient
from adapters.dynamo_repository import DynamoRepository
from core.actions.registry import REGISTRY
from core.assistant.anthropic_client import AnthropicClient
from core.assistant.anthropic_link import AnthropicCaptureResolver
from core.assistant.anthropic_propose import AnthropicAssistant
from core.assistant.capture import CaptureRequest, FocusedContext

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
TZ = "America/New_York"
MODEL = os.environ.get("NTAKE_ANTHROPIC_MODEL", "claude-haiku-4-5")


def _dump(label: str, value: Any) -> None:
    """Pretty-print a labelled JSON-ish blob to stdout (seen with ``pytest -s``)."""
    try:
        rendered = json.dumps(value, indent=2, default=str)
    except (TypeError, ValueError):
        rendered = repr(value)
    print(f"\n----- {label} -----\n{rendered}")


class ObservingAnthropicClient:
    """Wrap any ``AnthropicClient`` and print each request + raw response.

    A **test-only** observability shim (kept out of the production adapter so the
    request path carries no logging). It is a transparent pass-through — it
    forwards to the wrapped client and returns its response unchanged — but prints
    the system prompt, the user text, the ``tools`` / ``tool_choice`` it sent, and
    the raw Messages response (``content`` blocks, ``stop_reason``, ``usage``) for
    each call. Labelled with a ``tag`` (``LINK`` / ``PROPOSE``) so the two calls in
    a capture are distinguishable. Visible under ``pytest -s`` (``make
    integration`` runs ``-v``; add ``-s`` to see the prints).
    """

    def __init__(self, inner: AnthropicClient, tag: str) -> None:
        self._inner = inner
        self._tag = tag
        self.calls = 0

    def create_message(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls += 1
        print(f"\n========== {self._tag} call #{self.calls} ==========")
        print(f"\n----- {self._tag} system prompt -----\n{system}")
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    text = block.get("text") if isinstance(block, dict) else None
                    if text:
                        print(f"\n----- {self._tag} user text -----\n{text}")
        if tools is not None:
            _dump(f"{self._tag} tools sent ({len(tools)})", tools)
        if tool_choice is not None:
            _dump(f"{self._tag} tool_choice", tool_choice)
        response = self._inner.create_message(
            system, messages, tools=tools, tool_choice=tool_choice
        )
        _dump(f"{self._tag} RAW response", response)
        return response


def _dump_focused_context(fc: FocusedContext) -> None:
    """Print what LINK resolved — the grounding result + the rendered deep context."""
    print("\n========== LINK result (FocusedContext) ==========")
    print(f"  note:                 {fc.text!r}")
    print(f"  resolved work items:  {fc.resolved_work_item_ids}")
    print(f"  resolved events:      {fc.resolved_event_ids}")
    print(f"  resolved members:     {fc.resolved_member_ids}")
    print(f"\n----- deep_context PROPOSE will see -----\n{fc.deep_context}")


def _dump_proposals(proposals: list[Any]) -> None:
    """Print the PROPOSE cards — the mapped ProposedActions, not just names."""
    print(f"\n========== PROPOSE result ({len(proposals)} card(s)) ==========")
    for i, p in enumerate(proposals):
        print(
            f"  [{i}] {p.name}  params={p.params}  target={p.target_type}:{p.target_id}"
        )


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


def _seed(dynamo_repo: DynamoRepository):
    """Seed a family + member + an in-family work item into the real dev table.

    Ids carry the ``itest-`` prefix (set by the integration conftest autouse
    fixture), so every row is swept by the prefix cleanup after the run.
    """
    family = factories.make_family(timezone=TZ)
    alex = factories.make_member(family.id, display_name="Alex")
    dynamo_repo.seed_family(family, [alex])
    plumber = factories.make_work_item(family.id, title="call plumber", status="doing")
    dynamo_repo.put_work_item(plumber)
    return family, alex, plumber


@pytest.mark.usefixtures("_require_anthropic_secret")
def test_live_link_then_propose_over_real_dynamo(
    dynamo_repo: DynamoRepository,
) -> None:
    family, alex, plumber = _seed(dynamo_repo)
    real = HttpAnthropicClient(model=MODEL, region_name=_region())

    # --- LINK: real model + real Dynamo reads -> a real FocusedContext --------
    resolver = AnthropicCaptureResolver(ObservingAnthropicClient(real, "LINK"))
    fc = resolver.focus(
        CaptureRequest(text="the plumber is coming friday", timezone=TZ, now=NOW),
        dynamo_repo,
        alex,
    )
    _dump_focused_context(fc)

    # Grounded to the in-family item via the REAL base-table Query (not a stub),
    # and the deep context was rendered from the real row.
    assert fc.resolved_work_item_ids == [plumber.id]
    assert "call plumber" in fc.deep_context
    # First-person linking is deterministic; "the plumber" names nobody, so the
    # capturing member is linked only if the note is first-person — here it isn't,
    # so member ids may be empty. The point is the context is real, not stubbed.
    assert fc.deep_context != "(none linked)"

    # --- PROPOSE: real model over the real focused context --------------------
    proposer = AnthropicAssistant(ObservingAnthropicClient(real, "PROPOSE"))
    proposals = proposer.propose(fc)
    _dump_proposals(proposals)

    names = [p.name for p in proposals]
    assert names  # the real model selected at least one tool
    # Every proposal is a real registered action (tool_choice:any + the registry
    # projection hold against the real model).
    assert all(n in set(REGISTRY.names()) for n in names)
    # Any modifier the model picked for the linked item carries the attached
    # target from LINK's resolved ids (selection + app-side target attach).
    for p in proposals:
        if p.target_type == "work_item":
            assert p.target_id == plumber.id

    # Selection-not-execution: nothing new was written (only the seed exists).
    items = dynamo_repo.list_work_items(family.id)
    assert [wi.id for wi in items] == [plumber.id]


@pytest.mark.usefixtures("_require_anthropic_secret")
def test_live_multi_intent_note_tool_call_signal(
    dynamo_repo: DynamoRepository,
    record_property: Callable[[str, object], None],
) -> None:
    """Observe (do NOT assert a count) whether the real model fans a multi-intent
    note into multiple tool calls — the open §3.5 question.

    The design consumes a *list* of ``tool_use`` blocks either way (reshape-free),
    so v1 correctness does not depend on the answer. This test just surfaces the
    signal: a genuinely multi-intent note ("call the plumber ... and add milk to
    the grocery list" — two independent intents over two different targets) goes
    through the real LINK→PROPOSE pipeline, and the resulting card count is
    recorded (visible with ``pytest -rA`` / ``--junitxml``) so the Session-8
    full-tool-count reconciliation has real data. The only assertions are the
    invariant contract: at least one card, every card a registered action.
    """
    family, alex, plumber = _seed(dynamo_repo)
    # A second existing target so a fan-out has somewhere to land.
    groceries = factories.make_work_item(family.id, title="grocery list", status="todo")
    dynamo_repo.put_work_item(groceries)
    real = HttpAnthropicClient(model=MODEL, region_name=_region())

    note = "call the plumber about friday and add milk to the grocery list"
    fc = AnthropicCaptureResolver(ObservingAnthropicClient(real, "LINK")).focus(
        CaptureRequest(text=note, timezone=TZ, now=NOW), dynamo_repo, alex
    )
    _dump_focused_context(fc)
    proposals = AnthropicAssistant(ObservingAnthropicClient(real, "PROPOSE")).propose(
        fc
    )
    _dump_proposals(proposals)

    names = [p.name for p in proposals]
    # Record the signal for the §3.5 reconciliation — NOT an assertion on count.
    record_property("note", note)
    record_property("proposal_count", len(names))
    record_property("proposal_names", ",".join(names))
    print(f"\n[§3.5 multi-tool-call signal] {len(names)} card(s): {names}")

    # Contract only (count is deliberately NOT pinned — it is the open question):
    assert names  # the real model selected at least one tool
    assert all(n in set(REGISTRY.names()) for n in names)
