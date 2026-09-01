# Family Calendar + Todo Board — Requirements

> **Status:** Draft, in progress. Split from the original combined DESIGN.md on
> 2026-08-30.
>
> This document describes **what** the app must do and **for whom** — the users,
> the consumption model, the functional capabilities, and the non-functional
> qualities it must have. It is intentionally **solution-neutral**: it should
> survive a change of implementation. Decisions about *how* (providers, hosting,
> schemas, data flows) live in [DESIGN.md](./DESIGN.md).
>
> **Rule of thumb for what belongs here:** if changing a statement would mean
> building a *different product*, it's a requirement (here). If it could
> reasonably change during implementation without changing what the product
> *is*, it's a design decision (DESIGN.md).
>
> **Traceability:** requirements carry stable IDs (`R-*` high-level, `F-*`
> functional, `NFR-*` non-functional). The design doc references these IDs
> rather than restating them, so we can spot "required but not designed" and
> "designed but not required" gaps.

---

## 1. Purpose & Core Value

A shared calendar and todo-list board for a single household. Family members
capture events and tasks from their own devices, and everything stays in sync so
the whole household sees one consistent, up-to-date view.

**Core value:** low-friction capture ("dentist Tuesday at 3", "add milk to the
grocery list") from wherever a family member is, reflected everywhere quickly —
and a shared, glanceable display of the family's calendar and todos.

### High-level requirements

- **R1 — iCalendar-compatible events.** Events must be **ICS/iCalendar
  (RFC 5545) compatible** so they can be rendered in / exported to standard
  calendar apps (Apple Calendar, Google Calendar, Outlook). *(Interop delivery
  — export/import — may be phased; see F-ICS and DESIGN §5.4.)*
- **R2 — Quick capture from a personal phone.** A family member must be able to
  capture an event or todo quickly from their own phone. *(Channel resolved to
  **PWA-first**; a text channel is a deferred later phase — see §3.1, F-CAP.)*
- **R3 — Shared family visibility.** All members see one shared family calendar
  and todo board.

---

## 2. Users & Personas

**Scale:** small, trusted household — 2–4 people.

**Personas:**

- **Primary adults** (e.g. two parents) — full access. Create/edit/delete any
  event or todo, and manage members and settings.
- **Children** *(possible future, not day-one)* — limited access: view, and add
  their own todos; cannot delete others' items. Designed for, not built
  initially.

**Trust model:** low-adversarial. Shared visibility is the default — everyone
sees the family calendar and board. No strict per-user privacy walls at launch,
though the door is kept open for per-item visibility later.

**Roles (initial):**

| Role | Calendar | Todo Board | Admin |
|---|---|---|---|
| Adult | Full CRUD | Full CRUD | Manage members / settings |
| Child *(future)* | View (+ maybe own events) | View + add own | None |

---

## 3. Consumption Model — How & Where It's Used

The app is consumed through two distinct surfaces with different jobs. Keeping
them distinct matters, because a channel that is great for one job is often poor
for the other.

### 3.1 Capture (input)

Quick, low-friction entry of events and todos from a family member's own phone,
wherever they are. Capture is about *getting an intent in fast* — "dentist
Tuesday 3pm", "add milk to groceries" — not about browsing or managing.

**Decision (OQ-CAP resolved): PWA-first.** The primary capture *and* management
surface is a **Progressive Web App** — the same web artifact as the shared
display (§3.2), opened on phones. Rationale:

- **Structured input** (tap a card, pick a date, choose from existing cards)
  sidesteps most free-text parsing *and* most of the entity-resolution problem —
  the user selects the target rather than the system guessing which "groceries"
  they meant.
- **One codebase** serves the wall display and phones.
- **No per-message cost, no A2P registration, no stateless-channel confirmation
  machinery** on day one.
- Fits the home-hosted, privacy-preserving direction (§ hosting in DESIGN).

Tradeoff accepted: each member opens the PWA / adds it to their home screen once
(mild friction), and it needs per-user identity; it doesn't serve the
borrowed-phone/guest case. That's acceptable at family scale.

**Deferred: a lightweight text channel (SMS or similar).** No-install messaging
remains attractive for *one-line-on-the-go* capture and is kept as a **later
phase**, not day-one. Its full design is retained in DESIGN §2. When revisited,
the choice includes SMS (universal, but paid + A2P + stateless) vs. a bot channel
like Telegram (free, tappable buttons, but requires that app).

*(A text channel is capture-only; the PWA remains the management surface
regardless.)*

### 3.2 Shared display (output)

A single, always-on, **glanceable shared display** — e.g. a wall-mounted tablet
in a common area — showing the family calendar and todo board side by side. This
is a **read-heavy shared view**, not a per-user interactive app:

- Legible from across the room.
- Always-on; updates without manual refresh as new items arrive.
- One shared family view — no per-person login at the display; authenticated
  once at setup.

*Future surfaces (not now):* phones may later get a more interactive
per-user view. See F-CAP / OQ-CAP.

---

## 4. Functional Requirements

Grouped by capability. Each includes concrete example scenarios. Requirement
statements are solution-neutral; example scenarios may name a channel for
concreteness but the requirement does not depend on it.

### 4.1 Capture — `F-CAP`

- **F-CAP-01** A family member can capture a **new event** from their phone
  using natural language.
  *Example:* an adult sends/enters "dentist Tuesday 3pm" and a dentist event is
  created for the next Tuesday at 15:00.
- **F-CAP-02** A family member can capture a **new todo** from their phone.
  *Example:* "add task buy tickets" creates a "buy tickets" card in the To Do
  column.
- **F-CAP-03** A family member can **add an item to an existing todo's
  checklist**.
  *Example:* "add milk to groceries" appends "milk" to the checklist on the
  "Groceries" card (creating the card if it doesn't exist).
- **F-CAP-04** Capture must accept **natural, unstructured phrasing** and resolve
  relative dates/times ("next Friday", "tomorrow 3pm") to concrete times.
  *(In the PWA-first design, much capture uses structured input — date pickers,
  card selection — so free-text parsing is a secondary path, not the only one.
  It becomes primary again if/when the deferred text channel ships.)*
- **F-CAP-05** When a capture is **ambiguous or unparseable**, the system
  responds asking the member to clarify, rather than failing silently or
  guessing.
- **F-CAP-06** The member receives **confirmation** that a capture succeeded.
  *(Whether confirmation is always sent or only on ambiguity/failure is an open
  question — OQ-CAP-CONF.)*

*Open questions:* OQ-CAP-CONF (confirmation policy), OQ-CAP-QUERY (is read-back
part of first release). *(OQ-CAP — capture channel — resolved to PWA-first,
§3.1.)*

### 4.2 Query / read-back — `F-QRY`

- **F-QRY-01** A family member can **ask what's scheduled** and get a reply.
  *Example:* "what's on today?" returns today's events (and due todos).
- **F-QRY-02** A family member can **ask what todos are outstanding**.
  *Example:* "what's left?" returns open cards.

*Open question:* OQ-CAP-QUERY — whether query/read-back ships in v1 or later.

### 4.3 Manage events — `F-EVT`

- **F-EVT-01** An adult can **create, read, update, and delete** any event.
- **F-EVT-02** Update includes **rescheduling** (change date/time) and editing
  title/details.
  *Example:* "move dentist to Friday 4pm" reschedules the matching event.
- **F-EVT-03** Deleting/cancelling an event is supported but treated as a
  **destructive operation** subject to safeguards (see F-SAFE).
  *Example:* "cancel dentist" removes the event, subject to confirmation/policy.
- **F-EVT-04** Events support **recurrence** (e.g. weekly chores, birthdays).
  *(How much recurrence — simple repeats vs. per-instance exceptions — is an
  open question; see OQ-RECUR.)*

### 4.4 Manage todos (single shared board) — `F-TODO`

The household shares **one todo board** (this is a product-level decision, not
just an implementation detail: there are no multiple named lists). A card *is* a
task; a card can itself hold a **checklist** (e.g. a "Groceries" card whose items
are milk, eggs, bread).

- **F-TODO-01** An adult can **create, read, update, and delete** todo cards.
- **F-TODO-02** A card moves through **workflow columns** (e.g. To Do / Doing /
  Done — labels TBD, OQ-COLS).
  *Example:* "move groceries to done" moves the card to the Done column.
- **F-TODO-03** A card can be **marked complete**.
  *Example:* "done with dentist" marks/moves the matching card done.
- **F-TODO-04** A card can hold a **checklist**; items can be added, checked, and
  unchecked.
- **F-TODO-05** A todo can have a **due date**, which makes it appear on the
  calendar alongside events (the calendar/board bridge).
- **F-TODO-06** A card can be **assigned** to a family member. *(Optional field;
  assignment enforcement is not required at launch.)*
- **F-TODO-07** Deleting a card or checklist item is a **destructive operation**
  subject to safeguards (see F-SAFE).

### 4.5 Shared display — `F-DISP`

- **F-DISP-01** The display shows the **calendar and todo board simultaneously**,
  legibly from a distance.
- **F-DISP-02** The display **updates automatically** as items are added/changed
  from any source, without manual refresh (see NFR-SYNC).
- **F-DISP-03** The display presents **one shared family view** with no per-user
  login during normal use.
- **F-DISP-04** The display runs **always-on** for long periods and must remain
  correct and stable across screen sleep/wake and days of uptime (see
  NFR-UPTIME).
- **F-DISP-05** **Decided: read-mostly.** At launch the display (and the phone
  PWA) are **read-mostly** — live-updating views with **simple tap/form
  mutations** (check a checklist item, move a card via a control, add via a
  form). No slick drag-and-drop day-one (deferred; OQ-DISP-INT). This keeps the
  build simple and lets the frontend stay a light HTML/HTMX layer (DESIGN §6).

*Open questions:* OQ-DISP-VIEW (default calendar view), OQ-DISP-CARD (card face
detail), OQ-DISP-DONE (completed-item handling), OQ-DISP-SORT (sort within
column). *(OQ-DISP-INT — interactivity depth — resolved to read-mostly for
launch; drag-and-drop deferred.)*

### 4.6 Member & device management — `F-MEMBER`

- **F-MEMBER-01** An admin (adult) can **add and remove family members**
  (name, role, contact info).
- **F-MEMBER-02** Only an admin can manage members and **enroll devices**; there
  is **no self-enrollment**.
- **F-MEMBER-03** A member gains access by being **enrolled on a device**, which
  provisions a per-device credential (see F-AUTH). Adding a member and enrolling
  their device is what grants access — not their phone number.

### 4.7 Setup / bootstrap — `F-SETUP`

- **F-SETUP-01** There is a defined way to **create the household** and its
  **first admin** (bootstrapping) before any members or data exist.
- **F-SETUP-02** There is a defined way to **enroll the shared display once at
  setup** as a low-privilege identity (F-DISP-03, F-AUTH).

### 4.8 Identity & authentication — `F-AUTH`

*(Resolved this session; design in DESIGN §1.4.)*

- **F-AUTH-01** Each device is **enrolled by an admin** and provisioned with a
  **per-device credential** (an unguessable secret token), carried on every
  request; the system maps it to a member and role.
- **F-AUTH-02** Credentials must **not be self-assertable** — a member must not
  be able to impersonate another or elevate their own role by editing a client
  value. (Drives the "credential, not a claim" design decision.)
- **F-AUTH-03** A lost/retired device's access can be **revoked**.
- **F-AUTH-04** The shared display authenticates by the **same mechanism** as
  phones, holding a low-privilege (read-mostly) identity.

### 4.9 Safeguards on destructive actions — `F-SAFE`

- **F-SAFE-01** Every request must be **authenticated and access-controlled**;
  unauthenticated or unreachable callers get nothing and no data is disclosed.
  *(The mechanism — device token + private-network trust — is F-AUTH / DESIGN
  §1.4, not restated here.)*
- **F-SAFE-02** **Destructive operations** (delete/cancel, destructive updates)
  are **gated** — by explicit confirmation and/or by restricting to adult role.
  The exact gate is an open question (OQ-DEL-POLICY). *(In the PWA, confirmation
  is a UI dialog — no stateless-channel machinery needed; that only returns with
  the deferred text channel.)*

### 4.10 Calendar interoperability — `F-ICS`

- **F-ICS-01** Because events are iCalendar-compatible (R1), the family calendar
  can be **exported / subscribed to** from standard calendar apps.
- **F-ICS-02** The system can **import** `.ics` events/invites. *(Likely later
  than export.)*

*Open questions:* OQ-ICS-PRIORITY (is export in v1 or a later arc),
OQ-ICS-DIRECTION (export-only vs. two-way sync). See DESIGN §5.4.

---

## 5. Non-Functional Requirements

These are quality attributes the product must have regardless of implementation.
Several are **new** relative to the original doc and are flagged as follow-on
gaps to run down this session.

- **NFR-PRIVACY** Family messages and data should stay within the household's
  trust boundary. **Satisfied by design:** home-hosted backend + database and a
  **local (self-hosted) parsing model** mean family data and message text do not
  leave owned hardware. *(See DESIGN §1, §3.)*
- **NFR-SYNC** An item added on one surface appears on the others **quickly**.
  The target latency (near-real-time "live" vs. "next time you open it") is an
  open question — OQ-SYNC-LATENCY — but the shared display (F-DISP-02) implies a
  live-update expectation. *(Follow-on gap G3.)*
- **NFR-UPTIME / availability** Capture and display should be **available when a
  family member needs them**. **Launch posture:** the app runs on a single
  always-on home PC, so availability equals that machine's uptime; this is an
  accepted simplification to ship. Home internet/power outages take the system
  down — an accepted risk at family scale. *(A two-tier always-on split is the
  planned future mitigation — see DESIGN §1. Concrete SLO still undefined,
  OQ-AVAIL.)*
- **NFR-DURABILITY** Family calendar/todo data must be **protected against loss**
  (e.g. disk failure). **Day-one minimum required:** an automated **off-machine
  backup** (e.g. a nightly copy of the database file/dump to a separate
  disk/location). This is a launch requirement, not deferrable — it is the one
  gap whose failure mode (disk failure with no backup) is **irreversible total
  loss**. Fuller strategy (retention, restore testing, encryption) is LLD.
- **NFR-TIME** Dates/times must be **correct across timezones and DST**. **Day-one
  requirement:** the system stores a **household timezone** (a
  `families.timezone` field, DESIGN §4.3) and stores timestamps in UTC — without
  it the first "Tuesday 3pm" capture (F-CAP-04) cannot be resolved, so it is
  **not deferrable**. Recurrence/DST *depth* (per-instance exceptions) remains
  LLD (OQ-RECUR).
- **NFR-COST** Running the system should have **low ongoing cost** appropriate to
  a family. **Launch posture is near-zero ongoing cost:** self-hosted on existing
  home hardware, local model (no per-call LLM fees), no paid messaging channel
  (SMS deferred). Ongoing cost is essentially electricity. *(Per-message fees
  re-enter only if the deferred SMS channel ships; interacts with OQ-CAP-CONF.)*
- **NFR-EFFORT** Setup and ongoing operation should be **low-burden** for a
  non-professional household admin (e.g. one-time registration is acceptable;
  ongoing manual maintenance is not).

---

## 6. Non-Goals / Out of Scope (at launch)

- Per-user privacy walls / strict access separation between family members.
- Rich media / MMS capture, interactive message buttons, group message threads.
- Hands-free voice assistants (e.g. Alexa) and in-app voice capture — deferred;
  revisit after the primary capture channel ships.
- Multi-household / multi-tenant support — this is a single-family system.
- Children's restricted role **enforcement** — the role may exist in the model,
  but enforced child access is not built day-one.
- Full two-way CalDAV sync — at most export/subscribe initially (F-ICS,
  OQ-ICS-DIRECTION).

---

## 7. Open Questions (requirements-level)

Design-level open questions (providers, topology, schemas, transport) live in
DESIGN.md; these are the *what/for-whom* questions.

- [x] **OQ-CAP** — Primary capture channel. **RESOLVED: PWA-first** (same web
      artifact as the display, opened on phones; structured input). A no-install
      text channel (SMS or a bot like Telegram) is **deferred to a later phase**.
      See §3.1; SMS design retained in DESIGN §2.
- [ ] **OQ-CAP-CONF** — Confirmation policy: always confirm, or only on
      ambiguity/failure (interacts with NFR-COST)?
- [ ] **OQ-CAP-QUERY** — Does query/read-back (F-QRY) ship in the first release?
- [ ] **OQ-DEL-POLICY** — How are destructive actions gated (confirmation reply,
      adult-only, app/phones-only)?
- [ ] **OQ-COLS** — Todo board column names (To Do / Doing / Done vs.
      family-friendlier labels)?
- [ ] **OQ-DISP-VIEW** — Default calendar view for the display (agenda / week /
      month) and time window?
- [ ] **OQ-DISP-INT** — Is the shared display interactive or read-only?
- [ ] **OQ-DISP-CARD** — How much detail on a card face (title only vs. +
      checklist progress / assignee / due date)?
- [ ] **OQ-DISP-DONE** — Completed-item handling (hide / keep in Done / "done
      today" then archive)?
- [ ] **OQ-DISP-SORT** — Sort within a column (manual / due date / priority)?
- [ ] **OQ-RECUR** — Recurrence depth (simple repeats vs. per-instance
      exceptions)?
- [ ] **OQ-ICS-PRIORITY** — Is `.ics` export part of v1 or a later arc?
- [ ] **OQ-ICS-DIRECTION** — Export-only vs. two-way sync?
- [~] **OQ-SYNC-LATENCY** — Direction resolved to **live push (SSE)**, DESIGN
      §5.4; a precise numeric target is not formalized (fine at family scale).
- [ ] **OQ-AVAIL** — What availability is expected for capture and display?
- [ ] **OQ-DEVICES** — Device mix (iOS/Android) and whether a shared tablet /
      kitchen display is in scope as a specific target.

---

## 8. Follow-on Gaps — Status

Connective-tissue gaps surfaced during the split. **All HLD-level questions are
now resolved**; remaining items are LLD (implementation detail that fits the
current architecture without reshaping it). Requirement-level framing lives here;
design mechanics are in DESIGN.md.

- [~] **G0 — Setup / bootstrap flow.** *Identity/auth HLD **RESOLVED*** —
      per-device credentialed token, admin-enrolled (F-AUTH; DESIGN §1.4). The
      first-admin bootstrap + token-delivery mechanics remain **LLD** (F-SETUP).
- [~] **G1 — Member/device-management surface.** *Decided:* it's an **adult-only
      admin area in the PWA** (add/remove members, enroll/revoke devices,
      F-MEMBER/F-AUTH). Screen design is **LLD**.
- [x] **G2 — Capture-channel decision (OQ-CAP).** **RESOLVED: PWA-first**, text
      channel deferred (§3.1). Shrinks G6 (no stateless-SMS confirmation day-one)
      and G7 (structured input reduces free-text entity resolution).
- [~] **G3 — Sync mechanism.** *RESOLVED* — **always-connected clients + SSE**
      transport (server→client push, auto-reconnect; DESIGN §5.4). Only event
      granularity + reconnect-replay remain **LLD**.
- [~] **G4 — Durability / backup (NFR-DURABILITY).** *Day-one minimum now
      **required**:* automated **off-machine backup** (nightly DB copy/dump) —
      the one gap whose failure is irreversible. Retention/restore-testing detail
      is LLD; the *mechanism* follows the datastore-engine choice.
- [~] **G5 — Timezone & DST (NFR-TIME).** *Day-one hook now **required**:*
      `families.timezone` must exist at launch (F-CAP-04 needs it to resolve
      "Tuesday 3pm"). DST/recurrence *depth* stays LLD (OQ-RECUR).
- [ ] **G6 — Stateful conversation model.** **Parked** — dissolved by PWA-first
      (UI dialog confirms). Lives in DESIGN-sms-deferred.md; returns only if the
      text channel ships.
- [ ] **G7 — Entity resolution.** **Parked** — dissolved by PWA structured input
      (tap the target). Lives in DESIGN-sms-deferred.md; returns with the text
      channel.

*Also LLD / open (scope, not architecture):* recurrence depth (OQ-RECUR), UID
minting, idempotency, concurrent-edit policy (resolved last-write-wins,
DESIGN §5.3), `.ics` priority/direction, and the display view/card/sort questions
(OQ-DISP-*).

---

## Change Log

- **2026-08-30** — **Split from the original combined DESIGN.md.** Extracted the
  *what/for-whom* content into this Requirements doc; added traceability IDs
  (`R-*`/`F-*`/`NFR-*`), a solution-neutral **Consumption Model** (§3) separating
  capture from display, reframed capture as channel-neutral with **OQ-CAP**
  (SMS vs. skinny app vs. both) held open, and added previously-implicit
  requirements (F-MEMBER member management, F-SETUP setup/bootstrap) plus
  non-functional requirements (sync, uptime, durability, timezone, cost, effort).
  Recorded connective-tissue **follow-on gaps G0–G7** (§8) to run down this
  session. Implementation content moved to DESIGN.md.
- **2026-08-30** — **Resolved OQ-CAP / G2: PWA-first capture & management**; a
  no-install text channel (SMS/Telegram) deferred to a later phase (§3.1).
  Updated R2, F-CAP-04. Reconciled NFRs to the chosen home-hosted posture:
  NFR-PRIVACY now *satisfied by design* (home-hosted + local model), NFR-COST
  near-zero at launch (self-hosted, local model, no paid messaging), NFR-UPTIME
  set to the **single always-on home-PC** launch posture with the two-tier split
  as a documented future mitigation (DESIGN §1).
- **2026-08-30** — **Resolved the identity/auth HLD (G0).** Added **F-AUTH**
  (per-device credentialed token, admin-enrolled, non-self-assertable,
  revocable; display uses the same mechanism at low privilege). Reworked
  **F-MEMBER** to member+device enrollment and **F-SAFE-01** to token +
  private-network trust (dropped the phone-number allowlist framing at launch —
  it belonged to the deferred SMS channel). Renumbered F-ICS → §4.10. Resolved
  the **G3 sync HLD** (always-connected, no offline queue). Updated §8 gap
  statuses: **all HLD questions now resolved; remainder are LLD** (G0/G1/G3
  reduced to implementation detail; G6/G7 parked under PWA-first).
- **2026-08-30** — **Review pass: promoted two day-one requirements and tightened
  auth framing.** (1) **NFR-DURABILITY** now mandates a **day-one off-machine
  backup minimum** (the one irreversible-loss gap), fuller strategy LLD. (2)
  **NFR-TIME** now mandates `families.timezone` **at launch** (F-CAP-04 needs it),
  DST/recurrence depth LLD — corrected the earlier "fully LLD/deferrable" framing.
  (3) Trimmed **F-SAFE-01** to the pure "requests must be authenticated"
  requirement, letting F-AUTH own the mechanism (removed the near-duplicate).
  Updated G4/G5 status accordingly. Companion DESIGN changes: extracted the
  deferred text channel to DESIGN-sms-deferred.md, reframed the device token as
  intra-family role/attribution (Tailscale = perimeter), and decided
  concurrent-edit = last-write-wins.
- **2026-08-30** — **Resolved OQ-DISP-INT: read-mostly at launch** (F-DISP-05) —
  live views with simple tap/form mutations; drag-and-drop deferred. This
  settled the implementation stack (DESIGN §1.1): FastAPI/Python + HTMX/light-JS
  + SQLite, with a clean JSON/SSE API as the escape hatch to a richer TS/React
  view later. Also recorded the SSE sync-transport decision (DESIGN §5.4) in the
  G3 status / OQ-SYNC-LATENCY.
