# Security Guard & Cable Guy (lab level)

Murmurent ships two distinct levels of the Security Guard role and two
distinct levels of the Cable Guy role. This page covers the **lab
level**: the copies of each agent a PI runs against their own group,
their own servers, and their own project rosters. The centre-wide
counterparts, which enforce institution-wide policy rather than
per-lab checks, are covered separately in
[`centre_guardians.md`](centre_guardians.md). Both agents are part of
the commons roster described in [`agents.md`](agents.md); this page
goes one level deeper into what each does at the lab scope and how
much of it is wired up today.

---

## Security Guard (lab)

The lab-level Security Guard is defined in
[`agents/security_guard.md`](https://github.com/hallettmiket/murmurent/blob/main/agents/security_guard.md).
It has two separate ways of running:

1. **Conversational mode.** Invoked on a PR or a diff ("Security Guard,
   check this PR before I merge"). It scans the diff for credentials,
   API tokens, SSH keys, age keys, `.env`-style assignments, and known
   cloud key formats; scans touched paths for restricted prefixes
   (`immutable/`, `keys/`, `.env*`, `secrets/`); and, for
   `sensitivity: clinical` projects, scans added text for PHI-shaped
   patterns (OHIP-like, MRN-like, SIN-like, DOB-near-name proximity).
   It refuses any PR that touches `immutable/`, and it treats
   `~/.murmurent/keys/**` and `~/.murmurent/age/**` as never-commit
   paths. Every finding carries a severity (`PASS`, `WARN`, `BLOCK`)
   and the report ends with an overall verdict.

2. **Periodic scan mode.** This is the mode a PI triggers on a regular
   basis, run against a registered host (typically a shared lab
   server) rather than against a single diff, via
   `murmurent security scan` or the `/security` dashboard panel.
   Documented in full in
   [`security-dashboard.md`](security-dashboard.md). It runs in two
   tiers:
   - **Tier 1** (unprivileged, no extra setup): walks POSIX
     permission bits under `immutable/`, `append_only/`, `~/repos/<project>/`,
     and the user's own `~/.ssh/`, `~/.murmurent/`, and dotfiles;
     flags world-readable or world-writable files, weak SSH key
     types, non-`0600` credential files, and secret-shaped tracked
     filenames.
   - **Tier 2** (root-owned ACL snapshot, requires a one-time sudoers
     grant from a sysadmin): reads the storage layer's real ACLs on
     enterprise NAS mounts where POSIX bits are not authoritative,
     plus `sshd -T` and lab-wide `authorized_keys` summaries, and
     diffs them against the lab's expected ACL templates.

   A related structured mode, the **agent-review mode** used by the
   `/security` dashboard's LLM-backed categories (`code`, `secrets`,
   `cc`), asks the Security Guard to review bundles of source files,
   git-tracked filenames, and Claude Code settings and reply with a
   JSON findings document rather than prose.

   In every mode, the Security Guard is hard-blocked (by its own
   prompt, by the scanner code, and by the `raw_guard` /
   `protected_paths` CC hooks) from ever modifying or deleting a file
   under `immutable/` or `append_only/`. Even a finding that looks like it needs
   a `chmod` fix is reported as text only, for the PI to apply by
   hand.

!!! warning "Work in progress"
    The implemented rule catalog covers filesystem permissions, SSH
    key hygiene, secret-shaped filenames, and code/config review; it
    does not yet cross-check a project's GitHub collaborator list
    against its certified member roster or flag departed members
    still holding access. Those checks belong conceptually to the
    Security Guard's periodic-audit role; today they live, if at all,
    in the separate `murmurent reconcile` / Cable Guy machinery,
    outside the Security Guard's own rule catalog.

---

## Cable Guy (lab)

The lab-level Cable Guy is defined in
[`agents/cable_guy.md`](https://github.com/hallettmiket/murmurent/blob/main/agents/cable_guy.md).
It runs on the PI's own machine (`freeze: frozen`, so members never
invoke it directly) and is responsible for making sure every member of
the lab has the access they need, and no more:

- **Onboarding.** `PROVISION_MEMBER` walks a new member through GitHub
  collaborator access to the lab's `lab_mgmt` repo (read-only), a
  generated SSH-key checklist, a Slack channel, and a personal
  Obsidian vault, then writes an installation record and reports to
  the PI. The member runs the checklist themselves; the Cable Guy
  never generates or transmits a private key on their behalf.
- **Scaffolding.** `SCAFFOLD_PROJECT` creates the project's GitHub
  repo, its Slack channel, and its `immutable/`/`append_only/` directories on
  each registered lab server.
- **Health checks.** `CHECK_HEALTH` walks every active installation
  record, confirms the member and the project are still active, and
  flags stale or unreachable entries.
- **Deprovisioning.** `DEPROVISION_MEMBER` marks installation records
  archived and generates (but does not itself execute) the
  access-revocation checklist for SSH keys, GitHub, and Slack.

Several of these operations are backed by real, tested code rather
than being purely agent-authored actions: GitHub-collaborator and
Slack-channel synchronization for a project
(`core.cert_provision.reconcile_github` /
`core.cert_provision.reconcile_slack`), read-only `lab_mgmt` grants
(`core.group_reconcile.grant_lab_mgmt_read`), and the drift-detection
sweep behind `CHECK_HEALTH` (`core.reconcile`, documented in
[`reconcile.md`](reconcile.md)) are implemented CLI-level functions,
not just agent prompt instructions.

!!! warning "Work in progress"
    The `machines/<machine_id>.md` and
    `installations/<handle>_<machine>_<project>.md` markdown records
    that `REGISTER_MACHINE` and `PROVISION_MEMBER` describe writing
    into the lab_mgmt repo are an agent-authored convention: there is
    no dedicated CLI command that creates or reads them today, unlike
    the separate, code-backed host registry (`murmurent host add`,
    `core.hosts`) that the Security Guard's periodic scan uses. The
    two registries describe overlapping but not identical concepts
    and have not yet been unified.

---

## Where to go next

| You want to… | Read |
|---|---|
| See both agents in the full commons roster | [`agents.md`](agents.md) |
| Read the periodic security-scan rule catalog in full | [`security-dashboard.md`](security-dashboard.md) |
| Read the drift-detection routine behind Cable Guy's health checks | [`reconcile.md`](reconcile.md) |
| See the centre-wide analogues of both roles | [`centre_guardians.md`](centre_guardians.md) |
