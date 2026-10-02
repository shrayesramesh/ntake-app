"""⚠️ THROWAWAY Bedrock tracer (Session 1.5) — the load-bearing seam. ⚠️

This resolves the single most important unverified assumption in the whole design
(AWS_HLD §13, AWS_LLD §3.5): does one Bedrock Converse **tool-use** turn behave
the way PROPOSE needs — and in particular, does ONE turn return **multiple
``toolUse`` blocks** (one capture → several proposal cards), or only one?

It makes ONE real ``Converse`` call with a **hand-written 2-tool** ``toolConfig``
(not the real registry — that is Session 5), shaped exactly like the real PROPOSE
design: ``toolChoice: {any: {}}`` forces a tool, ``no_action`` is a registered
tool, and the id-bearing param is an **enum-over-whitelist** so we can observe
whether the model honors the enum constraint. The deployed handler returns the
findings (stop reason, how many ``toolUse`` blocks, which tools, the enum values
it chose) as JSON so the agent can read them straight off the HTTP response.

Pure, gate-tested helpers (``build_tool_config``, ``parse_tool_uses``,
``summarize``) are separated from the deployed-only ``converse_once`` /
``handler`` so the shape logic is covered under ``make check`` with no network.
"""

from __future__ import annotations

import json
import os
from typing import Any

# A tiny, fixed whitelist of fake member ids — the enum-over-whitelist stand-in
# (AWS_LLD §3.2). On the deployed call we observe whether the model's chosen
# member_id stays inside this set.
WHITELIST_MEMBER_IDS = ["MEM#alex", "MEM#sam"]


def build_tool_config(member_ids: list[str]) -> dict[str, Any]:
    """A hand-written 2-tool ``toolConfig`` + ``no_action``, mirroring real PROPOSE.

    * ``flag_blocked`` — an id-bearing tool whose ``member_id`` is constrained to
      an **enum** of ``member_ids`` (the LINK whitelist analog, AWS_LLD §3.2).
    * ``set_due_date`` — a second id-bearing tool, so a single capture *could*
      plausibly yield two proposals (the multi-``toolUse`` question, §3.5).
    * ``no_action`` — the registered "nothing to propose" tool (§3.2).

    ``toolChoice`` is ``{any: {}}`` so the model must pick a registered tool and
    emit no free text (confirmed from the Bedrock ``ToolChoice`` docs).
    """
    member_enum = {"type": "string", "enum": member_ids}
    return {
        "tools": [
            {
                "toolSpec": {
                    "name": "flag_blocked",
                    "description": (
                        "Flag a work item as blocked and record who is blocked. "
                        "Use when the note says someone is stuck or waiting."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "member_id": member_enum,
                                "reason": {"type": "string"},
                            },
                            "required": ["member_id", "reason"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "set_due_date",
                    "description": (
                        "Set a due date on a work item. Use when the note mentions "
                        "a deadline or 'by <date>'."
                    ),
                    "inputSchema": {
                        "json": {
                            "type": "object",
                            "properties": {
                                "member_id": member_enum,
                                "due_date": {"type": "string"},
                            },
                            "required": ["member_id", "due_date"],
                        }
                    },
                }
            },
            {
                "toolSpec": {
                    "name": "no_action",
                    "description": "Nothing to propose for this note.",
                    "inputSchema": {"json": {"type": "object", "properties": {}}},
                }
            },
        ],
        "toolChoice": {"any": {}},
    }


def parse_tool_uses(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the ordered list of ``toolUse`` blocks from a Converse response.

    Returns each block's ``{name, input, toolUseId}``. Shaped so a handler that
    consumes a **list** works unchanged whether the model returns one block or
    several (the §3.5 fallback is then a call-count change, not a reshape).
    """
    content = response.get("output", {}).get("message", {}).get("content", [])
    uses: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, dict) and "toolUse" in block:
            tu = block["toolUse"]
            uses.append(
                {
                    "name": tu.get("name"),
                    "input": tu.get("input", {}),
                    "toolUseId": tu.get("toolUseId"),
                }
            )
    return uses


def summarize(response: dict[str, Any], whitelist: list[str]) -> dict[str, Any]:
    """Reduce a Converse response to the Session-1.5 findings (§3.5).

    Reports the stop reason, how many ``toolUse`` blocks came back in the one
    turn (the multi-tool-call answer), which tools were chosen, and whether every
    chosen ``member_id`` stayed within the enum whitelist (enum adherence).
    """
    uses = parse_tool_uses(response)
    chosen_member_ids = [
        u["input"]["member_id"] for u in uses if "member_id" in (u.get("input") or {})
    ]
    enum_respected = all(mid in whitelist for mid in chosen_member_ids)
    return {
        "stop_reason": response.get("stopReason"),
        "tool_use_count": len(uses),
        "multiple_tool_uses_in_one_turn": len(uses) > 1,
        "tools_chosen": [u["name"] for u in uses],
        "chosen_member_ids": chosen_member_ids,
        "enum_whitelist": whitelist,
        "enum_respected": enum_respected,
        "usage": response.get("usage"),
    }


def converse_once(client: Any, model_id: str, capture_text: str) -> dict[str, Any]:
    """One real Converse tool-use call (deployed-only; needs bedrock-runtime)."""
    return client.converse(
        modelId=model_id,
        system=[
            {
                "text": (
                    "You help a family triage notes into actions. Pick the best "
                    "registered tool(s) for the note. If the note implies both a "
                    "blocker and a deadline, you may use more than one tool."
                )
            }
        ],
        messages=[{"role": "user", "content": [{"text": capture_text}]}],
        toolConfig=build_tool_config(WHITELIST_MEMBER_IDS),
    )


def handler(event: dict[str, Any], _context: Any = None) -> dict[str, Any]:
    """Lambda entry — makes the real call and returns the §3.5 findings as JSON.

    A capture string can be supplied in the request body (``{"text": "..."}``);
    otherwise a default note engineered to invite BOTH a blocker and a due date is
    used, to probe the multi-``toolUse`` question. Any Bedrock error is returned
    (not raised) so the agent reads the failure off the HTTP response.
    """
    import boto3

    model_id = os.environ["TRACER_BEDROCK_MODEL_ID"]
    body = event.get("body")
    capture_text = "Sam is blocked on the taxes and they are due by April 15."
    if body:
        try:
            parsed = json.loads(body)
            capture_text = parsed.get("text", capture_text)
        except (ValueError, TypeError):
            pass

    client = boto3.client("bedrock-runtime")
    try:
        response = converse_once(client, model_id, capture_text)
    except Exception as exc:  # noqa: BLE001 - report, don't raise, on the tracer
        return {
            "statusCode": 500,
            "headers": {"content-type": "application/json"},
            "body": json.dumps({"error": type(exc).__name__, "detail": str(exc)}),
        }

    findings = summarize(response, WHITELIST_MEMBER_IDS)
    findings["capture_text"] = capture_text
    findings["model_id"] = model_id
    return {
        "statusCode": 200,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(findings),
    }
