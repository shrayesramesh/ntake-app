# AGENT — START HERE

> **You are a coding agent on the home Pop!_OS machine.** This file tells you
> what to read, what to build, and what to ignore. Read it fully before doing
> anything.

## Step 0 — read your instructions

Your full operating rules and task queue are in:

**`shovel-ready/agent_bootstrap_prompt.md`** ← read this first and follow it exactly.

That prompt is authoritative. If anything below conflicts with it, the bootstrap
prompt wins.

## Files you SHOULD read (in scope)

Read these before/while coding — they are the specs you build against:

| File | Why you need it |
|---|---|
| `shovel-ready/agent_bootstrap_prompt.md` | Your rules + ordered task queue (1a–1e). **Primary.** |
| `research/04-data-layer.md` | The ORM models / schema to implement. Use exactly. |
| `research/03-stack-libraries.md` | Which libraries + versions to install. |
| `shovel-ready/tasks_app_scaffold.md` | Pop!_OS venv/install specifics for 1a. |
| `PLAN.md` (Phase 0–1 only) | Checkpoint definitions 1a–1e. |

## Files you should NOT act on (out of scope for you)

- `shovel-ready/tasks_tailscale_account.md`,
  `shovel-ready/tasks_tailscale_host_serve.md`,
  `shovel-ready/tasks_verify_1f.md` — **human-only** (Tailscale, browser, devices).
- `USER_SETUP_GUIDE.md` — for family members, not you.
- `DESIGN.md`, `DESIGN-sms-deferred.md`, `REQUIREMENTS.md` — background/context;
  do **not** try to implement everything in them. Your scope is checkpoints
  1a–1e only. Read `DESIGN.md §4` only if you need data-model context beyond
  `research/04-data-layer.md`.
- `research/01`, `research/02`, `research/05` — Tailscale/hardware rationale, not
  code tasks.

## Your scope, in one sentence

Build **checkpoints 1a–1e** (health endpoint → DB + models → `GET /events` →
change-event seam → SSE endpoint), TDD, one at a time, stopping after each.
**Do not** touch Tailscale/deploy/hardware — the human does 1f.

## Definition of done (for this handoff)

- 1a–1e complete, each with passing `pytest` output you actually ran.
- `requirements.txt` with pinned versions.
- App runs locally on `127.0.0.1:8000`.
- You STOP and report "ready for human 1f (Tailscale)".
