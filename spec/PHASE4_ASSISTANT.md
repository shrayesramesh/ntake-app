# Phase 4 — the assistant (capture → propose → confirm)

> **Status:** design mock-up (no code yet). Builds on the LOCKED v1 action set in
> [`ASSISTANT_ACTIONS.md`](ASSISTANT_ACTIONS.md). The model runs via **Ollama on
> the host**; this machine develops against a **fake**. Everything is behind a
> swappable interface so the model is a config value, not a design commitment.

## 1. The modular boundary — `AssistantClient`

One interface; the rest of the app depends only on it.

```python
# app/assistant/base.py
@dataclass
class ProposedAction:
    name: str                 # a key in the action registry (e.g. "set_due_date")
    params: dict              # plain dict, lightly validated at apply time
    summary: str              # human-facing card text ("Set due date to Fri 3pm")

class AssistantClient(ABC):
    @abstractmethod
    def propose(self, ctx: CaptureContext) -> list[ProposedAction]:
        """Given the raw input + context, return zero or more proposed actions.
        MUST NOT mutate anything. MUST return [] on any failure (never raise into
        the request path)."""
```

Implementations (chosen by config, `NTAKE_ASSISTANT`):
- **`FakeAssistant`** (`fake`, default in dev/tests): deterministic canned actions
  derived from the input text (e.g. text contains "friday" → a `set_due_date`
  proposal). No model. Lets us TDD the entire flow with zero infra.
- **`OllamaAssistant`** (`ollama`, host): calls Ollama with a JSON-schema-
  constrained prompt, parses the result into `ProposedAction`s. Host-only live
  test (like Tailscale 1f).
- **`NullAssistant`** (`off`): always returns `[]` (assistant disabled).

