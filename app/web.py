"""Thin HTMX front end — dependency-free HTML rendering (Phase 3, task 6).

No templating dependency yet: the shell page is a static string and the board
fragment is built server-side with escaping. Two surfaces:

  * ``GET /``           — the shell: token entry + free-text capture (the ONLY
    write control) + a board container that HTMX loads and SSE refreshes.
  * ``GET /board/view`` — the read-only 4-column board as an HTML fragment.

Updates are NOT a manual UI action — they flow through the Phase 4 LLM capture
loop. Token handling is client-side: the pasted token lives in localStorage,
sent as an Authorization header on HTMX requests and as ``?token=`` on the SSE
URL (EventSource can't set headers). This grows into the Phase 4 inline
Confirm/Dismiss card surface (the capture response will carry proposals).
"""

from __future__ import annotations

from html import escape

from app.models import Event, WorkItem

# Display labels for the fixed status codes (UI-layer, per DESIGN §3).
COLUMN_LABELS = {
    "todo": "Todo",
    "on_deck": "On deck",
    "doing": "Doing",
    "done": "Done",
}
COLUMN_ORDER = ["todo", "on_deck", "doing", "done"]


def render_board(columns: dict[str, list[WorkItem]]) -> str:
    """Render the read-only 4-column board as an HTML fragment.

    ``columns`` maps each status code to its list of (non-archived) work items.
    """
    parts: list[str] = ['<div class="board" id="board">']
    for code in COLUMN_ORDER:
        items = columns.get(code, [])
        parts.append('<section class="column">')
        parts.append(f"<h2>{escape(COLUMN_LABELS[code])} ({len(items)})</h2>")
        if items:
            parts.append('<ul class="cards">')
            for wi in items:
                title = escape(wi.title)
                tags = "".join(
                    f'<span class="tag">{escape(t)}</span>' for t in (wi.tags or [])
                )
                parts.append(f'<li class="card">{title}{tags}</li>')
            parts.append("</ul>")
        else:
            parts.append('<p class="empty">—</p>')
        parts.append("</section>")
    parts.append("</div>")
    return "".join(parts)


def _event_when(ev: Event) -> str:
    """A short human-facing time/date line for an event card (skinny render).

    All-day events show their date range as plain dates (no tz — DESIGN §3);
    timed events show the stored UTC start (formatted later; ISO is fine for the
    testing list). Kept deliberately minimal — the UI is improved in a later task.
    """
    if ev.all_day:
        start = ev.start_date.isoformat() if ev.start_date else "?"
        end = ev.end_date.isoformat() if ev.end_date else start
        span = start if end == start else f"{start} – {end}"
        return f"all-day · {span}"
    if ev.start_at is not None:
        # Minute precision is enough for a card; drop seconds/microseconds.
        return ev.start_at.strftime("%Y-%m-%d %H:%M") + " UTC"
    return "unscheduled"


def render_calendar(events: list[Event]) -> str:
    """Render events as a simple long list of cards (task 11, skinny render).

    Agenda/list only — no grid. Each card shows the escaped title, a time/date
    line, and optional tag chips. ``events`` is already ordered by the caller.
    Titles/locations are escaped (untrusted free text).
    """
    parts: list[str] = ['<div class="calendar" id="calendar">']
    if events:
        parts.append('<ul class="events">')
        for ev in events:
            title = escape(ev.title)
            when = escape(_event_when(ev))
            location = (
                f'<span class="loc">@ {escape(ev.location)}</span>'
                if ev.location
                else ""
            )
            tags = "".join(
                f'<span class="tag">{escape(t)}</span>'
                for t in (getattr(ev, "tags", None) or [])
            )
            parts.append(
                '<li class="event-card">'
                f'<span class="title">{title}</span>'
                f'<span class="when">{when}</span>'
                f"{location}{tags}"
                "</li>"
            )
        parts.append("</ul>")
    else:
        parts.append('<p class="empty">No events.</p>')
    parts.append("</div>")
    return "".join(parts)


