#!/usr/bin/env python3
"""Bedrock prerequisite preflight — a one-command diagnosis of model-access state.

Standalone (no ``tracer`` dependency, so it survives Session 5). Checks the real
prerequisites the official AWS model-access doc names, which the Session 0.2 note
("retired, nothing to manually grant, auto-enabled") under-stated:

  1. **Anthropic First Time Use (FTU) use-case form** — REQUIRED once per account
     before any Claude invocation (self-service: console model catalog or the
     ``PutUseCaseForModelAccess`` API; granted immediately). A missing FTU form
     makes Claude fail — and it is NOT a support case.
  2. **AWS Marketplace subscribe perms** on the invoking identity
     (``aws-marketplace:Subscribe``/``ViewSubscriptions``/``Unsubscribe``) — the
     first-invoke auto-subscription needs these.
  3. **A classified Converse probe** on BOTH a first-party model (Amazon Nova
     Lite — NO FTU form) and Claude. The error type disambiguates the cause:
       - ``ValidationException: Operation not allowed`` on **Nova** (first-party,
         no FTU) => an **account-level data-plane hold** (new/dormant-account
         anti-fraud). Only AWS can lift it → **Account & Billing support case**.
       - ``AccessDeniedException`` / Claude-only failure => a **missing FTU form
         or Marketplace perms** → self-service, fix now.
       - Both succeed => Bedrock is usable; backfill AWS_LLD §3.5.

Run (from ntake-aws/, with dev AWS creds):
    .venv/bin/python scripts/bedrock_preflight.py

Env: NTAKE_REGION / AWS_REGION (default us-east-1). Optional args:
    scripts/bedrock_preflight.py [claude_profile_id] [nova_model_id]
"""

from __future__ import annotations

import os
import sys

import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get("NTAKE_REGION") or os.environ.get("AWS_REGION", "us-east-1")
# Claude is inference-profile-only (bare on-demand ids are retired) — pin the
# us. cross-region profile. Nova Lite exposes a bare on-demand id (no FTU form).
CLAUDE_PROFILE = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
NOVA_MODEL = "amazon.nova-lite-v1:0"
_PROBE_MSG = [{"role": "user", "content": [{"text": "Say OK."}]}]


def _hdr(title: str) -> None:
    print(f"\n=== {title} ===")


def check_identity() -> None:
    _hdr("1. Caller identity")
    try:
        ident = boto3.client("sts", region_name=REGION).get_caller_identity()
        print(f"account={ident['Account']} arn={ident['Arn']}")
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: no usable creds ({type(exc).__name__}: {exc}).")
        print("Configure dev creds (aws configure) and retry.")
        sys.exit(1)


def check_marketplace_perms() -> None:
    _hdr("2. AWS Marketplace subscribe perms (first-invoke auto-subscription)")
    # NOTE: the first-invoke auto-subscription uses the aws-marketplace:Subscribe
    # IAM action, but there is no `aws-marketplace` boto3 CLIENT (the real client
    # names are marketplace-catalog / marketplace-entitlement). We use
    # marketplace-catalog purely as a reachability/perms proxy — a cheap call that
    # tells us whether the identity can talk to Marketplace at all.
    try:
        mc = boto3.client("marketplace-catalog", region_name=REGION)
        mc.list_entities(Catalog="AWSMarketplace", EntityType="Offer", MaxResults=1)
        print("marketplace-catalog reachable (Marketplace perms likely present).")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("AccessDeniedException", "AccessDenied"):
            print(
                "ACCESS DENIED on Marketplace — the invoking identity may lack "
                "aws-marketplace:Subscribe/ViewSubscriptions, needed for the "
                "first-invoke auto-subscription. (Not the cause if Nova fails with "
                "'Operation not allowed' below — that is the account hold.)"
            )
        else:
            print(f"marketplace-catalog reachable (perms present); probe said {code}.")
    except Exception as exc:  # noqa: BLE001
        print(
            f"could not probe Marketplace ({type(exc).__name__}); "
            "check perms manually. (Non-fatal — the Converse probe below is the "
            "decisive signal.)"
        )


