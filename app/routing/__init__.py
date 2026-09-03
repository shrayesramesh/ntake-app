"""``app.routing`` — the reusable, domain-agnostic propose/route/confirm engine.

Separated from the ntake plugin (``app.assistant``) so the machinery — register
actions, validate params, dispatch to a handler with an opaque context, describe
an action, bounded propose — is reusable and knows nothing about work items,
events, SQLAlchemy, or FastAPI. A boundary test enforces the import rule.

Package-shape now (a self-contained sub-package), not a separately published
package — extractable by a directory move if a second consumer appears. The
whole engine lives in :mod:`app.routing.engine`; this re-exports its public API.
"""

from __future__ import annotations

from app.routing.engine import (
    ActionContext,
    ActionError,
    ActionRegistry,
    ActionSpec,
    AssistantClient,
    DescribeFn,
    Handler,
    NullAssistant,
    ProposedAction,
    propose_bounded,
    require_params,
)

__all__ = [
    "ActionContext",
    "ActionError",
    "ActionRegistry",
    "ActionSpec",
    "AssistantClient",
    "DescribeFn",
    "Handler",
    "NullAssistant",
    "ProposedAction",
    "propose_bounded",
    "require_params",
]
