"""The Lambda bundle needs nothing the Python 3.12 Lambda runtime doesn't provide.

The regression guard for the Session-6 first-deploy failure: the CDK Lambda asset
is our source only (no dependency bundling), and the managed Python runtime ships
``boto3`` (+ its dependencies) but no other third-party package. When
``core.schemas`` used Pydantic, every handler that imported it died at import
time (HTTP 500) while the pydantic-free authorizer worked.

This test imports every Lambda entry-point module in a **clean interpreter**
(subprocess — immune to whatever earlier tests imported) and asserts each
non-stdlib top-level module it loads is either provided by the Lambda runtime or
is one of our own packages. Adding a third-party import to the Lambda code fails
here, at Tier 1, instead of as a 500 after a deploy.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# The handler entry points CDK wires (see infra/lib/ntake-stack.ts).
_ENTRY_MODULES = ("handlers.authorizer", "handlers.http_api", "handlers.ws")

# Provided by the AWS Lambda Python 3.12 managed runtime: boto3 and its deps.
_RUNTIME_PROVIDED = {
    "boto3",
    "botocore",
    "s3transfer",
    "jmespath",
    "dateutil",
    "urllib3",
    "six",
}

# Our own packages, shipped in the asset.
_OWN = {"core", "adapters", "handlers"}

_PROBE = """
import importlib, json, sys
for name in {modules!r}:
    importlib.import_module(name)
print(json.dumps(sorted({{m.split('.')[0] for m in sys.modules}})))
"""


def _loaded_top_levels() -> set[str]:
    root = Path(__file__).resolve().parents[1]  # ntake-aws/
    out = subprocess.run(
        [sys.executable, "-c", _PROBE.format(modules=_ENTRY_MODULES)],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return set(json.loads(out.stdout))


def test_lambda_code_imports_only_stdlib_runtime_and_own_packages() -> None:
    loaded = _loaded_top_levels()
    third_party = {
        m for m in loaded if m not in sys.stdlib_module_names and not m.startswith("_")
    }
    unexpected = third_party - _RUNTIME_PROVIDED - _OWN
    assert not unexpected, (
        "Lambda code imports packages the Lambda runtime does not provide "
        f"(they would fail at import → HTTP 500): {sorted(unexpected)}"
    )


def test_pydantic_is_not_imported_by_lambda_code() -> None:
    loaded = _loaded_top_levels()
    assert "pydantic" not in loaded and "pydantic_core" not in loaded
