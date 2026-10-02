"""``core.engine`` — the reusable, infra-agnostic propose/route/confirm engine.

Separated from any plugin so the machinery — register actions, validate params,
dispatch to a handler with an opaque context, describe an action, bounded propose
— is reusable and knows nothing about work items, events, DynamoDB, Bedrock, or
any HTTP framework. A boundary test (``tests/test_boundary.py``) enforces the
import rule (no persistence/DTO models, no ``boto3``, no ``sqlalchemy``, no
``fastapi``).

The engine lives in :mod:`core.engine.engine`; import public symbols from there
directly (no package-level facade until the engine splits into multiple modules).
"""

from __future__ import annotations
