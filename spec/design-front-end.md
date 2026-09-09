# Front-end LLD — device onboarding, primary views, capture, and kiosk

> Companion to [`DESIGN.md`](DESIGN.md). This document defines the next PWA-shell
> evolution without changing the existing propose-and-confirm domain contract.
> It is the implementation source for the front-end arc after capture-to-confirm
> observability lands.

## 1. Status and decisions

| Topic | Decision |
|---|---|
| Primary views | Board and Calendar are mutually exclusive views, selected by an in-app toggle. The active choice is stored per device. |
| First active view | Calendar on first use; restore the last selected view thereafter. |
| Capture | A deliberate `Capture` action opens a focused dialog on desktop/tablet and a bottom sheet on narrow phones. It is not permanently visible in the shell. |
| Device onboarding | Retain per-device bearer tokens. Add QR delivery of the existing token before considering a more complex pairing-code protocol. Keep manual token paste as recovery fallback. |
| QR transport | Encode the app URL and token in a URL fragment, never a query parameter. The client consumes the fragment once, stores the token, and removes the fragment from browser history. |
| Phone / wall distinction | The intended phone and kiosk experiences differ, but the current app is one shared shell. A dedicated kiosk surface or server-side mutation denial is required before the wall tablet is called technically read-only. |
| Voice | MVP capture uses OS/browser keyboard dictation into the ordinary text field. Do not add app-owned microphone capture, remote speech services, or persisted audio in this slice. |

## 2. Goals and non-goals

### Goals

- Make Board and Calendar independently glanceable instead of competing in one
  split view.
- Make capture intentional and focused, while preserving the current
  `/capture` → proposal → `/actions/confirm` behavior.
- Remove device-token entry from the ordinary paired-device shell.
- Reduce setup friction by allowing the host to deliver the existing token as a
  QR code.
- Preserve keyboard, screen-reader, and narrow-phone usability.
- Give future kiosk work a clean surface boundary instead of embedding more
  kiosk exceptions in the shared shell.

### Non-goals

- No change to assistant action semantics, persistence, authentication model,
  or family-local time contract.
- No background/automatic assistant actions.
- No in-app account administration or self-enrollment.
- No app-owned voice recording/transcription in MVP.
- No claim that a low-privilege member role is currently a kiosk permission.

## 3. Device lifecycle and authentication UI

### 3.1 States

```text
unpaired
  └─ manual token or QR fragment → paired
paired
  └─ valid authenticated requests → normal shell
invalid / revoked token
  └─ clear local credential → unpaired with actionable explanation
```

The persistent server contract remains a hashed, per-device `DeviceToken`. QR
is a delivery format for that same credential, not a replacement authentication
system.

### 3.2 Unpaired screen

An unpaired browser renders no household data and no Board/Calendar/capture UI:

```text
Family Calendar

Connect this device
Scan the setup QR code provided by the household owner.

Have a device token instead?
[ Paste device token                         ]
[ Connect ]
```

Manual paste is a recovery/admin fallback. It is not shown after pairing.

### 3.3 QR bootstrap

The host mints the normal device token and presents it as a QR code whose payload
is conceptually:

```text
https://<tailnet-host>/#token=<existing-device-token>
```

When a browser opens that URL:

1. Read `token` from `location.hash`.
2. Validate it with an ordinary authenticated request.
3. On success, store it in the existing device-local credential store.
4. Call `history.replaceState()` to remove the fragment immediately.
5. Enter the paired shell and show a short confirmation.
6. On failure, remove the fragment and show the unpaired screen with a safe
   recovery message.

Fragments are intentional: regular endpoints must not accept credentials in URL
query parameters because queries may appear in logs, browser history, and referrer
metadata. The QR remains a bearer credential, so host delivery must be private and
the token remains revocable through the existing host CLI.

A future short-lived pairing-code exchange can build on this lifecycle if manual
or QR delivery proves insufficient; do not add temporary enrollment state now.

### 3.4 Paired device controls

The normal shell has no permanent token bar. A low-emphasis device menu may show:

```text
Device connected
Refresh
Reconnect this device
Remove this device from this browser
```

`Remove this device from this browser` only clears the local credential. It does
not revoke the server token; revocation remains an operator CLI action.

## 4. Normal paired shell

### 4.1 Layout

