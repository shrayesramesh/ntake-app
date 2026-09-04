# Calendar grid design — EventCalendar default

**Author:** shrayesr  
**Date:** 2026-09-04  
**Status:** Draft — starting point for iteration  
**Scope:** Replace the current agenda-list calendar display with a standard,
read-only calendar grid. This document resolves the initial direction but leaves
interaction details open until the first working slice is reviewed.

## Summary

Use a locally served EventCalendar integration for the calendar display. The
month grid is the default view; users can switch to week and day views. The app
keeps its existing FastAPI, authenticated `/events` API, HTMX shell, and SSE
refresh model. EventCalendar owns client-side calendar layout and navigation; the
server remains the source of truth for events and mutations remain
propose-and-confirm.

This avoids custom month/week/day grid arithmetic and does not require React,
Vue, or another reactive framework.

## 1. Product decision: standard grid, month by default

The current agenda-list calendar is a useful minimal display, but it does not
provide the household overview expected from a shared wall calendar. The default
calendar should be a conventional monthly grid, with week and day views available
when someone needs more detail.

Initial defaults:

| Decision | Default |
|---|---|
| Calendar library | EventCalendar vanilla-JS build, served locally |
| Default view | Month grid (`dayGridMonth`) |
| Optional views | Week time grid (`timeGridWeek`) and day time grid (`timeGridDay`) |
| Navigation | Previous, Today, Next |
| Event editing | Read-only in the first slice |
| Event mutations | Continue through assistant proposals and Confirm; no direct calendar editing |
| Live updates | SSE change event calls `calendar.refetchEvents()` |

The week-start convention remains open. Start with the EventCalendar locale
default until the household reviews the first working grid.

## 2. Why use EventCalendar instead of a custom grid

EventCalendar already provides the hard parts of a standard calendar:

- Month, week, and day layouts.
- Navigation and Today controls.
- Timed-event placement and all-day lanes.
- Responsive behavior suitable for phones and the wall display.
- Keyboard and accessibility behavior maintained by the library.

A custom grid would require date-bucketing, week boundaries, adjacent-month cells,
all-day spans, timed overlaps, overflow handling, responsive behavior, and
accessibility work. Those are calendar-library concerns, not household-planning
logic.

The app should self-host the library assets rather than use a public CDN. The app
is self-hosted and should remain usable without a third-party asset fetch.

## 3. Architecture: client-side calendar state, server-side event truth

This is not a front-end framework rewrite. The current HTMX/server-rendered shell
remains. EventCalendar owns only the display's local view state (month/week/day and
current anchor date).

```text
Browser shell
  └─ EventCalendar
       ├─ view state: current anchor + month/week/day
       ├─ custom event source
       │    └─ authenticated GET /events
       │         └─ FastAPI / SQLite source of truth
       └─ SSE change event
            └─ calendar.refetchEvents()
```

The existing `EventSource` already reconnects and refreshes board/calendar
surfaces. The grid integration replaces the agenda-fragment reload with a
EventCalendar event refetch. On a confirmed event change, the calendar refreshes
from `/events`; it does not attempt to patch individual cells optimistically.

## 4. Event API adapter

The existing authenticated `GET /events` response is the source for EventCalendar.
The browser uses the current device token to fetch it, maps each app event into a
EventCalendar event, and returns the mapped list to EventCalendar.

### Timed events

App storage uses UTC timestamps (`start_at`, `end_at`). The adapter marks
SQLite's naive stored values as UTC (`Z`) before handing them to EventCalendar, so
the browser converts them correctly. EventCalendar's documented timezone modes are
browser-local, UTC, or a fixed offset; it does not take the app's IANA family
zone directly in this standalone integration. The first slice uses **browser-local
time**. This is correct for household devices normally located in the same home
zone; a cross-zone/family-zone consistency requirement is a later design decision
that may require an adapter or a different calendar runtime.

### All-day events

The app stores `start_date` and `end_date` as inclusive dates. EventCalendar treats
an all-day event's `end` as exclusive. The adapter must map:

```text
app:          start_date=2026-09-07, end_date=2026-09-07
EventCalendar: start=2026-09-07,      end=2026-09-08
```

For a multi-day app event, the adapter similarly adds one day to the inclusive
end date. This conversion needs direct unit tests because an off-by-one error is
visible and confusing on a month grid.

### Extended display metadata

Initial EventCalendar events need title, timing, and all-day state. The adapter can
also carry these as `extendedProps` for a future event detail popover:

- `description`
- `location`
- `participants` (already resolved to member names in the current calendar UI)
- app event id

The first slice does not require a popover; standard title rendering is enough to
validate the grid.

## 5. Authentication and asset delivery

The EventCalendar event source must use the existing device token:

```text
GET /events
Authorization: Bearer <localStorage ntake_token>
```

The event source should be a custom JavaScript fetch function rather than a plain
URL event source, because browser event-source configuration needs the bearer
header. Existing token storage and `authHeaders()` logic in the shell can be
reused.

EventCalendar JS/CSS assets should be installed/pinned and served from the app
origin. Do not use a CDN. Exact package/version and asset build/copy mechanism are
implementation details to decide during the first slice after checking the
project's dependency tooling.

