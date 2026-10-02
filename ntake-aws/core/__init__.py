"""``core`` — the infra-agnostic domain core of the AWS-native ntake app.

Lifted from the self-hosted app during the AWS rebuild (AWS_PLAN Phase 1b /
Session 0.1), kept unchanged where it was already infra-agnostic and rewired to
this ``core.*`` layout. The engine (:mod:`core.engine`) imports nothing
infra-specific; the persistence seam (a ``Repository``) and the Bedrock seams are
supplied by the ``adapters`` layer in later sessions. See ``spec/AWS_HLD.md`` §5.
"""

from __future__ import annotations
