# Plan: Slack ↔ Claude Code integration for a murmurent lab

## Intent

Let a lab (e.g. `lab_mh`, PI = @mhallet) run projects where **certified members**
collaborate through a **private Slack channel** and a **private GitHub repo**, and
where each member's **Claude Code session posts to Slack as themselves**, with
attribution that is cryptographically anchored to the identity layer we already
built. The PI is the lab's certificate authority (self-issued via `pi-init`).

## Locked decisions (from the design Q&A)

- **Model C (relay).** A single **lab relay** holds the bot token (the only copy).
  Each member's CC session authenticates to the relay with **its murmurent card**;
  the relay posts to Slack *as that member* (`chat:write.customize` name + avatar)
  and can attach a card-anchored provenance tag so "m1 said X" is verifiable, not
  a spoofable display name.
- **Project = a project-scoped certificate** issued by the PI (the lab CA) to the
  project's members. Registering the project writes a project record; **only the
  PI can delete it** (revoke the certs via the CRL).
- **Provisioning:** each project gets a **private** Slack channel (the bot is a
  member of it) + a **private** GitHub repo; membership on both = exactly the
  certified members; the PI has repo access by owning the account.
- **Onboarding:** when the PI cards a member, CC **checks whether they're in the
  Slack workspace** and reports it; if not (atypical), it adds them (auto on a
  paid workspace with an admin token, else it surfaces the status and hands the
  PI the shared invite link).
- **Deletion:** archive the Slack channel (`conversations.archive`), strip GitHub
  collaborators, revoke the project certs.
- **No self-hosting for now.** Self-hosting the relay is deferred (avoid infra).
  Consequences:
  - **Phase E (reactive / inbound, Socket Mode) is DEFERRED** — revisit only when
    CC genuinely needs to *react* to Slack messages.
  - **Phases A–C need no relay and no server at all** (they run from the PI's
    machine + bot token, like existing provisioning) — this is the MVP.
  - **Outbound attribution (Phase D)** becomes one of two **no-infra** options,
    chosen when we get there (deferrable):
    - **In-Slack relay** (Slack-hosted Deno function): token stays in Slack,
      card-verified — but requires reimplementing the verifier in TypeScript.
    - **Shared bot token + `chat:write.customize`**: trivial, but the token sits
      on every member's machine and attribution is display-only (no anti-spoof).
  - Model C's *card-authenticated* relay remains the target design if/when
    non-repudiation matters and self-hosting is back on the table.

## OAuth scope ledger

**Slack bot token** — the PI creates one Slack app in the existing lab workspace,
grants these, and pastes the token into the one-time setup form (stored in
`~/.config/wigamig/`, never committed; treated like the signing/age keys):

| Scope | For |
|---|---|
| `groups:write` | create/manage **private** project channels; invite, kick, **archive** |
| `chat:write` | post messages |
| `chat:write.customize` | post *as* m1/m2/m3 (per-message username + avatar) — the relay's attribution |
| `users:read`, `users:read.email` | resolve member email → Slack user id (invite + workspace-membership check) |
| `groups:read` (+ `channels:read`) | read channel membership to reconcile against the cert roster |
| `im:write` | DM members (onboarding nudges) |
| `channels:manage` | only if the lab also wants public/lab-wide channels |
| `groups:history` (+ app-level `connections:write` for **Socket Mode**) | **Phase E only** — CC reading/reacting to channel messages |
| `admin.users.invite` (admin token, Business+/Enterprise only) | **conditional** — auto-add a member to the *workspace*; on Free/Pro there is no API, so CC surfaces status + the invite link instead |

**GitHub** — the PI's own `gh` token (they own the account; not a separate bot):

| Scope | For |
|---|---|
| `repo` | create private project repos + add/remove collaborators |
| `admin:org` / `write:org` | if `lab_mh` is a GitHub **org** (team/repo membership) |

## What already exists (reuse — don't rebuild)

- Channel create (private): `centre_provision.slack_create_channel(private=True)`.
- Member invite engine: `slack_notify.sync_project_channel_members` (handle→email→uid→invite, idempotent).
- Channel membership read / kick: `slack_notify._channel_member_ids`, `centre_provision` `conversations.kick`.
- Message posting: `slack_notify` `chat.postMessage` (extend for `chat:write.customize`).
- GitHub repo scaffolding: `project_provision` (`gh repo create` + collaborators).
- Identity/certs: `idcert` / `issuance` / `revocation` (PI self-root, member cards, CRL).
- Dashboard project scoping (member lens vs PI/registrar lens).
- PI setup capturing `github` + `slack_workspace` + `slack_invite_url` (`group-setup`).

