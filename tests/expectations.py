"""Golden-file ("expectation") snapshots for LLM-facing text.

Prompts (and, later, recorded model responses) are artifacts you review by eye,
not boolean logic — so we snapshot them to plain ``.txt`` files under
``tests/expectations/`` and assert equality. The file *is* the reviewable
artifact: open it to see exactly what the model receives; PR diffs show prompt
changes cleanly.

Usage::

    from tests.expectations import assert_matches_expectation
    assert_matches_expectation("link_prompt_system", rendered_system)

Regenerate after an intentional change (then eyeball the git diff)::

    NTAKE_UPDATE_EXPECTATIONS=1 make test     # rewrites the .txt files, passes

Homemade (no dependency) on purpose — the golden files stay plain text you can
read, rather than a plugin's opaque snapshot format.
"""

from __future__ import annotations

import os
from pathlib import Path

_DIR = Path(__file__).parent / "expectations"


def assert_matches_expectation(name: str, actual: str) -> None:
    """Assert ``actual`` equals the stored expectation ``name``.

    If ``NTAKE_UPDATE_EXPECTATIONS`` is set, (re)write the file with ``actual``
    and pass — the regen path. Otherwise compare; a missing file (with the flag
    unset) fails with a hint to regenerate.
    """
    path = _DIR / f"{name}.txt"

    if os.environ.get("NTAKE_UPDATE_EXPECTATIONS"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(actual, encoding="utf-8")
        return

    if not path.exists():
        raise AssertionError(
            f"no expectation file: {path}\n"
            "Run with NTAKE_UPDATE_EXPECTATIONS=1 to create it, then review the diff."
        )

    expected = path.read_text(encoding="utf-8")
    assert actual == expected, (
        f"{name} does not match {path}.\n"
        "If this change is intentional, regenerate with "
        "NTAKE_UPDATE_EXPECTATIONS=1 and review the diff."
    )
