# UI-testing backlog

Running list of findings from hands-on live-LLM UI testing (`make ui-live`) — small
improvements + rough edges to run down, captured so they aren't lost. Not a
committed plan; groom into PLAN.md / spec docs when picked up. Newest at top.

Legend: **[open]** not started · **[wip]** in progress · **[done]** landed ·
**[wontfix]** decided against (with reason).

---

## Open

### 1. Deep context should include work-item (and event) tags — [open]
`deep_context._render` shows each work item as `[w{id}] {title} ({status}, due ...)`
but omits its `tags`; events likewise render no tags. Tags are shared-vocabulary
signal the LLM could use to reason (e.g. group errands, spot a recurring category).
**Proposed:** add tags to the work-item line (and event line) in `deep_context`.
Consider the prompt-bloat tradeoff, but tags are short. Add a test asserting a
tagged item's tags appear in the rendered context.

### 2. First-person ("I"/"me"/"my") should link the capturing member — [open]
When the note is first-person ("I have a dentist appointment", "remind me"), the
LINK stage should resolve the **capturing member** into `member_ids` (the same way
"Alex's ..." links Alex). Today the author is only shown downstream as
`NOTE FROM: [m{id}] {name}` in the deep context; the LINK prompt/world-view doesn't
tell the model "the person writing this is [m{id}] {name}", so first-person
references don't reliably link a member. **Proposed:** surface the capturing
member's identity to the LINK prompt (e.g. a "YOU ARE: [m1] Alex" line in the
world view or LINK system prompt) + a rule: "first-person references ('I', 'me',
'my') mean the note's author — include their member id." Add a test:
first-person note by Alex → `member_ids` includes Alex.

---

## Done

_(none yet)_
