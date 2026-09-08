"""Tests for deterministic benchmark import and authoring brief export."""

from __future__ import annotations

from datetime import UTC, datetime

from tools.prompt_optimizer.benchmark import load_cases, save_benchmark, source_hash
from tools.prompt_optimizer.models import PromptCase

NOW = datetime(2026, 9, 4, 18, 25, tzinfo=UTC)


def _raw_case(case_id: str = "case-1") -> dict:
    return {
        "case_id": case_id,
        "stage": "link",
        "tags": ["link.correct_event"],
        "timezone": "America/New_York",
        "now": NOW.isoformat(),
        "capture_author": "[m1] Alex (adult)",
        "world": {
            "members": [{"id": 1, "name": "Alex", "role": "adult"}],
            "work_items": [],
            "events": [{"id": 11, "title": "Dentist"}],
        },
        "world_view": (
            "FAMILY MEMBERS:\n- [m1] Alex (adult)\n\nEVENTS:\n- [e11] Dentist"
        ),
        "deep_context": "RELEVANT EVENTS:\n- [e11] Dentist",
        "capture": "move the dentist to Friday",
        "required_links": {"event_ids": [11]},
        "forbidden_links": {},
        "required_actions": [],
        "forbidden_actions": [],
    }


def test_benchmark_storage_round_trips_stage_cases_and_source_hash(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    source_file = source / "link.train.jsonl"
    source_file.write_text(
        PromptCase.model_validate(_raw_case()).model_dump_json() + "\n"
    )
    link_case = PromptCase.model_validate(_raw_case("link-1"))
    propose_raw = _raw_case("propose-1")
    propose_raw["stage"] = "propose"
    propose_raw["required_actions"] = [{"name": "no_action", "params": {}}]
    propose_case = PromptCase.model_validate(propose_raw)

    directory = save_benchmark(
        root=tmp_path / "benchmarks",
        benchmark_id="bench-1",
        link_train=[link_case],
        link_validate=[link_case],
        propose_train=[propose_case],
        propose_validate=[propose_case],
        source_hash=source_hash(source),
    )

    manifest = (directory / "manifest.json").read_text()
    assert "source_hash" in manifest
    assert load_cases(directory / "link.train.jsonl")[0].case_id == "link-1"
    assert load_cases(directory / "propose.train.jsonl")[0].case_id == "propose-1"
