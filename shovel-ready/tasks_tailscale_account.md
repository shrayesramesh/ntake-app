# Task: Tailscale account & tailnet setup

> **Run on:** any **personal** device with a browser (NOT a corp/work machine or
> network). Browser-only; no home PC needed yet. Independent of the other tasks —
> do it anytime.

## Steps

- [ ] Create a Tailscale account at `login.tailscale.com/start` (personal plan,
      free; ample for 2–4 devices). Sign in with any supported identity provider.
- [ ] Admin console → **DNS** page → **Enable MagicDNS**.
- [ ] Same DNS page → **Enable HTTPS** (turns on Let's Encrypt cert
      provisioning). Acknowledge the notice that machine + tailnet names get
      published to the public Certificate Transparency ledger.
- [ ] Set a **randomized tailnet name** (e.g. `yak-bebop.ts.net`) — privacy: keeps
      identifying info out of the CT ledger. (Custom names aren't supported here;
      random is the recommended pick. See `../research/02-tailscale-setup-and-test.md`.)

## Done when

- [ ] Account exists, MagicDNS + HTTPS enabled, tailnet name is the randomized one.
- [ ] Note the tailnet name for later: `______________________.ts.net`

## Notes / caveats

- Admin-console labels drift; anchors are **MagicDNS**, **Enable HTTPS**,
  **tailnet name**.
- No domain to register, nothing to buy.
