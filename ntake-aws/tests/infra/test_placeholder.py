"""Placeholder so ``make test-infra`` collects until Session 7.

Then: ``cdk synth`` + CloudFormation-template assertions (per-Lambda IAM scoping,
the two GSIs, the logs-bucket lifecycle rule, the Budgets construct, dev-vs-prod
prop differences). Session 1 proves synth itself via ``make synth``; these are
the template-level assertions on top. See AWS_LLD §7/§8.
"""

from __future__ import annotations

import pytest


@pytest.mark.skip(reason="Template assertions arrive in Session 7 (AWS_PLAN Phase 5).")
def test_stack_template_placeholder() -> None:  # pragma: no cover
    raise AssertionError("not implemented until Session 7")
