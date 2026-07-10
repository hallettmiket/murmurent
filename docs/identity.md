# Identity & membership cards

Murmurent membership is a **signed certificate**, not an honour-system registry
entry. Every member, PI, and mayor holds an ed25519 key; membership is a card
signed along a chain of trust that mirrors the org:

```
centre root key  ──signs──▶  PI card  ──(PI's key) signs──▶  member card
   (the mayor)                (a lab PI / core leader)         (a group member)
```

A card only verifies if it was signed by the group's **real** PI. So you cannot
claim a group you're not in, and each person has a unique cryptographic ID (their
public-key **fingerprint**).

**A mayor is optional.** By default a PI is their **own root** — a lab runs
standalone (`murmurent pi-init`), the PI signs member cards, and members pin the
PI's key. When a lab *joins* a centre, the mayor adds a higher root: the centre
root signs the PI's card, so those same member cards also chain up to the centre
(only the trust anchor changes — nothing is re-issued). Your **key** is the
constant across both.

## Two ideas kept separate

- **A card attests *identity*** — "the centre root vouches that @yxia266 is a PI",
  "PI @yxia266 vouches that @allie is in xia_lab". It is verifiable offline.
- **Live *authorization* stays in the registry + Slack/GitHub ACLs.** Removing
  someone pulls their real access immediately; the card is corroborating identity,
  never a standalone key to the building. A revoked/expired card is refused, but a
  valid card by itself grants nothing the registry doesn't also say.

## Your key (everyone)

The first `murmurent` command you run after cloning mints your keypair under
`~/.murmurent/keys/` (0600). Its fingerprint is your unique ID.

```bash
murmurent identity-init          # explicit mint (idempotent; --rotate to replace)
murmurent whoami                 # your handle, key ID (fingerprint), and card status
```

Losing the key means re-enrolling; leaking it means someone can act as you until
the card is revoked — treat it like an SSH key.

## Joining a group (member)

```bash
murmurent enroll --group <group> --out enroll.json    # proves you hold your key (PoP)
# → send enroll.json to your PI (the command tells you how)
# ← they send back a signed card bundle + the trust root to pin
murmurent import-card bundle.json --trust-root <ed25519:…pubkey>
murmurent whoami                                       # now shows your group role
```

`--trust-root` is the group's (or centre's) published signing key; confirm its
fingerprint with the PI/mayor out-of-band the first time (see `centre-pin`
below to fetch it from the public hub instead).

**Sending `enroll.json` to your PI** is unauthenticated hand-off — murmurent
can't automate the member→PI leg, since the PI has to be the one who decides
to trust you. `enroll` prints the concrete next step: if you're already in
your lab's Slack workspace (you usually are), **DM your PI the file
directly**; otherwise email or paste it works fine too. Either way your PI
needs the file/JSON in hand before they can run `issue-member-card`.

## Vouching for a member (PI / group registrar)

```bash
murmurent issue-member-card enroll.json --group <group>
```

Signs the member's card with **your** key and bundles your PI card so the member
can verify the whole chain. You can only issue for a group you lead.

**Sending the bundle back is where Slack *is* automated** — the leg from PI
back to member goes through the group's own bot token, which you (the PI)
control, so murmurent can safely send it for you. By default this command:

1. reads the member's email from their enrollment request,
2. resolves it to a Slack user id in your lab's workspace (via
   `murmurent group-slack-setup`'s token),
3. DMs them the bundle + the exact `import-card` command to run.

If your lab's Slack isn't connected, or the lookup fails, it falls back to
printing the bundle for you to send by hand — nothing is lost, you just do
that last step yourself. Pass `--dm <slack_user_id>` to target a known user
id directly (skips the email lookup), or `--out bundle.json` to also write
the bundle to disk, or `--no-dm` to always skip Slack.

## Run a lab standalone (PI, no mayor)

You self-issue your own PI ID and become your lab's root — no centre needed:

```bash
murmurent pi-init <your-lab>      # prints a trust root; give it to your members
```

Now issue member cards as above; members import with
`murmurent import-card <bundle> --trust-root <your-trust-root>`. If you later join a
centre, the mayor issues you a **separate** centre PI card attesting the same key
(see below) — your members keep working, they just gain a higher anchor.

## Onboarding a PI into a centre (mayor / admin registrar)

```bash
# one-time: create the centre's root signing key (the CA)
murmurent centre-root-keygen           # BACK IT UP OFFLINE — see docs/centre_root_key.md

# for each PI (after their lab/core exists + they send you enroll.json):
murmurent issue-pi-card enroll.json --actor @<you> --out pi_card.json
# → send pi_card.json + your centre's signing recipient to the PI
```

## Publishing + fetching trust material

The centre publishes its **public** keys (age + signing) and its revocation list
to the public hub; members fetch and pin them.

```bash
# mayor: publish signing key + CRL alongside the directory listing
murmurent centre-hub-publish [--submit]

# member: fetch the centre's signing key + CRL from a local murmurent_public clone,
# pin the anchor (confirm the fingerprint out-of-band), and enable revocation
murmurent centre-pin <unique-name> --fingerprint <SHA256:…>
```

## Revocation

Cards have a 90-day TTL, so revocation is explicit and **fail-closed** — a
verifier with no fresh CRL refuses the card.

```bash
murmurent revoke --handle <handle>          # or --card-id / --fingerprint (mayor)
murmurent crl --out crl.json                # export the signed CRL to publish
```

`murmurent group-remove-member` also revokes the departing member's card as
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
(separate `MURMURENT_HOME` roots) and runs the whole lifecycle including a
revocation. Related: `docs/centre_root_key.md` (root-key handling + rotation).
