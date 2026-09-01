# Task: Enroll host, run `tailscale serve`, enroll devices — PLAN Phase 1 wiring

> **Run on:** the **home PC** first, then each family phone + the wall tablet.
> Prereqs: `tasks_tailscale_account.md` done; app runs locally
> (`tasks_app_scaffold.md`).

## Host PC

## Host PC — Pop!_OS (Ubuntu-based)

- [ ] Install Tailscale (official script works on Pop!_OS):
      ```
      curl -fsSL https://tailscale.com/install.sh | sh
      sudo tailscale up
      ```
      Follow the printed auth URL to sign in → the host joins the tailnet.
      (`tailscaled` runs as a systemd service and starts on boot automatically.)
- [ ] **Rename the machine** to a non-sensitive name (e.g. `calendar-host`) in
      the admin console — do this **before** wiring the URL, since renaming
      changes the MagicDNS name.
- [ ] With the app running locally on port 8000, run:
      ```
      sudo tailscale serve 8000
      ```
      This fronts it at `https://calendar-host.<tailnet>.ts.net` with an
      auto-renewing Let's Encrypt cert.
      > On modern Tailscale, `serve` config **persists** and is re-applied by
      > `tailscaled` across reboots (it's not just a foreground session). Verify
      > with `tailscale serve status`. Making the *app itself* start on boot is a
      > separate step — see the systemd note below.
- [ ] Record the URL: `https://__________________________.ts.net`

- [ ] **(Phase 5 hardening, note now) Keep the app running on boot** via a
      systemd unit, e.g. `/etc/systemd/system/family-calendar.service` running
      `uvicorn app.main:app --host 127.0.0.1 --port 8000`, then
      `sudo systemctl enable --now family-calendar`. Not required for the first
      1f test (a manual `uvicorn` run is fine), but this is what makes the
      always-on posture (NFR-UPTIME) real. Listen on **127.0.0.1** only — Serve
      proxies to localhost, and localhost-only avoids exposing the app on the LAN.

## Each phone + wall tablet

- [ ] Install the Tailscale app; sign in to the **same** tailnet.
- [ ] Leave it running (stays connected in the background). This one-time join is
      what lets the device reach the `.ts.net` URL from **anywhere** (home WiFi
      or cellular).

## Done when

- [ ] `tailscale serve` is running on the host and prints the HTTPS URL.
- [ ] Host machine renamed; all family devices signed into the tailnet.

## Notes / caveats

- Prefer `tailscale serve` over manual `tailscale cert` — Serve auto-renews the
  90-day cert; the manual path makes renewal your problem.
- CLI flags drift; `tailscale serve --help` for current usage.
- Keeping `serve` running across reboots (as a service) is a later hardening
  item (PLAN Phase 5) — for the first test, a foreground session is fine.

## Next

- `tasks_verify_1f.md` — end-to-end test.
