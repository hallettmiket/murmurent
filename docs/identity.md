# Identity & membership cards

Wigamig membership is a **signed certificate**, not an honour-system registry
entry. Every member, PI, and mayor holds an ed25519 key; membership is a card
signed along a chain of trust that mirrors the org:

```
centre root key  ──signs──▶  PI card  ──(PI's key) signs──▶  member card
   (the mayor)                (a lab PI / core leader)         (a group member)
```

A card only verifies if it was signed by the group's **real** PI, whose own card
was signed by the **centre root**. So you cannot claim a group you're not in, and
each person has a unique cryptographic ID (their public-key **fingerprint**).

## Two ideas kept separate

- **A card attests *identity*** — "the centre root vouches that @yxia266 is a PI",
  "PI @yxia266 vouches that @allie is in xia_lab". It is verifiable offline.
- **Live *authorization* stays in the registry + Slack/GitHub ACLs.** Removing
  someone pulls their real access immediately; the card is corroborating identity,
  never a standalone key to the building. A revoked/expired card is refused, but a
  valid card by itself grants nothing the registry doesn't also say.

## Your key (everyone)

The first `wigamig` command you run after cloning mints your keypair under
`~/.wigamig/keys/` (0600). Its fingerprint is your unique ID.

```bash
wigamig identity-init          # explicit mint (idempotent; --rotate to replace)
wigamig whoami                 # your handle, key ID (fingerprint), and card status
```

Losing the key means re-enrolling; leaking it means someone can act as you until
the card is revoked — treat it like an SSH key.

## Joining a group (member)

```bash
wigamig enroll --group <group> --out enroll.json    # proves you hold your key (PoP)
# → send enroll.json to your PI
# ← they send back a signed card bundle (bundle.json) + the centre's fingerprint
wigamig import-card bundle.json --trust-root <ed25519:…pubkey>
wigamig whoami                                       # now shows your group role
```

`--trust-root` is the centre's published signing key; confirm its fingerprint
with the mayor/PI out-of-band the first time (see `centre-pin` below to fetch it
from the public hub instead).

## Vouching for a member (PI / group registrar)

```bash
wigamig issue-member-card enroll.json --group <group> --out bundle.json
```

Signs the member's card with **your** key and bundles your PI card so the member
can verify the whole chain. You can only issue for a group you lead.

## Onboarding a PI (mayor / admin registrar)

```bash
# one-time: create the centre's root signing key (the CA)
wigamig centre-root-keygen           # BACK IT UP OFFLINE — see docs/centre_root_key.md

# for each PI (after their lab/core exists + they send you enroll.json):
wigamig issue-pi-card enroll.json --actor @<you> --out pi_card.json
# → send pi_card.json + your centre's signing recipient to the PI
```

## Publishing + fetching trust material

The centre publishes its **public** keys (age + signing) and its revocation list
to the public hub; members fetch and pin them.

```bash
# mayor: publish signing key + CRL alongside the directory listing
wigamig centre-hub-publish [--submit]

# member: fetch the centre's signing key + CRL from a local wigamig_public clone,
# pin the anchor (confirm the fingerprint out-of-band), and enable revocation
wigamig centre-pin <unique-name> --fingerprint <SHA256:…>
```

## Revocation

Cards have a 90-day TTL, so revocation is explicit and **fail-closed** — a
verifier with no fresh CRL refuses the card.

```bash
wigamig revoke --handle <handle>          # or --card-id / --fingerprint (mayor)
wigamig crl --out crl.json                # export the signed CRL to publish
```

`wigamig group-remove-member` also revokes the departing member's card as
defense-in-depth (after pulling their Slack/GitHub access). Revocation is
mayor-centric (the CRL is root-signed); members see a revocation once they
`centre-pin`/re-fetch the updated CRL.

## What the dashboard enforces

Opening the dashboard checks, in order: the signed-in netname matches this
machine's card owner; the stored card still **verifies** (chain to the pinned
root, not expired, not revoked when a CRL is present, not tampered); and the
registry actually claims this identity. Any failure → refused.

## Try it end-to-end

`scripts/identity_smoke.sh` simulates a mayor, a PI, and a member on one machine
(separate `WIGAMIG_HOME` roots) and runs the whole lifecycle including a
revocation. Related: `docs/centre_root_key.md` (root-key handling + rotation).
