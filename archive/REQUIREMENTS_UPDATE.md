# Requirements — Updates & Additions

> **Purpose:** an **append-only log of requirement changes** made after
> `REQUIREMENTS.md` was frozen. New/changed requirements are recorded here rather
> than editing the base doc, so the original stays stable and every change is
> dated and traceable. IDs continue the base doc's scheme (`F-*`, `NFR-*`,
> `OQ-*`).
>
> When the base doc is eventually reconciled, these fold in and this becomes the
> changelog of how they got there.

---

## 2026-08-30 — Todo board: fixed columns + manual archive

### Resolves OQ-COLS — fixed Kanban columns
- **OQ-COLS → RESOLVED.** The board has a **fixed set of four columns**:
  **Todo / On deck / Doing / Done**. No user-defined columns. (Stored internally
  as stable codes; the labels above are display text — DESIGN/LLD detail in
  `research/04-data-layer.md`.)

### Resolves OQ-DISP-DONE — completed-item handling via manual archive
- **OQ-DISP-DONE → RESOLVED:** completed cards **stay in the Done column** and are
  **manually archived** during a periodic review (not auto-hidden, not
  auto-swept).

### New functional requirements — `F-TODO` (archive)
- **F-TODO-08** A `done` card can be **archived** by an adult: it is removed from
  the active board view but **retained** (not deleted) for history.
- **F-TODO-09** Archiving is a **manual action** tied to a periodic review — the
  system does **not** auto-archive on a timer. A convenience "**archive all Done
  cards**" action is supported for the review moment.
- **F-TODO-10** Only cards in the **Done** column may be archived (archiving
  unfinished work is not allowed).
- **F-TODO-11** An archived card can be **unarchived** (restored to the board).

*Rationale:* keeps the Done column meaningful between reviews, gives a deliberate
"clean the board" moment, and preserves history (no data loss) — consistent with
the family-scale, low-ceremony design. Manual-only avoids adding any scheduler /
background-job infrastructure.

*Non-goal (for now):* automatic time-based archiving (e.g. "auto-archive Done
cards older than N days"). The data model leaves room for it (`archived_at`
exists), but it would require a scheduled job and is deliberately deferred.

*Design/LLD:* `todos.archived_at` timestamp (nullable), board view filters
`archived_at IS NULL`, `completed_at` kept distinct from `archived_at`. See
`research/04-data-layer.md`.

---

## 2026-08-30 — Reframe: update-log todos, labor visibility, inline LLM

This is a substantive reframe of the todo half of the product and the LLM's role.
It supersedes parts of the standard-Kanban framing in the base doc. Events are
unaffected.

### New core purpose — `R4` (labor visibility)

- **R4 — Make household/emotional labor visible for recognition & fairness.** A
  core purpose of the system is to surface *who is carrying the load* around the
  house — including the invisible coordination work (following up, chasing
  blockers, partial progress), not just completed tasks.
- **Framing guardrail (required, not optional):** this is **visibility and
  recognition, not scoring, ranking, or surveillance.** The system must not
  produce leaderboards or automated judgments of people. It surfaces contribution
  to prompt fairness and celebrate effort. This framing constrains all
  labor-related features.

### Todo model reframe — item + append-only update log

- **F-TODO-12 — Free-text items.** A todo is primarily a **title + free-text
  description**, deliberately loose (closer to a ticket than a rigid card).
- **F-TODO-13 — Append-only update log (primary daily interaction).** Family
  members **append free-text updates** to a todo over time (like ticket
  comments). Each update records **the update text, its author, and when** — the
  minimal set, intentionally no metadata taxonomy. This log is the **living
  source of truth** for a task's real state.
- **F-TODO-14 — The log also records LLM-driven outcomes.** When a human confirms
  an LLM-proposed change (see F-LLM-*), the resulting change is **recorded as an
  entry in the same update log**, so the log is the single narrative of
  everything that happened — human-written notes and confirmed LLM actions alike.
- **Structured status retained** (Todo / On deck / Doing / Done, per prior entry)
  but is a **grooming-time snapshot**, not live truth. The update log is live
  truth; status is adjusted during review or by confirming an LLM suggestion.
- **"Blocked / needs help / partial" are NOT columns** — they are surfaced by the
  LLM from the update log when relevant, keeping the four columns clean.

### Board & labor are distinct views (F-DISP / R4)

- **F-TODO-15 — Board view is a periodic grooming instrument (~monthly),** not a
  daily driver. Its jobs: **prioritize** when time is contentious, **review
  workload**, and **celebrate completed** work (ties to the manual-archive review
  moment, F-TODO-08..11).
- **F-TODO-16 — Labor view.** A view over the **raw update log by author over
  time** that makes household/coordination labor visible (R4). Computed **on
  demand by the LLM reading the raw updates** — deliberately **not** a persisted
  metrics/scoring layer (keeps the model simple and avoids metrics-drift toward
  surveillance).

### `due_at` becomes inferred, not core

- **F-TODO-17 — Due dates are LLM-inferred and human-confirmed, not a core
  human-set field.** A task's timing is **relational to the calendar** ("when
  should I do this given everything else on?"), so the LLM *proposes* a due date
  in calendar context and a human confirms. Once confirmed, it is stored and
  renders on the calendar (F-TODO-05 bridge still holds). No all-day-todo
  handling needed (the problem dissolves when due timing is a proposal, not a
  required field).

### LLM role & cadence — `F-LLM` (expands DESIGN §3 capture-time triage)

- **F-LLM-01 — Inline interpretation at input.** When a member enters an update
  (typed in the PWA, or via a future text channel), the LLM **both** parses the
  inbound text **and** produces recommendations **in the same interaction**,
  returned into the PWA. No background/scheduled analyst pass.
- **F-LLM-02 — Propose-and-confirm (safety).** The LLM **never auto-applies**
  changes. It proposes; a human accepts/rejects inline. Especially for calendar
  mutations. Confirmed outcomes are applied and logged (F-TODO-14).
- **F-LLM-03 — Recommendation types (illustrative, not a stored taxonomy).** The
  LLM may surface: (a) needs more info / **blocker**, (b) **request for help**,
  (c) task became **multi-step / partial progress**, (d) a **calendar event this
  impacts** (propose creating/updating an event). These are transient
  interpretations shown at input time, not persisted classifications.
- **F-LLM-04 — On-demand grooming/labor review.** The monthly board grooming and
  the labor view (R4) are run **on demand** ("review now"), not on a schedule —
  the LLM reads the update histories at that moment.

### Model simplifications adopted (no bloat)

- **No `suggestions` table.** With inline propose-and-confirm, suggestions live in
  the PWA request/response; only **confirmed outcomes** are stored (as an update
  log entry). Unconfirmed suggestions do not persist.
- **`todo_updates` is the only new table:** `{id, todo_id, author, body,
  created_at}` — append-only, minimal, no type/metadata columns. (A single
  nullable "LLM-driven?" flag is a possible future addition but is **deliberately
  not built now**; the body narrates the outcome.)

### Superseded / non-goals

- Supersedes the standard-Kanban assumption that humans set status/due_at as core
  structured input, and the passive "due_at reflects on calendar" being a
  human-entered field.
- **Non-goals:** persisted labor metrics/scores, background/scheduled LLM passes,
  a separate suggestions/audit table, automatic (non-confirmed) calendar
  mutations.

*Design/LLD:* see `research/06-todo-updatelog-llm.md`.
