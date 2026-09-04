# Family Calendar + Work Items — Requirements

> Clean, reconciled requirements (supersedes the earlier REQUIREMENTS.md +
> REQUIREMENTS_UPDATE.md). Describes **what** the system does and **for whom** —
> solution-neutral. Implementation lives in DESIGN.md; the phased plan in PLAN.md.

---

## 1. Purpose

A private, self-hosted calendar + work-item system for one household (2–4
people). Two core jobs:

1. **A shared family calendar + work-item board** everyone can see and update, on
   a glanceable always-on display and from their phones.
2. **Making household/emotional labor visible** — surfacing workload, including the invisible coordination work (following up, chasing blockers, partial progress), for **recognition and fairness**.

**Hard framing constraint:** labor visibility is for recognition and fairness —
**never scoring, ranking, or surveillance**. No leaderboards, no automated
judgment of people. This constrains every labor-related feature.

---

## 2. Users

- **Adults** — full access: create/edit/delete events and work items, write
  updates,
  manage members/devices, run the periodic board grooming.
- **Children** *(future, not built day-one)* — schema anticipates a limited role;
  not enforced at launch.

**Trust model:** low-adversarial, single trusted household. Shared visibility by
default; no per-user privacy walls.

---

## 3. How it's used

Two surfaces, different jobs:

- **Phones (PWA):** the everyday surface — capture events, write work-item
  updates, confirm the assistant's suggestions, view the calendar/board.
- **Shared display (PWA kiosk):** an always-on wall tablet showing the calendar +
  board, glanceable across the room, live-updating, read-mostly.

There is no separate app to install beyond adding the PWA to the home screen.
(A no-install text channel — SMS/bot — is a possible later addition, deferred.)

---

## 4. Functional requirements

### 4.1 Calendar & events — `EVENT`

- **EVENT-1** Create, view, edit, delete calendar events.
- **EVENT-2** An event is **timed** (start/end datetime) or **all-day** (a date,
  rendered correctly in the household timezone — not a UTC instant).
- **EVENT-3** Events carry: a title, optional description and location,
  **participants**, and **tags** (see EVENT-5/6). No status/tentative, no
  built-in recurrence (see EVENT-4, INTEROP).
- **EVENT-4** Recurring needs are **not** an event feature. A repeating need
  surfaces via the work-item update log and the assistant proposing it (see
  ASSIST-*); the calendar itself stores only discrete events. *(Future evolution
  lives on the assistant/log side, not the calendar schema.)*
- **EVENT-5** An event has **participants** — who it's for/about (e.g. "Kid1",
  "Mom", "Grandma"). Each participant is **either a linked family member or a
  free-text name**, so non-members (Grandma, a teacher) can be named without
  being enrolled. Participants are calendar metadata, not a labor signal.
- **EVENT-6** An event has **tags** (a list of strings) from a **shared family
  vocabulary** (e.g. "Kid1", "school", "household"). Tags drive display
  color-coding (see DISP-6) and cross-surface grouping with work items
  (WORKITEM-9).
- **EVENT-7** For a work-item-originated event, the **"why it exists" context** is
  the
  link back to the update record that drove it (ACCESS-4); no separate stored
  category is needed. Thematic grouping is via tags (EVENT-6).

### 4.2 Work items — item + update log — `WORKITEM`

