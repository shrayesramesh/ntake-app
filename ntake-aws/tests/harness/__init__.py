"""Shared test harness — the DRY backbone every later session imports (AWS_LLD §8).

Pieces:

* :mod:`tests.harness.boundary` — import/call-graph assertions (the boundary
  test's tooling): "this module transitively imports none of these packages".
* :mod:`tests.harness.bedrock_double` — :class:`ScriptedBedrockClient`, the
  deterministic Bedrock Converse double (canned LINK JSON + ``toolUse`` blocks),
  the Converse-shaped analog of the old ``ScriptedLLM``.
* :mod:`tests.harness.repos` — the in-memory repository factory the ``repo``
  fixture builds (Tier 1 is in-memory only; Tier 2 points a ``DynamoRepository``
  at the real dev table via its own conftest, AWS_LLD §8).

Sessions 2-9 import from here instead of re-inventing fixtures.
"""