`CaptureContext` carries everything the assistant needs (and nothing it
shouldn't): the raw text, the target work item (+ its recent update log), a
compact calendar window, the family `timezone`, and `now`. Kept lean = fewer
tokens = faster.

## 2. The flow (synchronous, propose-and-confirm)

```
Member types free text in the capture bar (targets an item, or "new")
        │
        ▼
[ auth ]  device token → member (existing)
        │
        ▼
[ SAVE (existing item only) ]  human prose is truth:
     • existing item → add_note(body=text)   (source=human) → saved NOW; this
       commit publishes via the 1d seam → SSE broadcasts to ALL devices.
     • new item → save NOTHING. Bare text does NOT auto-create a work item;
       it becomes a create_work_item / create_event PROPOSAL to confirm.
        │
        ▼
[ assistant.propose(ctx) ]  bounded by NTAKE_ASSISTANT_TIMEOUT (~4s).
   On timeout / error / disabled → returns [] (graceful degrade).
        │
        ▼
[ response ]  { item: <existing item | null>, proposals: [ProposedAction, ...] }
        │
        ▼
[ UI: inline Confirm/Dismiss cards, AUTHOR'S DEVICE ONLY ]
   (proposals are NOT broadcast; the existing-item note, if any, was above)
        │
   ├─ Dismiss ─► nothing applied. Correct by restating (new capture).
   └─ Confirm ─► POST the action back → registry apply-handler runs:
                 the mutation + append a source=assistant update (author=confirmer).
                 That commit publishes via the seam → SSE → all devices update.
```

Key invariants (from ASSIST-2 / research/06):
- **Never auto-applies.** Confirm is the only path to a mutation.
- **New-item capture is propose-only.** Bare text no longer auto-creates a work
  item — the human confirms `create_work_item` (and/or `create_event`). Only an
  **existing-item** capture saves immediately (a `source=human` note — genuine
  human content added to an item the member explicitly targeted, WORKITEM-2).
- **No suggestions table.** Proposals live only in this request/response; the
  Confirm payload IS the action object the client sends back.
- **Author-device-only proposals**; an existing-item note still SSE-broadcasts.

## 3. The contract (model output)

The assistant must produce exactly:

```json
{ "actions": [ { "name": "set_due_date", "params": { "due_at": "2026-09-04T19:00:00Z" } } ] }
```

- `name` ∈ the v1 registry keys; unknown names dropped.
- `params` a plain dict; lightly checked against the registry entry; invalid
  dropped. `work_item_id` is injected server-side from the capture target (the
  model doesn't guess IDs).
- Empty / nothing to suggest → `{ "actions": [ { "name": "no_action" } ] }`.

**Ollama specifics (OllamaAssistant):**
- Use Ollama's **structured output** (`format` = a JSON schema for the above) so
  the model is constrained to valid shape — fewer tokens, reliable parsing.
- Prompt = system (role, the available actions + their params, "propose only
  from these; use no_action if nothing applies; dates in the family timezone")
  + context (now, tz, the item's recent log, a small calendar window) + the raw
  text.
- Non-thinking model (llama3.1:8b / qwen2.5:7b) → no `<think>` stripping needed.

## 4. Config (all swappable, no code change)

| var | default | meaning |
|---|---|---|
| `NTAKE_ASSISTANT` | `fake` | `fake` \| `ollama` \| `off` — which client |
| `NTAKE_ASSISTANT_MODEL` | `llama3.1:8b` | Ollama model tag (host) |
| `NTAKE_OLLAMA_URL` | `http://localhost:11434` | Ollama endpoint (host-local) |
| `NTAKE_ASSISTANT_TIMEOUT` | `4.0` | seconds before graceful-degrade to `[]` |

Dev/tests here run `fake`. The host sets `NTAKE_ASSISTANT=ollama` +
`NTAKE_ASSISTANT_MODEL=...`. A/B models by changing the model var only.

## 5. Worked example (Qwen/llama, via the fake in tests)

Input (on item #7 "call plumber"): *"he's coming friday at 3"*
Context: tz America/New_York, now 2026-09-02T…

Model returns:
```json
{ "actions": [
  { "name": "set_due_date", "params": { "due_at": "2026-09-05T19:00:00Z" } },
  { "name": "create_event",
    "params": { "title": "Plumber visit", "start_at": "2026-09-05T19:00:00Z",
                "end_at": "2026-09-05T20:00:00Z" } }
] }
```
→ Two inline cards on the author's phone: "Set due date to Fri Sep 5, 3:00 PM"
and "Add event: Plumber visit, Fri 3–4 PM". Confirm either independently; each
applies + logs a `source=assistant` update on item #7 (the event links back via
`source_update_id`). The `FakeAssistant` reproduces this deterministically from
the word "friday" so the whole flow is TDD-able with no model.

## 6. Build order (fake-first; Ollama last, host-tested)

1. **Action registry + apply-handlers** for the 5 v1 actions (plain dict; each
   apply mutates + appends the `source=assistant` update). TDD.
2. **`AssistantClient` + `FakeAssistant`.** TDD the propose contract.
3. **Capture-with-proposals endpoint** (save raw → propose → return). TDD w/ fake.
4. **Confirm endpoint** (apply the returned action). TDD w/ fake.
5. **Inline Confirm/Dismiss cards** in the capture UI. Manual browser verify.
6. **`OllamaAssistant`** (host-only): `format`-constrained call to Qwen/llama,
   prompt with tz/now/log/calendar, parse to actions. Live-tested on the host.

## 7. Open questions (non-blocking)

- **OQ-P4-1** Capture routing: v1 targets an explicit item (or "new"); the
  assistant deciding new-vs-append for bare free text is v2.
- **OQ-P4-2** `create_work_item` from capture also being an assistant *proposal*
  vs. always a direct save — v1: bare text saves directly (source=human);
  proposals layer on top.
- **OQ-P4-3** Prompt/param tuning per model — behind `OllamaAssistant`, not
  architectural.
- **OQ-P4-4** Future: async proposal delivery over SSE (ASSIST-6) — the
  raw-save/propose split already makes this a later, non-breaking change.
