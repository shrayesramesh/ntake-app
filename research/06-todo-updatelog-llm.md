# Todo reframe — update-log model, labor visibility, inline LLM

> **⚠ HISTORICAL.** This note *is* where the work-item/update-log reframe was
> worked out — its **thinking is current**, but its naming/IDs are pre-final
> (`todo`, `F-TODO-*`, `REQUIREMENTS_UPDATE.md`). The reconciled, authoritative
> version is **[`../spec/`](../spec/)** (see DESIGN §3–4, REQUIREMENTS `WORKITEM`
> / `ASSIST`). Read this for *why*; build from `spec/`.
>
> **Type: design exploration + decisions.** Reframes the work-item half of the
> product (events unaffected).

## The shift, in one line

A todo is a **loose free-text item with an append-only stream of updates** (like
a SIM ticket, not a rigid Kanban card). Humans write updates in prose; an **LLM
interprets each update inline and proposes** structured changes (status, due
date, calendar impact) that a **human confirms**. Structured Kanban status still
exists but is a **grooming-time snapshot**, and the board is a **~monthly review
tool**, not the daily surface.

## Why the standard Kanban model was wrong here

The earlier model assumed humans maintain structured state (status/position/
due_at) continuously. In reality:
- Daily interaction is **writing items and appending updates**, not dragging cards.
- **Timing is relational** to the calendar, so `due_at` is better *inferred in
  context* than set as an intrinsic field.
- The valuable signal — **who's carrying the household/coordination load** — lives
  in the **free-text update stream**, not in status columns.

## Core purpose added: labor visibility (R4)

The update log makes **emotional/household labor visible for recognition &
fairness** — surfacing the invisible coordination work (following up, chasing
blockers, partial progress), not just completed tasks.

**Guardrail (hard constraint):** visibility & recognition, **not** scoring,
ranking, or surveillance. No leaderboards, no automated judgment of people. The
labor view exists to *credit usually-uncredited work* and prompt fairness. This
framing is why the labor view is **not** a persisted-metrics feature (see below).

## Data model delta

### Keep (from `04-data-layer.md`, adjusted)
- `todos`: `title`, free-text `description`, `status` (fixed 4-col enum:
  todo/on_deck/doing/done), `position`, `assigned_to`, `archived_at`,
  `created_at`, `updated_at`, `completed_at`, `sequence`.
- **`due_at`**: still nullable UTC datetime, but **set only via a confirmed LLM
  suggestion** — not a core human-entered field. No all-day-todo handling needed
  (the problem dissolves when due timing is a proposal). Renders on the calendar
  when set (F-TODO-05 bridge unchanged).

### Add — the only new table
```python
class TodoUpdate(Base):
    __tablename__ = "todo_updates"
    id: Mapped[int] = mapped_column(primary_key=True)
    todo_id: Mapped[int] = mapped_column(ForeignKey("todos.id", ondelete="CASCADE"))
    author: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL"), default=None
    )  # who wrote it / who confirmed the LLM-driven outcome
    body: Mapped[str]                 # free text — human note OR narrated confirmed outcome
    created_at: Mapped[datetime] = mapped_column(default=func.now())
```
- **Append-only. Minimal by design** — update, author, time. **No `update_type`
  / classification column** (would drift toward metrics/surveillance; interpretation
  is transient, done by the LLM on read).
- **Single source of narrative truth:** entries are *either* human-written notes
  *or* records of **confirmed LLM-driven outcomes** (e.g. "set due date Fri;
  linked to dentist event"). The `body` narrates it; `author` = who confirmed.
- *(Deferred, not built:* a single nullable `llm_driven: bool` flag if we ever
  need to distinguish human vs. confirmed-LLM entries. The body carries it for now.)

### Drop
- **No `suggestions` table.** Inline propose-and-confirm means suggestions live in
  the PWA request/response; only confirmed outcomes persist (as a `todo_updates`
  entry + the actual field change). Unconfirmed proposals do not survive the
  interaction.

## The interaction loop (inline LLM, propose-and-confirm)

```
Member types an update in the PWA (free text)
        │
        ▼
LLM (local GPU, in the request path):
   • parse the text (capture role, DESIGN §3)
   • interpret in context (this todo's history + the calendar)
   • produce recommendation(s): blocker / needs-help / multi-step-partial /
     calendar-impact / propose due date
        │
        ▼
PWA shows the update AS SAVED, plus proposed action(s) inline
        │
     human confirms / rejects  ── reject ─► nothing changes (update still saved)
        │ confirm
        ▼
Apply the confirmed change (status / due_at / create-or-update event) AND
append a todo_updates entry narrating the outcome (author = confirmer)
```

Key properties:
- **Per-update, synchronous** — no scheduler, no background analyst. One local
  inference per input. Fits the local-GPU-model reality.
- The **raw update is always saved** regardless of whether the LLM suggestion is
  accepted (the human's prose is the truth; the suggestion is optional value-add).
- **Calendar mutations are always confirmed**, never auto-applied (safety; small
  local model).

## The three views over the same items

1. **Board view (~monthly grooming):** the fixed 4 columns, for prioritizing when
   time is contentious, reviewing workload, celebrating completed (+ manual
   archive of Done, F-TODO-08..11).
2. **Labor view (ongoing, R4):** the LLM reads the **raw update log by author over
   time**, on demand, and surfaces who's carrying/coordinating what — for
   recognition & fairness, **not** ranking. Computed live by the LLM each time; no
   stored metrics. (Conscious tradeoff: simplicity + anti-surveillance over a
   cheap SQL aggregate. Correct at family scale.)
3. **Item + its update history:** the day-to-day — read a task, see its narrative,
   append an update.

## LLM cadence (resolves the earlier open question)

- **Inline, per update, in the PWA request path** — parse + recommend in the same
  interaction (F-LLM-01).
- **On demand** for the monthly board grooming and the labor review (F-LLM-04) —
  "review now," not scheduled.
- **No background/periodic job** anywhere. (Consistent with the manual-archive and
  no-scheduler stances.)

## Consequences / open LLD (not blocking)

- **Prompt design** for the inline interpreter (structured JSON out:
  `{recommendations: [...], proposed_due_at?, proposed_event?}`) — build-time.
- **How proposed calendar changes are represented** to the user for confirmation
  (create vs. update which event) — UI/LLD, Phase 3+.
- The labor view's exact prompt/output (a summary, not scores) — build-time, with
  the R4 guardrail as the constraint.
- Whether the inline LLM call is fast enough in the request path on the local GPU
  — perf validation during Phase 4 (the parser is already a separable service, so
  a rules/fast-path fallback remains available).

## What is unchanged

- The **events** model, the calendar rendering, iCalendar alignment, sync (SSE),
  auth, hosting — all unaffected. This reframe is contained to the **todo half**
  and the **LLM's role**.
