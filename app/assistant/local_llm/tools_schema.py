"""``build_tools_schema`` — the constrained-output JSON schema (PROPOSE call).

The machine-side twin of ``build_tools_view``: where the tools *view* renders the
action registry as a human-readable menu for the prompt, the tools *schema*
renders the SAME registry as the JSON Schema the model's output is constrained to
(llamafile's grammar / an OpenAI ``response_format`` — the runtime knob lives in
``client.py``, step 3). Pure function, no network.

Shape (LLD OQ-1 / OQ-5): a uniform envelope
``{"actions": [ <action item>, ... ]}`` where each action item is one ``oneOf``
branch discriminated by ``name`` (a ``const``), carrying a ``params`` object built
from that action's ``Param`` list. Each param's JSON-Schema fragment is declared
on its :class:`~app.routing.engine.DataType` (the single source shared with the
tools view — ``human_token`` there, ``json_schema`` here), so this generator only
*assembles* fragments; it never maps a bare type string. ``exclusive_params``
(mutually-exclusive param groups) become a per-action ``oneOf`` over the
required-key sets.

Why this lives in ``local_llm`` and not beside ``tools_view``: ``tools_view`` is
backend-neutral (shared by the fake backend, returns a ``str``, knows no JSON
Schema); this is the live-model backend's constrained-decoding contract and knows
JSON-Schema types. Same input, opposite sides of the plugin↔backend boundary.

Note (step-2 shape decision): NEXT_SESSION sketched the emitted ``params`` as a
loose ``object`` with per-spec validation applied *after* emission; the LLD step
list also says "``exclusive_params`` → ``oneOf``". Emitting a loose ``object``
can't express ``oneOf``, so this generator emits the *richer* per-action params
schema (typed properties + required + the ``oneOf`` groups). Post-emission
param validation (graceful-degrade drop-invalid) still happens in the parse layer
(step 6); a stricter schema just means fewer invalid responses to drop.
"""

from __future__ import annotations

from app.routing.engine import ActionRegistry, ActionSpec


def build_tools_schema(registry: ActionRegistry) -> dict:
    """Render every registered action as the PROPOSE call's output JSON schema.

    Returns the full ``{actions: [oneOf: [...]]}`` schema (a ``dict``); one
    ``oneOf`` branch per action, in registry order.
    """
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["actions"],
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "oneOf": [_action_item(spec) for spec in registry.all()],
                },
            }
        },
    }


def _action_item(spec: ActionSpec) -> dict:
    """One action rendered as a ``oneOf`` branch: ``{name: const, params: {...}}``."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "params"],
        "properties": {
            "name": {"const": spec.name},
            "params": _params_schema(spec),
        },
    }


def _params_schema(spec: ActionSpec) -> dict:
    """The ``params`` object schema for one action, from its ``Param`` list.

    Typed properties (mapped from ``datatype``), a ``required`` list derived from
    the required params (omitted when none), and an ``oneOf`` over the
    ``exclusive_params`` groups when present (each group required in addition to
    the action's own required params).
    """
    schema: dict = {
        "type": "object",
        "properties": {
            # Each param's JSON-Schema fragment is declared on its DataType (the
            # single source shared with the tools view) — we just assemble them.
            p.name: p.datatype.json_schema
            for p in spec.params
        },
        "additionalProperties": False,
    }
    required = spec.required
    if required:
        schema["required"] = required
    if spec.exclusive_params:
        schema["oneOf"] = [
            {"required": required + group} for group in spec.exclusive_params
        ]
    return schema
