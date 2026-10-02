#!/usr/bin/env python3
"""bedrock_smoke.py — dev-stage integration checks against REAL Bedrock (Phase 5).

`make bedrock-smoke` delegates here. This drives the real capture→propose→confirm
flow against a deployed dev stack (real Bedrock + real DynamoDB + the real
authorizer and WebSocket post-back) — the cloud-only seams local tests cannot
prove (AWS_LLD §8, AWS_PLAN Session 8). It is NOT part of `make check`: it needs
a deployed stack and AWS credentials, so it runs only after `make deploy-dev`.

Session 1 ships this as a flagged placeholder so the tooling surface is complete
and the target exists; the real checks are implemented in Session 8. Running it
now exits non-zero with a clear "not implemented yet" message rather than
pretending to pass.
"""

from __future__ import annotations

import sys


def main() -> int:
    sys.stderr.write(
        "bedrock-smoke: not implemented yet (Session 8 / Phase 5c).\n"
        "This runs REAL Bedrock + a deployed dev stack; there is no AWS "
        "interaction before Session 1.5. See AWS_PLAN Part II, Session 8.\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
