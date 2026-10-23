"""The single-publish-boundary invariant (AWS_LLD §4.3).

The structural guard that replaces DynamoDB Streams: ``publish_change`` is called
from exactly **one** place — the confirm/execute boundary (``run_confirm`` in
``handlers._support``). If a future write path published from somewhere else,
"every committed change is announced exactly once" would no longer hold by
construction. This test fails loudly if a second call site appears, pointing at
the documented upgrade (Streams + a fan-out Lambda) if the invariant ever can't
hold.

Implemented by AST-scanning the ``core`` + ``handlers`` source for calls to
``publish_change``: there must be exactly one, inside ``run_confirm``.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Package roots that could legitimately publish. (Tests + the live_sync module's
# own definition are excluded — we count *call sites*, not the def.)
_ROOTS = ("core", "handlers")
_DEF_MODULE = "live_sync.py"  # where publish_change is DEFINED (not a call site)


def _call_sites() -> list[tuple[str, str]]:
    """Every ``publish_change(...)`` call site as (file, enclosing-function)."""
    here = Path(__file__).resolve().parents[2]  # ntake-aws/
    sites: list[tuple[str, str]] = []
    for root in _ROOTS:
        for path in (here / root).rglob("*.py"):
            if path.name == _DEF_MODULE:
                continue
            tree = ast.parse(path.read_text(), filename=str(path))
            _collect(tree, path.name, sites)
    return sites


def _collect(tree: ast.AST, filename: str, sites: list[tuple[str, str]]) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Name)
                and inner.func.id == "publish_change"
            ):
                sites.append((filename, node.name))


def test_publish_change_has_exactly_one_call_site_at_the_confirm_boundary() -> None:
    sites = _call_sites()
    assert len(sites) == 1, f"expected ONE publish_change call site, found: {sites}"
    filename, func = sites[0]
    assert filename == "_support.py"
    assert func == "run_confirm"
