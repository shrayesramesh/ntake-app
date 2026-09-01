# Family Calendar + Todo Board — Deferred Text Channel (SMS / Bot)

> **Status: DEFERRED — not part of the launch build.** The launch capture +
> management surface is the **PWA** (DESIGN §6; OQ-CAP resolved PWA-first in
> REQUIREMENTS §3.1). This document is parked here, separate from the launch
> design, so the main [DESIGN.md](./DESIGN.md) reflects only what is being built.
>
> When/if a no-install text channel is revisited, the channel choice includes
> **SMS** (universal; paid + A2P + stateless) vs. a **bot like Telegram** (free,
> tappable confirm/disambiguate buttons, but requires that app). The SMS design
> below is the worked example.
>
> **Adding this channel reintroduces parked complexity:** public ingress
> (DESIGN §1.3), the stateful-conversation model (G6), free-text parsing as the
> *primary* path, entity resolution (G7), A2P registration, and the
> phone-number allowlist. It satisfies **F-CAP / F-QRY / F-SAFE** for a text
> channel when built.

The SMS bot is a self-contained arc: it can be built, tested, and shipped largely
independently of the display UI, as long as the shared backend (parser + domain
actions + datastore) exists.

## 1. Goal & scope

Let an allowlisted family member text a dedicated number in natural language and
have it become a calendar event or todo, with a confirmation reply.

- **In scope:** inbound SMS → parse → create/query → reply; sender allowlisting;
  A2P registration; safe additive commands.
- **Out of scope (initially):** rich media/MMS, interactive buttons (a possible
  future messaging channel), effortless destructive commands over SMS, group MMS
  threads. (Aligns with REQUIREMENTS §6 non-goals.)

## 2. Provider

- **Default: Twilio** — mature API, first-class webhooks, guided 10DLC/toll-free
  registration in-console.
- **Alternative:** AWS End User Messaging / Pinpoint, if keeping everything in
  AWS (ties to the DESIGN §1 hosting decision — note the launch decision is
  home-hosted, so this would be a change).
- Requires one dedicated phone number owned by the family.

## 3. Message flow

```
Family member's phone
        │  (SMS)
        ▼
   Twilio (receives SMS on the family number)
        │  webhook (HTTPS POST)
        ▼
   SMS webhook endpoint (backend)
        │  1. verify Twilio signature
        │  2. check sender against allowlist      ─► not allowed ─► ignore / "not authorized"
        │  3. parse message → intent + slots      (DESIGN §3)
        │  4. execute domain action (CRUD)        (DESIGN §4 data model, §5 flows)
        │  5. persist to family DB                (syncs to all devices)
        ▼
   Reply SMS ("✅ Added 'milk' to Groceries")     (F-CAP-06; policy OQ-CAP-CONF)
```

> **Ingress note:** the launch topology (DESIGN §1.2) uses a private Tailscale
> mesh with **no public webhook**. A text channel needs the provider to reach the
> backend — via a tunnel (e.g. Cloudflare Tunnel) rather than raw home-IP
> exposure. This is the main infrastructure delta versus the launch build.

## 4. Command grammar (initial)

Natural language parsed into the shared intent model. This grammar is the SMS
surface of the generalized CRUD triage (DESIGN §5.1).

| Example text | Entity / Op | Result | Requirement |
|---|---|---|---|
| `add milk to groceries` | Todo / Update | Append "milk" to the checklist on "Groceries" (creates card if absent) | F-CAP-03 |
| `add task buy tickets` | Todo / Create | New card "buy tickets" in To Do | F-CAP-02 |
| `move groceries to done` | Todo / Update | Move "Groceries" card to Done | F-TODO-02 |
| `done with dentist` | Todo / Update | Mark/move the matching card done | F-TODO-03 |
| `delete buy tickets` | Todo / Delete | Remove the card *(⚠ gated — §5, F-SAFE-02)* | F-TODO-07 |
| `dentist Tuesday 3pm` | Event / Create | Event "dentist" next Tue 15:00 | F-CAP-01 |
| `move dentist to Friday 4pm` | Event / Update | Reschedule the matching event | F-EVT-02 |
| `cancel dentist` | Event / Delete | Remove/cancel the event *(⚠ gated)* | F-EVT-03 |
| `what's on today?` | Event / Read | Reply with today's events/todos | F-QRY-01 |
| `help` | — | Reply with example commands | — |

Ambiguous or unparseable messages get a friendly clarification reply
(F-CAP-05) rather than silent failure. Note the single-board model (DESIGN §4.2):
"add X to \<name\>" appends a **checklist item** to an existing card; it does not
create a list. Distinguishing "add a card" vs. "add a checklist item" is a parser
responsibility.

## 5. Security model (channel-level)

Implements F-SAFE for the messaging channel. The number is a locked door that
only recognizes family:

