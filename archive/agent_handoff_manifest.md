# Agent handoff — packaging & transfer

How to get the right context onto the home Pop!_OS machine for the local agent.

## What the agent needs (minimal in-scope set)

```
AGENT_START_HERE.md                     # entry point — agent reads this first
shovel-ready/agent_bootstrap_prompt.md  # rules + task queue (authoritative)
shovel-ready/tasks_app_scaffold.md      # Pop!_OS venv/install for 1a
research/03-stack-libraries.md          # libraries + versions
research/04-data-layer.md               # ORM models / schema to implement
PLAN.md                                 # checkpoint definitions (Phase 0-1)
```

Optional background (only if the agent asks for data-model context):
`DESIGN.md` (§4 in particular).

**Not needed by the agent:** the Tailscale task files, `USER_SETUP_GUIDE.md`,
`REQUIREMENTS.md`, `DESIGN-sms-deferred.md`, `research/01|02|05`. They're
human-facing or out of scope; leaving them out reduces the chance a small model
wanders off-task.

## Option A — copy the whole project (simplest)

Just copy the entire `calendar/` folder to the home machine and point the agent
at `AGENT_START_HERE.md`. The START-HERE + bootstrap files tell it what to ignore.
Simplest; relies on the agent respecting scope (the prompt is written to enforce
that).

## Option B — copy only the in-scope files (tightest for a small model)

Recommended for a smaller local model — less to wander into. From the project
root, on a machine that has the files:

```bash
# create a slim handoff bundle
mkdir -p agent_handoff/shovel-ready agent_handoff/research
cp AGENT_START_HERE.md agent_handoff/
cp PLAN.md agent_handoff/
cp shovel-ready/agent_bootstrap_prompt.md agent_handoff/shovel-ready/
cp shovel-ready/tasks_app_scaffold.md      agent_handoff/shovel-ready/
cp research/03-stack-libraries.md          agent_handoff/research/
cp research/04-data-layer.md               agent_handoff/research/
# then move agent_handoff/ to the home machine (USB, scp over tailnet, etc.)
```

> Note the relative paths in `AGENT_START_HERE.md` (e.g.
> `research/04-data-layer.md`) still resolve inside `agent_handoff/` because the
> subfolder structure is preserved.

## Kicking off the agent

1. On the home machine, open the coding agent in the project (or `agent_handoff/`)
   directory.
2. Give it, as the first message:
   > Read `AGENT_START_HERE.md`, then follow
   > `shovel-ready/agent_bootstrap_prompt.md`. Begin with checkpoint 1a and STOP
   > after it.
3. Review its 1a output, then tell it "continue" for 1b, and so on.

## Human-only, keep for yourself

Do the Tailscale/device steps yourself (not the agent):
`shovel-ready/tasks_tailscale_account.md`,
`tasks_tailscale_host_serve.md`, `tasks_verify_1f.md`.
