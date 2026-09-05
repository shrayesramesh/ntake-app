"""PWA shell markup and installability assets for the family calendar."""

# --- PWA installability (DISP): manifest + minimal service worker ---------

# The web app manifest (served as JSON at /manifest.webmanifest). Enough for a
# browser to offer "add to home screen" for the phones + the wall tablet (§3).
MANIFEST: dict = {
    "name": "Family Board",
    "short_name": "Family",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#ffffff",
    "theme_color": "#2563eb",
    "icons": [
        {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}
    ],
}

# A minimal, single-color app icon (SVG scales to any size the installer wants).
APP_ICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">'
    '<rect width="128" height="128" rx="24" fill="#2563eb"/>'
    '<rect x="28" y="34" width="72" height="16" rx="4" fill="#fff"/>'
    '<rect x="28" y="58" width="72" height="12" rx="4" fill="#bfdbfe"/>'
    '<rect x="28" y="78" width="48" height="12" rx="4" fill="#bfdbfe"/>'
    "</svg>"
)

# The service worker (served as JS at /sw.js, root scope so it covers the app).
# v1 is DELIBERATELY pass-through: no precache, no runtime cache. The app is a
# live server (SSE-driven board/calendar) — caching the shell would risk serving
# stale UI. The SW exists so the app is installable (a registered SW is required
# for the PWA install prompt), not for offline use (offline is a non-goal: the
# app is useless without the server). ``claim`` so it controls open pages at once.
SERVICE_WORKER = """\
// v1 pass-through service worker — installability only, NO caching.
self.addEventListener('install', (e) => { self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(self.clients.claim()); });
// No 'fetch' handler: requests go straight to network (never a stale shell).
"""

