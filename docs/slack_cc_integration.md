# Slack and Claude Code integration

!!! warning "Work in progress"
    This is a design and roadmap document. It lays out phased work (see
    "Phases" below) toward letting lab members drive Claude Code and
    Murmurent from inside Slack, with each member's Slack identity mapped to
    their Murmurent handle. Everything described here is intended work;
    check the codebase and each phase's status marker before assuming a
    given piece has shipped.

## Intent

Let a lab (e.g. `example_lab`, PI = @the_pi) run projects where **certified
members** collaborate through a **private Slack channel** and a **private
GitHub repo**, and where each member's **Claude Code session posts to
Slack as themselves**, with attribution that is cryptographically
anchored to the identity layer we already built. The PI is the lab's
certificate authority (self-issued via `pi-init`).

## Locked decisions (from the design Q&A)

- **Model C (relay).** A single **lab relay** holds the bot token (the only copy).
  Each member's CC session authenticates to the relay with **its Murmurent card**;
  the relay posts to Slack *as that member* (`chat:write.customize` name + avatar)
  and can attach a card-anchored provenance tag so "m1 said X" is
  cryptographically verifiable, unlike a spoofable display name.
- **Project = a project-scoped certificate** issued by the PI (the lab CA) to the
  project's members. Registering the project writes a project record; **only the
  PI can delete it** (revoke the certs via the CRL).
- **Provisioning:** each project gets a **private** Slack channel (the bot is a
  member of it) + a **private** GitHub repo; membership on both = exactly the
  certified members; the PI has repo access by owning the account.
- **Onboarding:** when the PI cards a member, CC **checks whether they're
  already in the Slack workspace** and reports the result; when they're
  missing (atypical), it adds them automatically on a paid workspace with
  an admin token, or else surfaces the status and hands the PI the shared
  invite link.
- **Deletion:** archive the Slack channel (`conversations.archive`), strip GitHub
  collaborators, revoke the project certs.
- **Self-hosting deferred for now.** Self-hosting the relay is deferred,
  keeping the initial deployment infra-free. Consequences:
  - **Phase E (reactive / inbound, Socket Mode) is DEFERRED**: revisit only when
    CC genuinely needs to *react* to Slack messages.
  - **Phases A–C run entirely from the PI's machine and the bot token**
    (like existing provisioning), with nothing else to deploy. This is
    the MVP.
  - **Outbound attribution (Phase D)** becomes one of two **infra-free**
    options, chosen when we get there (deferrable):
    - **In-Slack relay** (Slack-hosted Deno function): token stays in Slack,
      card-verified, but requires reimplementing the verifier in TypeScript.
    - **Shared bot token + `chat:write.customize`**: trivial, but the token sits
      on every member's machine and attribution stays display-only, relying on
      social trust rather than cryptographic anti-spoof protection.
  - Model C's *card-authenticated* relay remains the target design for when
    non-repudiation matters and self-hosting is back on the table.

## OAuth scope ledger

**Slack bot token**: the PI creates one Slack app in the existing lab workspace,
grants these, and pastes the token into the one-time setup form (stored in
`~/.config/murmurent/groups/<group>/`, kept out of version control always;
treated like the signing/age keys):

| Scope | For |
|---|---|
| `groups:write` | create/manage **private** project channels; invite, kick, **archive** |
| `chat:write` | post messages |
| `chat:write.customize` | post *as* m1/m2/m3 (per-message username + avatar): the relay's attribution |
| `users:read`, `users:read.email` | resolve member email → Slack user id (invite + workspace-membership check) |
| `groups:read` (+ `channels:read`) | read channel membership to reconcile against the cert roster |
| `im:write` | DM members (onboarding nudges) |
| `channels:manage` | only if the lab also wants public/lab-wide channels |
| `groups:history` (+ app-level `connections:write` for **Socket Mode**) | **Phase E only**: CC reading/reacting to channel messages |
| `admin.users.invite` (admin token, Business+/Enterprise only) | **conditional**: auto-add a member to the *workspace*; Free/Pro supports invite links only, so CC surfaces status + the invite link instead |

**GitHub**: the PI's own `gh` token, since the PI owns the account directly
rather than through a separate bot:

| Scope | For |
|---|---|
| `repo` | create private project repos + add/remove collaborators |
| `admin:org` / `write:org` | if `example_lab` is a GitHub **org** (team/repo membership) |

## What already exists (reuse these pieces)

