# Family Calendar — Host Setup Guide (operator)

> **For:** the person running the app on the home computer (the operator/admin).
> This covers standing the server up, configuring the household, enrolling
> devices, and testing reachability. The **family-facing phone/tablet steps** live
> separately in [`USER_SETUP_GUIDE.md`](USER_SETUP_GUIDE.md) — you hand each family
> member that guide plus the device token you mint here.
>
> **State callouts (honest, as of this writing):**
> - Config seeding, the token-enrollment CLI, request auth, and running the
>   server locally are **built and tested**.
> - `tailscale serve` fronting the app was **partially verified before** the
>   current auth/config changes — re-verify end-to-end.
> - PWA full-screen "add to home screen" is **not yet tested** (service worker /
>   manifest is Phase 5).

---

## 0. Prerequisites

- Python 3.12+ on the home computer (Pop!_OS: `sudo apt install python3-venv` if
  venv errors).
- This repo checked out on that machine.
- One-time environment build:
  ```bash
  make setup      # venv + pinned deps + runs the test suite
  ```

---

## 1. Create the household config (out-of-repo, holds PII)

The real config lives **outside this repo** (it holds family names/roles) and is
never committed. A helper scaffolds it:

```bash
./setup-config.sh
```

This copies `family.example.toml` to `~/.config/ntake/family.toml` (without
overwriting an existing one) and prints the environment variables to set. Then:

1. **Edit the config** with your household + members:
   ```bash
   $EDITOR ~/.config/ntake/family.toml
   ```
   ```toml
   [family]
   name = "Example Household"
   timezone = "America/New_York"   # IANA name, required

   [[members]]
   display_name = "Adult One"
   role = "adult"                  # "adult" | "child"

   [[members]]
   display_name = "Wall Display"
   role = "child"                  # low-privilege (the shared kiosk)
   ```

2. **Export the two environment variables** (add to `~/.bashrc` / `~/.zshrc` to
   persist across reboots):
   ```bash
   export NTAKE_CONFIG="$HOME/.config/ntake/family.toml"
   export NTAKE_TOKEN_SECRET="<a long random string>"   # setup-config.sh suggests one
   ```
   - `NTAKE_TOKEN_SECRET` hashes device tokens. **Keep it secret and constant** —
     changing it invalidates every existing device token. Never commit it.

Members are seeded into the database automatically on server startup. Editing the
config and restarting adds new members (it's an idempotent upsert; it won't
duplicate existing ones).

---

## 2. Run the server

```bash
make run        # dev server on http://127.0.0.1:8000
```

- Binds to **127.0.0.1** by design — Tailscale fronts it for real access (§4).
- On first run it **migrates the database to head** (creating `calendar.db` and
  all tables via Alembic) and seeds the household from your config. No manual
  database step is needed — startup runs the migrations for you.
- To run migrations **without** starting the server (e.g. after pulling a release
  that adds a migration): `python -m app.manage migrate` (this is
  `alembic upgrade head` on `CALENDAR_DB_URL`; safe to re-run — a DB already at
  head is a no-op). Migrations are the schema path for the real DB; the test
  suite builds its schema from the ORM models directly (fast, isolated).

**Quick local check (on the host itself):**
```bash
curl http://127.0.0.1:8000/health      # -> {"status":"ok","version":"..."}
```
`/events` and `/events/stream` require a device token (see §3) — a bare request
returns `401`, which is correct.

The assistant runs the deterministic `fake` backend by default (no model needed).
To enable the **live local LLM** helper, set up a model server — see §7 (optional).

---

## 3. Enroll a device (mint a token)

Every device (each phone, the wall tablet) needs its own token. Mint one per
device; the plaintext is shown **once** — copy it immediately and give it to that
device (it is never stored or recoverable, only its hash is kept).

```bash
python -m app.manage gen-token "Adult One" --label "Pixel phone"
# -> prints the token once; hand it to that person for USER_SETUP_GUIDE.md
```

Manage existing tokens:
```bash
python -m app.manage list-tokens          # id | member | label | active|revoked
python -m app.manage revoke 3             # revoke token id 3 (e.g. lost phone)
```

- The member name must match a `display_name` in your config.
- To re-enroll a replaced/lost device: `revoke` the old token, `gen-token` a new
  one.
- These commands need `NTAKE_TOKEN_SECRET` and `NTAKE_CONFIG` set (§1).

---

## 4. Make it reachable over Tailscale (private, TLS)

> **Partially verified previously; re-verify after today's changes.** These steps
> are the intended private-access path per the design (no public exposure).