## 6. First implementation boundary

The first implementation is intentionally read-only:

1. Add locally served EventCalendar assets.
2. Mount a month-grid calendar in the existing shell.
3. Fetch and adapt the existing `/events` data with bearer auth.
4. Add Month / Week / Day and Previous / Today / Next controls.
5. On SSE change, call `calendar.refetchEvents()`.
6. Preserve the current assistant-only event mutation flow.
7. Test all-day inclusive-to-exclusive conversion, timed timezone rendering, auth,
   view navigation, and SSE refetch behavior.

Out of scope for the first grid:

- Drag/drop rescheduling.
- Direct event create/edit/delete controls.
- A custom event-detail modal or popover.
- Recurrence.
- Offline calendar caching.
- Replacing the work-item board.

Direct editing would bypass propose-and-confirm and needs an explicit product and
audit decision before it is added.

## 7. Delivery plan and level of effort

| Slice | Outcome | Rough LOE |
|---|---|---:|
| Grid foundation | Local assets, authenticated event adapter, month default, live refetch | 0.5–1 focused dev day |
| Standard views | Week/day controls, navigation, timezone/all-day correctness, tests | 1–2 focused dev days total |
| Polish | Wall-display styling, event detail, overflow UX, accessibility review | 2–3 focused dev days total |

The first slice is compact because EventCalendar owns grid layout and navigation.
The app-specific work is the authenticated event adapter and correct date
semantics.

## 8. Open questions for the first review

1. Should weeks start Sunday or Monday for this household?
2. Should EventCalendar render in the family timezone (consistent across displays)
   or the browser timezone (viewer-local)? The initial recommendation is family
   timezone.
3. What should a cell show when it has more events than fit: EventCalendar default
   overflow link, or a wall-display-specific expansion?
4. Should the current agenda cards remain below the grid on phone widths, or be
   replaced entirely after the grid proves useful?
5. What event detail should a click show: title only, or description/location/
   participants immediately?
6. Should calendar event colors follow a fixed semantic tag palette? This requires
   adding tags to the Event model/API/action contract first; see
   `UI_TESTING_BACKLOG.md` item 4.

## 9. Alternatives and why EventCalendar is the selected default

| Option | Fit | Tradeoff |
|---|---|---|
| EventCalendar standalone build (`@event-calendar/build@5.12.2`) | Selected default. Vanilla JS, month/week/day, custom Promise event source, `refetchEvents()`, documented lazy fetching, MIT, zero runtime dependencies. Vendored locally as a 128 KB minified JS + 15 KB CSS bundle; source/version/license notice lives beside the assets. | Smaller ecosystem and community-support model; no commercial SLA. |
| FullCalendar vanilla-JS | Backup option. Larger/more mature ecosystem, strong documentation, standard grids and event-source API. | Heavier integration/asset footprint for requirements EventCalendar already meets. |
| Toast UI Calendar | Viable vanilla month/week/day alternative. | More opinionated visual model and no clear first-slice advantage. |
| Custom HTMX/server-rendered grid | Not recommended. | Reimplements date math, placement, overflow, navigation, and accessibility already supplied by a library. |

EventCalendar is selected for the first implementation because its documented
standalone bundle and Promise-based custom event source fit the existing vanilla
shell, bearer-auth `/events` API, and SSE refresh path. FullCalendar remains the
fallback if wall-display testing exposes an EventCalendar layout, browser, or
timezone limitation.

## 10. Latency, throughput, and scaling expectation

The current local `/events` endpoint is fast at the seeded household scale. A
2026-09-04 local measurement against the running app returned two events in a
442-byte payload: 10 requests averaged **1.8 ms** server round-trip time (minimum
1.6 ms, maximum 2.3 ms). This is an API baseline only; it does not measure browser
asset parsing, EventCalendar layout, or a production-sized event history.

The first grid can fetch the whole existing `/events` feed once and refetch after
an SSE change. At ordinary household scale this is likely sufficient: navigation
between month/week/day is local EventCalendar state, and event changes are rare.
The current API has no date-range filter, so payload size grows linearly with total
stored events; an event history with thousands of rows should trigger the next
optimization.

EventCalendar's custom event-source function receives the visible start/end range.
When the payload becomes material, extend `/events` with authenticated range
parameters and index/query timed and all-day events correctly for their overlap
with that range. This is a performance follow-up, not a first-slice prerequisite.

The first implementation should record browser-side timings for:

- EventCalendar asset load/initialization on phone and wall display.
- Initial event fetch and first month render.
- Month/week/day navigation with the existing event cache.
- SSE-triggered `refetchEvents()` after a confirmed change.

## 11. Acceptance criteria for the first slice

- A new user lands on a month grid by default.
- Month, week, and day controls work without a front-end framework.
- Events from authenticated `/events` render in the correct grid cell.
- Single-day all-day events render on exactly one date; multi-day events span the
  intended inclusive app range.
- Timed events display at the correct local/family time.
- Confirming an assistant event action causes the visible grid to refresh through
  the existing SSE path.
- The grid remains read-only; no direct mutation bypasses Confirm.
- `make check` remains green.
