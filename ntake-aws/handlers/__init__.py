"""``handlers`` — thin AWS Lambda entry points (REST + WebSocket connect/disconnect).

Empty in Session 1: the HTTP/auth surface and the confirm/execute → publish
boundary are built in Session 6 (AWS_PLAN Phase 4, AWS_LLD §4/§5). Handlers hold
almost no logic — they are thin I/O over the ``core`` registry, the ``adapters``
repository, and the Bedrock seams.
"""

from __future__ import annotations
