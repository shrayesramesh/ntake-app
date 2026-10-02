"""Placeholder so ``make test-assistant`` collects until Sessions 4-5.

Then: the LINK flow (world view → scripted Converse JSON → validate-against-family
→ whitelist → deep context) and PROPOSE (registry→toolConfig, selection-not-
execution, enum-over-whitelist, multiple toolUse blocks → multiple cards),
driven by the ``scripted_bedrock`` fixture. See AWS_LLD §3.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Assistant seams arrive in Sessions 4-5 (AWS_PLAN Phase 3).")
def test_bedrock_seams_placeholder() -> None:  # pragma: no cover
    raise AssertionError("not implemented until Session 4")
