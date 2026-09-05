"""Pure server-rendered board and calendar HTML fragments."""

from __future__ import annotations

from html import escape

from app.persistence.models import WORK_ITEM_STATUSES, Event, WorkItem

# Column order = the canonical domain status codes (single source of truth in
# models). Labels are the UI-layer display names, keyed off those codes.
COLUMN_ORDER = list(WORK_ITEM_STATUSES)
COLUMN_LABELS = {
    "todo": "Todo",
    "on_deck": "On deck",
    "doing": "Doing",
    "done": "Done",
}


def _fmt_dt_utc(dt: object) -> str:
    """Minute-precision UTC stamp for a card line, or '' if not a datetime."""
    from datetime import datetime as _dt

    if isinstance(dt, _dt):
        return dt.strftime("%Y-%m-%d %H:%M") + " UTC"
    return ""


def render_board(columns: dict[str, list[WorkItem]]) -> str:
    """Render the read-only 4-column board as an HTML fragment.

    ``columns`` maps each status code to its list of (non-archived) work items.
    Each card shows the full record: id, title, description, tags, due date,
    assignee, and a short update-log summary — a debugging/detail view (task 10).
    """
    parts: list[str] = ['<div class="board" id="board">']
    for code in COLUMN_ORDER:
        items = columns.get(code, [])
        parts.append('<section class="column">')
        parts.append(f"<h2>{escape(COLUMN_LABELS[code])} ({len(items)})</h2>")
        if items:
            parts.append('<ul class="cards">')
            for wi in items:
                parts.append(_render_work_item_card(wi))
            parts.append("</ul>")
        else:
            parts.append('<p class="empty">—</p>')
        parts.append("</section>")
    parts.append("</div>")
    return "".join(parts)


def _render_work_item_card(wi: WorkItem) -> str:
    """One work-item card with full record detail (all free text escaped)."""
    parts: list[str] = ['<li class="card">']
    parts.append('<div class="card-head">')
    parts.append(f'<span class="card-id">#{wi.id}</span>')
    parts.append(f'<span class="card-title">{escape(wi.title)}</span>')
    parts.append("</div>")

    if wi.description:
        parts.append(f'<p class="card-desc">{escape(wi.description)}</p>')

    meta: list[str] = []
    due = _fmt_dt_utc(getattr(wi, "due_at", None))
    if due:
        meta.append(f'<span class="meta due">due {escape(due)}</span>')
    assignee = getattr(wi, "assigned_to", None)
    if assignee is not None:
        meta.append(f'<span class="meta assignee">assignee m{assignee}</span>')
    # Update-log summary: count + latest body snippet (source-tagged).
    updates = getattr(wi, "updates", None) or []
    if updates:
        latest = updates[-1]
        snippet = escape((getattr(latest, "body", "") or "")[:80])
        src = escape(getattr(latest, "source", "") or "")
        meta.append(
            f'<span class="meta log">{len(updates)} update(s); '
            f"latest [{src}]: {snippet}</span>"
        )
    if meta:
        parts.append(f'<div class="card-meta">{"".join(meta)}</div>')

    tags = "".join(f'<span class="tag">{escape(t)}</span>' for t in (wi.tags or []))
    if tags:
        parts.append(f'<div class="card-tags">{tags}</div>')

    parts.append("</li>")
    return "".join(parts)


def _event_when(ev: Event) -> str:
    """A short human-facing time/date line for an event card (skinny render).

    All-day events show their date range as plain dates (no tz — DESIGN §3);
    timed events show the stored UTC start (formatted later; ISO is fine for the
    testing list). Kept deliberately minimal — the UI is improved in a later task.
    """
    if ev.all_day:
        # All-day events always have start_date (enforced at every write path)
        # and end_date (defaulted to start_date). Assert the invariant so the
        # read site is honest to the type checker instead of a silent fallback.
        assert ev.start_date is not None and ev.end_date is not None
        start = ev.start_date.isoformat()
        end = ev.end_date.isoformat()
        span = start if end == start else f"{start} – {end}"
        return f"all-day · {span}"
    # A timed event always has start_at (create_timed_event,
    # reschedule_timed_event, and seeding all require a timing). Assert the
    # invariant rather than carry an unreachable fallback.
    assert ev.start_at is not None
    # Minute precision is enough for a card; drop seconds/microseconds.
    return ev.start_at.strftime("%Y-%m-%d %H:%M") + " UTC"


def render_calendar(
    events: list[Event], member_names: dict[int, str] | None = None
) -> str:
    """Render events as a simple long list of cards (task 11, fuller render).

    Agenda/list only — no grid. Each card shows the id, escaped title, a
    time/date line, and optional description, location, participants, and tags.
    ``events`` is already ordered by the caller. All free text is escaped.
    """
    parts: list[str] = ['<div class="calendar" id="calendar">']
    if events:
        parts.append('<ul class="events">')
        for ev in events:
            parts.append(_render_event_card(ev, member_names))
        parts.append("</ul>")
    else:
        parts.append('<p class="empty">No events.</p>')
    parts.append("</div>")
    return "".join(parts)


def _render_event_card(ev: Event, member_names: dict[int, str] | None = None) -> str:
    """One event card with full record detail (all free text escaped).

    ``member_names`` maps member id → display name so participant member links
    render as names (e.g. "Alex") instead of raw ids ("m1"); falls back to the id
    token when a name isn't provided (the pure renderer has no DB session)."""
    names_map = member_names or {}
    parts: list[str] = ['<li class="event-card">']
    parts.append('<div class="card-head">')
    parts.append(f'<span class="card-id">e{ev.id}</span>')
    parts.append(f'<span class="title">{escape(ev.title)}</span>')
    parts.append(f'<span class="when">{escape(_event_when(ev))}</span>')
    parts.append("</div>")

    if ev.description:
        parts.append(f'<p class="card-desc">{escape(ev.description)}</p>')

    meta: list[str] = []
    if ev.location:
        meta.append(f'<span class="meta loc">@ {escape(ev.location)}</span>')
    participants = getattr(ev, "participants", None) or []
    if participants:
        names = []
        for p in participants:
            if isinstance(p, dict):
                mid = p.get("member_id")
                # Prefer an explicit name, else the resolved member name, else id.
                resolved = names_map.get(mid) if isinstance(mid, int) else None
                label = p.get("name") or resolved or f"m{mid}"
                names.append(str(label))
            else:
                names.append(str(p))
        meta.append(f'<span class="meta parts">with {escape(", ".join(names))}</span>')
    if meta:
        parts.append(f'<div class="card-meta">{"".join(meta)}</div>')

    tags = "".join(
        f'<span class="tag">{escape(t)}</span>'
        for t in (getattr(ev, "tags", None) or [])
    )
    if tags:
        parts.append(f'<div class="card-tags">{tags}</div>')

    parts.append("</li>")
    return "".join(parts)
