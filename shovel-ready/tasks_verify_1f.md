# Task: Verify end-to-end — PLAN checkpoint 1f (manual smoke test)

> **Run on:** host + a phone. Manual smoke test — **not** automated. Verify once,
> then trust. Prereqs: `tasks_tailscale_host_serve.md` complete.

## Test in widening circles (so failures isolate)

- [ ] **A — host, local:** on the host, open `http://127.0.0.1:8000/health` →
      app runs at all (no Tailscale involved).
- [ ] **B — host, via Serve URL:** on the host, open
      `https://calendar-host.<tailnet>.ts.net` → `tailscale serve` + cert work
      (valid HTTPS, no browser warning).
- [ ] **C — second device, same WiFi:** phone on the tailnet, at home, opens the
      `.ts.net` URL → MagicDNS resolves, another device reaches it privately.
- [ ] **D — off-network (the real one):** phone on **cellular** (off home WiFi),
      Tailscale running, opens the URL → proves "add from work" (R2).
- [ ] **E — PWA install:** phone → "Add to Home Screen" → launch from icon →
      opens full-screen (service worker registered — only possible via valid
      HTTPS). *(Only meaningful once the app ships a PWA manifest + service
      worker; if scaffold is still bare, defer E.)*

## Pass criteria

- [ ] Valid cert (no warning) from a second device **both on and off** home WiFi.
- [ ] Home-screen icon launches full-screen (when PWA assets exist).

## If it fails

- **Cert warning / not valid:** HTTPS not enabled in admin console, or cert still
  provisioning (wait; Let's Encrypt rate limits — don't retry aggressively).
- **URL won't resolve on a device:** device not signed into the tailnet, or
  MagicDNS off.
- **Works on WiFi, not cellular:** Tailscale not actually running on the phone
  (backgrounded / logged out).
- **PWA won't install:** hitting `http`/an IP instead of the `https://…ts.net`
  URL — service workers need the secure context.

## Access model reminder

Tradeoff is **on-your-tailnet vs. not**, not home-vs-away. Enrolled devices work
from anywhere; guests / un-enrolled devices can't reach it (by design — Funnel /
public exposure is NOT part of this design; it would reverse the
"Tailscale = perimeter" assumption, DESIGN §1.4).
