"""``adapters`` — the infra-coupled implementations behind the core's seams.

Empty in Session 1. Built out across later sessions (AWS_HLD §5, AWS_LLD §2-§6):

* ``dynamo_repository`` / in-memory repo — the persistence seam (Sessions 2-3).
* ``bedrock_link`` / ``bedrock_propose`` — the two Bedrock Converse seams
  (Sessions 4-5).
* ``ws_publisher`` — direct ``postToConnection`` at the execute boundary
  (Session 6).
* ``authorizer`` — the device-token Lambda authorizer (Session 6).
* ``bedrock_log`` — full-fidelity Bedrock call logging → S3 (Session 7).

The only place ``boto3`` is imported; the core never sees it (boundary test).
"""

from __future__ import annotations
