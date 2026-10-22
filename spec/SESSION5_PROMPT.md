# Session 5 — Assistant: PROPOSE tool-use + schema translation

You are continuing the from-scratch AWS-native rebuild of the family calendar +
work-item app. Work in `/Users/shrayesr/kiroprojects/ntake-app` on the
`aws-rebuild` branch. This is a single git repo; the app lives in `ntake-aws/`,
specs in `spec/`.

## Read first, in order
1. `spec/AWS_START_HERE.md` — how to work (one session per sitting, TDD, the gate).
2. `spec/AWS_PROGRESS.md` — the resume log. Read the "Pivot — Bedrock → Anthropic"
   and "Session 4" notes at the bottom: they are where you pick up.
3. `spec/AWS_LLD.md` §3 (the two Anthropic seams) — especially §3.2 (PROPOSE),
   §3.3 (schema translation), §3.4 (scriptable seam), §3.6 (the deferred Jev
   refactor + the PROPOSE action/parameter split factoring you must honor).
4. `spec/AWS_PLAN.md` Part II, "Session 5" — the goal + exit criteria you execute.

## Key context (decided and committed — do not re-litigate)
- The assistant is on the **Anthropic Messages API, NOT Bedrock** (account-level
  Bedrock hold). LINK ⇒ PROPOSE pipeline; forced-tool shape confirmed live.
- Session 4 built LINK end-to-end and it's verified Tier-1 (`make check`: 262
  passed) **and** Tier-2 live against the real model (`make integration`: green).
  The `AnthropicClient` protocol + `ScriptedAnthropicClient` double + real
  `HttpAnthropicClient` already exist — PROPOSE **reuses** them, don't rebuild.
- Reuse the existing registry→tools projection (`build_tools_schema`) and the
  `scripted_anthropic` conftest fixture.

## Your task (Session 5 — PROPOSE)
TDD + behaviour-faithful to the reference
(`git show main:app/assistant/local_llm/propose.py`):
- Project the action registry onto Anthropic `tools`; `tool_choice {type: "any"}`
  with `no_action` as a registered tool.
- ids as **enum-over-whitelist** in each tool `input_schema` (LINK's resolved
  ids), **plus** app-side re-validation against the whitelist (defense-in-depth).
- Consume a **list** of `tool_use` blocks → `ProposedAction` cards (parallel tool
  use is native; **selection-not-execution** — never return a `tool_result`,
  never loop, nothing is written).
- Port the **BUG-001..008 hardening regression suite** (reference:
  `git show main:tests/assistant/test_local_llm_hardening.py`): param-contract
  drops, BUG-002 local-weekday/time validation, UTC-leak drop, graceful-degrade.
- **Factor PROPOSE at the action/parameter split point** (LLD §3.6): keep
  schema-projection / model-call / card-mapping separable so the future
  GENERATE⇒DECIDE swap is localized. Do **not** build a separate param-generator
  or decision-model interface — that is the deferred refactor (YAGNI).

## Operating rules
- **TDD:** write the test first (watch it fail), then implement. The gate
  `make check` (ruff + mypy + Tier-1 pytest, ≥95% coverage) **must be green with
  real pasted output** before the session is done — never claim green without
  running it.
- Match the existing code's style/typing (full hints, no `Any`, the engine
  boundary: no `boto3` in `core`). Match the reference's observable behavior; pin
  exact outputs in tests. Keep prompts short / token-efficient.
- **Tier 2:** extend `make integration` with a live PROPOSE call (reuses the
  deployed Anthropic key secret, no Bedrock gate). `make integration` is
  **[HUMAN]-invoked** — build + surface the command; the human runs anything
  touching the AWS account (private account `111037110464`; never put its creds
  in your environment).
- Confirm scope decisions with the user before acting on them; surface, don't
  assume.
- At the end: append a **Session 5 hand-off note** to `spec/AWS_PROGRESS.md`, run
  the gate, and stop for the user to run `make integration` + commit. Do **NOT**
  `git push`.

## Start
Read the docs above and the existing Session-4 assistant modules
(`core/assistant/anthropic_link.py`, `anthropic_client.py`; `tests/harness/
anthropic_double.py`), then **propose your TDD plan for PROPOSE before writing
code.**