A work item is a **loose free-text item with an append-only stream of
updates** (closer to a ticket than a rigid card). *(Internal/UI name: "work
item"; "joule" is a possible future family-facing label.)*

- **WORKITEM-1** A work item is a **title + free-text description**, deliberately
  loose.
- **WORKITEM-2** Members **append free-text updates** to a work item over time
  (like ticket comments). Each update records **the text, its author (a member),
  and when**. This log is the **living source of truth** for the item's real
  state.
- **WORKITEM-3** The update log also records **confirmed assistant-driven
  outcomes** (e.g. "set due date Fri; created calendar event") as entries whose
  **author is the confirming member** and which are marked as **assistant-sourced**
  (vs. human-written). The log is thus the single narrative of everything that
  happened, and the labor view can tell human effort from assistant-confirmed
  actions.
- **WORKITEM-4** A work item has a **structured status** on a fixed board:
  **Todo / On deck / Doing / Done**. Status is a **grooming-time snapshot**, not
  live truth — adjusted during review or by confirming an assistant suggestion.
  There are no user-defined columns.
- **WORKITEM-5** "Blocked / needs help / partial progress" are **not** columns —
  the assistant surfaces them from the update log when relevant.
- **WORKITEM-6** A work item may have a **checklist** (sub-items) for the
  grocery-list-style use case.
- **WORKITEM-7** A work item may be **assigned** to a member (optional).
- **WORKITEM-8** A work item may have a **due date**, but it is
  **assistant-inferred and human-confirmed**, not a core human-set field (timing
  is relational to the calendar). Once confirmed, a due date renders the item on
  the calendar.
- **WORKITEM-9** A work item has **tags** (a list of strings) from the **same
  shared family vocabulary** as events (EVENT-6). Tags enable grouping a person's
  whole
  footprint across calendar + board (e.g. all "Kid1" items) and drive
  color-coding (DISP-6).

### 4.3 Board grooming & archive — `GROOM`

- **GROOM-1** The **board view** is a **periodic (~monthly) grooming instrument**,
  not the daily surface. Its jobs: prioritize when time is contentious, review
  workload, and celebrate completed work.
- **GROOM-2** A **Done** card can be **manually archived** (removed from the board,
  **retained** in the DB for history). Manual only — no automatic time-based
  sweep.
- **GROOM-3** An "**archive all Done cards**" action supports the review moment;
  archived cards can be **unarchived**.
- **GROOM-4** Only **Done** cards may be archived.

### 4.4 The assistant (LLM) — `ASSIST`

- **ASSIST-1** When a member enters an update or captures an event in natural
  language, a **local assistant** parses it **and** produces recommendations **in
  the same interaction**, returned into the PWA. No background/scheduled passes.
- **ASSIST-2** **Propose-and-confirm:** the assistant **never auto-applies**
  changes. Each proposal renders as an **inline card** (Confirm / Dismiss) on the
  **author's device only**; multiple proposals are actionable independently.
  Calendar mutations happen only on explicit Confirm.
- **ASSIST-3** Recommendations may include: needs-more-info/**blocker**, **request
  for help**, **multi-step/partial progress**, a **due-date proposal**, or a
  **calendar-event impact** (propose creating/updating an event). These are
  transient interpretations, not stored classifications; unacted proposals are
  not persisted.
- **ASSIST-4** The **labor view** (§1) and the board grooming are run **on demand**
  ("review now"), reading the raw update log at that moment — not scheduled, not
  precomputed metrics.
- **ASSIST-5** Correcting a wrong proposal is done by **restating** in a new
  update (which yields a fresh proposal), not a manual edit form. *(Future:
  in-place conversational refinement — telling the assistant what to change and
  it re-proposes. v1 uses the restate loop.)*
- **ASSIST-6 (accepted v1 limitation)** The assistant runs **synchronously** in
  the request path; capture waits on the model (seconds). Accepted for launch;
  async delivery of proposals is a known future refactor.

### 4.5 Shared display — `DISP`

- **DISP-1** Shows the calendar and work-item board together, legible from across
  the
  room.
- **DISP-2** **Live-updates** automatically as items change from any device — no
  manual refresh.
- **DISP-3** One shared family view; no per-user login during normal use
  (authenticated once at setup).
- **DISP-4** **Read-mostly:** live views with simple tap/form actions (tick an
  item, add via a form). No slick drag-and-drop day-one.
- **DISP-5** Runs always-on for days; must stay correct and stable across
  sleep/wake.
- **DISP-6** **Color-coding (day-1):** events and work items are colored on the
  display by **tag** (EVENT-6 / WORKITEM-9), via a family-defined **tag→color
  map** kept in settings (SETTINGS-1). Color is applied at render time — it is
  not stored on the event/work-item rows. Changing a tag's color updates
  everything with that tag.

### 4.6 Members, devices & setup — `ACCESS`

- **ACCESS-1** An admin (adult) can **add/remove members** and **enroll/revoke
  devices**. No self-enrollment.
- **ACCESS-2** Each device is enrolled with a **per-device credential**; every
  request is authenticated and access is restricted to enrolled family devices.
- **ACCESS-3** There is a defined way to **create the household + first admin**
  (bootstrap) and to **enroll the shared display** once at setup.
- **ACCESS-4** Attribution comes from the **update record** (its author), not from
  duplicated person fields on events — see DESIGN.

### 4.7 Destructive actions — `SAFE`

- **SAFE-1** All requests are authenticated (ACCESS-2).
- **SAFE-2** Destructive actions (delete/cancel) are gated by explicit
  confirmation and/or adult role.

### 4.8 Family settings — `SETTINGS`

- **SETTINGS-1** The family has a small **tag→color map** (which tag renders as
  which color, DISP-6). Kept minimal — a simple mapping in settings, **not** a
  tag-management subsystem (no per-tag entities, rename cascades, or metadata).
  Tags themselves are just strings on events/work items.

### 4.9 Calendar interoperability — `INTEROP`

- **INTEROP-1** *(Deferred capability.)* The calendar can eventually **export and
  import `.ics`** to interoperate with Google/Apple/Outlook. Export synthesizes
  the iCalendar fields on the fly — the stored event model stays minimal, **not**
  iCalendar-shaped. **Not** two-way sync.
- **INTEROP-2** *(Deferred capability.)* A **one-time backfill** to seed a fresh
  install from the tools the household already uses — **Trello** (board export →
  work items + their initial update log) and **Google Calendar** (`.ics` export →
  events). Operator-run and **file-based** (the operator supplies the export;
  no cloud API / OAuth in the data path — NFR-PRIVACY), idempotent, and
  **one-time seeding, not ongoing sync**. Design in DESIGN §6a.

---

## 5. Non-functional requirements

- **NFR-PRIVACY** Family data and messages stay on owned hardware. Satisfied by
  design: self-hosted backend + DB + local assistant model; no third-party cloud
  in the data path.
- **NFR-SYNC** Changes appear on other devices quickly (live push).
- **NFR-UPTIME** Available when the family needs it. **Launch:** runs on a single
  always-on home PC; availability = that machine's uptime (accepted). Home
  power/internet outage downtime accepted.
- **NFR-DURABILITY** Data protected against loss. Crash-safe via SQLite **WAL
  mode** (power loss → clean rollback, no corruption). **v1 backup:** an automated
  **weekly consistent snapshot** (via `VACUUM INTO`, not a raw copy). *(Accepted
  v1 limitation: the snapshot is **on the same disk** — protects against
  corruption/accidental deletion, **not** physical disk failure. Off-machine
  destination is the future fix, a one-line change. See DESIGN §3.1a.)*
- **NFR-TIME** Correct across timezones and DST. The household timezone is stored
  day-one; timestamps stored UTC; all-day events handled as dates.
- **NFR-COST** Low ongoing cost — self-hosted on existing hardware, local model
  (no per-call fees), no paid messaging at launch. Essentially electricity.
- **NFR-EFFORT** Low-burden setup/operation for a non-professional admin.

---

## 6. Non-goals (at launch)

- Per-user privacy walls / access separation between family members.
- Recurring-event machinery in the calendar (RRULE/exceptions).
- Two-way CalDAV sync (at most deferred `.ics` import/export).
- A no-install text channel (SMS/bot) — deferred.
- Voice assistants / in-app voice capture — deferred.
- Automatic (time-based) archiving; background/scheduled assistant passes.
- Persisted labor **metrics/scores**; any ranking or surveillance of people.
- A **tag-management subsystem** (tags are just strings + a small color map).
- Slick drag-and-drop board interactions day-one.
- Multi-household / multi-tenant.

---

## 7. Open questions

- **OQ-CONFIRM** Confirmation policy fine-tuning for the assistant (when to ask
  vs. act-then-log) — refine during build.
- **OQ-DISP-VIEW** Default calendar view for the wall display (agenda / week /
  month) and time window.
- **OQ-CARD** How much a card shows at a glance (title / checklist progress /
  assignee / due).
- **OQ-DISPLAY-HW** Final wall-display hardware (prototype on existing iPad;
  larger 24–27" display later).
- **OQ-INTEROP-WHEN** When `.ics` import/export lands (later arc).
