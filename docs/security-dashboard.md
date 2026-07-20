# Security dashboard: per-lab posture audit

Murmurent's per-lab security dashboard runs the `security_guard` agent
periodically against a registered host (a machine you have added to
Murmurent with `murmurent host add`, or from the dashboard's Machines
panel; typically a shared lab server) and surfaces permission, hygiene,
and policy findings in one screen.

Two tiers, two trust levels:

- **Tier 1**: unprivileged. Runs as the invoking user over SSH. Walks
  POSIX bits on filesystems where they're authoritative (`/home`,
  ext4), reads the user's own `~/.ssh/`, `~/.murmurent/`, `~/.claude*`,
  dotfiles, crontab, systemd user units, etc. Available without
  additional setup.
- **Tier 2**: root-owned ACL snapshot. Requires a sysadmin to install a
  narrowly-scoped sudoers entry on the target host (see
  [Tier 2 setup](#tier-2-setup)). Reads the storage layer's real ACLs
  plus `sshd -T` and lab-wide `authorized_keys` summaries. The dashboard
  consumes the snapshot if present and reports "ACL details unavailable"
  rows if absent.

**Hard rule (from the global Murmurent data-storage policy):** the
security agent **never modifies or deletes any file under the lab's
`immutable/` or `append_only/` data trees**, even when its own findings recommend
a fix. All `chmod`/`chown`/ACL adjustments in the dashboard are
display-only: the PI runs them by hand after vetting.

> **Site-specific configuration is kept privately.** The concrete server,
> storage host, mount layout, ACL templates, and authorised operators for
> a given lab are that lab's own operational record and are **not** part
> of this public documentation. Each lab keeps them in its private
> lab-management repo. This page describes only the general mechanism.

---

## Storage where POSIX bits are not authoritative

Many enterprise NAS platforms store native (NTFS-style / NFSv4) ACLs and,
when a directory is exported over **NFSv3**, can only project those ACLs
as synthesized POSIX bits. Those bits are **not authoritative**: a
`chmod` on the v3 mount may not flip the underlying ACE, and the bits you
see don't reflect deny-ACE chains.

The usual remedy is a parallel **NFSv4 view restricted to root** that
exposes the real ACLs (`nfs4_getfacl`). Tier 2 reads from that view.

The Tier 1 scanner detects this situation automatically: if
`nfs4_getfacl <data_root>` reports that the attribute isn't supported,
the scanner **skips the POSIX walks of `immutable/` and `append_only/`** (which
would produce nothing but noise) and emits a single info-finding
`POSIX-NOT-AUTHORITATIVE-01` pointing the PI at Tier 2.

Local filesystems (a server's own `/home` on ext4, for example) have
real POSIX ACLs, so the home-dir, ssh-key, and dotfile scanners stay
valid there.

The interpretation of the storage layer's ACL entries and the expected
per-directory ACL templates a given lab audits against are lab-specific
and are kept in that lab's private lab-management repo, not here.

---

## Rule catalog

Every Tier 1 / Tier 2 finding carries a stable rule ID. Use the anchors
below to deep-link from the dashboard rows. `<data_root>` stands for
the lab's data root.

### Tier 1: unprivileged scanners

| Rule | Severity | Description |
|---|---|---|
| <a id="POSIX-NOT-AUTHORITATIVE-01"></a>`POSIX-NOT-AUTHORITATIVE-01` | info | The data mount synthesizes POSIX bits over native ACLs. POSIX-bit walks of `immutable/`/`append_only/` were skipped to avoid noise. Run the Tier 2 sudo snapshot for the real picture. |
| <a id="RAW-IMMUTABLE-01"></a>`RAW-IMMUTABLE-01` | block | File under `<data_root>/immutable/<project>/` has a write bit set. **Only fires on filesystems where POSIX bits are authoritative**: see `POSIX-NOT-AUTHORITATIVE-01`. |
| <a id="RAW-LAB-ONLY-01"></a>`RAW-LAB-ONLY-01` | warn | File under `immutable/` is world-readable. Same caveat. |
| <a id="REFINED-LAB-WRITE-01"></a>`REFINED-LAB-WRITE-01` | warn / block | File in `append_only/` is world-readable (warn) or world-writable (block). Same caveat. |
| <a id="REFINED-NO-TOOLS-01"></a>`REFINED-NO-TOOLS-01` | info | Executable bit set on an `append_only/` file: tools should live under a tools/ or db/ area, not `append_only/`. |
| <a id="HOME-REPO-PRIVATE-01"></a>`HOME-REPO-PRIVATE-01` | warn | File in `~/repos/<project>/` is group/world-readable on a shared host. |
| <a id="HOME-REPO-LARGE-01"></a>`HOME-REPO-LARGE-01` | warn | Tracked file > `--repo-large-mb` (default 50 MB) and not in `.gitignore`. |
| <a id="HOME-REPO-GIT-SECRET-01"></a>`HOME-REPO-GIT-SECRET-01` | block | Tracked filename matches a secret pattern (`*.env`, `*.pem`, `*_rsa`, `*.key`, `id_*`, etc.). |
| <a id="GITHUB-PUBLIC-01"></a>`GITHUB-PUBLIC-01` | info | A Murmurent project's GitHub origin is `public`: verify intentional. *(Implemented dashboard-side, not in the bash scanner.)* |
| <a id="SSH-DIR-PERM-01"></a>`SSH-DIR-PERM-01` | warn | `~/.ssh` itself is not mode `0700`. |
| <a id="SSH-AUTHKEYS-PERM-01"></a>`SSH-AUTHKEYS-PERM-01` | warn | `~/.ssh/authorized_keys` is not mode `0600`. |
| <a id="SSH-PRIVKEY-PERM-01"></a>`SSH-PRIVKEY-PERM-01` | block | Private key file (`id_*`, `*_rsa`, `*_ed25519`) is not mode `0600` or `0400`. |
| <a id="SSH-WEAK-KEY-01"></a>`SSH-WEAK-KEY-01` | warn | Key type is `ssh-rsa` or `ssh-dss`: replace with `ssh-ed25519`. |
| <a id="SSH-LOGIN-IPS-01"></a>`SSH-LOGIN-IPS-01` | info | Distinct IPs seen in `last` history (for the PI to vet). |
| <a id="DOT-CRED-MODE-01"></a>`DOT-CRED-MODE-01` | warn / block | `~/.gitconfig`, `~/.netrc`, `~/.pgpass`, `~/.aws/credentials` more permissive than `0600`. |
| <a id="WIGAMIG-MANIFEST-PERM-01"></a>`WIGAMIG-MANIFEST-PERM-01` | warn | `~/.murmurent/installations/*.yaml` is world-readable. |
| <a id="CLAUDE-CRED-MODE-01"></a>`CLAUDE-CRED-MODE-01` | warn | `~/.claude.json` or `~/.claude/settings.json` is world-readable (these contain MCP tokens). |
| <a id="TMP-LAB-LEAK-01"></a>`TMP-LAB-LEAK-01` | warn | World-readable file under `/tmp` or `~/tmp` whose path includes a lab data marker. |
| <a id="CRON-UNATTENDED-01"></a>`CRON-UNATTENDED-01` | info | User has an active crontab: review what runs unattended. |
| <a id="SYSTEMD-USER-RUNNING-01"></a>`SYSTEMD-USER-RUNNING-01` | info | User has `systemd --user` services running. |
| <a id="DOCKER-SOCK-01"></a>`DOCKER-SOCK-01` | warn | User is in the `docker` group (effective root via `/var/run/docker.sock`). |
| <a id="HOME-SIZE-01"></a>`HOME-SIZE-01` | warn | User's `~/` exceeds `--home-warn-gb` (default 100 GB). |
| <a id="HOME-SIZE-OK"></a>`HOME-SIZE-OK` | info | Home dir is under the threshold (reported for visibility). |

### Tier 2: root-owned ACL snapshot

The Tier 2 audit diffs observed ACLs against the lab's expected
templates (kept privately). Rules:

| Rule | Severity | Description |
|---|---|---|
| <a id="RAW-DENY-DELETE-MISSING-01"></a>`RAW-DENY-DELETE-MISSING-01` | block | A directory under `immutable/` is missing its inherited Deny-delete ACE: files there COULD be deleted. |
| <a id="RAW-FILE-WRITABLE-01"></a>`RAW-FILE-WRITABLE-01` | block | A file under `immutable/` has an allow-ACE granting write/append (the immutable template caps files at read-only). |
| <a id="REFINED-PATTERN-DRIFT-01"></a>`REFINED-PATTERN-DRIFT-01` | warn | The `append_only/` ACL drifts from the lab's canonical pattern. |
| <a id="REFINED-EXCEPTION-DETECTED-01"></a>`REFINED-EXCEPTION-DETECTED-01` | info | A subdir of `append_only/` has a locked-down pattern (group access stripped, named principals only). Surfaced for the PI to vet whether intentional. |
| <a id="ACL-UNEXPECTED-PRINCIPAL-01"></a>`ACL-UNEXPECTED-PRINCIPAL-01` | info | An ACE names a principal not in the expected template's allowlist. Could be a legitimate grant or drift. |
| <a id="SSHD-PWAUTH-01"></a>`SSHD-PWAUTH-01` | block | `sshd_config`'s `PasswordAuthentication` is not `no` (from `sshd -T`). |
| <a id="SSHD-ROOTLOGIN-01"></a>`SSHD-ROOTLOGIN-01` | warn | `PermitRootLogin` is not `no` or `prohibit-password`. |
| <a id="AUTH-PWD-ATTEMPTS-01"></a>`AUTH-PWD-ATTEMPTS-01` | warn | Any successful password-auth login in last 30 days (`auth.log` summary). |
| <a id="AUTH-WEAK-KEYS-LAB-01"></a>`AUTH-WEAK-KEYS-LAB-01` | warn | Any lab member's `authorized_keys` contains `ssh-rsa` or `ssh-dss` (lab-wide view, requires root walk). |

### Tier 2: per-core ACL diff (cores)

The snapshot script's per-core ACL files are diffed against the same
templates as the lab tree, with `CORE-`-prefixed rule IDs so the
dashboard can group findings per core. Each finding carries the core's
short id in its `project` field. Categories: `core_raw` and
`core_refined`.

| Rule | Severity | Description |
|---|---|---|
| <a id="CORE-RAW-DENY-DELETE-MISSING-01"></a>`CORE-RAW-DENY-DELETE-MISSING-01` | block | A directory under a core's `immutable/` is missing the inherited Deny-delete ACE. |
| <a id="CORE-RAW-FILE-WRITABLE-01"></a>`CORE-RAW-FILE-WRITABLE-01` | block | A file under a core's `immutable/` has an allow-ACE granting write/append/delete/write-ACL. |
| <a id="CORE-RAW-UNEXPECTED-PRINCIPAL-01"></a>`CORE-RAW-UNEXPECTED-PRINCIPAL-01` | info | A directory under a core's `immutable/` names a principal outside the standard allowlist. For the registrar to vet. |
| <a id="CORE-REFINED-PATTERN-DRIFT-01"></a>`CORE-REFINED-PATTERN-DRIFT-01` | warn | A core's `append_only/` root drifts from the canonical template. |
| <a id="CORE-REFINED-EXCEPTION-DETECTED-01"></a>`CORE-REFINED-EXCEPTION-DETECTED-01` | info | A subdir of a core's `append_only/` has a locked-down pattern. Surfaced for the core leader to vet. |
| <a id="CORE-ACL-UNEXPECTED-PRINCIPAL-01"></a>`CORE-ACL-UNEXPECTED-PRINCIPAL-01` | info | A directory under a core's tree names a principal outside the standard allowlist. |

---

## Tier 2 setup

Murmurent ships a root-owned snapshot script and a narrowly-scoped
NOPASSWD sudoers grant template under `scripts/`. The general one-time
install on the target host is:

1. SSH to the lab server and update the commons clone (`git pull`).
2. **Verify the shipped script's SHA256** against the recorded checksum
   before running anything as root (detects in-flight tampering; a
   mismatch means STOP, do not install).
3. Install the snapshot script root-owned (`install -m 0755 -o root -g root`).
4. Install the sudoers grant (`install -m 0440 -o root -g root`), after
   editing it to list the operators your lab authorises.
5. **Validate the sudoers file** with `visudo -c -f ...` before trusting
   it (a bad sudoers file can lock everyone out of sudo).
6. Smoke-test with `sudo -n <script>`: no password should be prompted.
7. (Recommended) Periodically re-check the installed binary's hash
   against the source, since anyone with root could later modify it.

After that, the `/security` dashboard's **Run sudo dump** button SSHes to
the host, runs the snapshot as root, ships the result back, and merges
Tier 2 findings into the table.

The host, mount paths, ACL templates, snapshot location, and the list of
authorised operators are **lab-specific** and are configured in the
script's constants and the sudoers grant on that host. A lab keeps those
concrete values in its own private lab-management repo, not here.

### What the snapshot writes

A per-run directory on the host's **local disk** (not on a network share,
since root is often not a valid principal on enterprise ACL storage),
readable only by the lab group. It contains a manifest, the `immutable/` and
`append_only/` ACL dumps, the effective `sshd -T` config, a per-member SSH
key summary (**no key bodies**), and an auth summary. The auth summary
records per-user counts of publickey / password / failed auth plus a
**distinct-subnet count only** (raw IPs are deliberately redacted, since
the file is lab-group readable). The dashboard parses each section
independently: a missing section only suppresses that section's findings.

### Retention

All snapshots are kept (each is MB-scale). The audit trail lets the PI
answer "when did this ACL change?" by diffing two snapshot dates. Prune
with a simple cron if storage ever becomes an issue.

### When Tier 2 isn't available

If the cluster admin can't grant sudo or expose a root-level ACL view,
the dashboard runs in **Tier 1 only mode**: the Tier 2 rule rows render
with a yellow "?" verdict and an "ACL snapshot unavailable" note.
POSIX-bit scanners on the ACL-backed data mount stay skipped (per
`POSIX-NOT-AUTHORITATIVE-01`). The dashboard remains useful for `/home`,
SSH keys, dotfiles, repos, and GitHub visibility.

---

## What the dashboard does *not* do

- **It never modifies any file on the target.** All suggested fixes are
  display-only strings. It specifically never writes under the lab's
  `immutable/` or `append_only/` data trees, enforced down to the
  `security_guard` agent's own prompt.
- **It does not audit other labs' trees.** Scope is this lab's slice of
  the host.
- **It does not store credentials.** No SSH password prompts, no sudo
  password prompts. Sudo is either NOPASSWD-on-one-script or not
  available.
