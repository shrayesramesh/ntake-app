# Dashboard hardware — prototype on iPad, upgrade to a larger display later

> **Type: decision (staged) + research.** The wall display hardware (DESIGN §6).
> **Decision: prototype on the existing iPad now; re-evaluate a larger display
> after living with it.** Options + the key firmware landmine captured below.

## Staged decision

- **Now — prototype on the existing iPad 7th gen (A2197, 10.2").** Free; proves
  the *software* (PWA renders, kiosk/Guided Access works, Tailscale connects,
  layout is readable) before spending on hardware.
- **Later — likely upgrade to a larger display** (see size analysis). Defer the
  size/firmware decision until the prototype tells you what "big enough" means in
  the actual kitchen.

Rationale: the iPad de-risks the software at zero cost; the size/firmware choice
is the expensive, gamble-prone part, so buy it *after* the app is proven on a
wall, not before.

## Size analysis (why the iPad likely isn't the final display)

- Target: the current fridge paper calendar is ~**15"×17"**.
- Screen sizes are **diagonal**, ~16:9. The iPad 10.2" is only ~**8"×6"** of
  glass — roughly **4× less area** than the paper calendar. Confirmed too small
  for the same glanceable presence.
- To match the fridge-calendar *presence*, aim ~**24"–27" diagonal**. A 15.6"
  tablet (~13.5"×7.6") is a middle step but still shorter than the paper
  calendar.

## The iPad as prototype — why it's a good proving device

- **iPadOS 18** (its max; last iPad w/o a Neural Engine) → **current Safari**, so
  the **PWA renders properly**. (Advantage over random old Android tablets stuck
  on ancient browser engines.)
- **Guided Access** = built-in kiosk lock to a single app; on every iPad, no MDM
  needed. (Unsupervised personal iPad → Guided Access only, which is fine here;
  full Single-App-Mode needs supervision/MDM.)
- **Runs Tailscale** (current iPadOS).
- Setup for prototype: install Tailscale + open the PWA → Add to Home Screen →
  Guided Access on → disable auto-lock/sleep.

## Upgrade options (evaluate after prototype)

### Option A — Large "smart calendar" device running open Android (24"–27")
- Examples: **Apolosign**, **Cozyla**, **EMOLENDAR** (24"/27", wall-mount
  included, often **subscription-free**, advertise "install apps & widgets").
- **Attraction:** right size, purpose-built for wall use (auto-brightness,
  portrait/landscape, always-on), one clean unit.
- **⚠ MAKE-OR-BREAK CAVEAT — verify before buying:** it must run **real Android
  with a browser (Chrome) + arbitrary APK sideload (incl. Tailscale)** — NOT a
  locked launcher that only runs the vendor's app store. "Supports app store" ≠
  "runs any app." **Skylight is explicitly locked** (already ruled out for this).
  Ask the vendor directly: *"Can I install Chrome and sideload an arbitrary APK
  like Tailscale?"* This firmware openness is the entire risk of Option A.

### Option B — 15.6" Android tablet (middle ground)
- Real category (~$150–300), open Android → PWA + Tailscale **definitely** work,
  VESA-mountable.
- Con: 15.6" is bigger than the iPad but still smaller than the paper calendar's
  presence.

### Option C — Touchscreen (or plain) monitor + mini-PC / Pi (max size & control)
- 24–27" monitor driven by a cheap mini-PC/Pi running a browser in kiosk mode.
- **Pros:** any size; fully open (just a browser on a real OS → PWA + Tailscale
  trivially); no firmware-lock gamble.
- **Cons:** most assembly (monitor + compute + mount + cabling + power).
- **Read-mostly insight (F-DISP-05):** since the display is read-mostly and
  mutations happen on phones, a **non-touch** monitor is acceptable — saves money
  and widens monitor choice. Touch is optional here.

## Recommendation (for the eventual upgrade)

- Lean **Option C** for a safe big-screen play (no firmware gamble; read-mostly
  means touch is optional), **or Option A** for a tidier single-unit look **iff**
  the open-Android / Chrome + Tailscale + APK spec is confirmed on the specific
  model.
- Ruled out: **e-paper** (slow refresh conflicts with live SSE updates, F-DISP-02),
  buying a new small tablet (weaker browser than the iPad you own), **Skylight**
  (locked firmware, not extensible).

## Power / always-on note

A wall display runs 24/7. Permanent charging wears tablet batteries over years
(acceptable for a free prototype iPad; a factor for a purchased device — some
purpose-built units handle this better). Mount near an outlet; disable
sleep/auto-lock.

## Related

- Display role & read-mostly: DESIGN §6 / F-DISP-05.
- Live updates (why not e-paper): DESIGN §5.4 / F-DISP-02 (SSE).
- Every display needs Tailscale: `01-tailscale-vs-lan.md`,
  `02-tailscale-setup-and-test.md`.
