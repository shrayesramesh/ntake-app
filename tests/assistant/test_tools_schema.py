"""build_tools_schema — the constrained-output JSON schema for the PROPOSE call.

The machine-side twin of ``build_tools_view`` (test_tools_view pins the human
menu; this pins the schema the model's output is *forced* to obey). Task 7 Track
A step 2 (LLD): a pure fn ``ActionRegistry`` →
``{actions:[{name, params}]}`` JSON schema, with each action's ``params`` built
from its ``Param`` list (``datatype`` → JSON-Schema ``type``) and
``exclusive_params`` → ``oneOf``.

Lives in the ``local_llm`` package (not next to ``tools_view``): the JSON-Schema
keyword ``"type"`` / ``oneOf`` emission is a backend concern the LLD confines to
this package, whereas ``tools_view`` is backend-neutral. No network — snapshot
the emitted schema like the views.
"""

from __future__ import annotations

from app.assistant.actions.registry import REGISTRY
from app.assistant.local_llm.propose import build_tools_schema
from app.routing.engine import ActionRegistry, ActionSpec, DataType, Param


def test_envelope_shape():
    # The uniform outer shape: {actions: [ <action item>, ... ]}.
    schema = build_tools_schema(ActionRegistry([ActionSpec(name="no_action")]))
    assert schema["type"] == "object"
    assert schema["required"] == ["actions"]
    assert schema["additionalProperties"] is False
    actions = schema["properties"]["actions"]
    assert actions["type"] == "array"
    # Each element is one of the per-action item schemas.
    assert "oneOf" in actions["items"]


