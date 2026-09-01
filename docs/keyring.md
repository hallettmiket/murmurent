# The keyring: syncing secrets across your machines

The **keyring** carries the private contents of `~/.murmurent` — keys, tokens —
across all of one principal's installs (a laptop, an always-online server, a
second laptop months later) **without ever hand-copying a private key**. Each
machine holds its own `age` identity whose private half never leaves it; each
secret is one `age`-encrypted "box" committed to the `lab_info` git repo, locked
**per role** so a `server` machine can hold every box yet be unable to open a
`mayor`-only one (e.g. the root CA).

Transport is git; crypto is [`age`](https://age-encryption.org) (the same tool
the encrypted-join flow uses). No new services.

## Why — the three tiers of `~/.murmurent`

When murmurent is deployed on a second machine, the *code* clones from GitHub and
the *lab-management* repo pulls normally — but `~/.murmurent` holds material that
is never shared automatically. Its contents fall into three tiers:

| What | Tier | Travels how |
|---|---|---|
| `keys/centre_root_ed25519` (root signing CA) | secret · restricted | to **mayor machines only** |
| `age/mayor.key` (decrypts join requests) | secret · shared | to machines that process joins |
| `~/.config/murmurent/slack-token` | secret · shared | to **all** machines incl. server |
| `lab_info/` registry (PII) | state · confidential | plain git (already a repo) |
| `keys/id_ed25519`, logs | per-machine | **never synced** — regenerated locally |

The registry is a *sync* problem (git solves it); the keys/tokens are a
*distribution* problem. The keyring is that distribution layer — it moves as
little as possible and keeps the crown jewel off any internet-facing box.

## What it does

Every machine generates its own keypair at setup; the private half stays put.
Each secret is one encrypted file. A box is locked so **any one of several
approved machines** can open it, and a machine opens exactly the boxes locked to
include its key. Two properties follow:

- **Public keys lock; private keys unlock.** The list in the repo is public keys,
  safe to share; only the private key on a machine opens anything.
- **Access lives in the box, not on the machine.** There is no per-machine
  allow-list — each box carries a slot for every machine permitted to open it.

## How it works — envelope encryption

`age` encrypts *to recipients* (public keys) and decrypts *with an identity*
(a private key). Multi-recipient is what lets several machines share one file:

1. A random **inner key** ("file key") is invented for this file alone.
2. The secret is encrypted **once** with the inner key (the file's body).
3. A copy of the inner key is sealed into a per-recipient **stanza** (an
   "envelope") in the header — sealed via an X25519 Diffie–Hellman handshake so
   only that recipient's private key can reopen it.

A real box's header, with two authorized machines:

```
age-encryption.org/v1
-> X25519 GVsRhS4IGE4IgKAb…        ┐ envelope for machine 1
   IiMecIHzjL7Z8MfMuvyYBl…         ┘   = inner key, sealed for it
-> X25519 Tj+Nkx/jinoJTVAc…        ┐ envelope for machine 2
   uZZOh9o0drF+fb98VM1HXU…         ┘
--- LGBa1F3MJJH9Mbbd0eoB…          ← MAC: a tamper-seal over the whole header
…binary…                           ← the secret, encrypted once with the inner key
```

**Decrypting:** a machine tries each stanza — combining the stanza's ephemeral
public value with *its own* private key. For the stanza sealed to it, the
handshake reproduces the exact wrapping key → it recovers the inner key → it
decrypts the body. For stanzas sealed to others, it derives the wrong key and
skips. If **no** stanza opens, decryption fails entirely — that is the "refused"
case, and the whole security property. No private key ever appears in the file.

## Where it lives

The keyring rides inside the existing `lab_info` repo (given a **private** git
remote every machine pulls from). Secrets are per-file, so a change touches one
box, not a monolith.

```
lab_info/
  _registry.yaml  centre.md  labs/  join_requests/   # state plane (plaintext)
  .keyring/
    recipients.yaml     # roster: 1 public key per machine + role
    manifest.yaml       # declarative: each secret's target path, mode, consumers
    secrets/
      slack-token.age       # locked to [mayor, server]
      centre-root-key.age   # locked to [mayor] ONLY  ← crown jewel
```

`consumers` in the manifest **is** the security tiering: `secrets/<name>.age` is
encrypted to exactly the recipients whose `role` is listed. What counts as a
secret, its tier, and where it unpacks are all *data* — adding a secret or a
machine is an edit plus a re-lock, never a code change. Targets under `$HOME` are
stored `~`-relative so each machine unpacks under its own home.

## The flows

- **Add a machine** — the new machine `keyring init`s and prints its public
  recipient; an existing machine `keyring authorize`s it (adds the key, re-locks
  its boxes) and pushes; the new machine `keyring sync`s and opens its boxes. No
  private key is hand-carried; the only out-of-band credential is git access to
  the private repo.
- **Sync** — pull; decrypt the entitled boxes; write each to its target at mode
  0600 (atomic write). Idempotent; dry-run by default. `murmurent reconcile` runs
  a best-effort sync so rotations self-heal.
- **Rotate** — `rotate-secret` stores a new value you supply and re-locks the box.
- **Revoke** — `revoke` drops a machine and re-locks without it, and **flags every
  secret whose value must be rotated** (see the hard rule below).

## Command surface

| Command | Who | What |
|---|---|---|
| `keyring init` | new machine | make this machine's identity; print its recipient |
| `keyring authorize` | existing ≥role | add a recipient; re-lock its boxes |
| `keyring set-secret` | any consumer | add/update a secret; lock it for roles |
| `keyring rotate-secret` | any consumer | replace an existing secret's value |
| `keyring revoke` | mayor | remove a machine; flag secrets to rotate |
| `keyring sync` | any | unpack entitled secrets (dry-run by default) |
| `keyring status` | any | this machine's identity, role, entitlements |
| `keyring check` | any | end-to-end health on THIS machine (decrypts) |
| `keyring verify` | any · CI | structural integrity of the store, no key needed |

Every mutating command pulls first (warning if it can't fast-forward) and takes
`--push` to commit + push in one step.

## Security model

- **Confidentiality rests on `age`, not on the repo being private.** A private
  repo is a second fence; a swapped/tampered box **fails closed** (AEAD).
- **Least privilege by construction.** The CA box has no `server` recipient, so a
  server compromise cannot yield the CA even with full repo access.
- **Consent-gated growth.** A machine joins only when an existing trusted machine
  adds its key; grants are role-gated and audit-logged.
- **Safe writes.** Secrets land atomically at mode 0600 (temp + `fchmod` +
  rename) — no world-readable or partial-write window.

!!! danger "The one rule you cannot bend"
    **git history is permanent.** A box committed today stays decryptable forever
    by any key that was a recipient then. So **revocation ⇒ rotation is
    mandatory**: removing a machine only stops *future* access; to neutralise a
    *lost* machine you must rotate the secret's value. If it was a mayor, treat
    the CA as compromised and rotate the root key.

The keyring is online *distribution*, not disaster recovery: if every mayor
machine is lost at once, only the **offline root-CA backup** recovers the centre.

## See also

- [`docs/keyring_deploy.md`](keyring_deploy.md) — production deployment runbook.
