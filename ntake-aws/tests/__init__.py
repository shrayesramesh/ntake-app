"""Test suite for the ntake-aws rebuild.

Tiers (AWS_LLD §8): unit (core logic over the in-memory repo + scripted Bedrock),
boundary (import/call-graph assertions), access patterns (DynamoDB Local),
Bedrock contract (scripted Converse), infra (cdk synth). The shared harness lives
in ``tests/conftest.py`` + ``tests/harness/`` so later sessions import it rather
than rebuild fixtures.
"""
