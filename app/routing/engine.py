"""The reusable, domain-agnostic propose/route/confirm engine.

One cohesive module: the propose contract (``ProposedAction`` /
``AssistantClient`` / ``NullAssistant``), the generic action registry
(``ActionRegistry`` / ``ActionSpec`` / ``ActionError`` / ``require_params``), and
the bounded/graceful-degrade ``propose_bounded`` wrapper.

Imports NOTHING app-specific (no app.models, no sqlalchemy, no fastapi) — that
boundary (enforced by tests/test_engine.py) is what makes it extractable into
its own package by a directory move. Any project reuses it by registering its
own actions and injecting its own opaque context.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

# --- the propose contract -------------------------------------------------


@dataclass
class ProposedAction:
    """A single proposed, unconfirmed action — exactly what an assistant returns.

    Domain-free: ``name`` is a registry key, ``params`` a plain dict. ``target_id``
    /``target_type`` identify what it operates on (opaque to the engine).
    ``llm_rationale`` is the model's own narration (may be wrong/empty). There is
    deliberately no ``action_summary`` here — that is derived from the registry's
    ``describe`` (ground truth), not carried by the model.

    ``proposal_id`` is a batch-local handle assigned by the propose seam.
    ``target_ref`` is reserved for dependency chaining (a proposal targeting
    another proposal's to-be-created entity); unused in v1.
    """

    name: str
    params: dict
    llm_rationale: str = ""
    target_id: int | None = None
    target_type: str | None = None
    proposal_id: str = ""
    target_ref: str | None = None


class AssistantClient(ABC):
    """Proposes zero or more actions for an opaque context. MUST NOT mutate
    anything and MUST return [] on any failure (never raise into the request
    path). The engine treats ``ctx`` as opaque (``Any``) — it never inspects it;
    a concrete client may annotate its own context type."""

    @abstractmethod
    def propose(self, ctx: Any) -> list[ProposedAction]: ...


class NullAssistant(AssistantClient):
    """The 'off' client — never proposes anything."""

    def propose(self, ctx: Any) -> list[ProposedAction]:
        return []


# --- the generic action registry ------------------------------------------

# A handler receives the OPAQUE context the app injects at dispatch time, plus
# the action params, and returns a human summary. The engine never inspects the
# context — its type is ``Any`` because the engine imposes NOTHING on it; the
# plugin's handler annotates and unpacks its own concrete context type.
Handler = Callable[[Any, dict], str]

# describe(params) -> deterministic action_summary. Pure fn of params (no app
# types); must tolerate missing/partial params (runs on unconfirmed proposals).
DescribeFn = Callable[[dict], str]


class ActionError(Exception):
    """Unknown action, missing/invalid params, or a bad target. Callers catch
    this and drop the action rather than failing the whole request."""


@dataclass(frozen=True)
class ActionSpec:
    """A registered action: its param contract, flags, describe, and handler."""

    required: list[str] = field(default_factory=list)
    needs_target: bool = True  # operates on an existing entity?
    logs: bool = True  # appends a source=assistant log entry on apply?
    apply: Handler = None  # type: ignore[assignment]
    describe: DescribeFn = None  # type: ignore[assignment]


def require_params(params: dict, keys: list[str]) -> None:
    """Raise ActionError if any required key is missing/empty."""
    for k in keys:
        if params.get(k) in (None, ""):
            raise ActionError(f"missing required param: {k}")


class ActionRegistry:
    """A name → ActionSpec registry with validate + dispatch + describe.

    Domain-agnostic: the app registers its actions and injects an opaque context
    at dispatch time. Reusable across projects by construction.
    """

    def __init__(self) -> None:
        self._actions: dict[str, ActionSpec] = {}

    def register(self, name: str, spec: ActionSpec) -> None:
        self._actions[name] = spec

    def get(self, name: str) -> ActionSpec | None:
        return self._actions.get(name)

    def names(self) -> list[str]:
        return list(self._actions)

    def describe(self, name: str, params: dict) -> str:
        """The deterministic action_summary for ``name`` + ``params``.

        Looks up the spec and calls its ``describe``. Unknown names fall back to
        the name itself (display-only; never raises).
        """
        spec = self._actions.get(name)
        if spec is None or spec.describe is None:
            return name
        return spec.describe(params)

    def dispatch(self, name: str, params: dict, context: Any) -> str:
        """Validate + apply a confirmed action. Returns a human summary.

        Raises ActionError for unknown names or missing required params. The
        handler does the actual work using the opaque ``context``.
        """
        spec = self._actions.get(name)
        if spec is None:
            raise ActionError(f"unknown action: {name}")
        require_params(params, spec.required)
        return spec.apply(context, params)


# --- bounded, graceful-degrade propose ------------------------------------


def propose_bounded(
    client: AssistantClient, ctx: Any, timeout: float
) -> list[ProposedAction]:
    """Call ``client.propose(ctx)`` bounded by ``timeout`` seconds; degrade to [].

    Runs under a timeout and treats any timeout/error as "no proposals", so a
    capture never fails or hangs on the model.
    """
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(client.propose, ctx).result(timeout=timeout)
    except Exception:  # noqa: BLE001 — graceful degrade on any failure/timeout
        return []
