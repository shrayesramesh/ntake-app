"""CLI orchestration for importing and evaluating synthetic prompt benchmarks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .benchmark import benchmark_root, load_cases, save_benchmark, source_hash
from .models import PromptCase, Stage, Variant, VariantSet
from .validation import validate_batch

Mode = Literal["benchmark", "evaluate"]


@dataclass(frozen=True)
class RuntimeConfig:
    """Local target model settings used only by the evaluator worker."""

    base_url: str
    model: str
    timeout: float


def main(argv: list[str] | None = None) -> int:
    """Dispatch benchmark import and stage-scoped local evaluation."""
    parser = argparse.ArgumentParser(prog="make prompt")
    parser.add_argument("mode", choices=["benchmark", "evaluate"])
    parser.add_argument("--stage", choices=["link", "propose", "both"], required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--benchmark")
    parser.add_argument("--variants-file", type=Path)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("NTAKE_LLM_BASE_URL", "http://localhost:8080"),
    )
    parser.add_argument(
        "--model", default=os.environ.get("NTAKE_LLM_MODEL", "llama3.1:8b")
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("NTAKE_LLM_TIMEOUT", "120")),
    )
    args = parser.parse_args(argv)
    config = RuntimeConfig(args.base_url, args.model, args.timeout)
    try:
        if args.mode == "benchmark":
            return _benchmark(args)
        if args.stage == "both":
            parser.error("evaluate requires STAGE=link or STAGE=propose")
        return _evaluate(args, config)
    except ValueError as error:
        parser.error(str(error))


def _benchmark(args: argparse.Namespace) -> int:
    if args.source is None:
        raise ValueError("benchmark requires --source <generated-benchmark-directory>")
    stages: list[Stage] = ["link", "propose"] if args.stage == "both" else [args.stage]
    collected: dict[str, tuple[list[PromptCase], list[PromptCase]]] = {}
    for stage in stages:
        train = _load_source_stage(args.source, stage, "train")
        validate = _load_source_stage(args.source, stage, "validate")
        errors = validate_batch(train) + validate_batch(validate)
        if errors:
            raise ValueError("source benchmark invalid: " + "; ".join(errors))
        collected[stage] = (train, validate)
    benchmark_id = "benchmark-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    directory = save_benchmark(
        root=benchmark_root(Path.cwd()),
        benchmark_id=benchmark_id,
        link_train=collected.get("link", ([], []))[0],
        link_validate=collected.get("link", ([], []))[1],
        propose_train=collected.get("propose", ([], []))[0],
        propose_validate=collected.get("propose", ([], []))[1],
        source_hash=source_hash(args.source),
    )
    print(f"benchmark: {directory}")
    return 0


def _evaluate(args: argparse.Namespace, config: RuntimeConfig) -> int:
    if args.variants_file is None:
        raise ValueError("evaluate requires --variants-file <prompt-set.json>")
    train = _load_stage(args.benchmark, args.stage, "train")
    validate = _load_stage(args.benchmark, args.stage, "validate")
    variants = _load_variants(args.variants_file, args.stage)
    rows: list[dict[str, Any]] = []
    for variant in variants.variants:
        train_rows = _run_worker(config, args.stage, train, variant.template)
        validate_rows = _run_worker(config, args.stage, validate, variant.template)
        rows.append(
            {
                "name": variant.name,
                "train": _summary(train_rows),
                "validate": _summary(validate_rows),
                "template": variant.template,
            }
        )
    winner = _select_winner(rows)
    print(_render_report(args.stage, rows, winner))
    return 0


def _load_source_stage(source: Path, stage: Stage, split: str) -> list[PromptCase]:
    path = source / f"{stage}.{split}.jsonl"
    cases = load_cases(path)
    if not cases:
        raise ValueError(f"source has no {stage} {split} cases: {path}")
    return cases


def _load_stage(benchmark_id: str | None, stage: Stage, split: str) -> list[PromptCase]:
    if not benchmark_id:
        raise ValueError("--benchmark is required")
    path = benchmark_root(Path.cwd()) / benchmark_id / f"{stage}.{split}.jsonl"
    cases = load_cases(path)
    if not cases:
        raise ValueError(f"benchmark has no {stage} {split} cases: {path}")
    return cases


def _load_variants(path: Path, stage: Stage) -> VariantSet:
    supplied = VariantSet.model_validate_json(path.read_text(encoding="utf-8"))
    if supplied.stage != stage:
        raise ValueError("variant set stage does not match --stage")
    candidates = [variant for variant in supplied.variants if variant.stage == stage]
    if not any(variant.name == "control" for variant in candidates):
        candidates.insert(0, Variant(name="control", stage=stage, template=None))
    if not candidates:
        raise ValueError("variant set contains no variants for the selected stage")
    return VariantSet(stage=stage, variants=candidates)


def _run_worker(
    config: RuntimeConfig, stage: Stage, cases: list[PromptCase], template: str | None
) -> list[dict[str, Any]]:
    payload = {
        "stage": stage,
        "cases": [case.model_dump(mode="json") for case in cases],
        "template": template,
        "base_url": config.base_url,
        "model": config.model,
        "timeout": config.timeout,
    }
    with tempfile.TemporaryDirectory(prefix="ntake_prompt_worker_") as directory:
        input_path = Path(directory) / "input.json"
        input_path.write_text(json.dumps(payload), encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "tools.prompt_optimizer.worker",
                "--input",
                str(input_path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    return json.loads(completed.stdout)


def _summary(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {"recall": 0.0, "precision": 0.0, "latency": 0.0}
    scores = [row["score"] for row in rows]
    return {
        "recall": sum(float(score["required_recall"]) for score in scores)
        / len(scores),
        "precision": sum(float(score["forbidden_precision"]) for score in scores)
        / len(scores),
        "latency": sum(float(row["elapsed_seconds"]) for row in rows) / len(rows),
    }


def _select_winner(rows: list[dict[str, Any]]) -> dict[str, Any]:
    control = next(row for row in rows if row["name"] == "control")
    control_train = control["train"]
    candidates = [
        row for row in rows if row["train"]["precision"] >= control_train["precision"]
    ]
    return max(
        candidates,
        key=lambda row: (row["train"]["recall"], -row["train"]["latency"]),
    )


def _render_report(
    stage: Stage, rows: list[dict[str, Any]], winner: dict[str, Any]
) -> str:
    lines = [
        f"# Prompt evaluation ({stage})",
        "",
        (
            "| variant | train recall | train precision | validation recall | "
            "validation precision |"
        ),
        "|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        train = row["train"]
        validate = row["validate"]
        lines.append(
            f"| {row['name']} | {train['recall']:.3f} | "
            f"{train['precision']:.3f} | {validate['recall']:.3f} | "
            f"{validate['precision']:.3f} |"
        )
    lines.extend(["", f"Selected train winner: `{winner['name']}`"])
    return "\n".join(lines)
