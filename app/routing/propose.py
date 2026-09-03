"""Bounded, graceful-degrade propose wrapper — engine core.

Runs ``client.propose(ctx)`` under a timeout and treats any timeout/error as
"no proposals" ([]), so a capture never fails or hangs on the model. Returns the
raw ``ProposedAction`` list; the app maps them to its own DTO (and assigns
proposal_ids / derives action_summary) at its boundary.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from app.routing.contract import AssistantClient, ProposedAction


def propose_bounded(
    client: AssistantClient, ctx: object, timeout: float
) -> list[ProposedAction]:
    """Call ``client.propose(ctx)`` bounded by ``timeout`` seconds; degrade to []."""
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(client.propose, ctx).result(timeout=timeout)
    except Exception:  # noqa: BLE001 — graceful degrade on any failure/timeout
        return []
