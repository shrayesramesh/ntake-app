"""Placeholder so ``make test-api`` collects until Session 6.

Then: each route through its thin handler over the in-memory repo + scripted
Bedrock (health, events read, work-item/board read+append, /capture propose-only,
/actions/confirm execute+publish-once), plus the single-publish-boundary
invariant and the authorizer hashing. See AWS_LLD §4/§5.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="HTTP/auth surface arrives in Session 6 (AWS_PLAN Phase 4).")
def test_handlers_placeholder() -> None:  # pragma: no cover
    raise AssertionError("not implemented until Session 6")
