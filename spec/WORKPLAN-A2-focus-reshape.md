# Work plan — A2: reshape FocusedContext + wire the fake onto the real pipeline

> **For the next session.** Self-contained plan to (1) reshape `FocusedContext`
> to the LLD's two-call target, (2) add a deterministic **fake link** MVP so the
> fake path runs the real `link → deep_fetch → propose` flow with no model,
> (3) retire the `EventSummary`/`calendar_window` legacy. Parent design:
> `spec/LLD-assistant-pipeline.md` (esp. OQ-1 resolved: two LLM calls). House
> rules: `spec/AGENT_START_HERE.md` + `SKILL.md`. TDD; `make check` green per step.

## Goal & invariants

- **Decision A2 (locked):** full reshape now (not a minimal wire-up).
- **Invariant B (locked):** `FakeAssistant`'s **proposals stay identical** —
  same action `name`/`params`/`target` for the same input. Internals and the
  `llm_rationale` text MAY change. The existing capture/confirm/proposal tests
  that assert *actions* must still pass (adjust only rationale/really-internal
  assertions).
- Everything stays deterministic + model-free (the local-LLM backend is still task 7, separate).
- `make check` (lint + mypy + ≥95% cov) green after every step; commit per step.

## Current shape (what we're changing)

`FocusedContext` (in `app/assistant/context.py`) today:
```
text, work_item_id: int|None, timezone, now,
item_log: list[str], calendar_window: list[EventSummary]
```
- `EventSummary` + `calendar_window` are **fake-path legacy**. Read by:
  `FakeAssistant` (deconflict pairs + target), `FakeCaptureResolver`
  (`_event_summaries`), and `render_focus` (context.py). The real pipeline
  (`build_world_view` + `resolve.py`) renders to text and does NOT use them.
- `FakeCaptureResolver.focus()` resolves NO target (`work_item_id=None`) and fills
  `calendar_window` — the deterministic v1 that predates the two-call design.

Target shape (per LLD): `focus()` = `build_world_view → link → deep_fetch`,
producing a `FocusedContext` that carries the **deep context** (the string
`resolve.deep_context` builds) + the resolved target ids — NOT `calendar_window`.

## Pieces that already exist (built + tested — reuse, don't rebuild)

