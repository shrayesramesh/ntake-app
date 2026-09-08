"""Isolated subprocess worker for one prompt-template evaluation profile."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from app.assistant.actions.registry import REGISTRY
from app.assistant.local_llm import link, propose
from app.assistant.local_llm.client import LocalLlmClient
from app.assistant.local_llm.protocol import LLM
from app.assistant.tools_view import build_ntake_tools_view

from .models import PromptCase, Score, Stage
from .scoring import score_actions, score_links


@dataclass(frozen=True)
class CaseEvaluation:
    """One prompt/model result with normalized deterministic scoring."""

    case_id: str
    system: str
    user: str
    raw_reply: dict
    score: Score
    elapsed_seconds: float


@contextmanager
def _override_template(stage: Stage, template: str | None) -> Iterator[None]:
    """Temporarily replace one stage's system template and always restore it."""
    if template is None:
        yield
        return
    if stage == "link":
        original = link.LINK_SYSTEM
        link.LINK_SYSTEM = template
        try:
            yield
        finally:
            link.LINK_SYSTEM = original
    else:
        original = propose.PROPOSE_SYSTEM
        propose.PROPOSE_SYSTEM = template
        try:
            yield
        finally:
            propose.PROPOSE_SYSTEM = original


def evaluate_cases(
    *, stage: Stage, cases: list[PromptCase], llm: LLM, template: str | None = None
) -> list[CaseEvaluation]:
    """Evaluate one stage against cases inside the current isolated process."""
    if any(case.stage != stage for case in cases):
        raise ValueError("case stage does not match evaluation stage")
    results: list[CaseEvaluation] = []
    with _override_template(stage, template):
        for case in cases:
            started = time.monotonic()
            if stage == "link":
                system, user = link.build_link_prompt(
                    world_view=case.world_view,
                    note=case.capture,
                    now=case.now,
                    timezone=case.timezone,
                )
                raw = llm.complete(system=system, user=user, schema=link._LINK_SCHEMA)
                work_item_ids, event_ids, member_ids = link.parse_ids(raw)
                score = score_links(
                    actual_work_item_ids=work_item_ids,
                    actual_event_ids=event_ids,
                    actual_member_ids=member_ids,
                    required=case.required_links,
                )
            else:
                tools_view = build_ntake_tools_view(REGISTRY)
                system, user = propose.build_propose_prompt(
                    tools_view=tools_view,
                    capture_author=case.capture_author,
                    deep_context=case.deep_context,
                    note=case.capture,
                    now=case.now,
                    timezone=case.timezone,
                )
                raw = llm.complete(
                    system=system,
                    user=user,
                    schema=propose.build_tools_schema(REGISTRY),
                )
                score = score_actions(
                    actual=propose._parse_actions(raw),
                    required=case.required_actions,
                )
            results.append(
                CaseEvaluation(
                    case_id=case.case_id,
                    system=system,
                    user=user,
                    raw_reply=raw,
                    score=score,
                    elapsed_seconds=time.monotonic() - started,
                )
            )
    return results


def main(argv: list[str] | None = None) -> int:
    """Run a JSON-described stage evaluation in a dedicated Python process."""
    parser = argparse.ArgumentParser(description="Prompt optimizer worker")
    parser.add_argument("--input", required=True, type=Path)
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    stage = payload["stage"]
    cases = [PromptCase.model_validate(case) for case in payload["cases"]]
    llm = LocalLlmClient(
        base_url=payload["base_url"],
        model=payload["model"],
        timeout=float(payload["timeout"]),
    )
    results = evaluate_cases(
        stage=stage,
        cases=cases,
        llm=llm,
        template=payload.get("template"),
    )
    print(
        json.dumps(
            [
                {
                    **asdict(result),
                    "score": result.score.model_dump(),
                }
                for result in results
            ],
            default=str,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess CLI
    raise SystemExit(main())