def test_action_item_has_name_const_and_params():
    reg = ActionRegistry(
        [ActionSpec(name="complete_work_item", description="Mark a work item done.")]
    )
    item = build_tools_schema(reg)["properties"]["actions"]["items"]["oneOf"][0]
    assert item["type"] == "object"
    assert item["required"] == ["name", "params"]
    assert item["additionalProperties"] is False
    # name is pinned to this action (const), so oneOf discriminates by name.
    assert item["properties"]["name"] == {"const": "complete_work_item"}
    # A paramless action still carries a params object (uniform), empty.
    assert item["properties"]["params"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def test_datatype_mapping_and_required():
    reg = ActionRegistry(
        [
            ActionSpec(
                name="t",
                params=[
                    Param("s", DataType.STRING, required=True),
                    Param("dt", DataType.DATETIME),
                    Param("d", DataType.DATE),
                    Param("n", DataType.INTEGER),
                    Param("xs", DataType.ARRAY_STRING),
                    Param("xi", DataType.ARRAY_INTEGER),
                    Param("o", DataType.OBJECT),
                ],
            )
        ]
    )
    params = build_tools_schema(reg)["properties"]["actions"]["items"]["oneOf"][0][
        "properties"
    ]["params"]
    assert params["properties"] == {
        "s": {"type": "string"},
        "dt": {"type": "string", "format": "date-time"},
        "d": {"type": "string", "format": "date"},
        "n": {"type": "integer"},
        "xs": {"type": "array", "items": {"type": "string"}},
        "xi": {"type": "array", "items": {"type": "integer"}},
        "o": {"type": "object"},
    }
    # required derives from the required Params only.
    assert params["required"] == ["s"]
    assert params["additionalProperties"] is False


def test_no_required_key_when_no_required_params():
    reg = ActionRegistry([ActionSpec(name="t", params=[Param("x", DataType.STRING)])])
    params = build_tools_schema(reg)["properties"]["actions"]["items"]["oneOf"][0][
        "properties"
    ]["params"]
    assert "required" not in params


def test_exclusive_params_become_oneof():
    reg = ActionRegistry(
        [
            ActionSpec(
                name="create_event",
                params=[
                    Param("title", DataType.STRING, required=True),
                    Param("start_at", DataType.DATETIME),
                    Param("end_at", DataType.DATETIME),
                    Param("start_date", DataType.DATE),
                    Param("end_date", DataType.DATE),
                ],
                exclusive_params=[["start_at", "end_at"], ["start_date", "end_date"]],
            )
        ]
    )
    params = build_tools_schema(reg)["properties"]["actions"]["items"]["oneOf"][0][
        "properties"
    ]["params"]
    # Each exclusive group becomes a oneOf branch requiring exactly that group
    # (on top of the action's own required params).
    assert params["oneOf"] == [
        {"required": ["title", "start_at", "end_at"]},
        {"required": ["title", "start_date", "end_date"]},
    ]


def test_names_enum_covers_every_action():
    # Structural guard independent of the exact snapshot: one oneOf branch per
    # registered action, each pinned to its name.
    schema = build_tools_schema(REGISTRY)
    branches = schema["properties"]["actions"]["items"]["oneOf"]
    consts = [b["properties"]["name"]["const"] for b in branches]
    assert consts == REGISTRY.names()


def test_empty_registry_yields_no_action_branches():
    schema = build_tools_schema(ActionRegistry([]))
    assert schema["properties"]["actions"]["items"]["oneOf"] == []


def test_full_schema_snapshot_over_the_real_registry():
    # The exact constrained-output schema the model is bound to. If this changes,
    # it's a deliberate change to the tool contract — update the snapshot on
    # purpose (mirrors test_tools_view's full-render snapshot).
    def obj(properties, required=None, one_of=None):
        out = {
            "type": "object",
            "properties": properties,
            "additionalProperties": False,
        }
        if required:
            out["required"] = required
        if one_of is not None:
            out["oneOf"] = one_of
        return out

    def action(name, params):
        return obj(
            {"name": {"const": name}, "params": params},
            required=["name", "params"],
        )

    dt = {"type": "string", "format": "date-time"}
    d = {"type": "string", "format": "date"}
    s = {"type": "string"}
    arr_s = {"type": "array", "items": {"type": "string"}}

    empty_params = obj({})
    expected = {
        "type": "object",
        "additionalProperties": False,
        "required": ["actions"],
        "properties": {
            "actions": {
                "type": "array",
                "items": {
                    "oneOf": [
                        action(
                            "create_work_item",
                            obj(
                                {
                                    "title": s,
                                    "description": s,
                                    "tags": arr_s,
                                    "checklist_items": arr_s,
                                },
                                required=["title"],
                            ),
                        ),
                        action("append_update", obj({"body": s}, required=["body"])),
                        action(
                            "set_due_date",
                            obj({"due_at": dt}, required=["due_at"]),
                        ),
                        action("complete_work_item", empty_params),
                        action("start_work_item", empty_params),
                        action("move_to_on_deck", empty_params),
                        action("move_to_todo", empty_params),
                        action("reopen_work_item", empty_params),
                        action(
                            "assign_work_item",
                            obj(
                                {"member_id": {"type": "integer"}},
                                required=["member_id"],
                            ),
                        ),
                        action("archive_work_item", empty_params),
                        action("archive_all_done", empty_params),
                        action(
                            "add_checklist_items",
                            obj(
                                {"items": arr_s},
                                required=["items"],
                            ),
                        ),
                        action(
                            "check_off_items",
                            obj(
                                {"items": arr_s},
                                required=["items"],
                            ),
                        ),
                        action(
                            "create_timed_event",
                            obj(
                                {
                                    "title": s,
                                    "start_at": dt,
                                    "end_at": dt,
                                    "description": s,
                                    "location": s,
                                    "participants": arr_s,
                                },
                                required=["title", "start_at", "end_at"],
                            ),
                        ),
                        action(
                            "create_all_day_event",
                            obj(
                                {
                                    "title": s,
                                    "start_date": d,
                                    "end_date": d,
                                    "description": s,
                                    "location": s,
                                    "participants": arr_s,
                                },
                                required=["title", "start_date"],
                            ),
                        ),
                        action(
                            "reschedule_timed_event",
                            obj(
                                {"start_at": dt, "end_at": dt},
                                required=["start_at", "end_at"],
                            ),
                        ),
                        action(
                            "reschedule_all_day_event",
                            obj(
                                {"start_date": d, "end_date": d},
                                required=["start_date"],
                            ),
                        ),
                        action(
                            "set_event_location",
                            obj({"location": s}, required=["location"]),
                        ),
                        action(
                            "add_event_participants",
                            obj({"participants": arr_s}, required=["participants"]),
                        ),
                        action("delete_event", empty_params),
                        action("deconflict_events", empty_params),
                        action("no_action", empty_params),
                    ]
                },
            }
        },
    }
    assert build_tools_schema(REGISTRY) == expected
