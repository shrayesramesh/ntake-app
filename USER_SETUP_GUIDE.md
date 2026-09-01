# Family Calendar — Device Setup Guide

> **For:** a family member setting up the calendar on their phone or the wall
> tablet. One-time setup; after this you just tap the app icon.
>
> **Status: TEMPLATE / draft.** Some details below can't be finalized until the
> app is built and running (the real URL, whether there's an in-app sign-in
> screen, exact per-phone menu wording). Blanks are marked `<FILL IN>`. Finalize
> before sharing with the family.

---

## What you're setting up (30 seconds of context)

The family calendar runs on our home computer, kept private. To use it on your
phone you do two one-time things:

1. **Install Tailscale** — a small app that securely connects your phone to our
   home computer (think of it as a private tunnel; you set it up once and forget
   it).
2. **Add the calendar to your home screen** — so it opens full-screen like a
   normal app.

After that, you just tap the calendar icon. You never open Tailscale directly —
it runs quietly in the background.

**Why the extra app?** It's what keeps the calendar private to our family and
lets it work when you're away from home (at work, out and about). It is *not* a
per-use step — install once, leave it on.

---

## Step 1 — Install Tailscale and join our network

- [ ] Install **Tailscale** from your phone's app store
      (iPhone: App Store · Android: Google Play).
- [ ] Open it and **sign in** using: `<FILL IN: which login the family uses —
      e.g. "the shared Google account xyz@gmail.com" or "I'll send you an invite
      link">`.
      > *Builder note:* decide the family enrollment method — a shared login, or
      > sending each person a Tailscale **invite link** to join the tailnet under
      > their own login. Fill this in once decided.
- [ ] Allow it to set up the VPN connection when your phone asks
      (iOS: "Allow" the VPN configuration · Android: "OK" the VPN request).
- [ ] Leave Tailscale **turned on**. You can close the app — it keeps running in
      the background. (You should see a small VPN/key indicator; that's normal.)

**Check:** the Tailscale app shows you as **connected**.

---

## Step 2 — Open the calendar and add it to your home screen

- [ ] In your phone's browser, go to:
      **`https://<FILL IN: e.g. calendar-host.your-tailnet.ts.net>`**
      > *Builder note:* this is the `tailscale serve` URL from
      > `shovel-ready/tasks_tailscale_host_serve.md`. Paste the real one here.
- [ ] `<FILL IN: sign-in / enrollment step, if any — e.g. "tap your name" or
      "enter the setup code I give you">`
      > *Builder note:* this depends on the auth model (per-device token /
      > enrollment, DESIGN §1.4). Fill in the real user-facing step once built.
- [ ] Add it to your home screen:
      - **iPhone (Safari):** tap the **Share** button → **Add to Home Screen** →
        **Add**.
      - **Android (Chrome):** tap the **⋮** menu → **Add to Home screen** (or
        **Install app**) → **Add / Install**.
- [ ] Tap the new **Family Calendar** icon on your home screen — it should open
      full-screen, like an app.

**Check:** the calendar opens full-screen from the icon and shows our events /
todos.

---

## Everyday use

- Just tap the **Family Calendar** icon. That's it.
- It updates live — things others add show up automatically.
- Works at home and away, as long as Tailscale is on (it stays on by itself).

---

## If something's not working

- **Calendar won't load / "can't reach the site":**
  - Make sure **Tailscale is on** (open the Tailscale app; it should say
    connected). This is the #1 cause.
  - If you just installed it, give it a moment and try again.
- **Browser warns the site isn't secure:** `<FILL IN / builder note: should not
  happen once HTTPS is set up; if it does, tell the setup owner — it's a cert
  issue, not something to click past>`.
- **The home-screen icon opens a browser bar instead of full-screen:** you may
  have added a plain bookmark — remove it and redo Step 2 using **Add to Home
  Screen** from the browser menu.
- **Still stuck:** contact `<FILL IN: household setup owner / you>`.

---

## Builder checklist before sharing this guide

- [ ] Fill every `<FILL IN>` (real URL, sign-in method, enrollment login).
- [ ] Confirm the per-OS "Add to Home Screen" wording against current iOS/Android
      (menu labels drift).
- [ ] Confirm the PWA actually installs full-screen (needs manifest + service
      worker shipped — PLAN Phase 5 / F-DISP).
- [ ] Decide + document the enrollment method (shared login vs. per-user invite).
- [ ] Remove all `> *Builder note:*` lines from the family-facing version.