```text
┌──────────────────────────────────────────────────────────────┐
│ Family Calendar      [ Board ] [ Calendar ]       [ Capture ] │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│                       Active primary view                    │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

- The selector uses semantic buttons with `aria-pressed` or a tablist with the
  matching tab/panel relationships; implementation chooses one pattern and tests
  the complete keyboard behavior.
- Calendar is the first-use default.
- `localStorage` persists the active view per browser/device. Invalid or missing
  values fall back to Calendar.
- The active view fills the main region. The inactive view is not relied on as a
  stale hidden DOM cache.

### 4.2 Board view

The board remains a read projection of committed work-item state. Selecting Board
fetches/refetches the board fragment. It does not add manual lifecycle controls in
this slice.

### 4.3 Calendar view

Calendar remains the existing authenticated EventCalendar projection. Selecting
Calendar initializes or refetches it and preserves its internal month/week/day
controls. It continues to render family-local event values and all-day local
dates.

### 4.4 Live updates

On SSE `change` and SSE reconnect:

- Refresh the currently active Board or Calendar view.
- Do not interrupt an open capture dialog or discard typed text.
- If a Confirm succeeds, refresh the active view after the response is handled.

## 5. Capture interaction

### 5.1 Entry point

`Capture` is a header button on desktop/tablet. Narrow phones may render the same
action as a labelled floating/bottom action, but it must retain an accessible name
and must not hide the current active view permanently.

Opening capture:

- opens a modal dialog on desktop/tablet;
- opens a bottom sheet on narrow phones;
- moves focus to the text field;
- traps focus until close on modal-capable layouts;
- supports Escape/Cancel without any request;
- restores focus to the trigger when closed.

### 5.2 Capture panel states

```text
idle → submitting → proposals | no proposal | actionable failure
```

The panel owns the capture request and its resulting proposal cards:

```text
Capture

[ What needs to happen?                         ]

[ Cancel ]                             [ Capture ]
```

After a response, cards retain the existing deterministic action summary,
detail lines, model rationale, Confirm, and Dismiss behavior. Successful Confirm
refreshes the active primary view. Dismiss removes only that proposal card.

### 5.3 Failure feedback and observability

This shell work follows the observability implementation in `PLAN.md`. The UI
must distinguish at least:

- device credential rejected or revoked;
- server/network unavailable;
- assistant unavailable, timed out, or returned no usable proposal;
- Confirm rejected by action validation.

Messages must state the next useful action without revealing tokens, raw server
errors, or internal model prompts. Logs correlate the capture → assistant →
proposal → Confirm response path, but do not log raw household note text or
credentials by default.

## 6. Voice capture decision

### 6.1 MVP: operating-system dictation

The capture field is the voice entry point in MVP. Users activate the microphone
provided by their phone/tablet keyboard or browser, review the resulting text,
and submit the ordinary capture form using the keyboard Done/Enter control.

The UI supports this by:

- keeping a conventional focused text input/textarea in the capture panel;
- using an appropriate mobile `enterkeyhint` and an explicit submit handler;
- adding brief helper text such as “Use your keyboard microphone to dictate”; and
- requiring the user to review and submit the transcript themselves.

This keeps audio outside the app and preserves the same transparent
propose-and-confirm path as typed text. The app does not need, and cannot
reliably invoke, the platform keyboard’s microphone button.

### 6.2 Deferred: app-owned speech capture

App-owned microphone capture is a separate privacy, browser-support, and model
runtime project. If adopted later, it must:

1. use explicit microphone permission and an obvious recording state;
2. transcribe locally/on owned hardware only;
3. show an editable transcript before any `/capture` request;
4. discard raw audio after transcription by default; never store or log it;
5. provide a full typed fallback; and
6. never send audio directly to the assistant or auto-confirm a transcript.

Web Speech APIs and cloud speech services are not an MVP substitute because their
privacy, browser behavior, and data routing are not consistent with the app’s
local-data promise.

## 7. Kiosk boundary

The desired wall experience is:

```text
Family Calendar      [ Board ] [ Calendar ]
```

It displays committed state only. The normal phone shell’s `Capture` and device
controls are absent.

Current implementation does not enforce that distinction. Before claiming this
mode, choose one of:

1. a dedicated authenticated kiosk route/shell with no mutation controls; or
2. server-side mutation denial for kiosk credentials, paired with hidden controls.

Guided Access can limit casual physical interaction but is not authorization.

## 8. Implementation slices

1. Implement capture-to-confirm observability and actionable failure feedback.
2. Refactor the paired shell into Board/Calendar selector plus Capture dialog.
3. Add unpaired/paired shell states and QR-fragment bootstrap while retaining
   manual token paste.
4. Choose and implement the kiosk boundary.
5. Run human Tailscale HTTPS/PWA smoke on phone and tablet, including keyboard
   dictation, then conduct the kiosk soak.

## 9. Acceptance checks

### Automated

- Paired/unpaired state rendering and invalid-token recovery.
- QR fragment consumption, fragment removal, and no token rendering after
  successful bootstrap.
- Board/Calendar selection, first-use default, and per-device persistence.
- Keyboard-accessible selector and capture dialog focus behavior.
- Capture success, no-proposal, and categorized failure states.
- Confirm refreshes the active view without losing unrelated typed capture text.
- SSE refreshes the active view and does not close capture.

### Human device smoke

- Scan the host-delivered QR on phone and tablet over Tailscale HTTPS.
- Add the paired app to the home screen and launch standalone.
- Dictate a note through the keyboard microphone, review it, and submit with
  mobile Done/Enter.
- Verify Board, Calendar, EventCalendar controls, and sleep/wake reconnect.
- Verify the selected kiosk access model before leaving the tablet unattended.
