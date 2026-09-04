# Next session — what's left to build

A lean, forward brief. Depth lives in the specs; read them, don't re-derive:
**`REQUIREMENTS.md`** (what/why), **`DESIGN.md`** (how — esp. §4.1a assistant
architecture + design decisions, §6a backfill), **`PLAN.md`** (phases + status),
**`LLD-assistant-pipeline.md`** (the two-call assistant), and **`SKILL.md`** at
the repo root (how to work here + conventions).

## Current state (one paragraph)

Phases 0–3 and the **fake-first Phase 4** are built and green (`make check` → 300
tests, ≥95% cov; + `make smoke`, 12 real-stack checks). The app (FastAPI +
SQLite): events, work-items + append-only update log, board, `/capture`
(propose-only) + `/actions/confirm`, config-seeded identity + token CLI, and live
SSE. The assistant is a reusable engine (`app/routing/`) + ntake plugin
(`app/assistant/`) with two config-selected seams (`CaptureResolver`,
`AssistantClient`) and a deterministic `fake/` backend that runs the **real
two-call shape** (`build_world_view → fake_link → deep_context → propose`), so it
resolves a target from free text with no model. **Live-surface hardening is done:**
SQLite WAL + `synchronous=NORMAL`; Alembic migrations as the real-DB schema path
(startup runs `upgrade head`; `python -m app.manage migrate`; tests use
`create_all`); a `VACUUM INTO` snapshot (`manage backup`); SSE re-sync on
(re)connect; PWA manifest + service worker.

## Remaining larger tasks (the menu)

1. **Local-LLM task 7 — the live local model (host-only). The last Phase-4 build.**
   Detailed below — this is the primary next task.
2. **Labor view** (Phase 5, ASSIST-4 / R-labor) — the app's core-purpose payoff.
   **Underspecified: needs a design spike on output shape first** (recognition,
   never scores), and it's LLM-coupled (reads the update log) → sequence it after
   task 7. See DESIGN §4.2.
3. **One-time backfill** (Trello / Google Calendar) — **designed, not built**
   (DESIGN §6a, REQUIREMENTS INTEROP-2): a file-based `manage import` CLI, no
   cloud in the data path, idempotent, one-time seeding (not sync). Good day-one
   onboarding since a fresh install starts empty.
4. **GROOM board UI** — manual archive / archive-all-Done / unarchive (GROOM-1..4).
   The *assistant* `archive_work_item` action exists; the manual UI doesn't.
5. **Phase-5 kiosk leftovers** — always-on soak (on-device), failure surfacing in
   the UI, basic logging.

Human-only (not agent tasks): Tailscale + TLS reachability; on-device PWA-install
+ browser-reconnect verification (HOST_SETUP_GUIDE §4/§4a).

---

## Task 7 — the local-LLM backend (host-only)

Swap real LLM calls behind the two existing seams. **All of Track A (the code) is
buildable + TDD-able here against a scripted `LLM` double / stubbed httpx (no live
model); only the final smoke needs a running model (Track B, host-only).**
Proposed layout, mirroring `fake/`:

```
app/assistant/local_llm/
├── seam.py       # LLM protocol: complete(system, user, schema) -> dict. The one
│                 #   injected effect. ScriptedLLM (test double) + LocalLlmClient
│                 #   both implement it. propose()/link() depend on THIS, not httpx.
├── client.py     # LocalLlmClient(LLM): httpx wrapper, JSON-constrained call;
│                 #   holds base_url/model/timeout. No prompt/domain logic.
├── schema.py     # registry -> constrained-output JSON schema (pure fn).
├── assistant.py  # LocalLlmAssistant[FocusedContext] (stage 2): build prompt+schema,
│                 #   call the LLM, parse -> [ProposedAction]
├── resolver.py   # LocalLlmCaptureResolver (stage 1): build_world_view + note
│                 #   -> LINK ids -> deep_context -> FocusedContext
├── prompt.py     # (or reuse app/assistant/prompts.py — already built)
└── infra.py      # host mgmt: health check + a warm ping (see Track B)
```