1. Install Tailscale on the host and sign in; the host joins your tailnet.
2. Enable **MagicDNS + HTTPS certificates** in the Tailscale admin console.
3. Front the local app with TLS:
   ```bash
   tailscale serve --bg 8000
   ```
   This serves `http://127.0.0.1:8000` at
   `https://<host>.<your-tailnet>.ts.net` with an auto-renewing Let's Encrypt
   cert (HTTPS is required for the PWA service worker).
4. Put that `https://…ts.net` URL into `USER_SETUP_GUIDE.md` (the `<FILL IN>`
   URL) before sharing it with the family.

### 4a. Verify the PWA installs (HTTPS-only — the second smoke)

The `make smoke` script runs over **HTTP** and covers the API, live-sync, and
SSE **reconnect re-sync** (server side). It deliberately does **not** cover the
PWA: install + service-worker registration require a **secure context (HTTPS)**,
so this is a separate, **on-device** smoke you run once TLS is up (§4). Do it in
a browser on a device that's on the tailnet, against the `https://…ts.net` URL:

1. **Assets serve:** open `…/manifest.webmanifest` (JSON loads), `…/sw.js` (JS
   loads), `…/icon.svg` (renders). Over HTTP these are already smoke-checked; the
   point here is they resolve under the real HTTPS origin.
2. **Service worker registers:** open the app, then DevTools → Application →
   Service Workers → expect `sw.js` **activated and running** (no HTTPS = no
   registration, so this only works via Tailscale).
3. **Installable:** the browser offers **Add to Home Screen / Install**; install
   it and confirm it launches standalone (no browser chrome) from the home
   screen — the phone + wall-tablet path (§3, DISP).
4. **Live reconnect (browser side):** with the installed PWA open, briefly drop
   Wi-Fi (or sleep/wake the tablet); on reconnect the board/calendar should
   re-sync automatically (the `EventSource` `open` handler). The *server* support
   for this is smoke-tested; this step confirms the *browser* behavior end-to-end.

> **Privacy note (CT logs):** the Let's Encrypt cert publishes
> `<host>.<tailnet>.ts.net` in public Certificate Transparency logs. It grants no
> access (you still need to be on the tailnet), but if the host/tailnet names are
> personal, rename the host before enabling HTTPS.

---

## 5. Test it now — LAN smoke (before Tailscale)

Useful to confirm the app is reachable from another device on the **same Wi-Fi**
before setting up Tailscale. This proves the API/live-sync over a real socket; it
does **not** exercise the PWA (that needs HTTPS, i.e. Tailscale).

1. Find the host's LAN IP:
   ```bash
   ipconfig getifaddr en0     # macOS; or check your OS network settings
   ```
2. Run the server bound to the LAN (not the default 127.0.0.1):
   ```bash
   .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
   ```
3. From another device's browser (same Wi-Fi), open:
   - `http://<LAN-IP>:8000/health` → should show the health JSON.
   - `/events` will be `401` without a token — expected.

**Caveats learned in testing:**
- Both devices must be on the **same Wi-Fi** (not cellular; not a "guest" SSID
  that isolates clients). If the request never reaches the host, this is the #1
  cause — check the phone isn't on LTE and the network doesn't have client
  isolation, and confirm the host firewall allows the connection.
- `0.0.0.0` exposes the app to your whole LAN with **no transport encryption** and
  auth is per-device only — fine for a brief smoke you control; don't leave it
  running. Use Tailscale (§4) for real use.

---

## 6. Backup & data

- The database is a single file, `calendar.db`, on the host. It is gitignored and
  never leaves the machine.
