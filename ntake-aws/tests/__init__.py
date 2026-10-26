"""Test suite for the ntake-aws rebuild.

Tiers (AWS_LLD §8): Tier 1 (``make check``) — unit + flow tests over the
in-memory repo + the scripted Anthropic double, boundary (import/call-graph)
assertions, and infra (``cdk synth`` + template assertions); Tier 2
(``tests/integration``, ``make integration``) — the real dev stage. The shared
harness lives in ``tests/conftest.py`` + ``tests/harness/`` so later sessions
import it rather than rebuild fixtures.
"""