# The capture form POSTs free text to /capture. It renders proposed actions;
# only an explicit Confirm mutates persisted state.
SHELL_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#2563eb">
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="stylesheet" href="/static/event-calendar/event-calendar.min.css">
  <title>Family Board</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 0; padding: 1rem; }
    .board { display: flex; gap: .75rem; align-items: flex-start; }
    .column { flex: 1; background: #f4f4f5; border-radius: 8px; padding: .5rem; }
    .column h2 { font-size: .9rem; margin: .25rem 0 .5rem; }
    .cards { list-style: none; margin: 0; padding: 0; }
    .card { background: #fff; border-radius: 6px; padding: .5rem; margin-bottom: .5rem;
            box-shadow: 0 1px 2px rgba(0,0,0,.08); }
    .card-head { display: flex; gap: .4rem; align-items: baseline; }
    .card-id { font-size: .7rem; color: #94a3b8; font-family: ui-monospace, monospace; }
    .card-title { font-weight: 600; }
    .card-desc { margin: .3rem 0; font-size: .82rem; color: #3f3f46; }
    .card-meta { display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .3rem; }
    .card-meta .meta { font-size: .7rem; color: #52525b; background: #f1f5f9;
                       border-radius: 4px; padding: 0 .35rem; }
    .card-meta .due { background: #fef3c7; }
    .card-tags { margin-top: .3rem; }
    .card-checklist { list-style: none; margin: .45rem 0 0; padding: 0; }
    .checklist-item { font-size: .82rem; margin-top: .15rem; }
    .checklist-item.checked { color: #71717a; text-decoration: line-through; }
    .done-summary { color: #71717a; font-size: .82rem; text-align: center; }
    .tag { display: inline-block; font-size: .7rem; background: #e0e7ff;
           border-radius: 4px; padding: 0 .35rem; margin-left: .35rem; }
    .empty { color: #a1a1aa; text-align: center; }
    .calendar { margin-top: 1rem; }
    /* Stable kiosk region: does not change when month/week/day changes. */
    #calendar-container { height: clamp(32rem, 62vh, 48rem); min-height: 0; }
    #calendar-grid { height: 100%; min-height: 0; }
    .calendar-event-content { min-width: 0; overflow: hidden; line-height: 1.2; }
    .calendar-event-title { font-weight: 650; overflow: hidden; text-overflow: ellipsis;
                            white-space: nowrap; }
    .calendar-event-meta { font-size: .72rem; opacity: .88; overflow: hidden;
                           text-overflow: ellipsis; white-space: nowrap; }
    .calendar .events { list-style: none; margin: 0; padding: 0; }
    .event-card { background: #fff; border: 1px solid #e4e4e7; border-radius: 6px;
                  padding: .5rem .6rem; margin-bottom: .4rem; }
    .event-card .card-head { flex-wrap: wrap; }
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
    .proposal .proposal-details { margin: .25rem 0 0; padding-left: 1rem;
                                  font-size: .8rem; color: #374151; }
    .proposal .proposal-details li { margin: .1rem 0; }
    .proposal button { font-size: .8rem; padding: .2rem .6rem; }
    .proposal .confirm { background: #2563eb; color: #fff; border: none;
                         border-radius: 4px; }
    .proposal .dismiss { background: transparent; border: none; color: #6b7280; }
    /* Debug panel (live-LLM testing only) */
    #debug-panel { margin-bottom: 1rem; border: 1px dashed #cbd5e1; border-radius: 6px;
                   background: #fafafa; }
    #debug-panel > summary { cursor: pointer; padding: .5rem .6rem; font-size: .85rem;
                             font-weight: 600; color: #475569; }
    .dbg-section { padding: 0 .6rem .5rem; }
    .dbg-section h4 { margin: .5rem 0 .2rem; font-size: .75rem; color: #64748b;
                      text-transform: uppercase; letter-spacing: .03em; }
    .dbg-section pre { margin: 0; padding: .5rem; background: #0f172a;
                       color: #e2e8f0; border-radius: 4px; font-size: .72rem;
                       line-height: 1.35; overflow-x: auto; white-space: pre-wrap;
                       word-break: break-word; }
    .dbg-ids { font-family: ui-monospace, monospace; font-size: .78rem;
               color: #334155; }
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
    <input id="capture-text"
           placeholder="Capture a note, task, or plan…"
           enterkeyhint="done"
           onkeydown="captureOnKeydown(event)"
           required>
    <button type="submit">Capture</button>
  </form>

  <!-- Assistant proposals render here, on the author's device only. -->
  <div id="proposals"></div>

  <!-- Live-LLM debug trace (prompts + raw model replies), rendered per capture. -->
  <div id="debug-panel-container"></div>

  <div id="board-container">Enter your device token to load the board.</div>

  <h2 style="font-size:1rem;margin:1rem 0 .5rem;">Calendar</h2>
  <div id="calendar-container">
    <div id="calendar-grid" aria-label="Family calendar"></div>
  </div>

  <!-- Locally vendored EventCalendar standalone bundle (no public CDN). -->
  <script src="/static/event-calendar/event-calendar.min.js"></script>
  <script>
    // Register the service worker so the app is installable (add to home
    // screen) on phones + the wall tablet. Pass-through SW (no caching); needs a
    // secure context (HTTPS via Tailscale, or localhost).
    if ('serviceWorker' in navigator) {
      window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').catch(() => {});
      });
    }
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
               startSSE(); reloadBoard(); initCalendar(); }
    }

    // Submit from physical Enter and mobile keyboard Done. Explicitly submit so
    // browser quirks cannot bypass the form handler; ignore IME composition so
    // Enter can still confirm an in-progress composed character.
    function captureOnKeydown(event) {
      if (event.key !== 'Enter' || event.isComposing) return;
      event.preventDefault();
      document.getElementById('capture').requestSubmit();
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
                        renderDebug(data.debug || null);
                        reloadBoard(); refreshCalendar(); })
        .catch(() => { document.getElementById('proposals').textContent =
                       'Capture failed (check your token).'; });
      return false;
    }

    // Render the live-LLM debug trace (prompts + raw replies) as a collapsible
    // panel. No-op / cleared when the backend isn't the local LLM (debug null).
    function renderDebug(dbg) {
      const box = document.getElementById('debug-panel-container');
      box.innerHTML = '';
      if (!dbg) return;
      const j = (v) => JSON.stringify(v, null, 2);
      const wi = (dbg.resolved_work_item_ids || []).join(', ') || '(none)';
      const ev = (dbg.resolved_event_ids || []).join(', ') || '(none)';
      const mem = (dbg.resolved_member_ids || []).join(', ') || '(none)';
      const section = (title, text) =>
        '<div class="dbg-section"><h4>' + title + '</h4><pre>' +
        escapeHtml(text) + '</pre></div>';
      const details = document.createElement('details');
      details.id = 'debug-panel';
      details.innerHTML =
        '<summary>🔍 LLM debug trace (stage 1 LINK → stage 2 PROPOSE)</summary>' +
        '<div class="dbg-section"><h4>Resolved ids (what stage 1 linked)</h4>' +
        '<div class="dbg-ids">work items: ' + escapeHtml(wi) +
        ' &nbsp;·&nbsp; events: ' + escapeHtml(ev) +
        ' &nbsp;·&nbsp; members: ' + escapeHtml(mem) + '</div></div>' +
        section('LINK — system prompt', dbg.link_system || '') +
        section('LINK — user prompt (world view + note)', dbg.link_user || '') +
        section('LINK — raw model reply', j(dbg.link_reply)) +
        section('PROPOSE — system prompt', dbg.propose_system || '') +
        section('PROPOSE — user prompt (tools + deep context + note)',
                dbg.propose_user || '') +
        section('PROPOSE — raw model reply', j(dbg.propose_reply));
      box.appendChild(details);
    }

    function escapeHtml(s) {
      return String(s).replace(/[&<>]/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
    }

    // Reformat any ISO-8601 timestamps/dates in a string to the VIEWER's locale +
    // timezone (the browser knows both; the server emits unambiguous ISO). Timed
    // values (with 'T') show date + time; bare dates (YYYY-MM-DD) show just the
    // date. Unparseable matches are left as-is (graceful).
    function humanizeDates(s) {
      if (!s) return s;
      // Full datetime, e.g. 2026-09-10T14:00:00Z or with offset.
      s = String(s).replace(
        /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?/g,
        (m) => {
          const d = new Date(m);
          return isNaN(d) ? m
            : d.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });
        }
      );
      // Bare calendar date (all-day), e.g. 2026-09-10 (not followed by 'T').
      s = s.replace(/\b\d{4}-\d{2}-\d{2}\b(?!T)/g, (m) => {
        const d = new Date(m + 'T00:00:00');
        return isNaN(d) ? m : d.toLocaleDateString([], { dateStyle: 'medium' });
      });
      return s;
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
          ? humanizeDates(p.action_summary) + ' — ' + p.target_label
          : humanizeDates(p.action_summary);
        body.appendChild(action);
        // Verbose, id-resolved detail lines (per-action render_card output).
        if (Array.isArray(p.detail_lines) && p.detail_lines.length) {
          const dl = document.createElement('ul');
          dl.className = 'proposal-details';
          p.detail_lines.forEach(line => {
            const li = document.createElement('li');
            li.textContent = humanizeDates(line);
            dl.appendChild(li);
          });
          body.appendChild(dl);
        }
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
        .then(() => { card.remove(); reloadBoard(); refreshCalendar(); })
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
    // EventCalendar (locally vendored) — month grid by default, week/day
    // optional, read-only. Its event source fetches the existing authenticated
    // /events feed and adapts app DTOs to calendar events.
    let calendar = null;

    // App all-day end_date is INCLUSIVE; EventCalendar's all-day end is
    // EXCLUSIVE. Shift an inclusive YYYY-MM-DD end forward by one day.
    function addOneDay(isoDate) {
      const d = new Date(isoDate + 'T00:00:00');
      d.setDate(d.getDate() + 1);
      return d.toISOString().slice(0, 10);
    }

    // SQLite returns stored UTC timestamps without an offset; make UTC explicit
    // before EventCalendar/browser parsing so a local display converts correctly.
    function utcIso(value) {
      if (!value) return value;
      return /(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : value + 'Z';
    }

    // Map an app Event DTO -> an EventCalendar event object.
    function toCalendarEvent(e) {
      if (e.all_day) {
        const end = e.end_date || e.start_date;
        return {
          id: String(e.id),
          title: e.title,
          allDay: true,
          start: e.start_date,
          end: end ? addOneDay(end) : undefined,
          extendedProps: {
            location: e.location,
            description: e.description,
            participants: e.participants || []
          }
        };
      }
      return {
        id: String(e.id),
        title: e.title,
        allDay: false,
        start: utcIso(e.start_at),
        end: utcIso(e.end_at || e.start_at),
        extendedProps: {
          location: e.location,
          description: e.description,
          participants: e.participants || []
        }
      };
    }

    // EventCalendar default content leads with time and omits the context the
    // former agenda cards showed. Return DOM nodes (not unsafe HTML) so each grid
    // event leads with title, then compact metadata: time, participants, location.
    function calendarEventContent(info) {
      const root = document.createElement('div');
      root.className = 'calendar-event-content';

      const title = document.createElement('div');
      title.className = 'calendar-event-title';
      title.textContent = info.event.title;
      root.appendChild(title);

      const props = info.event.extendedProps || {};
      const bits = [];
      if (info.timeText) bits.push(info.timeText);
      if (Array.isArray(props.participants) && props.participants.length) {
        bits.push(props.participants.join(', '));
      }
      if (props.location) bits.push('@ ' + props.location);
      if (bits.length) {
        const meta = document.createElement('div');
        meta.className = 'calendar-event-meta';
        meta.textContent = bits.join(' · ');
        root.appendChild(meta);
      }
      return { domNodes: [root] };
    }

    // Authenticated custom event source: fetch /events with the bearer token
    // and return adapted events (a Promise, per EventCalendar's fetch contract).
    function fetchCalendarEvents(fetchInfo, successCallback, failureCallback) {
      if (!getToken()) { successCallback([]); return; }
      fetch('/events', { headers: authHeaders(false) })
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(list => successCallback((list || []).map(toCalendarEvent)))
        .catch(err => failureCallback && failureCallback(err));
    }

    function initCalendar() {
      const el = document.getElementById('calendar-grid');
      if (!el || typeof EventCalendar === 'undefined') return;
      if (calendar) { refreshCalendar(); return; }
      calendar = EventCalendar.create(el, {
        view: 'dayGridMonth',
        height: '100%',
        headerToolbar: {
          start: 'title',
          center: '',
          end: 'dayGridMonth,timeGridWeek,timeGridDay today prev,next'
        },
        // Read-only first slice: no drag/drop/resize/direct editing.
        editable: false,
        eventStartEditable: false,
        eventDurationEditable: false,
        eventContent: calendarEventContent,
        eventSources: [{ events: fetchCalendarEvents }]
      });
    }

    // Refresh the mounted grid from the server (used on capture + SSE change).
    function refreshCalendar() {
      if (calendar) { calendar.refetchEvents(); } else { initCalendar(); }
    }
    let es = null;
    function startSSE() {
      const t = getToken(); if (!t) return;
      if (es) es.close();
      es = new EventSource('/events/stream?token=' + encodeURIComponent(t));
      // On (re)connect, re-sync both surfaces. EventSource auto-reconnects after
      // a drop (sleep/wake, network blip); a 'change' that happened WHILE we were
      // disconnected is never delivered, so without this the display would stay
      // stale until the next change. Re-fetching on 'open' closes that gap
      // (DISP-2/5: stays correct across sleep/wake for days).
      es.addEventListener('open', reloadBoard);
      es.addEventListener('open', refreshCalendar);
      es.addEventListener('change', reloadBoard);
      es.addEventListener('change', refreshCalendar);
    }
    // On load, if a token is already saved, go.
    if (getToken()) { document.getElementById('token-status').textContent = 'saved';
                      startSSE(); reloadBoard(); initCalendar(); }
  </script>
</body>
</html>
"""
