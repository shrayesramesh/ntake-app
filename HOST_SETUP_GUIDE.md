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
- On first run it creates the SQLite database (`calendar.db`) and seeds the
  household from your config. No manual database step is needed.

**Quick local check (on the host itself):**
```bash
curl http://127.0.0.1:8000/health      # -> {"status":"ok","version":"..."}
```
`/events` and `/events/stream` require a device token (see §3) — a bare request
returns `401`, which is correct.

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