# The capture form is the only write control; it POSTs free text to /work-items
# (the text becomes the item title for now — the Phase 4 assistant will split it).
SHELL_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Family Board</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; padding: 1rem; }
    .board { display: flex; gap: .75rem; align-items: flex-start; }
    .column { flex: 1; background: #f4f4f5; border-radius: 8px; padding: .5rem; }
    .column h2 { font-size: .9rem; margin: .25rem 0 .5rem; }
    .cards { list-style: none; margin: 0; padding: 0; }
    .card { background: #fff; border-radius: 6px; padding: .5rem; margin-bottom: .5rem;
            box-shadow: 0 1px 2px rgba(0,0,0,.08); }
    .tag { display: inline-block; font-size: .7rem; background: #e0e7ff;
           border-radius: 4px; padding: 0 .35rem; margin-left: .35rem; }
    .empty { color: #a1a1aa; text-align: center; }
    .calendar { margin-top: 1rem; }
    .calendar .events { list-style: none; margin: 0; padding: 0; }
    .event-card { background: #fff; border: 1px solid #e4e4e7; border-radius: 6px;
                  padding: .5rem .6rem; margin-bottom: .4rem; display: flex;
                  gap: .5rem; align-items: baseline; flex-wrap: wrap; }
    .event-card .title { font-weight: 600; }
    .event-card .when { font-size: .8rem; color: #52525b; }
    .event-card .loc { font-size: .8rem; color: #6b7280; }
    #capture { display: flex; gap: .5rem; margin-bottom: .5rem; }
    #capture input { flex: 1; padding: .5rem; font-size: 1rem; }
    #token-bar { margin-bottom: 1rem; font-size: .85rem; color: #52525b; }
    #proposals { margin-bottom: 1rem; }
    .proposal { display: flex; align-items: center; gap: .5rem; background: #eff6ff;
                border: 1px solid #bfdbfe; border-radius: 6px; padding: .4rem .6rem;
                margin-bottom: .4rem; }
    .proposal .proposal-body { flex: 1; }
    .proposal .action-summary { font-size: .9rem; font-weight: 600; }
    .proposal .rationale { font-size: .78rem; color: #6b7280; font-style: italic;
                           margin-top: .15rem; }
    .proposal button { font-size: .8rem; padding: .2rem .6rem; }
    .proposal .confirm { background: #2563eb; color: #fff; border: none;
                         border-radius: 4px; }
    .proposal .dismiss { background: transparent; border: none; color: #6b7280; }
  </style>
</head>
<body>
  <div id="token-bar">
    <label>Device token:
      <input id="token" type="password" size="24" placeholder="paste token">
    </label>
    <button onclick="saveToken()">Save</button>
    <span id="token-status"></span>
  </div>

  <form id="capture" onsubmit="return onCapture(event)">
    <input id="capture-text" placeholder="Capture a note, task, or plan…" required>
    <button type="submit">Capture</button>
  </form>

  <!-- Assistant proposals render here, on the author's device only. -->
  <div id="proposals"></div>

  <div id="board-container">Enter your device token to load the board.</div>

  <h2 style="font-size:1rem;margin:1rem 0 .5rem;">Calendar</h2>
  <div id="calendar-container">Enter your device token to load the calendar.</div>

  <script>
    function getToken() { return localStorage.getItem('ntake_token') || ''; }
    function authHeaders(json) {
      const h = { 'Authorization': 'Bearer ' + getToken() };
      if (json) h['Content-Type'] = 'application/json';
      return h;
    }
    function saveToken() {
      const t = document.getElementById('token').value.trim();
      if (t) { localStorage.setItem('ntake_token', t);
               document.getElementById('token-status').textContent = 'saved';
               startSSE(); reloadBoard(); reloadCalendar(); }
    }

    // Capture: POST free text to /capture (JSON) -> {item, proposals}. Save the
    // raw input (server-side), then render inline Confirm/Dismiss cards here.
    function onCapture(event) {
      event.preventDefault();
      const input = document.getElementById('capture-text');
      const text = input.value.trim();
      if (!text || !getToken()) return false;
      fetch('/capture', {
        method: 'POST', headers: authHeaders(true),
        body: JSON.stringify({ text: text })
      })
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(data => { input.value = ''; renderProposals(data.proposals || []);
                        reloadBoard(); reloadCalendar(); })
        .catch(() => { document.getElementById('proposals').textContent =
                       'Capture failed (check your token).'; });
      return false;
    }

    function renderProposals(proposals) {
      const box = document.getElementById('proposals');
      box.innerHTML = '';
      proposals.filter(p => p.name !== 'no_action').forEach(p => {
        const card = document.createElement('div');
        card.className = 'proposal';
        const body = document.createElement('div');
        body.className = 'proposal-body';
        // Ground truth — what WILL happen (registry-derived). Prominent.
        const action = document.createElement('div');
        action.className = 'action-summary';
        action.textContent = p.target_label
          ? p.action_summary + ' — ' + p.target_label
          : p.action_summary;
        body.appendChild(action);
        // The model's narration — why it proposed this. Secondary; only if set.
        if (p.llm_rationale) {
          const why = document.createElement('div');
          why.className = 'rationale';
          why.textContent = p.llm_rationale;
          body.appendChild(why);
        }
        card.appendChild(body);
        const confirm = document.createElement('button');
        confirm.className = 'confirm'; confirm.textContent = 'Confirm';
        confirm.onclick = () => confirmProposal(p, card);
        card.appendChild(confirm);
        const dismiss = document.createElement('button');
        dismiss.className = 'dismiss'; dismiss.textContent = 'Dismiss';
        dismiss.onclick = () => card.remove();  // Dismiss = client-side only
        card.appendChild(dismiss);
        box.appendChild(card);
      });
    }

    function confirmProposal(p, card) {
      fetch('/actions/confirm', {
        method: 'POST', headers: authHeaders(true),
        body: JSON.stringify({ name: p.name, params: p.params,
                               target_id: p.target_id, target_type: p.target_type })
      })
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(() => { card.remove(); reloadBoard(); reloadCalendar(); })
        .catch(() => { card.querySelector('.action-summary').textContent +=
                       ' (failed)'; });
    }

    function reloadBoard() {
      const t = getToken(); if (!t) return;
      fetch('/board/view', { headers: authHeaders(false) })
        .then(r => r.ok ? r.text() : Promise.reject(r.status))
        .then(html => { document.getElementById('board-container').innerHTML = html; })
        .catch(() => { document.getElementById('board-container').textContent =
                       'Could not load board (check your token).'; });
    }
    function reloadCalendar() {
      const t = getToken(); if (!t) return;
      fetch('/calendar/view', { headers: authHeaders(false) })
        .then(r => r.ok ? r.text() : Promise.reject(r.status))
        .then(html => {
          document.getElementById('calendar-container').innerHTML = html; })
        .catch(() => { document.getElementById('calendar-container').textContent =
                       'Could not load calendar (check your token).'; });
    }
    let es = null;
    function startSSE() {
      const t = getToken(); if (!t) return;
      if (es) es.close();
      es = new EventSource('/events/stream?token=' + encodeURIComponent(t));
      es.addEventListener('change', reloadBoard);
      es.addEventListener('change', reloadCalendar);
    }
    // On load, if a token is already saved, go.
    if (getToken()) { document.getElementById('token-status').textContent = 'saved';
                      startSSE(); reloadBoard(); reloadCalendar(); }
  </script>
</body>
</html>
"""
