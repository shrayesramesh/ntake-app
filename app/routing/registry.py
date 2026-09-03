"""Generic action registry + dispatch — the domain-agnostic engine core.

Register named actions (``required`` params, ``describe`` for the ground-truth
summary, an ``apply`` handler); ``dispatch`` validates params and calls the
handler with an OPAQUE context the engine never inspects. No app types.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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

    def dispatch(self, name: str, params: dict, context: object) -> str:
        """Validate + apply a confirmed action. Returns a human summary.

        Raises ActionError for unknown names or missing required params. The
        handler does the actual work using the opaque ``context``.
        """
        spec = self._actions.get(name)
        if spec is None:
            raise ActionError(f"unknown action: {name}")
        require_params(params, spec.required)
        return spec.apply(context, params)
