"""Tests for the offline command surface of the local-LLM installer."""

from __future__ import annotations

import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "install_local_llm.sh"


def test_local_llm_installer_help_is_available_without_network():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--model llama|qwen" in result.stdout
    assert "does not start the server" in result.stdout


def test_local_llm_installer_rejects_unknown_model_without_network():
    result = subprocess.run(
        ["bash", str(SCRIPT), "--model", "unknown"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Unsupported model" in result.stderr
