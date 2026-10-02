"""Boundary-test tooling: assert a module imports none of a forbidden set.

The AWS analog of the old sqlalchemy-boundary check. The engine
(:mod:`core.engine.engine`) must stay infra-agnostic — importing it (freshly)
must not transitively pull in persistence/DTO models, ``boto3``, ``sqlalchemy``,
or any HTTP framework. Factored here so Sessions 2-9 reuse the exact same
assertion for other boundaries (e.g. the single ``publish_change`` call site, or
"handlers import no ``boto3``").
"""

from __future__ import annotations

import importlib
import sys


def imported_modules_on_fresh_import(module_name: str) -> set[str]:
    """Import ``module_name`` from a clean slate and return the modules it loaded.

    Drops ``module_name`` and its submodules from ``sys.modules`` first so the
    measurement reflects a genuine fresh import, then returns the set of newly
    added ``sys.modules`` keys.
    """
    for name in list(sys.modules):
        if name == module_name or name.startswith(module_name + "."):
            del sys.modules[name]

    before = set(sys.modules)
    importlib.import_module(module_name)
    return set(sys.modules) - before


def assert_imports_none_of(module_name: str, forbidden: set[str]) -> None:
    """Assert a fresh import of ``module_name`` leaks none of ``forbidden``.

    A module counts as leaked if its full dotted name is in ``forbidden`` OR its
    top-level package is (so ``sqlalchemy.orm`` is caught by ``"sqlalchemy"``).
    Raises ``AssertionError`` naming the leaked modules — the message a failing
    boundary test prints.
    """
    newly = imported_modules_on_fresh_import(module_name)
    leaked = {m for m in newly if m in forbidden or m.split(".")[0] in forbidden}
    assert not leaked, f"{module_name} leaked forbidden imports: {sorted(leaked)}"
