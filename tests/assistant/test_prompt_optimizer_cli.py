"""Deterministic CLI-selection tests for the external prompt optimizer."""

from __future__ import annotations

from tools.prompt_optimizer.cli import _select_winner, _summary


def _row(
    name: str, train_recall: float, train_precision: float, latency: float
) -> dict:
    summary = {
        "recall": train_recall,
        "precision": train_precision,
        "latency": latency,
    }
    return {"name": name, "train": summary, "validate": summary, "template": None}


def test_selection_rejects_precision_regression_before_recall_gain():
    control = _row("control", 0.5, 1.0, 1.0)
    risky = _row("risky", 0.9, 0.8, 0.5)
    safe = _row("safe", 0.7, 1.0, 2.0)

    assert _select_winner([control, risky, safe])["name"] == "safe"


def test_selection_uses_latency_only_after_recall_and_precision_tie():
    control = _row("control", 0.5, 1.0, 1.0)
    slow = _row("slow", 0.7, 1.0, 2.0)
    fast = _row("fast", 0.7, 1.0, 0.5)

    assert _select_winner([control, slow, fast])["name"] == "fast"


def test_summary_averages_worker_rows():
    rows = [
        {
            "score": {"required_recall": 1.0, "forbidden_precision": 0.5},
            "elapsed_seconds": 2.0,
        },
        {
            "score": {"required_recall": 0.5, "forbidden_precision": 1.0},
            "elapsed_seconds": 4.0,
        },
    ]

    assert _summary(rows) == {"recall": 0.75, "precision": 0.75, "latency": 3.0}