## Phases (each independently shippable + green)

### Phase A — Foundations: setup form + identity mapping
- Extend the PI's one-time setup (`group-setup` / `murmurent init` PI path) to capture
  the **lab Slack workspace id + bot token** and the **lab GitHub org/account**;
  store the token in `~/.config/wigamig/`.
- Establish the per-member **identity map**: murmurent handle ↔ email ↔ Slack user id
  (`users.lookupByEmail`) ↔ GitHub login. Email is the join key (captured on the
  member's enrollment/card).
- `security_guard`: token is never committed/logged; add it to the key-hygiene set.

### Phase B — Project lifecycle (certs + registry + dashboard)
- **[NEW] Project-scoped cert:** extend the member card so a project card binds a
  member's key to a project (`group = lab_mh/<project>`). The PI issues it; a
  member requests via `murmurent enroll --project <p>`.
- **Project registry record** (in the lab-mgmt repo): id, members, created, status.
- **PI-only delete = revoke** the project certs (CRL) — no Slack/GitHub yet.
- **Dashboard:** members see only their projects; PI/registrar sees all. PI has a
  "remove project" action. (Builds on existing project scoping.)

### Phase C — Provisioning (Slack channel + GitHub repo, membership = certs)
- On project create: private Slack channel (bot joins), private GitHub repo.
- Sync membership on both to exactly the certified members (`sync_project_channel_members`
  + gh collaborators). PI has repo by ownership.
- **Onboarding check:** for each member, `users.lookupByEmail` → in workspace?
  Report per member. If missing → auto-invite (paid + `admin.users.invite`) else
  surface + hand the PI the shared invite link.
- On project delete: `conversations.archive` the channel, remove gh collaborators,
  revoke certs (ties Phase B delete to real teardown).
- Reconcile loop: diff desired (certs) vs actual (channel + repo) membership.

### Phase D — Outbound attribution (no-infra; deferrable) — OPTIONAL
Members post to Slack *as themselves*. Self-hosting is off the table, so pick one:
- **In-Slack relay** (Slack-hosted Deno function via a webhook trigger): verifies
  the member's card (member→PI→root) against a trust root + CRL in a Slack
  datastore, then posts with `chat:write.customize`. Token stays in Slack. Cost: a
  TypeScript reimplementation of the verifier + replay-nonce + CRL sync.
- **Shared bot token + `chat:write.customize`**: each session posts as its own
  member. Trivial to build; token on every machine; attribution is display-only.
Not required for the A–C MVP.

### Phase E — Bidirectional (inbound; CC reacts to Slack) — DEFERRED
Deferred with self-hosting. When revisited: a receiver (self-hosted relay running
Socket Mode, or per-member polling) routes channel events to the member's session,
filtered to the channels they're certified for. Requires `groups:history` (+ Socket
Mode `connections:write`).

### Phase F — Hardening, reconcile, tests, agents
- Injectable seams so the suite stays green without a token (no-op pattern).
- Tests: cert issuance/revoke for projects, provisioning membership sync, relay
  attribution + card verification, onboarding workspace-check branches, archive on
  delete, reconcile drift.
- Agent duties: `cable_guy` provisions/tears down channel+repo; `security_guard`
  audits the bot token + relay; `registrar`/PI issues + revokes project certs.
- Docs: `docs/slack_cc_integration.md` + the scope ledger.

## Open infra decision (needs a call before Phase D)

**Where does the relay run?** It holds the only copy of the bot token and must be
reachable by every member's CC session. Options: the lab's always-online murmurent
server (natural for a distributed lab) vs. the PI's machine (fine for a co-located
lab, but off when the laptop sleeps). This shapes Phase D deployment.

## Suggested delivery order

**A → B → C is the MVP** — projects with a private channel + repo, certified
members, PI-controlled, all relay-free and infra-free. **F** (tests/agents/docs)
runs throughout. **D** (outbound attribution, no-infra) is optional and can come
after C. **E** (reactive/inbound) is deferred with self-hosting.
