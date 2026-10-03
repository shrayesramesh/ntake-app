#!/usr/bin/env python3
"""⚠️ THROWAWAY Session-1.5 Bedrock Converse bisect probe (deleted with the tracer). ⚠️

The deployed tracer gets ``ValidationException: Operation not allowed`` from
Converse on BOTH Nova and Claude — so it is NOT model-specific; it is either the
request SHAPE or account/model ENABLEMENT. This probe bisects it against a given
model by trying, in order:

  1. plain text (no toolConfig)         -> if THIS fails, it's enablement, not shape
  2. tools, no toolChoice
  3. tools + toolChoice=auto
  4. tools + toolChoice=any             -> the design's assumption (AWS_LLD §3.2)
  5. the EXACT toolConfig the tracer builds (import tracer.bedrock_tracer)

Run (from ntake-aws/, with AWS creds):
    .venv/bin/python scripts/bedrock_bisect.py us.anthropic.claude-haiku-4-5-20251001-v1:0
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import boto3

from tracer.bedrock_tracer import WHITELIST_MEMBER_IDS, build_tool_config

REGION = "us-east-1"
TEXT = "Sam is blocked on the taxes and they are due by April 15."
TOOLS = build_tool_config(WHITELIST_MEMBER_IDS)["tools"]
MSG = [{"role": "user", "content": [{"text": TEXT}]}]


def _try(label: str, client, model_id: str, **kwargs) -> None:
    try:
        r = client.converse(modelId=model_id, messages=MSG, **kwargs)
        content = r["output"]["message"]["content"]
        tools = [b["toolUse"]["name"] for b in content if "toolUse" in b]
        print(f"[{label}] OK stop={r['stopReason']} tools={tools} blocks={len(content)}")
    except Exception as exc:  # noqa: BLE001
        print(f"[{label}] ERROR {type(exc).__name__}: {str(exc)[:150]}")


def main() -> None:
    model_id = sys.argv[1] if len(sys.argv) > 1 else "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    print(f"model: {model_id}\n")
    c = boto3.client("bedrock-runtime", region_name=REGION)
    _try("1 plain text", c, model_id)
    _try("2 tools, no choice", c, model_id, toolConfig={"tools": TOOLS})
    _try("3 tools + auto", c, model_id, toolConfig={"tools": TOOLS, "toolChoice": {"auto": {}}})
    _try("4 tools + any", c, model_id, toolConfig={"tools": TOOLS, "toolChoice": {"any": {}}})
    _try("5 exact tracer cfg", c, model_id, toolConfig=build_tool_config(WHITELIST_MEMBER_IDS))


if __name__ == "__main__":
    main()