- Channel create (private): `centre_provision.slack_create_channel(private=True)`.
- Member invite engine: `slack_notify.sync_project_channel_members` (handle→email→uid→invite, idempotent).
- Channel membership read / kick: `slack_notify._channel_member_ids`, `centre_provision` `conversations.kick`.
- Message posting: `slack_notify` `chat.postMessage` (extend for `chat:write.customize`).
- GitHub repo scaffolding: `project_provision` (`gh repo create` + collaborators).
- Identity/certs: `idcert` / `issuance` / `revocation` (PI self-root, member cards, CRL).
- Dashboard project scoping (member lens vs PI/registrar lens).
- PI setup capturing `github` + `slack_workspace` + `slack_invite_url` (`group-setup`).

## Phases (each independently shippable + green)

### Phase A: Foundations: setup form + identity mapping
- Extend the PI's one-time setup (`group-setup` / `murmurent init` PI path) to capture
  the **lab Slack workspace id + bot token** and the **lab GitHub org/account**;
  store the token in `~/.config/murmurent/groups/<group>/`.
- Establish the per-member **identity map**: Murmurent handle ↔ email ↔ Slack user id
  (`users.lookupByEmail`) ↔ GitHub login. Email is the join key (captured on the
  member's enrollment/card).
- `security_guard`: token stays out of commits and logs at all times; add it to
  the key-hygiene set.

### Phase B: Project lifecycle (certs + registry + dashboard)
- **[NEW] Project-scoped cert:** extend the member card so a project card binds a
  member's key to a project (`group = example_lab/<project>`). The PI issues it; a
  member requests via `murmurent enroll --project <p>`.
- **Project registry record** (in the lab-mgmt repo): id, members, created, status.
- **PI-only delete = revoke** the project certs (CRL), ahead of the Slack/GitHub
  teardown that Phase C adds.
- **Dashboard:** members see only their projects; PI/registrar sees all. PI has a
  "remove project" action. (Builds on existing project scoping.)

### Phase C: Provisioning (Slack channel + GitHub repo, membership = certs)
- On project create: private Slack channel (bot joins), private GitHub repo.
- Sync membership on both to exactly the certified members (`sync_project_channel_members`
  + gh collaborators). PI has repo by ownership.
- **Onboarding check:** for each member, `users.lookupByEmail` → in workspace?
  Report per member. If missing → auto-invite (paid + `admin.users.invite`) else
  surface + hand the PI the shared invite link.
- On project delete: `conversations.archive` the channel, remove gh collaborators,
  revoke certs (ties Phase B delete to real teardown).
- Reconcile loop: diff desired (certs) vs actual (channel + repo) membership.

### Phase D: Outbound attribution (infra-free; deferrable), OPTIONAL
Members post to Slack *as themselves*, using one of two infra-free approaches
(self-hosting stays deferred, per the locked decision above):
- **In-Slack relay** (Slack-hosted Deno function via a webhook trigger): verifies
  the member's card (member→PI→root) against a trust root + CRL in a Slack
  datastore, then posts with `chat:write.customize`. Token stays in Slack. Cost: a
  TypeScript reimplementation of the verifier + replay-nonce + CRL sync.
- **Shared bot token + `chat:write.customize`**: each session posts as its own
  member. Trivial to build; token on every machine; attribution is display-only.
Phase D is optional beyond the A–C MVP.

### Phase E: Bidirectional (inbound; CC reacts to Slack), DEFERRED
Deferred alongside self-hosting. When revisited: a receiver (self-hosted relay
running Socket Mode, or per-member polling) routes channel events to the
member's session, filtered to the channels they're certified for. Requires
`groups:history` (+ Socket Mode `connections:write`).

### Phase F: Hardening, reconcile, tests, agents
- Injectable seams so the suite stays green even without a token (stub pattern).
- Tests: cert issuance/revoke for projects, provisioning membership sync, relay
  attribution + card verification, onboarding workspace-check branches, archive on
  delete, reconcile drift.
- Agent duties: `cable_guy` provisions/tears down channel+repo; `security_guard`
  audits the bot token + relay; `registrar`/PI issues + revokes project certs.
- Docs: `docs/slack_cc_integration.md` + the scope ledger.

## Open infra decision (needs a call before Phase D)

**Where does the relay run?** It holds the only copy of the bot token and must be
reachable by every member's CC session. Options: the lab's always-online Murmurent
server (natural for a distributed lab) vs. the PI's machine (fine for a co-located
lab, but off when the laptop sleeps). This shapes Phase D deployment.

## Suggested delivery order

**A → B → C is the MVP**: projects with a private channel + repo, certified
members, PI-controlled, all relay-free and infra-free. **F** (tests/agents/docs)
runs throughout. **D** (outbound attribution, infra-free) is optional and can
come after C. **E** (reactive/inbound) stays deferred alongside self-hosting.
