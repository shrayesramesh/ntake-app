"""Reusable project-owned benchmark JSONL storage."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.assistant.actions.registry import REGISTRY

from .models import BenchmarkManifest, PromptCase, Stage


def save_benchmark(
    *,
    root: Path,
    benchmark_id: str,
    link_train: list[PromptCase],
    link_validate: list[PromptCase],
    propose_train: list[PromptCase],
    propose_validate: list[PromptCase],
    source_hash: str,
) -> Path:
    """Save only validated reusable benchmark JSONL and one manifest."""
    directory = root / benchmark_id
    directory.mkdir(parents=True, exist_ok=False)
    files = {
        "link.train.jsonl": link_train,
        "link.validate.jsonl": link_validate,
        "propose.train.jsonl": propose_train,
        "propose.validate.jsonl": propose_validate,
    }
    for filename, cases in files.items():
        _write_cases(directory / filename, cases)
    stages: list[Stage] = []
    if link_train or link_validate:
        stages.append("link")
    if propose_train or propose_validate:
        stages.append("propose")
    manifest = BenchmarkManifest(
        benchmark_id=benchmark_id,
        stages=stages,
        case_count=len(link_train) + len(propose_train),
        validation_count=len(link_validate) + len(propose_validate),
        registry_hash=_registry_hash(),
        train_hash=_hash_cases(link_train + propose_train),
        validate_hash=_hash_cases(link_validate + propose_validate),
        source_hash=source_hash,
    )
    (directory / "manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return directory


def load_cases(path: Path) -> list[PromptCase]:
    """Load one JSONL stage/split file."""
    if not path.exists():
        return []
    return [
        PromptCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def benchmark_root(project_root: Path) -> Path:
    """Return the visible project-owned benchmark storage root."""
    return project_root / "prompt-optimizer" / "benchmarks"


def source_hash(source: Path) -> str:
    """Hash all stage JSONL source files for benchmark provenance."""
    digest = hashlib.sha256()
    for path in sorted(source.glob("*.jsonl")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _write_cases(path: Path, cases: list[PromptCase]) -> None:
    path.write_text(
        "".join(case.model_dump_json() + "\n" for case in cases), encoding="utf-8"
    )


def _hash_cases(cases: list[PromptCase]) -> str:
    payload = "\n".join(
        case.model_dump_json(by_alias=True, exclude_none=True) for case in cases
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _registry_hash() -> str:
    payload = [
        {
            "name": spec.name,
            "target_type": spec.target_type,
            "params": [
                (param.name, param.datatype.human_token, param.required)
                for param in spec.params
            ],
        }
        for spec in REGISTRY.all()
    ]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
