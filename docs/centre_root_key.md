# The centre root key — handling & rotation runbook

The **centre root key** is the certificate-authority root of a murmurent centre.
It is an ed25519 signing key, held **only by the mayor**, that signs PI identity
cards (which in turn let PIs sign member cards) and the centre's revocation list
(CRL). Its public half is the centre's `signing_recipient`, published in the
`wigamig_public` installations table so anyone can verify a card chains to this
centre.

> **This runbook exists on purpose before the key does.** Per the security
> review, a key with this blast radius must not be generated until its recovery
> and rotation story is written down. If you are reading this while about to run
> `murmurent centre-root-keygen`, read to the end first.

## Blast radius — why this key is special

- **Whoever holds the private key *is* the centre.** They can mint valid PI
  cards for anyone, hence valid member cards for anyone, and publish a CRL.
- **If it is lost**, you cannot issue or revoke cards, and you cannot sign a new
  installations-table entry — the centre's identity layer is frozen until you
  rotate to a new root (see below).
- **If it leaks**, an attacker can impersonate the whole centre. Treat a
  suspected leak as a full compromise → rotate immediately.

Because of this, the root key is **used rarely** (only PI-card issuance and CRL
signing) and must be kept as close to offline as your workflow allows.

## Where it lives

- Private key: `~/.wigamig/keys/centre_root_ed25519` — mode **0600**, generated
  by `murmurent centre-root-keygen`.
- Public key: `~/.wigamig/keys/centre_root_ed25519.pub` and the centre's
  `signing_recipient:` field in `centre.md`.
- Pinned anchor (this machine's copy of the trusted fingerprint):
  `~/.wigamig/trust/<unique_name>.root`.

## MUST-do at generation time

1. **Back it up immediately, offline, encrypted, OFF this laptop.**
   - Encrypt the private key before it leaves the machine, e.g.
     `age -p ~/.wigamig/keys/centre_root_ed25519 > centre_root.age` (passphrase),
     or to a hardware/paper backup.
   - Store the encrypted copy somewhere physically separate from the laptop (a
     locked drawer, an institutional secrets vault, a second encrypted device).
     **Not** another file on the same disk, and **never** in any git repo.
2. **Never commit it.** The `wigamig-push` skill excludes `~/.wigamig/keys/**` by
   path, but the key never belongs in a working tree in the first place.
3. **Never wire it into CI or any automated signer.** A CI credential that can
   reach the root key turns a CI compromise into a centre compromise. Card
   issuance is a deliberate, human-run action.
4. **Record the fingerprint out-of-band.** Note the `SHA256:…` fingerprint
   somewhere durable (and tell PIs to confirm it via a second channel when they
   first import a card). The pinned fingerprint is the real trust anchor — the
   published pubkey is only trusted because it matches a fingerprint you
   confirmed out of band.

## Rotation — planned or after a suspected compromise

Rotation replaces the root key. **Every card and CRL signed by the old key
becomes stale** (they no longer chain to the new root), so this is a coordinated
operation, not a quiet swap.

1. `murmurent centre-root-keygen --rotate` — mints a new root key, re-pins the
   anchor locally, and updates `signing_recipient` in `centre.md`.
2. **Publish the new signing pubkey** in the installations table. Because a
   pubkey *change* on an existing centre is indistinguishable from an attack, the
   change must be confirmed out-of-band: the new entry should be signed by the
   **outgoing** key where possible (self-attested rotation), and the mayor must
   announce the new fingerprint to members through a trusted channel (Slack DM /
   email) so they update their pin deliberately.
3. **Re-issue all PI cards** with the new root, then have PIs **re-issue member
   cards**. Publish a fresh CRL signed by the new key.
4. Members re-pin: their machine will refuse the new root until the pin is
   updated (TOFU mismatch fails closed) — that refusal is the safety feature.
   They confirm the announced fingerprint, clear the old pin, and re-import.

## If the key is lost (no backup)

There is no recovery of the old key. You must **rotate to a brand-new root** and
treat it as the rotation flow above, except you cannot self-attest the change
with the outgoing key — so the out-of-band fingerprint announcement to every
member becomes mandatory, not optional. This is the scenario the mandatory
offline backup exists to prevent.

## Future hardening (not required for v1)

- Split the root across multiple admins (threshold / M-of-N signing) so no single
  stolen laptop is catastrophic.
- Hardware-backed root (Secure Enclave / YubiKey) and air-gapped signing.
- A signed, append-only transparency log of root-key changes so a silent swap is
  publicly detectable.
