# Identity & membership cards

## How Murmurent is organized

> Diagram: [tier architecture](diagrams.md#1-tier-architecture) sketches centre → group → project → member.

Before any cryptography: the shape. A **centre** is the top-level Murmurent
installation for an institution (or a standalone lab that never joins one). A
centre contains one or more **groups**, which are **labs** and **cores**, each
led by a PI or core leader. A group runs one or more **projects**, and a
project (or the group itself) has **members**, the people doing the work.

Everything on this page is about **identity and trust**: how Murmurent proves
that a given person really is who they claim to be, and really does belong to
the group or project they claim membership in. The mechanism is a chain of
signed certificates that mirrors this structure exactly: a centre vouches for
its PIs, a PI vouches for their members, and a project lead vouches for their
project's members.

This page follows the same reader order as the main [README](https://github.com/hallettmiket/murmurent/blob/main/README.md):
[Everyone] your key, [Members] joining a group, [PIs] running a lab, [PIs]
joining a centre, then the cross-cutting mechanics (membership levels,
publishing trust material, revocation).

## What a membership card is

A Murmurent membership card is a signed certificate: cryptographic proof that
a specific key belongs to a specific person, in a specific role, at a specific
group or centre. Every member, PI, and mayor holds an ed25519 key (a
public/private keypair used to sign and verify these certificates). Membership
is a card signed along a **chain** of trust, a sequence of signatures, that
mirrors the structure above:

```
centre root key  --signs-->  PI card  --(PI's key) signs-->  member card
   (the mayor)                (a lab PI / core leader)         (a group member)
```

Each card added beneath the root is one more **level**: a new link in the
chain, signed by the card immediately above it. A card verifies only when it
was signed by the group's real PI (or the centre's real root), so it proves
genuine membership in that specific group. Each person's public key has a
unique **fingerprint** (a short hash of the key, used as their cryptographic
ID), so identity claims stay unambiguous.

A mayor is optional. By default a PI is their own root: a lab runs standalone
(`murmurent pi-init`), the PI signs member cards, and members pin the PI's key
as their **trust root** (also called a trust anchor: the public key treated as
the top of the chain when verifying every card beneath it). When a lab later
joins a centre, the mayor adds a higher root: the centre root signs the PI's
card, so those same member cards chain up to the centre too, and only the
trust anchor changes. The PI's key is the constant across both setups.

## Card identity vs. live access

A card proves identity: "the centre root vouches that @the_pi is a PI", "PI
@the_pi vouches that @member_a is in example_lab". Anyone holding the right
public key can verify a card offline, without contacting Murmurent at all.

Live access comes from the registry plus Slack and GitHub access-control lists
(ACLs); that is what actually lets someone read a channel, clone a repo, or
open a dashboard. The dashboard's login check requires both a verifying card
and a matching registry entry, so removing a member from the registry (or
their Slack/GitHub group) cuts their real access immediately, independent of
their card's own status. Revoking or expiring the card is a second,
defense-in-depth layer: once a card is revoked or expired, it stops
verifying, so it can no longer corroborate that person's identity going
forward.

## [Everyone] Your key

Any `murmurent` command mints this machine's ed25519 keypair the first time
you run it (stored under `~/.murmurent/keys/`, file mode 0600); its
fingerprint is your unique ID. In practice, the first command you actually run
is `murmurent init`, the one-time session setup described in the README: it
prompts for your handle, name, email, official (institutional) handle, GitHub
username, and Slack handle, and asks you to choose a role (member, PI, or
mayor), minting your key as its first step if one does not exist yet.

A trimmed transcript for a new member:

```
$ murmurent init
Welcome to murmurent. Let's set up your session.

  your identity key (unique ID): SHA256:2b7ecf...c4d1

Your handle (username): member_a

What is your role?
  1. Member: you work in a lab/core that already uses murmurent
  2. PI: you lead a lab or core
  3. Mayor: you're setting up murmurent for a whole institution
Choose [1]: 1

Your full name: Member A
Your email: member_a@example.edu
Your official / institutional handle (e.g. your Western netname; may differ
from the murmurent handle above) [member_a]: member_a
Your GitHub username (optional):
Your Slack username or member ID (optional, lets your PI DM your ID card
straight back to you): member_a

  saved your profile to ~/.murmurent/profile.yaml

(you're also offered to create your personal Obsidian vault here; accept or
skip, either is fine)

Next steps:
  - Ask your PI for a membership ID (a signed certificate).
  - Import it:  murmurent import-card <file> --trust-root <centre-signing-key>

Done. Re-run `murmurent init` any time to change your role or info.
```

If you ever need to mint or replace the key on its own, without the full
session setup, `murmurent identity-init` does just that (idempotent;
`--rotate` replaces an existing key, which then needs a freshly re-issued
card):

```bash
murmurent identity-init          # explicit mint (idempotent; --rotate to replace)
murmurent whoami                 # your handle, key ID (fingerprint), and card status
```

Losing the key means re-enrolling; leaking it means someone can act as you
until the card is revoked. Treat it like an SSH key.

## [Members] Join a group

> Diagram: the [onboarding sequence](diagrams.md#5-onboarding-sequence) shows this whole flow at a glance.

```
$ murmurent enroll --group example_lab --out enroll.json
  wrote enrollment request for @member_a to enroll.json

Send the file enroll.json to your PI, they lead 'example_lab' and are who
signs your member ID:
  - On Slack: DM your PI directly (you're already in their lab's workspace),
    attach the file, or paste its contents in.
  - They run:  murmurent issue-member-card enroll.json --group example_lab
  - If their lab's Slack is connected (group-slack-setup), murmurent DMs your
    signed card straight back to you; otherwise they send it to you by email.
  - Either way, you finish with:  murmurent import-card <bundle-file>
    --trust-root <the root they give you>
```

Sending `enroll.json` to your PI is a plain, unauthenticated hand-off: DM your
PI the file directly on Slack (you're already in your lab's workspace, so no
extra sign-up is needed). Your PI needs the file in hand before they can run
`issue-member-card`, since deciding to trust you is their call to make.

Once your PI issues your card, you receive a bundle (your member card plus
their PI card, so you can verify the whole chain). Save it as a file, e.g.
`bundle.json`:

```json
{
  "member_card": {
    "payload": {"subject": {"handle": "@member_a", "fingerprint": "SHA256:jo8Aqfe6In..."}, "group": "example_lab"},
    "signature": "..."
  },
  "pi_card": {
    "payload": {"subject": {"handle": "@the_pi", "pubkey": "ed25519:Rgmuqeen5X3lW4pFV8GHVFafw0ozSxGk+uUeLC279Fw="}},
    "signature": "..."
  }
}
```

The trust root is the `pubkey` value inside `pi_card`, here
`ed25519:Rgmuqeen5X3lW4pFV8GHVFafw0ozSxGk+uUeLC279Fw=`. Confirm that value
with your PI out-of-band (in person or by phone, not the same Slack message)
before you pin it:

```
$ murmurent import-card bundle.json --trust-root ed25519:Rgmuqeen5X3lW4pFV8GHVFafw0ozSxGk+uUeLC279Fw=
  card verified (@member_a, role: member, group: example_lab) and imported
  - stored the verified card under ~/.murmurent/cards/

Restart your murmurent dashboard; the login will now show your role.
```

Confirm it worked:

```
$ murmurent whoami
handle:   @member_a  (via profile)
key ID:   SHA256:2b7ecf...c4d1
card:     centre 'example_lab'; roles: member
```

`import-card` stores the verified card locally, so from now on Murmurent
knows you are a member of the lab.

## [PIs] Set up your lab standalone (no mayor needed)

You self-issue your own PI ID and become your lab's root; no centre required:

```
$ murmurent pi-init example_lab
  your PI ID for 'example_lab' is ready. You are this lab's root.
  Give members this trust root so they can import their cards:
    ed25519:8fN3kPQZ7hR2mLxW9vY4tS6uJ1oC5aB0eD3gH8iK2nM=

  Issue a member ID:  murmurent issue-member-card <their-enroll.json> --group example_lab

  Your lab's management repo (the roster's home) is now at:
    ~/repos/murmurent_lab_mgmt_example_lab

  Keep this name, murmurent_lab_mgmt_example_lab, on GitHub too. Push it
  private, then members get read-only access and clone it under the same
  name:
    gh repo create <you>/murmurent_lab_mgmt_example_lab --private \
      --source ~/repos/murmurent_lab_mgmt_example_lab --remote origin --push
    murmurent group-reconcile example_lab --apply   # grants the roster read access

  A mayor can also issue you a centre PI ID later; that's a separate step for
  joining a centre, and your members' cards keep working throughout.
```

Add `--core` instead of a bare lab name if this group is a core facility
(`murmurent pi-init example_core --core`). Once you have your trust root,
issue member cards as below; members import with `murmurent import-card
<bundle> --trust-root <your-trust-root>`. Connect your lab's Slack workspace
next, so member IDs travel by DM instead of by hand:

```bash
murmurent group-slack-setup example_lab
```

Full setup, including the Slack app's security scopes: [group_slack_setup.md](group_slack_setup.md).

## [PIs] Issue the member's card (vouching for them)

Next, the PI vouches for the member: once you hold the member's `enroll.json`
(they DM it to you on Slack, as above), sign their card.

```
$ murmurent issue-member-card enroll.json --group example_lab
  signed member card for @member_a (group example_lab)

  DM'd @member_a their card on Slack
```

This signs the member's card with your own key and bundles your PI card so
the member can verify the whole chain. You can only issue a card for a group
you lead.

Sending the bundle back is where Slack is automated: the leg from PI back to
member travels through the group's own bot token, which the PI controls, so
Murmurent can safely send it to the joiner. By default this command:

1. looks up the member's Slack account from the Slack handle they recorded at
   `murmurent init` (or in their enrollment request),
2. DMs them the bundle as a downloadable file, plus the exact `import-card`
   command to run,
3. falls back to an email-based lookup (`users.lookupByEmail`) only when no
   Slack handle is on file for that member.

When the lab's Slack workspace is still unconnected, Murmurent falls back to
an email exchange instead: it prints the bundle to your terminal, you save it
as a file (e.g. `bundle.json`), and email it to the member, who runs
`import-card` on the file they received. Pass `--dm <slack_user_id>` to
target a known Slack user id directly (skips both lookups), `--out
bundle.json` to also write the bundle to disk, or `--no-dm` to always use the
email path instead of Slack.

## [PIs] Registering your lab or core with an existing centre

Once your lab exists (standalone, as above, or freshly created), you can also
register it under a centre's higher trust root. The mayor operates a
**certificate authority (CA)**, the centre's root signing key: the CA signs
every PI card, and the centre's **revocation list (CRL)**, the list of cards
no longer trusted, decides what stays valid over time.

### The mayor's side (once per centre, then once per PI)

```bash
# one-time: create the centre's root signing key (the CA)
murmurent centre-root-keygen           # BACK IT UP OFFLINE: see centre_root_key.md

# for each PI, once their lab/core exists and they have sent you their enroll.json:
murmurent issue-pi-card enroll.json --actor @the_mayor --out pi_card.json
# -> send pi_card.json plus your centre's signing recipient to the PI
```

### The PI's side

You request your centre-level identity card the same way a member requests a
group card. First, prove you hold your key:

```bash
murmurent enroll --out enroll.json
# -> send enroll.json to the centre's mayor
```

Once the mayor issues your card, import it and pin the centre's trust root
(its published signing key), confirming the fingerprint with the mayor
out-of-band first:

```bash
murmurent import-card pi_card.json --trust-root ed25519:...
```

Your existing members keep working throughout: your own key gains a new,
higher anchor, and every member card you already issued automatically chains
up to it. See [connect_to_hub.md](connect_to_hub.md) for the full walkthrough
of how a centre lists itself publicly and processes incoming join requests.

## Membership levels: group, centre, and project

Every card sits at some level in the chain: one more signing step below the
root. Three distinct things extend that chain, and it helps to keep them
separate.

### Group membership (lab or core)

The PI's own key (self-rooted, or centre-anchored once the lab joins a
centre) signs a member's card. This is the flow above: [Members] Join a
group and [PIs] Issue the member's card.

### Centre membership (a PI joining a centre)

The centre root key signs a PI's card, adding one level above the PI's own
key. This is [PIs] Registering your lab or core with an existing centre,
above: it changes only the top of the chain, so every member card the PI
already issued keeps verifying, now with one extra link above it.

### Project membership

A project adds one more level below the PI: when a project is created, the
PI signs its creator a **project-lead card**, a delegation credential scoped
to exactly that project. From then on the lead's own key signs each member's
project card, so day-to-day project joins are handled entirely by the lead:

```
centre root --> PI card --> project-lead card --(lead's key) signs--> project card
                              (the creator)                            (a project member)
```

See Delegating a project lead, below, for the full command set.

## Delegating a project lead

- `murmurent issue-project-lead-card <handle> --project <p>`: the PI
  delegates (done automatically when a project is approved from the
  dashboard; the bundle is DM'd to the lead).
- `murmurent project-add-member <handle> --project <p>`: the lead signs a
  member in, one click when the member's key is already attested on the
  roster. External or keyless members first run `murmurent enroll --project
  <p>` and send the file (`--enrollment`).
- `murmurent project-remove-member`: revokes the card (adds it to the CRL)
  and removes the member from the project's private Slack channel.
- `murmurent project-whoami`: shows which projects this machine's cards
  certify you for.

Revoking the lead card invalidates every project card it signed: the
verifier checks the delegation link against the CRL, which is fail-closed
(see Revocation, below). Deleting a project revokes the lead card and every
member card in one CRL update. The full walkthrough: [project_creation.md](project_creation.md).

## Publish and fetch trust material

The centre publishes its public keys (the age encryption key and the
signing key) and its CRL to the public hub; members fetch and pin them.

```bash
# mayor: publish the signing key + CRL alongside the directory listing
murmurent centre-hub-publish [--submit]

# member: fetch the centre's signing key + CRL from a local murmurent_public clone,
# pin the anchor (confirm the fingerprint out-of-band), and enable revocation checking
murmurent centre-pin <unique-name> --fingerprint <SHA256:...>
```

## Revocation

Cards carry a 90-day **TTL** (time-to-live: how long a card stays valid
before it needs renewal or reissue), so revocation stays explicit rather
than passive. The system is **fail-closed**: a verifier trusts a card only
when it also holds a CRL fresh enough to confirm the card is still
unrevoked.

```bash
murmurent revoke --handle <handle>          # or --card-id / --fingerprint (mayor)
murmurent crl --out crl.json                # export the signed CRL to publish
```

`murmurent group-remove-member` also revokes the departing member's card as
defense-in-depth, after pulling their Slack/GitHub access. Revocation is
mayor-centric (the CRL carries the root's own signature); members see a
revocation once they `centre-pin` or re-fetch the updated CRL.

## What the dashboard enforces

Opening the dashboard runs three checks, in order: the signed-in netname
matches this machine's card owner; the stored card verifies (it chains to
the pinned root, stays unexpired, remains unrevoked whenever a CRL is
present, and is untampered); and the registry confirms this identity is
real. All three must pass together; any check that fails blocks the
dashboard from opening.

## Try it end-to-end

`scripts/identity_smoke.sh` simulates a mayor, a PI, and a member on one
machine (separate `MURMURENT_HOME` roots) and runs the whole lifecycle,
including a revocation. Related: [centre_root_key.md](centre_root_key.md)
(root-key handling and rotation).
