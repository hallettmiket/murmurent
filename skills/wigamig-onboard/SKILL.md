---
name: wigamig-onboard
description: Mayor/registrar helper — process an incoming ENCRYPTED join request end to end. Takes the age-encrypted request a prospective member emailed, decrypts + files it, shows you who's asking, and (on your OK) approves + provisions it (lab/core Slack channel, GitHub repo, FS ACLs) or declines. Use when a join-request email arrives.
user_invocable: true
---

You are helping the **mayor/registrar** handle a join request that a prospective
member sent them (an `age`-encrypted blob, by email — nothing was posted to
GitHub). Walk the whole flow; do the mechanical parts for them and **pause for
an explicit go-ahead before approving**, because approval provisions real infra.

## 0. Preconditions (check, don't assume)
- A centre exists: `wigamig centre-status` (if not, stop — they need `centre-init`).
- The private key exists: `~/.wigamig/age/mayor.key` (created by `centre-init` /
  `centre-age-keygen`). If missing, decryption can't work — say so and stop.

## 1. Get the encrypted request into a file
Ask the mayor for it in whichever form they have:
- **A file** (they saved the `join-request.age` attachment) → use that path.
- **Pasted text** (the email body) → save everything from
  `-----BEGIN AGE ENCRYPTED FILE-----` through `-----END AGE ENCRYPTED FILE-----`
  (inclusive) into a temp file, e.g. your scratchpad `join-request.age`. Don't
  add or trim any other lines — age armor must start/end exactly at those markers.

## 2. Decrypt + file it
```bash
wigamig join-request decrypt <path-to.age>
```
This decrypts with the centre's private key **locally** and files a *pending*
request (prints its id). If it errors with a decrypt failure, the blob was
encrypted to a different key (wrong centre) or got mangled in copy/paste — say
so; don't retry blindly.

## 3. Show who's asking
```bash
wigamig join-request list
wigamig join-request show <id>
```
Summarise for the mayor in plain language: **who** (handle + email), **what kind**
(`lab` / `core` / `pi` / `admin`), the **name** they want, and their
**justification**. This is the moment to catch anything off (unknown person,
wrong lab, etc.).

## 4. Get an explicit decision — do NOT auto-approve
Ask the mayor: **approve or decline?** Approval creates real things (a Slack
channel, a GitHub repo, filesystem ACLs, registry entries) and notifies people —
so wait for a clear yes. Confirm the **approver handle** too (their `@handle`);
it's recorded in the audit log.

## 5. Approve (or decline)
Set the actor once so you don't repeat it: `export WIGAMIG_USER=@<mayor>` (or pass
`--actor @<mayor>`).
```bash
wigamig join-request approve <id> --actor @<mayor>
#   or:
wigamig join-request decline <id> --actor @<mayor>
```
**Slack provisioning is automatic here** — `approve` reads the bot token from
`$WIGAMIG_SLACK_TOKEN` **or** the `~/.config/wigamig/slack-token` file, so the
group's private channel gets created and members invited without exporting
anything, *as long as that token file / env var is set for the centre's
workspace*. If neither is present, the record is still approved and the Slack
step is reported as skipped (not a failure).

## 6. Read back the result
`approve` prints one line per provisioning step (`[ok] / [warn] / [block]`).
Translate them:
- **What got created**: Slack channel, GitHub repo, FS ACLs, registry entry.
- **Warnings** (e.g. `gh not installed`, Slack `missing_scope`, no token) are
  non-fatal — the record is provisioned; tell the mayor exactly what to fix and
  which step to re-run (`centre-slack-setup`, add a gh, etc.).
- **Blocks** mean the record was marked `failed` — surface the reason.

## What each kind does (so you set expectations)
- **`lab` / `core`** → full provisioning: private group Slack channel (members
  invited), GitHub repo, filesystem ACLs, registry entry.
- **`pi`** → records the PI's intent only; **no infra** is created (the lab is a
  separate `kind=lab` request later). Don't promise a channel for a `pi` approval.
- **`admin`** → adds the handle to the centre's registrars.

## Guardrails
- Never approve without the mayor's explicit yes (step 4).
- Never invent the requester's details — read them from `join-request show`.
- The decrypted plaintext contains a person's contact info: handle it like the
  private data it is (don't paste it into Slack/GitHub or anywhere public).
- If anything about the request looks wrong or suspicious, recommend `decline`
  and let the mayor decide.
