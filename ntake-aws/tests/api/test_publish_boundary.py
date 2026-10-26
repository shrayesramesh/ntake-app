"""The single-publish-boundary invariant (AWS_LLD §4.3).

The structural guard that replaces DynamoDB Streams: every committed change is
announced exactly once, from one place. Two properties, both checked by
AST-scanning the ``core`` + ``handlers`` source:

1. ``publish_change`` has exactly **one** call site — ``_announce`` in
   ``handlers/_support.py``. A second call site would let a write path publish
   on its own terms (or twice), and break "exactly once" by construction.
2. **Every write path** calls ``_announce``: the confirm/execute boundary
   (``run_confirm``) and the two direct REST writes (``create_work_item``,
   ``append_human_update``). A write path that forgot to announce would leave
   devices stale.

If the invariant ever can't hold (a write outside these paths), the documented
upgrade is DynamoDB Streams + a fan-out Lambda (HLD §8/§13).
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOTS = ("core", "handlers")
_DEF_MODULE = "live_sync.py"  # where publish_change is DEFINED (not a call site)
_WRITE_PATHS = {"run_confirm", "create_work_item", "append_human_update"}


def _call_sites(callee: str) -> list[tuple[str, str]]:
    """Every ``callee(...)`` call site as (file, enclosing function)."""
    here = Path(__file__).resolve().parents[2]  # ntake-aws/
    sites: list[tuple[str, str]] = []
    for root in _ROOTS:
        for path in (here / root).rglob("*.py"):
            if path.name == _DEF_MODULE:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                for inner in ast.walk(node):
                    if (
                        isinstance(inner, ast.Call)
                        and isinstance(inner.func, ast.Name)
                        and inner.func.id == callee
                    ):
                        sites.append((path.name, node.name))
    return sites


def test_publish_change_has_exactly_one_call_site_in_announce() -> None:
    sites = _call_sites("publish_change")
    assert sites == [("_support.py", "_announce")], (
        f"publish_change must be called only from _announce; found: {sites}"
    )


def test_every_write_path_announces() -> None:
    callers = {func for file, func in _call_sites("_announce") if file == "_support.py"}
    missing = _WRITE_PATHS - callers
    assert not missing, f"write paths that never announce: {sorted(missing)}"
