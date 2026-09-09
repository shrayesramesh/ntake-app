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
    button, input { font: inherit; }
    button { cursor: pointer; }
    [hidden] { display: none !important; }
    .shell-header { display: flex; align-items: center; gap: .75rem; flex-wrap: wrap;
                    margin-bottom: 1rem; }
    .shell-title { font-size: 1.15rem; margin: 0 auto 0 0; }
    .view-toggle { display: inline-flex; gap: .2rem; padding: .2rem;
                   background: #e4e4e7; border-radius: .5rem; }
    .view-toggle button { border: 0; border-radius: .35rem; padding: .35rem .6rem;
                          background: transparent; color: #3f3f46; }
    .view-toggle button[aria-pressed="true"] { background: #fff; color: #18181b;
                                                 box-shadow: 0 1px 2px
                                                   rgba(0,0,0,.12); }
    .capture-trigger { background: #2563eb; color: #fff; border: 0;
                       border-radius: .4rem; padding: .4rem .7rem; }
    .device-menu { position: relative; }
    .device-menu summary { cursor: pointer; color: #52525b; font-size: .8rem; }
    .device-menu-menu { position: absolute; right: 0; z-index: 2; min-width: 13rem;
                         background: #fff; border: 1px solid #d4d4d8;
                         border-radius: .4rem; box-shadow: 0 3px 12px rgba(0,0,0,.12);
                         padding: .5rem; }
    .device-menu-menu p { font-size: .8rem; margin: .2rem 0 .5rem; }
    .device-menu-menu button { width: 100%; text-align: left; border: 0;
                                background: transparent; padding: .35rem;
                                color: #374151; }
    #device-onboarding { max-width: 28rem; margin: 12vh auto; padding: 1.25rem;
                          border: 1px solid #d4d4d8; border-radius: .6rem; }
    #device-onboarding h1 { margin-top: 0; }
    #device-token { box-sizing: border-box; width: 100%; margin: .5rem 0;
                    padding: .55rem; }
    .onboarding-status, .capture-status { min-height: 1.2rem; color: #52525b;
                                           font-size: .85rem; }
    #capture-dialog { width: min(34rem, calc(100vw - 2rem)); border: 0;
                      border-radius: .7rem; box-shadow: 0 12px 40px rgba(0,0,0,.28);
                      padding: 0; }
    #capture-dialog::backdrop { background: rgba(24, 24, 27, .45); }
    .capture-panel { padding: 1rem; }
    .capture-panel h2 { margin: 0 0 .4rem; }
    #capture-text { box-sizing: border-box; width: 100%; min-height: 5rem;
                    resize: vertical; padding: .6rem; }
    .capture-actions { display: flex; justify-content: flex-end; gap: .5rem;
                       margin-top: .75rem; }
    .capture-actions button { padding: .4rem .7rem; }
    .capture-submit { background: #2563eb; border: 0; border-radius: .35rem;
                      color: #fff; }
    @media (max-width: 42rem) {
      body { padding: .7rem; }
      .shell-title { width: 100%; order: -1; }
      #capture-dialog { width: 100%; max-width: none; margin: auto 0 0;
                        border-radius: .8rem .8rem 0 0; }
    }
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
  <section id="device-onboarding" aria-labelledby="onboarding-title">
    <h1 id="onboarding-title">Family Calendar</h1>
    <p>Connect this device by scanning the setup QR code provided by the
       household owner.</p>
    <label for="device-token">Have a device token instead?</label>
    <input id="device-token" type="password" autocomplete="off"
           placeholder="Paste device token">
    <button type="button" onclick="connectDevice()">Connect</button>
    <p id="onboarding-status" class="onboarding-status" role="status"></p>
  </section>

  <div id="paired-shell" hidden>
    <header class="shell-header">
      <h1 class="shell-title">Family Calendar</h1>
      <div class="view-toggle" aria-label="Primary view">
        <button id="view-board" type="button" aria-pressed="false"
                onclick="setActiveView('board')">Board</button>
        <button id="view-calendar" type="button" aria-pressed="true"
                onclick="setActiveView('calendar')">Calendar</button>
      </div>
      <button id="open-capture" class="capture-trigger" type="button"
              onclick="openCapture()">Capture</button>
      <details class="device-menu">
        <summary>Device</summary>
        <div class="device-menu-menu">
          <p>Device connected</p>
          <button type="button" onclick="refreshActiveView()">Refresh</button>
          <button type="button" onclick="removeDevice()">Remove this device</button>
        </div>
      </details>
    </header>

    <main>
      <section id="board-view" aria-label="Family board" hidden>
        <div id="board-container"></div>
      </section>
      <section id="calendar-view" aria-label="Family calendar">
        <div id="calendar-container">
          <div id="calendar-grid" aria-label="Family calendar"></div>
        </div>
      </section>
    </main>
  </div>

  <dialog id="capture-dialog">
    <div class="capture-panel">
      <h2>Capture</h2>
      <p>Use your keyboard microphone to dictate, then review before submitting.</p>
      <form id="capture-form" onsubmit="return onCapture(event)">
        <textarea id="capture-text" rows="4" placeholder="What needs to happen?"
                  enterkeyhint="done" onkeydown="captureOnKeydown(event)"
                  required></textarea>
        <p id="capture-status" class="capture-status" role="status"></p>
        <div class="capture-actions">
          <button type="button" onclick="closeCapture()">Cancel</button>
          <button class="capture-submit" type="submit">Capture</button>
        </div>
      </form>
      <div id="proposals"></div>
      <div id="debug-panel-container"></div>
    </div>
  </dialog>

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
    const ACTIVE_VIEW_KEY = 'ntake_active_view';

    function getToken() { return localStorage.getItem('ntake_token') || ''; }
    function authHeaders(json) {
      const h = { 'Authorization': 'Bearer ' + getToken() };
      if (json) h['Content-Type'] = 'application/json';
      return h;
    }
    function setOnboardingMessage(message) {
      document.getElementById('onboarding-status').textContent = message;
    }
    function showOnboarding(message) {
      const dialog = document.getElementById('capture-dialog');
      if (dialog.open) dialog.close();
      document.getElementById('paired-shell').hidden = true;
      document.getElementById('device-onboarding').hidden = false;
      if (message) setOnboardingMessage(message);
    }
    function showPairedShell() {
      document.getElementById('device-onboarding').hidden = true;
      document.getElementById('paired-shell').hidden = false;
      setActiveView(localStorage.getItem(ACTIVE_VIEW_KEY) || 'calendar');
      startSSE();
    }
    function consumeFragmentToken() {
      const token = new URLSearchParams(location.hash.slice(1)).get('token');
      if (!token) return false;
      localStorage.setItem('ntake_token', token);
      history.replaceState(null, '', location.pathname + location.search);
      return true;
    }
    function connectDevice() {
      const token = document.getElementById('device-token').value.trim();
      if (!token) { setOnboardingMessage('Paste a device token to connect.'); return; }
      localStorage.setItem('ntake_token', token);
      setOnboardingMessage('Connecting this device…');
      showPairedShell();
    }
    function removeDevice() {
      localStorage.removeItem('ntake_token');
      if (es) es.close();
      showOnboarding('This device was removed from this browser.');
    }
    function handleUnauthorized(response) {
      if (response.status === 401) {
        localStorage.removeItem('ntake_token');
        if (es) es.close();
        showOnboarding('This device token is invalid or was revoked.');
      }
      return response;
    }
    function setActiveView(view) {
      const active = view === 'board' ? 'board' : 'calendar';
      localStorage.setItem(ACTIVE_VIEW_KEY, active);
      const boardButton = document.getElementById('view-board');
      const calendarButton = document.getElementById('view-calendar');
      boardButton.setAttribute('aria-pressed', String(active === 'board'));
      calendarButton.setAttribute('aria-pressed', String(active === 'calendar'));
      document.getElementById('board-view').hidden = active !== 'board';
      document.getElementById('calendar-view').hidden = active !== 'calendar';
      refreshActiveView();
    }
    function refreshActiveView() {
      if (!getToken()) return;
      const active = localStorage.getItem(ACTIVE_VIEW_KEY) || 'calendar';
      if (active === 'board') reloadBoard(); else refreshCalendar();
    }
    function openCapture() {
      const dialog = document.getElementById('capture-dialog');
      if (!dialog.open) dialog.showModal();
      setTimeout(() => document.getElementById('capture-text').focus(), 0);
    }
    function closeCapture() {
      document.getElementById('capture-dialog').close();
    }

    function captureOnKeydown(event) {
      if (event.key !== 'Enter' || event.isComposing) return;
      event.preventDefault();
      document.getElementById('capture-form').requestSubmit();
    }

    // Capture remains propose-only; only explicit Confirm persists a mutation.
    function onCapture(event) {
      event.preventDefault();
      const input = document.getElementById('capture-text');
      const status = document.getElementById('capture-status');
      const text = input.value.trim();
      if (!text || !getToken()) return false;
      status.textContent = 'Interpreting your capture…';
      fetch('/capture', {
        method: 'POST', headers: authHeaders(true),
        body: JSON.stringify({ text: text })
      })
        .then(r => {
          handleUnauthorized(r);
          return r.ok ? r.json() : Promise.reject(r.status);
        })
        .then(data => {
          input.value = '';
          renderProposals(data.proposals || []);
          renderDebug(data.debug || null);
          status.textContent = data.proposals && data.proposals.length
            ? 'Review the suggested changes below.'
            : 'No changes were suggested. You can revise and try again.';
          refreshActiveView();
        })
        .catch(() => {
          status.textContent =
            'Capture could not be completed. Check your connection and try again.';
        });
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
        .then(r => {
          handleUnauthorized(r);
          return r.ok ? r.json() : Promise.reject(r.status);
        })
        .then(() => {
          card.remove();
          document.getElementById('capture-status').textContent = 'Change confirmed.';
          refreshActiveView();
        })
        .catch(() => {
          document.getElementById('capture-status').textContent =
            'Confirm could not be completed. Try again.';
        });
    }

    function reloadBoard() {
      if (!getToken()) return;
      fetch('/board/view', { headers: authHeaders(false) })
        .then(r => {
          handleUnauthorized(r);
          return r.ok ? r.text() : Promise.reject(r.status);
        })
        .then(html => { document.getElementById('board-container').innerHTML = html; })
        .catch(() => {
          if (getToken()) document.getElementById('board-container').textContent =
            'Could not load board. Check your connection and retry.';
        });
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

    // Timed values in /events are already offset-free family-local wall times.
    // Keep them untouched so EventCalendar renders the household's schedule.
    function familyLocalIso(value) {
      return value;
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
        start: familyLocalIso(e.local_start_at),
        end: familyLocalIso(e.local_end_at || e.local_start_at),
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
        .then(r => {
          handleUnauthorized(r);
          return r.ok ? r.json() : Promise.reject(r.status);
        })
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
      // Re-fetch the active view on (re)connect so it cannot stay stale after a
      // sleep/wake or a missed change during a disconnect.
      es.addEventListener('open', refreshActiveView);
      es.addEventListener('change', refreshActiveView);
    }
    // QR setup links carry the existing token only in the fragment. Consume it
    // once, then clear it before rendering the normal paired-device shell.
    consumeFragmentToken();
    if (getToken()) { showPairedShell(); } else { showOnboarding(); }
  </script>
</body>
</html>
"""
