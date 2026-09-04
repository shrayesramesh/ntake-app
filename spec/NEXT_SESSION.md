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

Swap real LLM calls behind the two existing seams. **Steps 1–3 are buildable +
TDD-able here against a stubbed httpx (no live model); the live run is host-only**
(no model server runs on the dev Mac by default — installing one is a host step).
Proposed layout, mirroring `fake/`:

```
app/assistant/local_llm/
├── client.py     # LocalLlmClient: httpx wrapper, JSON-constrained call;
│                 #   holds base_url/model/timeout. No prompt/domain logic.
├── assistant.py  # LocalLlmAssistant[FocusedContext] (stage 2): build prompt+schema,
│                 #   call client, parse -> [ProposedAction]
├── resolver.py   # LocalLlmCaptureResolver (stage 1): build_world_view + note
│                 #   -> LINK ids -> deep_context -> FocusedContext
├── prompt.py     # (or reuse app/assistant/prompts.py — already built)
└── infra.py      # host mgmt: health check + a warm ping
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

**Build order** (each a `make check`-green sub-checkpoint, TDD vs. stubbed httpx):
1. **JSON schema generator** from the specs (pure fn; fully testable). Emitted as
   the model's constrained-output contract (llamafile grammar / `response_format`;
   the equivalent knob on any alternate endpoint).
2. **`client.py`** — the shared localhost call both LLM calls use. This is the one
   place the runtime (llamafile vs. Ollama vs. LM Studio) is visible.
3. **propose (call 2)** `LocalLlmAssistant` — test against a hand-built deep
   `FocusedContext`, no link needed yet.
4. **link (call 1)** `LocalLlmCaptureResolver` — `build_world_view` + note → ids →
   `deep_context` → `FocusedContext`.
5. **`infra.py`** + a `manage llm` health/warm subcommand + wire the `local`
   branch in both factory functions (they fall back to fake today).

**Config:** `NTAKE_ASSISTANT=local`, `NTAKE_ASSISTANT_MODEL` (default
`llama3.1:8b`), `NTAKE_LOCAL_LLM_URL` (default `http://localhost:8080` for
llamafile; e.g. `http://localhost:11434` for an Ollama endpoint),
`NTAKE_ASSISTANT_TIMEOUT` (currently 4.0 — tuned for the fake).

**⚠ Cold start + two calls (decide against real host measurement):** the pipeline
makes **two** sequential local-model calls per capture, and a model's *first* call
after idle takes seconds to tens of seconds to load into memory — 4.0s would
guarantee a cold-miss → graceful-degrade to `[]`. Give the `local` path a larger
timeout and/or a keep-warm setting + a startup warm ping. Non-thinking model → no
`<think>` stripping.

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