def check_anthropic_ftu() -> None:
    _hdr("3. Anthropic First Time Use (FTU) use-case form")
    # GetUseCaseForModelAccess lives on the bedrock control plane. If it reports
    # the form is not submitted, THAT is a self-service fix (console model catalog
    # or PutUseCaseForModelAccess) — not a support case.
    try:
        bedrock = boto3.client("bedrock", region_name=REGION)
    except Exception as exc:  # noqa: BLE001
        print(f"could not create bedrock client ({type(exc).__name__}).")
        return
    getter = getattr(bedrock, "get_use_case_for_model_access", None)
    if getter is None:
        print(
            "This boto3 version has no get_use_case_for_model_access. Check the "
            "FTU form in the console: Bedrock → Model catalog → an Anthropic model "
            "→ submit the use-case form (one sentence + a URL; granted instantly)."
        )
        return
    try:
        resp = getter()
        status = resp.get("formData") or resp.get("status") or resp
        print(f"FTU form present/response: {str(status)[:200]}")
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("ResourceNotFoundException", "ValidationException"):
            print(
                "FTU use-case form appears NOT submitted. Submit it (self-service, "
                "immediate): Bedrock console → Model catalog → an Anthropic model → "
                "use-case form, OR call PutUseCaseForModelAccess. REQUIRED before "
                "any Claude invoke (not needed for Amazon Nova)."
            )
        else:
            print(f"FTU check inconclusive ({code}); verify in the console.")
    except Exception as exc:  # noqa: BLE001
        print(f"FTU check error ({type(exc).__name__}); verify in the console.")


def _classify_converse(label: str, model_id: str) -> str:
    client = boto3.client("bedrock-runtime", region_name=REGION)
    try:
        r = client.converse(modelId=model_id, messages=_PROBE_MSG)
        print(f"[{label}] OK stop={r['stopReason']}")
        return "ok"
    except ClientError as exc:
        err = exc.response.get("Error", {})
        code, msg = err.get("Code", "?"), err.get("Message", "")[:160]
        print(f"[{label}] {code}: {msg}")
        if code == "ValidationException" and "Operation not allowed" in msg:
            return "hold"
        if code in ("AccessDeniedException", "AccessDenied"):
            return "denied"
        return "other"
    except Exception as exc:  # noqa: BLE001
        print(f"[{label}] {type(exc).__name__}: {str(exc)[:160]}")
        return "other"


def probe_and_diagnose(claude_id: str, nova_id: str) -> None:
    _hdr("4. Converse probe (Nova = first-party/no-FTU; Claude = needs FTU)")
    nova = _classify_converse("nova ", nova_id)
    claude = _classify_converse("claude", claude_id)

    _hdr("Diagnosis")
    if nova == "ok" and claude == "ok":
        print(
            "Bedrock is USABLE. Run scripts/bedrock_bisect.py to confirm the "
            "multi-tool-call + enum behavior and backfill AWS_LLD §3.5."
        )
    elif nova == "hold":
        print(
            "ACCOUNT-LEVEL DATA-PLANE HOLD. Nova is first-party with no FTU form, "
            "so 'Operation not allowed' on Nova cannot be a form/perms issue — it "
            "is the new/dormant-account anti-fraud hold on bedrock-runtime. Only "
            "AWS lifts it: open an Account & Billing support case (free on Basic "
            "Support) and confirm a REAL credit card (not just credits) is on "
            "file. This matches the Session 1.5 finding."
        )
    elif nova == "ok" and claude in ("hold", "denied", "other"):
        print(
            "Nova works but Claude does NOT → it was the ANTHROPIC FTU FORM (and/or "
            "Marketplace perms), not an account hold. Submit the FTU use-case form "
            "(step 3) and re-run — Claude should work immediately. The Session 0.2 "
            "'nothing to grant' note was wrong for Anthropic."
        )
    elif nova == "denied":
        print(
            "AccessDenied on Nova → IAM/Marketplace-subscribe perms missing on the "
            "invoking identity. Grant aws-marketplace:Subscribe/ViewSubscriptions "
            "(step 2) and bedrock:InvokeModel on the model, then re-run."
        )
    else:
        print(
            "Inconclusive — see the per-probe errors above. If Nova shows "
            "'Operation not allowed', treat as the account hold (support case)."
        )


def main() -> None:
    claude_id = sys.argv[1] if len(sys.argv) > 1 else CLAUDE_PROFILE
    nova_id = sys.argv[2] if len(sys.argv) > 2 else NOVA_MODEL
    print(f"Bedrock preflight — region={REGION}")
    check_identity()
    check_marketplace_perms()
    check_anthropic_ftu()
    probe_and_diagnose(claude_id, nova_id)


if __name__ == "__main__":
    main()
