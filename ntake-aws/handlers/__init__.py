"""``handlers`` — thin AWS Lambda entry points (HTTP + WebSocket + authorizer).

Built in Session 6 (AWS_PLAN Phase 4, AWS_LLD §4/§5). Handlers hold almost no
logic — they parse the AWS event envelope and delegate to the pure, Tier-1-tested
logic in ``_support`` (capture / confirm / read conversions) and ``_auth``
(authorizer decision + pairing), over the ``core`` seams (``Repository`` /
``TokenStore`` / the ``AnthropicClient`` + ``ConnectionPoster`` effects). The real
boto3-backed adapters are assembled in ``_runtime`` from the Lambda environment —
the only handler code that touches boto3 + env.

Entry points (design B: one Lambda per route group, each with a scoped IAM role):

* ``authorizer.handler`` — device-token REQUEST authorizer (simple response).
* ``http_api.{reads,capture,confirm,pairing,pair}_handler`` — the HTTP routes.
* ``ws.{connect,disconnect}_handler`` — the WebSocket connection registry.
"""

from __future__ import annotations
