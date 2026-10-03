# Session 4 kickoff prompt

> Paste the block below to a fresh agent context to run **Session 4** of the
> AWS-native rebuild. Self-contained: it points the agent at the resume state and
> source-of-truth docs. One session per sitting; stop at the exit and report.

---

We're continuing the AWS-native rebuild on the `aws-rebuild` branch. First read
`spec/AWS_PROGRESS.md` to resume state — read the **Session 3 hand-off note at the
bottom first** ("Tier-2 dev run — CLOSED GREEN" + its deferred-gaps list), then
the **two-tier testing decision note** (2026-10-02) including its **"Tier 2 is
always WIRED, and self-skips on unmet preconditions"** clarification, which is
authoritative. Sessions 0.1–3 are done:

- **Core + data layer complete.** Engine, action registry/specs, ULID-string
  DTOs, temporal, token hashing lifted + live. `Repository` protocol + pure
  key/sort helpers in `core/repository.py`; `InMemoryRepository` (Tier 1) +
  `DynamoRepository` (Tier 2, boto3 single-table) both satisfy it. All six
  former-parked handlers ported onto the Repository seam, under the gate; boundary
  test covers the actions package (no boto3 in core/handlers).
- **Infra:** real `ntake-<stage>` single table + GSI1 (board) + GSI2 (calendar) +
  reserved TTL in `NtakeStack` (dev `DESTROY`, prod `RETAIN`+PITR). The throwaway
  `TracerStack`/`tracer/` + tracer scripts still exist — deleted in **Session 5**,
  not now.
- **Two-tier model authoritative.** Tier 1 = `make check` (ruff + mypy +
  in-memory/scripted-Bedrock unit+flow tests, the TDD inner loop; mandatory +
  pasted). Tier 2 = `make integration` ([HUMAN]-invoked, self-checking). Test
  families use the `itest-` id prefix + session-scoped prefix-sweep cleanup;
  `make dev-reset` drops the dev table. Shared harness in `tests/harness/` +
  `tests/conftest.py`; the `ScriptedBedrockClient` double + `link_response` /
  `propose_response` helpers exist and are self-tested in `tests/test_harness.py`.
- **Bedrock is account-auth-BLOCKED** (support case pending, §3.5). This blocks
  only the *real-model* Converse call, not the Tier-1 code or the Tier-2 *wiring*.

Then re-read source-of-truth docs under the two-tier model: `AWS_PLAN.md`
(Part II → **Session 4**; the **amended Operating rules**, esp. the Tier-2
wired/self-skip gate; the Tooling table), `AWS_HLD.md` (§7 the two Bedrock seams,
§2a the privacy tradeoff), `AWS_LLD.md` (**§3.1 LINK**, §3.3 schema-translation
context, **§3.4 the scriptable `BedrockClient` seam**, §3.5 deferred findings +
locked decisions, §8 two-tier test strategy).

**Do Session 4 only this sitting; stop at its exit and report. Do NOT start
Session 5 (and do NOT delete the tracer — that's Session 5).**

## Session 4 — Assistant: LINK + the scriptable seam (Phase 3a/3c)

Goal: stage-1 LINK grounding works deterministically with no network — world view
in → scripted Converse JSON out → validate-against-family → resolved whitelist →
deep-context → `FocusedContext` — fully TDD'd at Tier 1. The real-model LINK run
is a wired-but-self-skipping Tier-2 [HUMAN] follow-up (Bedrock blocked).

### Scope

1. **[AGENT] `BedrockClient` protocol + the real boto3 Converse client**
   (`adapters/bedrock_*.py` — the only place `bedrock-runtime` is imported; extend
   the boundary test to keep it out of `core`). **Endpoint-/region-configurable**
   (same discipline as `DynamoRepository`) so the exact code Tier 1 exercises via
   the scripted double is what a Tier-2 run hits. Reuse the existing
   `ScriptedBedrockClient` double — don't rebuild it.
2. **[AGENT] LINK seam** (`core.assistant` stage-1 `CaptureResolver` impl,
   AWS_LLD §3.1): LINK Converse call shape (world view = family members +
   candidate work-item/event id+label lists + capture text + server `now` +
   family `timezone`), constrained to `{work_item_ids, event_ids, member_ids}`.
   **Validate-don't-trust** (every id checked against the family; unknown
   dropped). Deterministic **first-person linking** (add capturing member for
   I/me/my) in code. Output → whitelist → deep-context fetch (single-Query reads,
   §1.3) → `FocusedContext`. LINK **never emits actions**. **Graceful degrade:**
   malformed/error → safe empty result, never raises into the request path. Also
   fix the `FocusedContext.resolved_*_ids` `list[int]` → ULID-string loose end
   (LINK is the first real producer of those ids).