- The real config (`family.toml`) and `NTAKE_TOKEN_SECRET` are **not** in the
  repo — back them up separately (a lost `NTAKE_TOKEN_SECRET` invalidates all
  device tokens; you'd re-enroll every device).
- Weekly consistent snapshot: **`python -m app.manage backup`** writes a
  `VACUUM INTO` snapshot — a fresh, self-contained copy of the whole DB (safe
  under WAL; preferable to a raw file copy). By default it lands in
  `./backups/ntake-YYYYMMDD-HHMMSS.db`; pass `--dest /path/to/snap.db` to choose
  the location.
  ```bash
  python -m app.manage backup                       # ./backups/ntake-<stamp>.db
  python -m app.manage backup --dest /mnt/usb/ntake.db
  ```
  **Scheduling is a host step (not built into the app).** Run it weekly via cron
  or a systemd timer — for example, a crontab line (Sunday 03:00):
  ```cron
  0 3 * * 0  cd /path/to/ntake-app && NTAKE_TOKEN_SECRET=… NTAKE_CONFIG=… \
             .venv/bin/python -m app.manage backup --dest /mnt/usb/ntake-weekly.db
  ```
  *(v1 limitation: the default lands on the same disk — protects against
  corruption/accidental deletion, not physical disk failure. Point `--dest` at an
  external/mounted volume for off-machine safety; NFR-DURABILITY.)*

---

## 7. Local assistant model (optional — the propose-and-confirm helper)

The app runs fine **without** a model: by default the assistant is the
deterministic `fake` backend (keyword rules), so capture → propose → confirm
works for testing. The **live local LLM** is what makes the assistant actually
reason over free-text notes. It is entirely local — no cloud, no data leaves the
machine (NFR-PRIVACY) — and it is **operator-provisioned**: the app never
downloads the model (fetching multi-GB weights with checksum/verify is a
subsystem we deliberately don't build; you manage the binary + weights below).

> **Reference runtime: llamafile.** A single portable executable that serves an
> OpenAI-compatible `/v1/chat/completions` on localhost with grammar/JSON-
> constrained output. The app is runtime-agnostic — **Ollama, LM Studio, and
> llama.cpp `llama-server` expose the same endpoint** and work by pointing the
> config's `base_url` at them (e.g. `http://localhost:11434` for Ollama). We
> document llamafile because it's the one we test against on both the dev Mac and
> the host.

### 7.1 Acquire the binary + a model (manual, one time)

Pick **one** distribution shape:

- **(a) Self-contained model-llamafile** — one executable with the weights baked
  in (simplest; larger file). Download from the llamafile releases, `chmod +x`,
  done.
- **(b) Bare `llamafile` binary + a `.gguf`** — the reusable binary plus a model
  file you point it at (lets you A/B models without re-downloading the runtime).

**Reference model (this box: M4 Pro, 48 GB):** **Llama 3.1 8B Instruct**, `Q8_0`
quant (~8.5 GB) to start. **Qwen2.5 14B Instruct** `Q4_K_M` (~9 GB) is a quality
A/B — both fit a ~9–10 GB budget. Use a **non-thinking** instruct model (the
prompts expect a direct JSON answer, no `<think>` blocks to strip).

**On-disk location (choose one and keep it stable):**
```
~/.local/share/ntake/llm/          # suggested
  llamafile                        # (b) the binary, chmod +x
  llama-3.1-8b-instruct.Q8_0.gguf  # (b) the weights
```
Verify the download's checksum against the release page before trusting it. These
files are large and **must not** go in the repo or any backup that leaves the
machine.

### 7.2 Serve it on localhost:8080

The app's default `base_url` is `http://localhost:8080` (see §7.4), so serve
there (or change the config to match your port).

**Dev Mac — run it directly** (foreground; Ctrl-C to stop):
```bash
# shape (a), self-contained model-llamafile:
~/.local/share/ntake/llm/llamafile --server --host 127.0.0.1 --port 8080

# shape (b), bare binary + gguf:
~/.local/share/ntake/llm/llamafile --server --host 127.0.0.1 --port 8080 \
  -m ~/.local/share/ntake/llm/llama-3.1-8b-instruct.Q8_0.gguf
```
> **Note (llamafile ≥ 0.10.0):** `--server` mode has no TUI/browser, and the old
> `--nobrowser` flag was removed — passing it makes the server exit immediately
> with `error: invalid argument: --nobrowser`. Omit it (as above).
Confirm it's up:
```bash
curl http://localhost:8080/v1/models      # lists the served model
```

**Host — a systemd unit** (auto-start on boot, restart on failure). This is the
one operational cost we accepted vs. Ollama's turnkey service. Create
`~/.config/systemd/user/ntake-llm.service`:
```ini
[Unit]
Description=ntake local LLM (llamafile)
After=network.target

[Service]
ExecStart=%h/.local/share/ntake/llm/llamafile --server --host 127.0.0.1 --port 8080 -m %h/.local/share/ntake/llm/llama-3.1-8b-instruct.Q8_0.gguf
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```
```bash
systemctl --user daemon-reload
systemctl --user enable --now ntake-llm.service
loginctl enable-linger "$USER"     # so it runs without you logged in
systemctl --user status ntake-llm.service
```
Bind to **127.0.0.1** — the model server is local-only; nothing about it is
exposed over Tailscale.

### 7.3 Warm it + check health (from the app)

Once the server is up, the app has a small operational surface over the
*already-running* endpoint (it does **not** start/stop the model):
```bash
python -m app.manage llm health    # is the endpoint up + serving the expected model?
python -m app.manage llm warm      # send a tiny priming request to load the model into RAM
python -m app.manage llm status    # health + warmth summary
```
**Why warm matters (cold start):** the pipeline makes **two** sequential model
calls per capture, and a model's *first* call after idle takes seconds to tens of
seconds to load into memory. Run `llm warm` after (re)starting the server — and
note the app runs a warm-ping on startup — so the first real capture isn't a cold
miss that times out and degrades to "no suggestions." The `local` timeout default
is large (120s) for the same reason.

### 7.4 Turn the assistant on (config-in-code)

The assistant backend is selected by a code value, **not an env var**:
`AssistantConfig` in `app/assistant/factory.py` (`kind`, `model`, `base_url`,
`timeout`). To run the live model, construct the config with `kind="local"`
(defaults: `model="llama3.1:8b"`, `base_url="http://localhost:8080"`,
`timeout=120.0`). Point `base_url` at another runtime (e.g. Ollama on `:11434`)
or name a different `model` there.

**Dev/UI-testing opt-in (env override).** So you don't have to hand-edit the
code for a throwaway live session, `get_assistant_config()` honors an optional
environment override while keeping the **committed default `fake`** (so the test
suite is unaffected): set `NTAKE_ASSISTANT_KIND=local` to flip the request path
to the live backend, and optionally `NTAKE_LLM_MODEL`, `NTAKE_LLM_BASE_URL`,
`NTAKE_LLM_TIMEOUT` to override the model id / URL / timeout. The served model id
must exactly match `NTAKE_LLM_MODEL` for `llm health` to report green (llamafile
reports the full `.gguf` path as the id). These are read only when the override
is `local`; unset, nothing changes. **`make ui-live` sets all of these for you**
(see §7.6) — you rarely set them by hand.

### 7.5 End-to-end smoke (with the model actually serving)

This is the one thing the automated tests can't check — real reasoning quality:
```bash
make smoke        # runs the host integration smoke; --serve keeps the server up
```
Confirm real captures produce sane proposals; expect to **tune** prompt wording
and the timeout against what you observe (the prompt drafts anticipate this).

### 7.6 One-command live-LLM UI session (`make ui-live`)

For hands-on **browser** testing against the live model, `make ui-live` brings
the whole thing up in one command — the persistent-DB, real-household counterpart
to `make smoke`:

```bash
make llm-up        # (infra) start the model server first — §7.2
make ui-live       # bring the app up on the live backend, seed, mint, serve
```

What it does (see `scripts/live_llm_ui.sh`, which is self-documented):
1. **Preflights** the model server at `NTAKE_LLM_BASE_URL` (default `:8080`) and
   auto-probes the served model id (so `llm health` matches — §7.4).
2. **Flips** the assistant to `local` for the app process via the §7.4 env
   override (the committed default stays `fake` — the test suite is unaffected).
3. Starts the app on the **persistent** `./calendar.db`, seeds sample events, and
   **mints a device token** for a member (`NTAKE_MEMBER`, default: first adult).
4. Prints the **URL + token**, then serves (Ctrl-C to stop).

How it differs from `make smoke`: `make smoke` uses an isolated **temp** DB, a
hardcoded "Smoke Household", the **fake** assistant, and 12 fake-shaped
assertions (self-cleaning; proves the plumbing). `make ui-live` uses your real
`family.toml` household, the persistent DB, and the **live** model — for eyeballing
real reasoning in the browser. In the UI, expand the **"LLM debug trace"** panel
under a proposal to see both prompts, the raw model replies, and the resolved ids;
the board/event cards show full record detail.

Secret handling: if `NTAKE_TOKEN_SECRET` isn't set, the script persists a stable
one to `<config-dir>/token_secret` (out-of-repo, `chmod 600`) so tokens survive
re-runs — set the env var yourself to control it.

---

## Troubleshooting

- **`/events` returns 401 with a token:** confirm `NTAKE_TOKEN_SECRET` is the
  same value used when the token was minted (changing it invalidates tokens).
- **`no such table` / 500 on startup:** shouldn't happen — schema is created on
  startup. If you see it, confirm you're running via `make run` / `uvicorn
  app.main:app` (which triggers startup), not importing pieces manually.
- **CLI says "No member named …":** the name must match a `display_name` in
  `~/.config/ntake/family.toml`; edit the config and restart the server to seed
  the new member.
- **Phone can't reach the LAN URL:** see the §5 caveats (same Wi-Fi, client
  isolation, host firewall).
- **Captures return no suggestions with the local model on:** most often a
  cold-start timeout — run `python -m app.manage llm warm` after (re)starting the
  model server (§7.3), and confirm `llm health` reports the endpoint up and the
  expected model. The app degrades to empty proposals (never errors) when the
  model is down/slow, so an always-empty result usually means the model server
  isn't reachable at the configured `base_url`.
- **`llm health` says wrong/missing model:** the served model name must match the
  config's `model`; check `curl http://localhost:8080/v1/models` against §7.4.
