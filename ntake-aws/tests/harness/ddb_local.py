"""DynamoDB Local availability probe — the skipped-if-absent gate (AWS_LLD §8).

Access-pattern tests (Session 3+) run ``DynamoRepository`` against DynamoDB Local
on ``localhost:8000`` (``make ddb-up``). On a machine with no container runtime
there is no DynamoDB Local, so those tests must **skip**, not fail — this probe is
how they decide. Session 1 ships the probe (no docker in this environment, so it
returns False here) and a ready-made ``requires_dynamodb_local`` marker.
"""

from __future__ import annotations

import os
import socket

import pytest

DDB_LOCAL_HOST = os.environ.get("NTAKE_DDB_LOCAL_HOST", "127.0.0.1")
DDB_LOCAL_PORT = int(os.environ.get("NTAKE_DDB_LOCAL_PORT", "8000"))


def dynamodb_local_available(
    host: str = DDB_LOCAL_HOST, port: int = DDB_LOCAL_PORT, timeout: float = 0.25
) -> bool:
    """True iff something is accepting TCP connections on the DynamoDB Local port.

    A cheap liveness probe (no boto3, no AWS call) so collection stays fast and
    the gate never blocks on a missing container.
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# A reusable marker: decorate a test/class to skip it when DynamoDB Local is down.
requires_dynamodb_local = pytest.mark.skipif(
    not dynamodb_local_available(),
    reason=(
        f"DynamoDB Local not reachable on {DDB_LOCAL_HOST}:{DDB_LOCAL_PORT} "
        "— run 'make ddb-up' (needs a container runtime). Skipped-if-absent."
    ),
)
