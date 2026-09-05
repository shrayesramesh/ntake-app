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

### 4. Add tag-based calendar colors — [open]
The event-tag data/action contract is now built: `Event.tags: list[str]`, the API,
create actions, `set_event_tags`, and deep context all carry normalized shared tags.
The remaining work is visual mapping: assign a fixed, accessible household palette
to EventCalendar `backgroundColor`/`textColor` or `classNames`. First tag is the
primary grid color; remaining tags belong in a later event-detail surface. Unknown
tags use a neutral fallback. Do not accept arbitrary model-supplied colors.

### 1. Deep context includes work-item and event tags — [done]
Deep context now renders normalized work-item and event tags in a compact
`[tags: ...]` suffix, with direct coverage for both surfaces.

### 2. First-person ("I"/"me"/"my") links the capturing member — [done]
Both Fake and local LINK resolvers now deterministically add the capturing member
to `resolved_member_ids` when a note contains `I`, `me`, `my`, or `mine`. The
member is then included in deep-context construction exactly as a LINK-resolved
member, without relying on a model decision.

---

## Done

_(none yet)_
