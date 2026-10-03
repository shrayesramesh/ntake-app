#!/usr/bin/env python3
"""⚠️ THROWAWAY Session-1.5 Nova tool-use probe (deleted with the tracer). ⚠️

Confirms the §3.5 finding directly against Nova Lite: does the model accept
``toolChoice: {any: {}}`` (force a tool — what the PROPOSE design assumes), and/or
``toolChoice: {auto: {}}``? Prints the stop reason + content block shapes for each,
so we know whether "Operation not allowed" was caused by ``any``.

Run (from ntake-aws/, with AWS creds):  .venv/bin/python /tmp/nova_probe.py
(or wherever you save it). No stack needed — calls Bedrock directly.
"""

from __future__ import annotations

import boto3

MODEL = "amazon.nova-lite-v1:0"
REGION = "us-east-1"

TOOLS = {
    "tools": [
        {
            "toolSpec": {
                "name": "flag_blocked",
                "description": "Flag a work item as blocked and record who is blocked.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "member_id": {
                                "type": "string",
                                "enum": ["MEM#alex", "MEM#sam"],
                            },
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
                "description": "Set a due date on a work item.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {
                            "member_id": {
                                "type": "string",
                                "enum": ["MEM#alex", "MEM#sam"],
                            },
                            "due_date": {"type": "string"},
                        },
                        "required": ["member_id", "due_date"],
                    }
                },
            }
        },
    ]
}

MSG = [
    {
        "role": "user",
        "content": [
            {"text": "Sam is blocked on the taxes and they are due by April 15."}
        ],
    }
]


def main() -> None:
    client = boto3.client("bedrock-runtime", region_name=REGION)
    for tc in ({"auto": {}}, {"any": {}}, None):
        config = {"tools": TOOLS["tools"]}
        label = "none" if tc is None else next(iter(tc))
        if tc is not None:
            config["toolChoice"] = tc
        try:
            resp = client.converse(
                modelId=MODEL,
                messages=MSG,
                toolConfig=config,
                inferenceConfig={"maxTokens": 512},
            )
            content = resp["output"]["message"]["content"]
            shapes = [sorted(b.keys()) for b in content]
            tool_uses = [b["toolUse"]["name"] for b in content if "toolUse" in b]
            print(
                f"toolChoice={label}: OK stop={resp['stopReason']} "
                f"blocks={shapes} tools={tool_uses}"
            )
        except Exception as exc:  # noqa: BLE001
            print(f"toolChoice={label}: ERROR {type(exc).__name__}: {str(exc)[:160]}")


if __name__ == "__main__":
    main()
