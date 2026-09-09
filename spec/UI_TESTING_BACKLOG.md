# UI-testing backlog

Running list of findings from hands-on live-LLM UI testing (`make ui-live`) — small
improvements + rough edges to run down, captured so they aren't lost. Not a
committed plan; groom into PLAN.md / spec docs when picked up. Newest at top.

Legend: **[open]** not started · **[wip]** in progress ·
**[awaiting live verification]** automated coverage is present but human browser/
device testing remains · **[done]** landed · **[wontfix]** decided against (with
reason).

---

## Open

### 5. Enforce or explicitly accept the wall-tablet kiosk access boundary — [open: MVP]
The intended wall surface is calendar/board-only, while phones own capture and
Confirm. The current implementation serves one authenticated PWA shell: calendar
and board are read-only, but every authenticated device can still see and use the
capture form and proposal controls. The configured `child` role is stored for
attribution but does not gate these routes.

Before the owner installs the wall tablet, choose one explicit path and record it
in `PLAN.md`:

- implement a dedicated kiosk surface or server-side mutation denial; or
- consciously accept a physical-use convention (for example Guided Access) and
  do not call it access-controlled read-only.

Do not solve this by treating a low-privilege token as an enforced permission;
it is not one today.


### 3. Capture must submit from Enter / mobile keyboard Done; support OS dictation — [awaiting live verification]
The capture field should submit when the user presses **Enter** on a hardware
keyboard or the phone keyboard's **Done/Enter** action, without requiring a tap on
the Capture button. This matters for the intended PWA phone flow: the user will
use the OS/browser voice-to-text dictation to fill the focused field, then should
be able to submit from the keyboard.

The rendered shell has automated coverage for a native `<form>` submit, the
mobile Done hint, and its keyboard handler. Verify the behavior on desktop and an
installed/mobile PWA before closing this item. Do not add app-owned speech
recognition in this slice — OS dictation writes into the ordinary field. If capture
later becomes a multiline textarea, define the contract explicitly: Enter submits;
Shift+Enter adds a newline.

### 4. Add tag-based calendar colors — [deferred: kiosk hardening]
The event-tag data/action contract is now built: `Event.tags: list[str]`, the API,
create actions, `set_event_tags`, and deep context all carry normalized shared tags.
Defer the visual palette decision until immediately before kiosk hardening starts,
when the wall-display constraints can steer it. The eventual mapping should use a
fixed accessible household palette; first tag is the primary grid color, remaining
tags belong in a later event-detail surface, and unknown tags use a neutral
fallback. Do not accept arbitrary model-supplied colors.

---

## Done

### 1. Deep context includes work-item and event tags
Deep context now renders normalized work-item and event tags in a compact
`[tags: ...]` suffix, with direct coverage for both surfaces.

### 2. First-person ("I"/"me"/"my") links the capturing member
Both Fake and local LINK resolvers now deterministically add the capturing member
to `resolved_member_ids` when a note contains `I`, `me`, `my`, or `mine`. The
member is then included in deep-context construction exactly as a LINK-resolved
member, without relying on a model decision.
