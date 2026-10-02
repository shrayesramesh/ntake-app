"""Shared test harness — the DRY backbone every later session imports (AWS_LLD §8).

Pieces:

* :mod:`tests.harness.boundary` — import/call-graph assertions (the boundary
  test's tooling): "this module transitively imports none of these packages".
* :mod:`tests.harness.bedrock_double` — :class:`ScriptedBedrockClient`, the
  deterministic Bedrock Converse double (canned LINK JSON + ``toolUse`` blocks),
  the Converse-shaped analog of the old ``ScriptedLLM``.
* :mod:`tests.harness.repos` — the repository factories the ``repo`` fixture
  parametrizes over: the in-memory fake now, the DynamoDB-Local-backed one later
  (Session 3). One test body, two backends.
* :mod:`tests.harness.ddb_local` — the skipped-if-absent DynamoDB Local probe.

Sessions 2-9 import from here instead of re-inventing fixtures.
"""
