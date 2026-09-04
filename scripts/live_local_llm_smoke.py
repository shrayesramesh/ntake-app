#!/usr/bin/env python
"""Live local-LLM smoke — drive the REAL model and PRINT its proposals.

Unlike ``integration_smoke_on_host.py`` (which asserts the deterministic *fake*
backend), this points the app at a **running local model** (llamafile on
``localhost:8080``) via ``AssistantConfig(kind="local")`` and prints what the
assistant proposes for a handful of captures — plus timings. Reasoning quality is
a human judgement, so this ASSERTS almost nothing (only that the request path
returns 201 and never 500s); you read the output.

Prereq: a model already serving (HOST_SETUP_GUIDE §7). Everything is localhost —
no Tailscale.

    python scripts/live_local_llm_smoke.py
    python scripts/live_local_llm_smoke.py --model ./llama-3.1-8b-instruct.Q8_0.gguf
    python scripts/live_local_llm_smoke.py --base-url http://127.0.0.1:8080

The default ``--model`` is what a bare llamafile reports as its served id (the
gguf path); override to match ``curl localhost:8080/v1/models``.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import threading
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="ntake_live_smoke_"))
os.environ["CALENDAR_DB_URL"] = f"sqlite:///{_TMP / 'live.db'}"
os.environ.setdefault("NTAKE_TOKEN_SECRET", "live-smoke-secret")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn  # noqa: E402

import app.main as main  # noqa: E402
from app.assistant.factory import AssistantConfig  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.manage import gen_token_for, seed_event  # noqa: E402
from app.models import Family, Member  # noqa: E402
from app.tokens import token_secret  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _seed() -> tuple[str, int]:
    """Seed a family + member + a couple of existing entities; return (token,
    family_id). Gives the LINK call something real to resolve against."""
    now = datetime.now(UTC)
    s = SessionLocal()
    try:
        fam = Family(name="Live Household", timezone="America/New_York")
        s.add(fam)
        s.commit()
        s.add(
            Member(
                family_id=fam.id,
                display_name="Tester",
                role="adult",
                created_at=now,
            )
        )
        s.commit()
        # Existing entities the notes below can refer to.
        seed_event(
            s,
            fam.id,
            title="Piano recital",
            start_at=datetime(2026, 9, 4, 19, 0, tzinfo=UTC),
            end_at=datetime(2026, 9, 4, 20, 0, tzinfo=UTC),
        )
        token = gen_token_for(s, "Tester", label="live", secret=token_secret())
        return token, fam.id
    finally:
        s.close()


def _start_server(port: int) -> uvicorn.Server:
    config = uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not server.started:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        raise RuntimeError("uvicorn did not start within 15s")
    return server


def _capture(base: str, token: str, text: str) -> tuple[dict, float]:
    body = json.dumps({"text": text}).encode()
    req = urllib.request.Request(base + "/capture", data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")
    t0 = time.monotonic()
    with urllib.request.urlopen(req, timeout=180) as r:  # generous: cold start
        data = json.loads(r.read())
        assert r.status == 201, r.status
    return data, time.monotonic() - t0


NOTES = [
    "buy milk",
    "dentist appointment friday",
    "call the plumber about the leak, he's coming tuesday",
    "move the piano recital to saturday",
    "we finished the taxes",
]


def main_(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Live local-LLM smoke.")
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:8080",
        help="the running model's OpenAI endpoint",
    )
    parser.add_argument(
        "--model",
        default="./llama-3.1-8b-instruct.Q8_0.gguf",
        help="served model id (see curl localhost:8080/v1/models)",
    )
    args = parser.parse_args(argv)

    # Point the app's assistant at the live model (config-in-code): override the
    # dependency the capture endpoint reads.
    cfg = AssistantConfig(
        kind="local", model=args.model, base_url=args.base_url, timeout=180.0
    )
    main.app.dependency_overrides[main.get_assistant_config] = lambda: cfg

    server: uvicorn.Server | None = None
    try:
        port = _free_port()
        server = _start_server(port)
        token, _fam = _seed()
        base = f"http://127.0.0.1:{port}"

        print(f"\nLive local-LLM smoke — model {args.model} @ {args.base_url}")
        print(f"app @ {base} (temp DB {_TMP})\n")
        print("Sending captures (first is a cold start — may take tens of seconds):\n")

        for note in NOTES:
            data, secs = _capture(base, token, note)
            proposals = data.get("proposals", [])
            print(f'NOTE: "{note}"   ({secs:.1f}s)')
            if not proposals:
                print("   → (no proposals — degraded; model cold/miss or nothing apt)")
            for p in proposals:
                tgt = (
                    f" [target {p['target_type']}#{p['target_id']}]"
                    if p.get("target_type")
                    else ""
                )
                print(f"   → {p['name']}({json.dumps(p['params'])}){tgt}")
                if p.get("llm_rationale"):
                    print(f"       rationale: {p['llm_rationale']}")
            print()

        print("Done. Read the proposals above — is the reasoning sane?\n")
        return 0
    finally:
        if server is not None:
            server.should_exit = True
            time.sleep(0.3)
        try:
            engine.dispose()
        except Exception:  # noqa: BLE001
            pass
        import shutil

        shutil.rmtree(_TMP, ignore_errors=True)
        print(f"Cleaned up temp DB ({_TMP}).")


if __name__ == "__main__":
    raise SystemExit(main_())