1. **Sender allowlist (primary control).** Backend checks inbound sender against
   approved numbers. **This is where `members.phone_number` regains a security
   role** (at launch, under PWA + token auth, it is just a contact field —
   DESIGN §4.3). Unknown senders are ignored — no parsing, no action, no
   disclosure.
2. **No self-enrollment (F-MEMBER-02).** Numbers are added only by an admin
   through the management surface, never by texting the bot.
3. **No data leakage.** Unknown senders get nothing back.
4. **Provider signature verification.** Validate the Twilio request signature so
   only the provider can invoke the webhook.
5. **Safe-by-default commands (F-SAFE-02).** Additive/query actions are open;
   destructive actions are gated (OQ-DEL-POLICY; stateful mechanics in §6).

**Accepted residual risks (appropriate at family scale):**
- **Sender-ID spoofing** — uncommon, high-effort, near-zero payoff (a fake todo).
- **Compromised family phone** — a device-security problem, out of scope.

## 6. Stateful conversation — confirmation & disambiguation (G6)

> This is the complexity the PWA-first launch **avoids** (a UI dialog confirms
> directly). It returns only with a stateless text channel.

Both confirmation ("Reply YES to delete 'dentist'") and disambiguation ("did you
mean the Tue or Thu dentist?") require the backend to hold **pending-operation
state keyed to the sender**, because SMS is stateless. An adequate design must
define:

- **State store** — pending op per sender (entity, op, resolved target(s),
  created-at).
- **Expiry** — how long a pending confirmation stays valid.
- **Non-affirmative follow-ups** — what happens if the next message isn't "YES"
  (new command? cancel the pending op?).
- **Concurrency** — more than one pending op per sender?

A bot channel with **tappable buttons** (e.g. Telegram inline keyboards) reduces
this to a button press instead of the "reply YES" state machine — a reason to
prefer it over raw SMS if this channel is built.

## 7. Entity resolution (G7)

> Also largely dissolved by the PWA (the user taps the target). Returns with the
> text channel.

Read/Update/Delete must identify *which* existing event(s)/todo(s) a message
refers to ("move groceries to done", "cancel the dentist appointment"). This is a
distinct, harder capability than Create and the main parsing risk. Undefined
matching rules to design: title-keyword match, most-recent, date-scoping,
reply-to-confirmation. If confidence is low, disambiguate (§6) rather than guess.

## 8. A2P / 10DLC registration

US carriers require registration of application-to-person SMS (anti-spam).

- **One-time setup, not ongoing burden** (aligns with NFR-EFFORT).
- **Sole-proprietor / low-volume path** fits a family bot — no business/EIN
  required, low cost, low throughput.
- **Lighter alternative: toll-free number** — A2P with a lighter *verification*
  process instead of full 10DLC brand/campaign registration.
- **Decision pending:** 10DLC (standard local number) vs. toll-free verification.

## 9. Components to build

- **SMS webhook endpoint** — receives provider webhooks, verifies signature.
- **Public ingress** — tunnel to the home backend (see §3 ingress note).
- **Allowlist check** — enforced first, against member phone numbers.
- **Intent parser** — text → intent + slots (shared with the PWA free-text path;
  DESIGN §3).
- **Domain actions** — CRUD on events/todos; persist to family DB.
- **Reply formatter** — concise SMS confirmations and clarifications.
- **Stateful-conversation store** — for confirmation/disambiguation (§6).
- **Provider account + number + A2P registration** — operational setup.

## 10. Phased delivery

- **Phase 1 — Echo & auth:** provision number, webhook receives SMS, signature
  verified, allowlist enforced, replies "got it." Proves the pipe end-to-end.
- **Phase 2 — Core intents:** add todo, add event, `help`; confirmation replies.
- **Phase 3 — Queries & NLP polish:** "what's on today?", date/time parsing,
  clarification on ambiguity.
- **Phase 4 — Hardening & registration:** finalize A2P/toll-free, error handling,
  rate limiting, logging/observability, idempotency (DESIGN §5.3).

## 11. Open questions (SMS-specific)

- [ ] **Provider** — Twilio vs. AWS End User Messaging/Pinpoint vs. a bot channel
      (Telegram)?
- [ ] **Number type** — 10DLC local number vs. toll-free verification?
- [ ] **Confirmations** — always reply vs. only on ambiguity/failure (OQ-CAP-CONF,
      NFR-COST)?
- [ ] **Query at launch** — is read-back in the first release (OQ-CAP-QUERY)?

---

## Change Log

- **2026-08-30** — **Extracted from DESIGN.md §2** so the launch design reflects
  only the PWA-first build. Folded the previously-separate stateful-conversation
  (G6) and entity-resolution (G7) design notes into this deferred channel, since
  they are the complexity this channel reintroduces. Added an ingress note
  reconciling with the launch Tailscale topology.
