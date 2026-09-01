# Tailscale — Setup & Test Guide

> **Type: reference / execution guide.** Concrete steps to stand up and verify
> the Tailscale HTTPS access described in DESIGN §1.2 / §1.6. Covers checkpoint
> **1f** in [../PLAN.md](../PLAN.md) (manual smoke test, not automated).
>
> *Caveat:* admin-console UI labels drift over time. The stable anchors are the
> concepts — **MagicDNS, Enable HTTPS, tailnet name, `tailscale serve`** — so if
> a menu label differs, look for those.

## Naming: what you can and can't choose

- **Machine name — freely chosen, renameable.** The left half of the URL
  (`calendar-host` in `calendar-host.yak-bebop.ts.net`). Pick a clean,
  **non-sensitive** name (it lands in the public cert-transparency ledger).
  Rename it *before* wiring the display/cert to the URL, since renaming changes
  the name. **This is where to spend your naming energy.**
- **Tailnet name — pick from two, not custom.** Only the **default**
  (`tailNNNN.ts.net`) or a **Tailscale-generated random** name
  (`yak-bebop.ts.net`) are allowed; arbitrary custom strings are **not**. The
  **random** name is the recommended choice — equally private (no identifying
  info in the CT ledger) and more memorable than the numeric default.
- **A truly custom name** (e.g. `calendar.myfamily.com`) requires a **registered
  domain + self-managed certs** (see `03-custom-domain-options` if/when written).
  Not worth it for a private family app; tracked as future LLD only.

## Part 1 — Account & tailnet setup (browser only, no machine needed)

1. Create a Tailscale account at `login.tailscale.com/start` (personal plan,
   free; ample for 2–4 devices). Sign in with any supported identity provider.
2. Admin console → **DNS** page:
   - **Enable MagicDNS** (internal DNS resolving `*.ts.net` for your devices).
   - **Enable HTTPS** (turns on Let's Encrypt cert provisioning).
3. **Set the randomized tailnet name** (privacy; see naming section above).

Nothing to buy, no domain to register.

## Part 2 — Enroll devices (needs the machines)

4. **Host PC** (always-on machine running the app): install Tailscale, sign in
   (joins the tailnet), then **rename the machine** to a non-sensitive name
   (e.g. `calendar-host`) — before pointing anything at the URL.
5. **Each phone + the wall tablet:** install the Tailscale app, sign in to the
   **same** tailnet, leave it running in the background. This one-time join is
   what lets the device resolve/reach the `.ts.net` URL **from anywhere**
   (home WiFi *or* cellular) — Tailscale is a mesh VPN, not tied to the home
   router.

## Part 3 — Serve the app over HTTPS (on the host)

6. With the app running locally (e.g. port 8000):
   ```
   tailscale serve 8000
   ```
   Fronts the local app at `https://calendar-host.<tailnet>.ts.net`, provisions
   the cert, and **auto-renews** it. Prefer this over manual `tailscale cert`
   (which makes 90-day renewal your problem).

## Part 4 — Test in widening circles (checkpoint 1f)

Test outward so failures isolate cleanly:

- **A — host, local:** on the host, open `http://127.0.0.1:8000` → app runs at
  all (no Tailscale involved).
- **B — host, via Serve URL:** on the host, open
  `https://calendar-host.<tailnet>.ts.net` → `tailscale serve` + cert work
  (valid HTTPS, no warning).
- **C — second device, same WiFi:** phone on the tailnet at home opens the
  `.ts.net` URL → MagicDNS resolves, another device reaches it privately.
- **D — off-network (the real one):** phone on **cellular** (off home WiFi),
  Tailscale running, opens the URL → proves the "add an event from work"
  scenario (R2).
- **E — PWA install:** "Add to Home Screen," launch from the icon → service
  worker registered (only possible via valid HTTPS), opens full-screen.

**Pass = ** valid cert (no warning) from a second device both on and off home
WiFi, and the home-screen icon launches full-screen.

## Common snags

- **Cert not valid / warning:** HTTPS not enabled, or cert still provisioning
  (wait; Let's Encrypt has rate limits — don't retry aggressively).
- **URL won't resolve on a device:** that device isn't signed into the tailnet,
  or MagicDNS is off.
- **Works on WiFi, not cellular:** Tailscale isn't actually running on the phone
  (backgrounded / logged out).
- **PWA won't install:** you're on `http`/an IP instead of the `https://…ts.net`
  URL — service workers require the secure context.

## Access model reminder

The tradeoff is **on-your-tailnet vs. not**, *not* home-vs-away. Enrolled family
devices work from anywhere. A guest or an un-enrolled device can't reach it — the
only thing that would change that is Funnel/public exposure, which is **not**
part of this design (it would reverse the "Tailscale = perimeter" assumption in
DESIGN §1.4). See `01-tailscale-vs-lan.md`.