3. **[AGENT] TDD, integration-first:** write the end-to-end LINK flow test first
   (scripted Converse JSON in → assert resolved whitelist + deep-context over the
   in-memory repo), watch it RED, implement to GREEN. Include malformed→degrade +
   first-person linking. Supplement with focused unit tests for pure bits only.
4. **[AGENT] Wire the Tier-2 LINK integration path, self-skipping (per the
   standing rule).** Extend `make integration` with a real-model LINK Converse
   call against dev that **self-checks Bedrock authorization and stops cleanly**
   ("Bedrock not authorized — [HUMAN] follow-up"), mirroring the `sts` self-check
   — so when the ticket clears, `make integration` runs the real LINK call **with
   no code change**. Build the path now; the *run* is the deferred [HUMAN]
   follow-up. Do not fake a Bedrock pass.

### Operating rules / method (two-tier)

TDD (Tier 1 is the red-green loop; the scripted double makes the whole LINK flow
deterministic — this is real integration testing of our code, §3.4). DRY
(registry/`DataType` single source; LINK reuses `core.temporal`, the existing
DTOs, the scripted harness). YAGNI (LINK only — PROPOSE tool-use is Session 5;
don't build it). Reuse the harness — extend, don't rebuild. Branch additive; never
reset/force-push/rewrite main/mainline/aws-rebuild. Commit at a green Tier-1 gate
(conventional-commit); append a Session 4 hand-off note to `spec/AWS_PROGRESS.md`.

### Exit

- **Tier 1 (`make check`) green (paste real output):** LINK flow tests pass over
  in-memory repo + scripted Bedrock (first-person linking, validate-against-family,
  malformed→degrade); `BedrockClient` seam + scripted double in place; boundary
  test forbids `bedrock-runtime`/`boto3` in `core`; the `FocusedContext`
  ULID-string fix is in.
- `make synth` clean (no new infra this session — the capture Lambda/IAM is
  Session 6).
- **Tier 2 LINK path is WIRED and self-skips cleanly** on the Bedrock block (paste
  the self-skip message to prove it stops, not fakes); the real-model LINK run
  recorded as the [HUMAN] follow-up tracked with the §3.5 support case. The
  Session-3 data-layer `make integration` suite is unaffected (re-run optional,
  regression only).
- Committed on `aws-rebuild`. Report what landed + what's deferred (real LINK run)
  + confirm next session is 5 (PROPOSE tool-use + schema translation).

### Hard rules

- Branch additive. Never reset/force-push/rewrite main/mainline/aws-rebuild.
- `make integration` / deploy is [HUMAN]-invoked — don't deploy or vend creds;
  surface the command. The Tier-2 LINK path must self-skip on the Bedrock block,
  never fake a pass.
- Don't build PROPOSE and don't delete the tracer (Session 5). Stop at Session 4's
  exit and report.

### Carry-forward (not Session 4 tasks unless noted)

- Bedrock account-auth is the standing blocker for real-model runs;
  `scripts/bedrock_bisect.py us.anthropic.claude-haiku-4-5-20251001-v1:0`
  backfills §3.5 when AWS grants it (no redeploy). Locked decisions (handler
  consumes a list of toolUse blocks; `toolChoice:any`;
  one-primary-proposal-per-capture default) stand.
- Session 5 = PROPOSE tool-use + schema translation **and** deletes the tracer
  package/stack + scripts, repoints `make deploy-dev` at `NtakeStack-dev`.
- Session 6 adds the capture Lambda + scoped `bedrock:InvokeModel` IAM +
  confirm/execute→publish boundary — first real end-to-end LINK+PROPOSE on dev.
  Deferred tests: transaction-rollback (Session 6), concurrency/LWW (v1 non-goal).
