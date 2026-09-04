"""The reusable, domain-agnostic propose/route/confirm engine.

One cohesive module: the propose contract (``ProposedAction`` /
``AssistantClient`` / ``NullAssistant``), the generic action registry
(``ActionRegistry`` / ``ActionSpec`` / ``ActionError`` / ``require_params``), and
the bounded/graceful-degrade ``propose_bounded`` wrapper.

The opaque context is a **type parameter** (``ContextT`` bound to
``ActionContext``): the engine never inspects it, and each plugin binds its own
concrete context type — no ``Any``, and no parameter-variance issues, because a
plugin's ``AssistantClient[FocusedContext]`` / handler is a fully-typed
specialization rather than an override that narrows a base parameter.

Imports NOTHING app-specific (no app.models, no sqlalchemy, no fastapi) — that
boundary (enforced by tests/test_engine.py) is what makes it extractable into
its own package by a directory move.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum


class ActionContext:
    """Opaque context base — the thing the engine passes around but NEVER
    inspects. Plugins subclass it with their own fields (a session, target ids,
    the focused capture world, …) and bind it as the ``ContextT`` type parameter.
    Naming the concept (instead of ``Any``) documents the boundary and bounds the
    type parameter.
    """


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


class AssistantClient[ContextT: ActionContext](ABC):
    """Proposes zero or more actions for its context type. MUST NOT mutate
    anything and MUST return [] on any failure (never raise into the request
    path). The engine never inspects ``ctx``; a concrete client binds ``ContextT``
    to its own ActionContext subclass (e.g. ``AssistantClient[FocusedContext]``)."""

    @abstractmethod
    def propose(self, ctx: ContextT) -> list[ProposedAction]: ...


class NullAssistant(AssistantClient[ActionContext]):
    """The 'off' client — never proposes anything (accepts any context)."""

    def propose(self, ctx: ActionContext) -> list[ProposedAction]:
        return []


# --- the generic action registry ------------------------------------------

# A handler receives the plugin's concrete context (its bound ContextT) plus the
# action params, and returns a human summary. The engine never inspects it.
type Handler[ContextT: ActionContext] = Callable[[ContextT, dict], str]

# describe(params) -> deterministic action_summary. Pure fn of params (no app
# types); must tolerate missing/partial params (runs on unconfirmed proposals).
DescribeFn = Callable[[dict], str]

# render_card(params, resolved) -> the card's human-readable detail lines. Pure,
# like DescribeFn, but also given a ``resolved`` dict the APP pre-populates with
# session-backed lookups (id->name maps, a target label, timezone) — the engine
# never inspects it, so id/date resolution stays in the app while each action
# owns HOW its card reads (cohesion). Must tolerate missing/partial params +
# resolved (runs on unconfirmed proposals) and never raise.
RenderCardFn = Callable[[dict, dict], list[str]]


class ActionError(Exception):
    """Unknown action, missing/invalid params, or a bad target. Callers catch
    this and drop the action rather than failing the whole request."""


class DataType(Enum):
    """The closed param-type vocabulary — each member carries BOTH projections.

    A param's type is one member of this enum, and every member knows how to
    render itself two ways: ``human_token`` for the LLM tools *view* (the prompt
    menu) and ``json_schema`` for the tools *schema* (the constrained-output
    contract). Because both projections live on the one member, adding or changing
    a type is a single edit that can't leave the view and schema out of sync —
    ``params`` (built from these) is the single source of truth for both renders.

    Modelled as an ``Enum`` so the vocabulary is a genuinely closed, named,
    mypy-checkable type (no stray ad-hoc types can be invented at a call site) and
    is iterable/introspectable. Each member's *value* is
    ``(human_token, json_schema)``; the properties expose them by name.

    ``json_schema`` is a plain data fragment (a dict), NOT emission logic: the
    engine only stores it and never acts on it, so this stays domain-agnostic —
    the JSON-Schema *assembly* still happens in the local_llm package. (Named
    ``DataType`` to avoid shadowing the builtin ``type``; the literal JSON-Schema
    keyword ``"type"`` lives inside these fragments only.) ``INTEGER`` /
    ``ARRAY_INTEGER`` / ``OBJECT`` are pre-shaped for v2 actions (assign,
    checklist, participants).
    """

    STRING = ("string", {"type": "string"})
    DATETIME = ("datetime", {"type": "string", "format": "date-time"})
    DATE = ("date", {"type": "string", "format": "date"})
    INTEGER = ("integer", {"type": "integer"})
    ARRAY_STRING = ("array<string>", {"type": "array", "items": {"type": "string"}})
    ARRAY_INTEGER = ("array<integer>", {"type": "array", "items": {"type": "integer"}})
    OBJECT = ("object", {"type": "object"})

    @property
    def human_token(self) -> str:
        """The token the tools view prints (e.g. ``"array<string>"``)."""
        return self.value[0]

    @property
    def json_schema(self) -> dict:
        """The JSON-Schema fragment the tools schema assembles for this type."""
        return self.value[1]


@dataclass(frozen=True)
class Param:
    """One action parameter: its name, value type, and whether it's required.

    ``datatype`` is a :class:`DataType` member — a value carrying both the human
    token (tools view) and the JSON-Schema fragment (tools schema), so both renders
    derive from this one source. The engine treats it as opaque data (it never
    inspects the fragment).
    """

    name: str
    datatype: DataType
    required: bool = False


@dataclass(frozen=True)
class ActionSpec[ContextT: ActionContext]:
    """A registered action: identifier, human description, typed param contract,
    flags, describe, and handler. Parameterized by the plugin's context type so
    ``apply`` is fully typed.

    ``name`` is the identifier AND the registry key (``register(spec)`` keys off
    it). ``params`` is the single source of the param contract — ``required`` is
    derived from it. ``exclusive_params`` holds mutually-exclusive param *groups*
    (supply exactly one group; references param names) — the one cross-param
    constraint a flat ``params`` list can't express (for example, a future plugin
    action with mutually exclusive modes). ``description`` is the human sentence
    shown to the model.
    """

    name: str = ""
    description: str = ""
    params: list[Param] = field(default_factory=list)
    exclusive_params: list[list[str]] = field(default_factory=list)
    # What kind of existing entity this action operates on, as an opaque string
    # ("work_item" | "event") or None (a creator / meta action that targets
    # nothing). Defaults to None — the safe/inert, domain-neutral default: an
    # action targets nothing unless it opts in, so a forgotten declaration
    # mis-attaches no target (rather than silently defaulting to a work item). The
    # engine treats the value as opaque (it never inspects it); the app supplies
    # the domain ``TargetType`` str-enum, whose members ARE these strings. Single
    # source for the target category — both assistants read it to attach a
    # proposal's target. ``needs_target`` is derived from it.
    target_type: str | None = None
    logs: bool = True  # appends a source=assistant log entry on apply?
    apply: Handler[ContextT] = None  # type: ignore[assignment]
    describe: DescribeFn = None  # type: ignore[assignment]
    # Optional per-action card renderer (pure): (params, resolved) -> [str] detail
    # lines. None ⇒ the app falls back to a generic params render. See RenderCardFn.
    render_card: RenderCardFn | None = None

    @property
    def needs_target(self) -> bool:
        """Whether this action operates on an existing entity — derived;
        ``target_type`` is the single source (None ⇒ targets nothing)."""
        return self.target_type is not None

    @property
    def required(self) -> list[str]:
        """The required param names — derived; ``params`` is the single source."""
        return [p.name for p in self.params if p.required]

    @property
    def prompt_line(self) -> str:
        """This action rendered as one free-text line for the LLM tools view.

        Renders ALL params (the model needs the optional ones too), marking
        optional with ``?``, plus the exclusive-group clause when present.
        """
        parts = [
            f"{p.name}: {p.datatype.human_token}{'' if p.required else '?'}"
            for p in self.params
        ]
        params_txt = ", ".join(parts) if parts else "(no params)"
        line = f"- {self.name}: {self.description} — params: {params_txt}"
        if self.exclusive_params:
            groups = " OR ".join(
                "{" + ", ".join(g) + "}" for g in self.exclusive_params
            )
            line += f"  (exactly one of: {groups})"
        return line

    def execute(self, params: dict, context: ContextT) -> str:
        """Execute this action (a confirmed tool call): validate its own required
        params, then apply. The spec owns its validation — it knows its param
        contract — so the registry only needs to resolve name→spec. Raises
        ActionError on a missing required param.
        """
        require_params(params, self.required)
        return self.apply(context, params)

    def accepts(self, params: dict) -> bool:
        """Whether ``params`` structurally satisfies this action's contract.

        Non-raising counterpart to ``execute``'s validation, for the propose
        seam's **drop-invalid** graceful-degrade (LLD OQ-5: params validated
        against ``params``/``exclusive_params`` after emission): every required
        param must be present and non-empty, and — when ``exclusive_params`` is
        set — exactly ONE of the mutually-exclusive groups must be selected.

        A group is "selected" by its **anchor** (its first param), matching the
        apply handlers, which discriminate on the anchor (``start_at`` vs
        ``start_date``) and treat the rest of the group as optional (a missing
        ``end_at`` defaults to the start). So this checks the *mode* is
        unambiguous — exactly one anchor supplied — not that every group key is
        present. Deep per-value type coercion is left to ``apply``.
        """
        if any(params.get(k) in (None, "") for k in self.required):
            return False
        if self.exclusive_params:
            selected = sum(
                params.get(group[0]) not in (None, "")
                for group in self.exclusive_params
                if group
            )
            if selected != 1:
                return False
        return True


def require_params(params: dict, keys: list[str]) -> None:
    """Raise ActionError if any required key is missing/empty."""
    for k in keys:
        if params.get(k) in (None, ""):
            raise ActionError(f"missing required param: {k}")


class ActionRegistry[ContextT: ActionContext]:
    """A name → ActionSpec lookup with validate + dispatch + describe.

    Built from a flat list of specs (the config); no imperative registration.
    Parameterized by the plugin's context type: the app supplies its actions and
    injects a ``ContextT`` at dispatch time. Reusable across projects.
    """

    def __init__(self, specs: list[ActionSpec[ContextT]] | None = None) -> None:
        """Build the name→spec map from a flat list of specs (keyed by
        ``spec.name``). The specs ARE the config; there is no imperative
        registration step."""
        self._actions: dict[str, ActionSpec[ContextT]] = {
            s.name: s for s in (specs or [])
        }

    def get(self, name: str) -> ActionSpec[ContextT] | None:
        return self._actions.get(name)

    def names(self) -> list[str]:
        return list(self._actions)

    def all(self) -> list[ActionSpec[ContextT]]:
        """All specs, in config order (for the tools view)."""
        return list(self._actions.values())

    def describe(self, name: str, params: dict) -> str:
        """The deterministic action_summary for ``name`` + ``params``.

        Looks up the spec and calls its ``describe``. Unknown names fall back to
        the name itself (display-only; never raises).
        """
        spec = self._actions.get(name)
        if spec is None or spec.describe is None:
            return name
        return spec.describe(params)

    def dispatch(self, name: str, params: dict, context: ContextT) -> str:
        """Resolve ``name`` → spec and execute the confirmed tool call.

        The registry owns name resolution + the unknown-name policy; the spec
        owns validation + apply (``ActionSpec.execute``). Raises ActionError for
        an unknown name or a missing required param.
        """
        spec = self._actions.get(name)
        if spec is None:
            raise ActionError(f"unknown action: {name}")
        return spec.execute(params, context)


# --- bounded, graceful-degrade propose ------------------------------------


def propose_bounded[ContextT: ActionContext](
    client: AssistantClient[ContextT], ctx: ContextT, timeout: float
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
