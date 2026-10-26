"""``adapters`` — the infra-coupled implementations behind the core's seams.

(AWS_HLD §5, AWS_LLD §2-§6):

* ``dynamo_repository`` — the family persistence seam over the single table.
* ``dynamo_token_store`` — the identity seam (device tokens + pairing codes).
* ``anthropic_http`` — the real Anthropic Messages client behind the LINK /
  PROPOSE seams (API key from Secrets Manager).

Assistant call logging → S3 arrives in Session 7. With the Lambda ``handlers``
runtime wiring, this is where ``boto3`` is imported; the core never sees it
(boundary test).
"""

from __future__ import annotations
