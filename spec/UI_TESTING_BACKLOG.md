# UI-testing backlog

Running list of findings from hands-on live-LLM UI testing (`make ui-live`) — small
improvements + rough edges to run down, captured so they aren't lost. Not a
committed plan; groom into PLAN.md / spec docs when picked up. Newest at top.

Legend: **[open]** not started · **[wip]** in progress · **[done]** landed ·
**[wontfix]** decided against (with reason).

---

## Open

### 3. Capture must submit from Enter / mobile keyboard Done; support OS dictation — [open]
The capture field should submit when the user presses **Enter** on a hardware
keyboard or the phone keyboard's **Done/Enter** action, without requiring a tap on
the Capture button. This matters for the intended PWA phone flow: the user will
use the OS/browser voice-to-text dictation to fill the focused field, then should
be able to submit from the keyboard.

The current markup is a `<form>` with a text input and an `onsubmit` handler, so
native Enter should already submit; verify it on desktop and installed/mobile PWA
and fix any browser/handler regression. Do not add app-owned speech recognition in
this slice — OS dictation writes into the ordinary field. If capture later becomes
a multiline textarea, define the contract explicitly: Enter submits; Shift+Enter
adds a newline.

### 4. Add event tags and tag-based calendar colors — [open]
The EventCalendar grid would be easier to scan with semantic colors (school,
health, travel, sports, meal, work, etc.). **Events do not currently have tags**
(the `Event` model/API/action contract has no `tags` field; only work items do),
so this is a data/action feature before it is a visual tweak.

**Proposed:** add `Event.tags: list[str]` (JSON + Alembic migration + API DTO),
add optional `tags` to `create_event`, and map a fixed, accessible household tag
palette to EventCalendar `backgroundColor`/`textColor` or `classNames`. First tag
is the primary grid color; remaining tags belong in a later event-detail surface.
Unknown tags use a neutral fallback. Do not accept arbitrary model-supplied
colors. This should also satisfy/open backlog item 1 by exposing tags to deep
context for model reasoning.

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
