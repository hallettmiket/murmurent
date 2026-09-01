# Security Guard & Cable Guy (centre level)

Murmurent ships two distinct levels of the Security Guard role and two
distinct levels of the Cable Guy role. This page covers the **centre
level**: the analogues that watch over the whole institution rather
than a single lab. The lab-level copies, which run per-project checks
a PI triggers directly, are covered in
[`guardians.md`](guardians.md). Where the lab-level guard audits one
project or one server at a time, the centre-level guard is meant to
carry an institutional-police character: it enforces policies that
hold across every lab, core, and shared server in the centre,
independent of which PI happens to be looking.

---

## Centre Security Guard

There is currently **no dedicated `centre_security_guard` agent file**
in [`agents/`](https://github.com/hallettmiket/murmurent/tree/main/agents).
The commons ships thirteen reference agents; of those, only
`centre_cable_guy` operates at centre scope (see
[`agents.md`](agents.md)). The role described here is the natural
centre-scope extension of the lab-level Security Guard, and pieces of
its intended function already exist as separate mechanisms without yet
being unified under a single agent:

- **Centre root key hygiene.** The lab-level Security Guard's prompt
  already contains a centre-scope rule: `BLOCK` if the centre root
  signing key is wired into CI or any automated signer, or lacks an
  offline encrypted backup. The full handling and rotation runbook is
  institution-wide policy, documented in
  [`centre_root_key.md`](centre_root_key.md), not lab-specific.
- **Institution-wide SSH and login-method policy.** The Tier 2
  root-owned scan (see [`security-dashboard.md`](security-dashboard.md))
  reads `sshd -T` and `authorized_keys` and can flag password
  authentication being enabled, weak key types, or a permissive
  `PermitRootLogin`. Today this runs **per lab server**, triggered by
  a PI, against that lab's expected ACL templates. Extending the same
  mechanism into a centre-wide sweep across every registered host, run
  on a schedule rather than per-lab request, and checked against a
  single institution-wide policy rather than each lab's private
  template, is the shape a Centre Security Guard would take.
- **Password rotation and institution-wide permission policy.**
  Neither is enforced by any shipped code today. A lab-level PI can run
  `murmurent security scan` against their own server whenever they
  choose; nothing currently confirms that every lab in the centre has
  done so recently, or that every lab's ACL templates agree with a
  centre-wide baseline.

!!! warning "Work in progress"
    A centre-wide Security Guard singleton, analogous to
    `centre_cable_guy`, is designed but not yet implemented. The
    institution-wide policies it would enforce (SSH login-method
    compliance across every registered host, password-rotation
    cadence, and a single permission baseline that every lab's ACL
    templates must satisfy) exist today only as the sum of individual
    labs each running their own Tier 1/Tier 2 scans against their own
    templates, not as one centre-scope check.

---

## Centre Cable Guy

The **Centre Cable Guy** is, by contrast, a real, shipped agent:
[`agents/centre_cable_guy.md`](https://github.com/hallettmiket/murmurent/blob/main/agents/centre_cable_guy.md).
It is a singleton, one copy for the whole centre, living on the
registrar's machine rather than any individual PI's. Its job is
reconciliation across labs rather than onboarding within one:

- **Per-project filesystem ACLs on shared servers.** For projects that
  span more than one lab, it grants and audits ACLs on
  `<lab_vm_root>/{raw,refined}/<project>/` via a narrowly-scoped
  sudo-only script (`murmurent_project_acl.sh`), rather than the ad
  hoc directory creation the lab-level Cable Guy does for a
  single-lab project.
- **Cross-lab project provisioning.** `PROVISION_PROJECT` creates the
  project's Slack channel in its primary lab's workspace, issues
  single-channel guest invites for members from other labs, and calls
  the same GitHub-provisioning logic the lab-level Cable Guy uses
  (`core.project_provision.provision_project_remote`) rather than
  duplicating it.
- **Membership-drift reconciliation.** `RECONCILE` diffs a project's
  declared member set (`<lab_info>/projects/<project>.md`) against
  actual Slack channel membership, actual GitHub collaborators, and
  actual filesystem ACLs, and reports or applies the deltas. This is
  the centre-scope counterpart to the lab-level Cable Guy's
  `CHECK_HEALTH`, but it reconciles against shared, cross-lab
  infrastructure rather than one lab's own installation records.

The Centre Cable Guy never edits a per-lab `lab_mgmt` repo (member
rosters stay authored by each lab's own PI) and it always requests
registrar sign-off before a write action on shared infrastructure, the
same dry-run-first discipline the lab-level Cable Guy applies before
touching a single lab's infrastructure.

!!! warning "Work in progress"
    `SERVER_SETUP`, the operation that wires a freshly-bootstrapped
    centre's server profile into working infrastructure, is
    explicitly a dry-run-and-report step today. The agent definition
    states that server-side Claude Code installation is deferred to a
    later automation phase; for now the agent reports the install
    command for the mayor to run by hand rather than running it
    itself.

---

## Where to go next

| You want to… | Read |
|---|---|
| See the lab-level Security Guard and Cable Guy | [`guardians.md`](guardians.md) |
| See both agents in the full commons roster | [`agents.md`](agents.md) |
| Read the centre root key runbook | [`centre_root_key.md`](centre_root_key.md) |
| Read the periodic security-scan rule catalog | [`security-dashboard.md`](security-dashboard.md) |
| Understand what a centre is and its administrative roles | [`centre_overview.md`](centre_overview.md) |