**Runtime decision (resolved): llamafile is the reference runtime; the backend is
runtime-agnostic.** The backend is named for what it *is* — a local LLM behind an
OpenAI-style localhost HTTP seam — not for one server. **llamafile** (a single
portable executable that serves an OpenAI-compatible `/v1/chat/completions` with
grammar/JSON-constrained output) is the default on both the dev Mac and the host,
so we test what we ship. **Ollama, LM Studio, and llama.cpp `llama-server` are
interchangeable alternate endpoints** behind the same seam — switching is a
URL/knob change in `client.py`, not a code change above it. On the always-on host
the one added cost vs. Ollama's turnkey service is writing a systemd unit + warm
ping (below); accepted, in exchange for one runtime everywhere and no
runtime-specific coupling. Reference model on this box (M4 Pro, 48 GB): **Llama
3.1 8B Instruct** (`Q8_0`, ~8.5 GB) to start, with Qwen2.5 14B Instruct (`Q4_K_M`,
~9 GB) as a quality A/B — both well within a ~9–10 GB budget.

**Pipeline shape (LLD OQ-1, resolved): two LLM calls.**
`build_world_view → link(LLM) → deep_context → propose(LLM)` — broad-but-shallow
to find target ids, then narrow-but-deep to reason. Both prompt templates
(`build_link_prompt`, `build_propose_prompt`) and both views (`build_world_view`,
`build_tools_view`) already exist. The param contract on `ActionSpec` (`params` /
`exclusive_params`) is what the JSON-schema generator reads.

Task 7 has **two tracks**. Track A is all in-repo code, fully TDD-able **here on
the dev Mac with no model running** (a scripted `LLM` double stands in for the
transport). Track B is the llamafile + model runtime — acquiring it, serving it,
and the in-app health/warm surface — needed only for the final real end-to-end
smoke. **Build all of Track A first; stand up Track B at the end.**

### Track A — the code (in-repo, `make check`-green vs. a scripted `LLM` double)

Each step is its own sub-checkpoint; run `make check` and paste output.

1. **`LLM` seam (`seam.py`).** Define the one injected effect —
   `complete(system, user, schema) -> dict` — as an ABC/Protocol, plus a
   **`ScriptedLLM`** test double that returns canned JSON keyed off the call. This
   is the fixture every step below tests against; nothing above the seam ever
   imports httpx. (Mirrors LLD "LLM is an injected effect, not a session.")
2. **JSON schema generator (`schema.py`).** Pure fn: `ActionRegistry`
   (`ActionSpec.params` / `exclusive_params`) → the constrained-output JSON schema
   (uniform `{actions:[{name: enum[...], params: object}]}`; `exclusive_params` →
   `oneOf`). No network; snapshot-test the emitted schema like the views.
3. **`client.py` — `LocalLlmClient(LLM)`.** The `httpx` wrapper implementing the
   seam: OpenAI-style `/v1/chat/completions` POST with the schema attached, holding
   `base_url`/`model`/`timeout`. **The one place the runtime is visible.** Test
   against a **stubbed httpx** (monkeypatched transport) — still no live model.
4. **propose — call 2 (`assistant.py`, `LocalLlmAssistant`).** Build the propose
   prompt + schema → call the `LLM` → parse/validate/attach → `[ProposedAction]`.
   Test with a hand-built deep `FocusedContext` + `ScriptedLLM` (no link needed
   yet).
5. **link — call 1 (`resolver.py`, `LocalLlmCaptureResolver`).**
   `build_world_view` + note → LINK call → `parse_ids` (exists) → `deep_context`
   (exists) → `FocusedContext`. Test with `ScriptedLLM`.
6. **Parsing / graceful-degrade hardening.** Malformed JSON, invalid/unknown tool
   name, missing required params, wrong types, empty/timeout → **degrade to `[]`**,
   never raise into the request path. The engine's `propose_bounded` already bounds
   the timeout; the client + parse layer must not raise. Explicit adversarial
   tests for each failure mode.
7. **Wire the `local` branch + config.** Point both factory functions
   (`get_assistant`, `get_capture_resolver`) at the real classes for
   `NTAKE_ASSISTANT=local` (they fall back to fake today). Plumb the config knobs
   below, incl. the larger timeout + warm behavior.