- `app/assistant/world.py` → `build_world_view(session, family_id, now, tz, *, window_days=7) -> str`
- `app/assistant/resolve.py` → `parse_ids(link_json) -> (work_item_ids, event_ids)`;
  `deep_context(session, member, work_item_ids, event_ids) -> str`
  (validates to family, unions the member's footprint, renders full update history)
- `app/assistant/tools.py` → `build_tools_view(registry) -> str`
- `app/assistant/prompts.py` → `build_link_prompt(...)`, `build_propose_prompt(...)`
- `app/assistant/actions.py` → the 13-action `REGISTRY`
- Golden-file snapshots: `tests/expectations/*.txt` (regen: `make update-expectations`)

## Plan (each step: TDD, `make check` green, its own commit)

### Step 1 — Reshape `FocusedContext`
Reshape to the two-call target. Proposed fields:
```
text: str
timezone: str
now: datetime
resolved_work_item_ids: list[int]      # from the (fake or real) link
resolved_event_ids: list[int]
deep_context: str                       # resolve.deep_context(...) output
```
- **Drop** `calendar_window` and the single `work_item_id`. Drop `EventSummary`
  from `context.py` (and its re-export in `base.py`).
- Keep it an `ActionContext` (read-only, no Session) — the propose seam stays
  session-free.
- **Target attachment** (LLD OQ-4): `FakeAssistant` will attach a work-item
  target from `resolved_work_item_ids` (type-based, ≤1 per type in v1). Decide the
  helper: a small `ctx.primary_work_item_id` / `primary_event_id` accessor, or the
  assistant reads the lists directly. (Lean: a tiny accessor for readability.)

### Step 2 — Deterministic **fake link** (the resolver MVP)
New `app/assistant/fake/link.py` (or into `fake/resolver.py`):
```
fake_link(session, family_id, note, now, tz) -> (work_item_ids, event_ids)
```
- Deterministic substring/keyword match of `note` against the family's
  **non-archived work item titles** and **event titles** (+ optionally member
  names). Case-insensitive; return the matched ids. No LLM.
- Keep it intentionally simple (an MVP): e.g. a work item matches if a significant
  word of its title appears in the note ("plumber" ∈ note → that item). Document
  the matching rule in the docstring; it's the fake analog of the LINK call.
- This is what makes the fake path actually resolve a target from text (today it
  resolves none) — so proposals like `set_due_date` on an existing item become
  reachable deterministically.

### Step 3 — Rewrite `FakeCaptureResolver.focus()` onto the real seams
```
focus(request, session, member):
    world = build_world_view(session, member.family_id, request.now, request.timezone)  # (available if needed)
    wi_ids, ev_ids = fake_link(session, member.family_id, request.text, request.now, request.timezone)
    dc = deep_context(session, member, wi_ids, ev_ids)
    return FocusedContext(text=..., timezone=..., now=...,
                          resolved_work_item_ids=wi_ids, resolved_event_ids=ev_ids,
                          deep_context=dc)
```
- Delete `_event_summaries`. `focus()` now runs the real `link → deep_fetch` shape
  (fake link, real deep_fetch), producing the deep-context string.

### Step 4 — Rewrite `FakeAssistant.propose()` to the new shape (KEEP proposals)
- Read `ctx.text` + `ctx.resolved_work_item_ids` (instead of `work_item_id`) for
  targeting; attach the work-item target from the resolved ids.
- **Deconflict:** today it reads `calendar_window` for same-start pairs. That data
  is gone. Options: (a) drop the deconflict *proposal* from the fake (the action
  still exists + is tested in `test_actions`/`test_confirm`), or (b) re-derive
  conflict detection from a light event query in the resolver and pass minimal
  event info in the context. **Lean: (a) drop it from the fake's proposals** — it
  was a placeholder proving calendar context flows; the two-call design proves that
  differently now. Confirm with the owner; update `test_deconflict.py` accordingly.
- **Invariant B:** every *other* proposal (create_work_item, create_event,
  set_due_date, complete, etc.) must come out identical for the same input.
- `render_focus` → rewrite (or drop) since `calendar_window`/`work_item_id` are
  gone; the fake's `llm_rationale` can just summarize `ctx.text` + resolved ids.

### Step 5 — Retire `EventSummary` + clean up
- Remove `EventSummary` from `context.py`/`base.py`; delete `_event_summaries`.
- Update every test that built `EventSummary`/`calendar_window`: `test_focus.py`,
  `test_deconflict.py`, `test_fake_assistant.py`, `test_confirm.py` (proposal
  tests). Keep assertions on *actions*; drop/relocate assertions on the retired
  fields.
- Update `spec/NEXT_SESSION.md` (remove the "EventSummary cleanup — deferred"
  note; it's done) and the LLD if the `FocusedContext` shape section needs it.

## Risks / watch-outs
- **Big test blast radius** (Step 5): `calendar_window`/`work_item_id`/`EventSummary`
  are referenced across ~4 test files + `context.py`. Do Step 1 + fix compile/
  imports before touching behavior, so failures are legible.
- **Invariant B is the guardrail:** if a proposal *action* changes, that's a
  regression — only rationale/internal wording may move. Lean on the existing
  `test_capture.py`/`test_confirm.py` action assertions as the safety net.
- **Deconflict decision** (Step 4) is the one real behavior question — get the
  owner's nod on dropping it from the fake vs. re-deriving conflicts.
- **`make smoke`** still references the old `work_item_id`-on-capture shape (noted
  in NEXT_SESSION) — out of scope here, but don't let this work make it worse.

## Definition of done
- `FocusedContext` reshaped; `EventSummary`/`calendar_window` gone; fake path runs
  `build_world_view`→`fake_link`→`deep_context`→`propose`; `FakeAssistant`
  proposals unchanged (Invariant B); `make check` green; docs updated; per-step
  commits.
