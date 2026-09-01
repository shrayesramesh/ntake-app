# Why Tailscale rather than plain same-WiFi LAN?

> **Type: research** (rationale capture; no new decision — the topology is
> already decided in DESIGN §1). Answers the recurring "if everyone's on the same
> WiFi, why do we need Tailscale?" question.

## Short answer

Same-WiFi LAN solves **connectivity** (devices can reach the home PC by local
IP). It does **not** cleanly solve two things this app needs, and Tailscale does
both for near-zero effort:

1. **HTTPS for the PWA (the decisive reason).**
2. **Access from outside the house.**

Plus a minor third (stable addressing/identity).

## 1. HTTPS / the PWA requirement — the big one

A PWA's **service worker** (offline caching, "add to home screen" kiosk
behavior) **requires a secure context (HTTPS)**. On a bare LAN the app is served
at `http://192.168.x.y:8000`, which is **not** a secure context, so the service
worker won't register and PWA features break (F-DISP-04 kiosk behavior depends on
this).

Getting a *valid* TLS cert for a private LAN IP is genuinely painful: public CAs
won't issue certificates for RFC-1918 addresses, so you'd hand-roll self-signed
certs and install/trust them on every device. Tailscale's `tailscale serve` hands
you a valid, **auto-renewing Let's Encrypt cert** for `<machine>.<tailnet>.ts.net`
for free (see DESIGN §1.6).

**So Tailscale is mostly solving the HTTPS problem, not the connectivity
problem** — and HTTPS is a hard PWA requirement, not a nice-to-have. This reason
alone justifies it.

## 2. Access from outside the house

Same-WiFi assumes everyone is home. The moment someone adds "dentist Tuesday 3pm"
from the office, a store, or the commute, LAN-only cannot reach the home PC.
Tailscale makes the home PC reachable from anywhere the phone has internet, still
privately. The core value prop is "capture from wherever you are" (R2), so
LAN-only quietly kills the on-the-go case.

*How much this matters depends on usage:* if capture only ever happens at home,
this reason weakens — but #1 (HTTPS) still stands on its own.

## 3. Stable addressing + identity (minor)

LAN IPs shift with DHCP (`192.168.1.42` today, `.51` next week), breaking the
display's configured URL and bookmarks. Tailscale gives a stable
`machine.tailnet.ts.net` name, plus verified identity headers (DESIGN §1.6
research). Minor next to #1 and #2, but real.

## Honest counterpoint

If you decided you would *only* add/view at home **and** were willing to fight
self-signed certs (or accept a degraded, non-PWA plain-HTTP page), you could skip
Tailscale. That trades away the PWA (kiosk/offline) **and** off-home capture to
save one `tailscale up`. For the effort Tailscale costs, that's a poor trade —
#1 alone usually justifies keeping it.

## Bottom line

Same WiFi handles **connectivity**; Tailscale earns its place as the **HTTPS
provider** (PWA-enabling) and the **off-network reach** path — neither of which
bare LAN gives cleanly.