**Config:** `NTAKE_ASSISTANT=local`, `NTAKE_ASSISTANT_MODEL` (default
`llama3.1:8b`), `NTAKE_LOCAL_LLM_URL` (default `http://localhost:8080` for
llamafile; e.g. `http://localhost:11434` for an Ollama endpoint),
`NTAKE_ASSISTANT_TIMEOUT` (currently 4.0 — tuned for the fake; the `local` path
needs a much larger value — see cold-start).

### Track B — the runtime + model provisioning (host / operational)

Needed to actually *run* a model (final smoke + host deploy). **Decision
(resolved): model acquisition is operator-managed, not app-downloaded, for v1.**
The app owns only *health / warm / which-file-to-serve*; **downloading, updating,
and removing the llamafile binary + `.gguf` are operator steps documented in
`HOST_SETUP_GUIDE`**, not app code. Rationale: fetching multi-GB binaries with
checksum/verify, disk management, and update semantics is a mini-subsystem that
re-introduces a network-fetch path into an app whose ethos is "no cloud in the
data path" (NFR-PRIVACY), and it's the kind of speculative machinery SKILL.md says
to avoid until earned. This is the convenience we knowingly traded away by
dropping Ollama's `pull`/registry. A `manage llm pull` remains a **possible future
add** (additive) if the manual step proves annoying.

8. **Acquire llamafile + a model (operator, manual).** Either a self-contained
   model-llamafile (one executable, weights baked in) or the bare `llamafile`
   binary + a downloaded `.gguf` (Llama 3.1 8B Instruct `Q8_0` to start). Decide
   the distribution shape and the on-disk location; document both in
   `HOST_SETUP_GUIDE`. *(Not app code.)*
9. **Serve it (operator).** Run llamafile in server mode on a fixed localhost port
   (matches `NTAKE_LOCAL_LLM_URL`). Dev Mac: run the binary / a small `make`
   helper. Host: a **systemd unit** (auto-start on boot, restart on failure) —
   this is the "one added cost vs. Ollama's turnkey service." Document in
   `HOST_SETUP_GUIDE`. *(Not app code, beyond an optional make/dev helper.)*
10. **`infra.py` + `manage llm` (app code — TDD-able like the other `manage`
    helpers).** The in-app operational surface over an *already-running* endpoint:
    **health** (is `NTAKE_LOCAL_LLM_URL` up + serving the expected model?),
    **warm** (send a tiny priming request to load the model into memory so the
    first real capture isn't a cold miss), and **status**. Pure-ish core fns +
    a thin CLI wrapper + a startup warm-ping hook. Test against stubbed httpx.

### End-to-end smoke (after A + B)

With a model actually serving: `NTAKE_ASSISTANT=local make smoke` (or `--serve`)
and confirm real captures produce sane proposals — the one thing the scripted
double can't verify (reasoning quality). Tune prompt wording + timeout against
observed behavior; the prompt drafts (`prompts.py`) explicitly expect tuning here.

**⚠ Cold start + two calls (tune against real host measurement).** The pipeline
makes **two** sequential local-model calls per capture, and a model's *first* call
after idle takes seconds to tens of seconds to load into memory — the fake's 4.0s
would guarantee a cold-miss → graceful-degrade to `[]`. Give the `local` path a
much larger timeout and/or a keep-warm setting + the startup warm ping (task 10).
Non-thinking model → no `<think>` stripping.

---

## FakeAssistant trigger vocabulary (smoke / manual testing)

Timing needs a **weekday** word. New capture: **event word**
(appointment/event/meeting/visit) **+ weekday** → `create_event` only; else →
`create_work_item`. Existing item (resolved by `fake_link` from the note text):
weekday → `set_due_date` (+ linked `create_event` if event-ish); **done word** →
`complete_work_item`. Resolved **event** + a **reschedule/move word** + weekday →
`reschedule_event`. (The `deconflict_events` *action* exists and is
confirm/apply-tested, but the fake no longer *proposes* it.) Full table:
`app/assistant/fake/assistant.py` docstring.

## House rules

TDD; **`make check`** (lint + mypy + ≥95% cov) is the gate before any task is
done — paste real output. **`make smoke`** for the host integration smoke;
`--serve` keeps the server up + prints a token for a browser check. Small,
verified steps; update the relevant `spec/` docs in the same change. Do NOT do
Tailscale/device/deploy steps (human-only). Do NOT `git push`.
