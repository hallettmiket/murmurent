# Security dashboard: per-lab posture audit

Murmurent's per-lab security dashboard runs the `security_guard` agent
periodically against a registered host (typically a shared lab server
such as lab-server) and surfaces permission, hygiene, and policy
findings in one screen.

Two tiers, two trust levels:

- **Tier 1**: unprivileged. Runs as the invoking user over SSH. Walks
  POSIX bits on filesystems where they're authoritative (`/home`,
  ext4), reads the user's own `~/.ssh/`, `~/.murmurent/`, `~/.claude*`,
  dotfiles, crontab, systemd user units, etc. Ships immediately.
- **Tier 2**: root-owned ACL snapshot. Requires a sysadmin to install
  a narrowly-scoped sudoers entry on the target host (see
  [Tier 2 setup](#tier-2-setup)). Reads NFSv4 ACLs via the sudo-only
  v4 mount + `sshd -T` + lab-wide `authorized_keys` summaries. The
  dashboard consumes the snapshot if present and reports "ACL details
  unavailable" rows if absent.

**Hard rule (carried over from the global Murmurent charter):**
the security agent **never modifies or deletes any file under
`/data/lab_vm/raw/` or `/data/lab_vm/refined/`**, even when its own
findings recommend a fix. All `chmod`/`chown`/ACL adjustments in the
dashboard are display-only: the PI runs them by hand after vetting.

---

## Why POSIX bits are not the whole story on the NAS

lab-server (and any Schulich storage tier mounted from
`nas.example.edu:/nas-export/...`) exposes `/data` over **NFSv3**.
the NAS speaks NTFS-style ACLs natively, and the v3 mount can only
project them as synthesized POSIX bits. Those bits are **not
authoritative**: `chmod` on the v3 mount may not flip the underlying
ACE, and the bits you see don't reflect deny-ACE chains.

There's a parallel **NFSv4.1 mount at `/srv/acl-view`** restricted to
root that exposes the real ACLs (`nfs4_getfacl`). That's where the
Tier 2 audit reads from.

The Tier 1 scanner detects this situation automatically: if
`nfs4_getfacl <lab_vm_root>` returns `Operation to request attribute
not supported`, the scanner **skips the POSIX walks of `raw/` and
`refined/`** (which would produce nothing but noise) and emits a
single info-finding `POSIX-NOT-AUTHORITATIVE-01` pointing the PI at
Tier 2.

`/home` on lab-server is local ext4 (`/dev/md0`), so POSIX ACLs there
are real: the home-dir, ssh-key, and dotfile scanners stay valid.

---

## NFSv4 ACL primer

(Adapted from notes by Dr. the core lead, who configured the the NAS
ACL policy for the Hallett lab tree. Reproduced here so the dashboard
+ any future PI reading a finding can interpret ACEs without
reverse-engineering them.)

Each ACE line is `type:flags:principal:perms`.

| Field | Meaning |
|---|---|
| `A` / `D` | Allow / Deny |
| `f` | inherit to new files |
| `d` | inherit to new subdirs |
| `i` | inherit-only: ACE does **not** apply to this object, only its children |
| `n` | no-propagate: child loses inheritance flags after one hop |
| `g` | principal is a group |

Permission letters (only the ones that show up in our ACLs):

| Letter | Meaning |
|---|---|
| `r` | read |
| `w` | write |
| `a` | append / create-subdir |
| `x` | execute / traverse |
| `d` | delete-self |
| `D` | delete-child |
| `t` | read-attrs |
| `T` | write-attrs |
| `n` | read-named-attrs (xattr) |
| `N` | write-named-attrs |
| `c` | read-ACL |
| `C` | write-ACL |
| `o` | write-owner |
| `y` | synchronize |

`rwaDdxtTnNcCoy` = full control.

**Evaluation order:** ACEs are checked top-to-bottom per permission bit;
the first ACE that mentions a bit wins.

**Inheritance rule:** an ACE with `f`/`d` but without `i` applies to
the directory itself AND is copied to new children. With `i`, it only
seeds children.

---

## Expected ACL templates (Tier 2 reference)

These are the canonical patterns Core Lead set up for `/data/lab_vm/`.
The Tier 2 audit diffs observed ACLs against these and flags
deviations. The PI sorts out which deviations are intentional
(exception patterns like `bc_brca/`) vs accidental drift.

### `<lab_vm>/raw/`: immutable policy

```
D::OWNER@   : Dd                  # owner cannot delete THIS dir's contents or itself
D::GROUP@   : Dd                  # group cannot either
D:fdi:OWNER@: Dd                  # every child (file or dir) inherits Deny-delete
D:fdi:GROUP@: Dd                  # same for the group
A::OWNER@   : rwaDdxtTnNcCoy      # on this dir itself, owner is otherwise full
A::GROUP@   : rwaxtTnNcy          # group can read/write/list, can't delete
A:di:OWNER@ : rwaDdxtTnNcCoy      # new SUBDIRS: owner full
A:di:GROUP@ : rwaxtTnNcy          # new SUBDIRS: group r/w/x but no delete
A:fi:OWNER@ : rxtTcy              # new FILES: owner read-only (no w/a, no d)
A:fi:GROUP@ : rxtTcy              # new FILES: group read-only
```

Net effect: files born under `raw/` are read-only and undeletable, even
to their nominal owner. New subdirs are writable (to make ingest
possible) but the files they hold inherit the immutability.

### `<lab_vm>/refined/`: collaborative read-write

```
A::OWNER@                  : rwaDxtTnNcCy            # owner: nearly full on this dir
A::GROUP@                  : rwaDxtTnNcy             # lab group: nearly full on this dir
A::EVERYONE@               : tcy                     # everyone else: metadata only
A:fdg:Administrators@example.edu: rwaDdxtTnNcCoy          # admins: full, inherited
A::OWNER@                  : rwaDdxtTnNcCoy          # (duplicate owner-full)
A:fdi:OWNER@               : rwaDdxtTnNcCoy          # future child OWNER: full (inherit-only)
A:fdg:Users@example.edu         : rxtncy                  # UWO Users: READ everything, inherited
A:dg:Users@example.edu          : way                     # UWO Users on subdirs only: write/append/sync
```

Net effect: the lab group has full control; the broader `Users@example.edu`
group can list/read everything under refined and can add files in
subdirs (but not at the refined/ root). Files (vs subdirs) end up
read-only for UWO Users since the `dg:Users:way` ACE is dir-only.

### `<lab_vm>/refined/<exception>/`: locked-down project (e.g. `bc_brca`)

```
A:fd:<named-user-1>@example.edu : rwaDdxtTnNcCoy   # explicit user: full, inherited
A:fd:OWNER@                : rwaDdxtTnNcCoy   # owner: full, inherited
A:fd:<named-user-2>@example.edu : rwaDdxtTnNcCoy   # second explicit user
A:fdg:Administrators@example.edu: rwaDdxtTnNcCoy   # admins: full, inherited
A::OWNER@                  : tcy              # bare OWNER@: metadata only
A::GROUP@                  : tcy              # GROUP@ stripped to metadata-only
A::EVERYONE@               : tcy              # everyone-else metadata-only
```

Net effect: the lab `labgroup` group is **deliberately locked out**;
only the named principals and Administrators can enter. This is a
named-exception pattern: the security dashboard flags it as
`REFINED-EXCEPTION-DETECTED-01` (info) rather than drift, and **the
PI vets which restricted dirs are intentional**.

### `<lab_vm>/` (top level)

```
A:fdg:labgroup@example.edu : rwaDdxtTnNcCoy   # helpdesk: full, inherited everywhere
A:fdg:Users@example.edu           : tcy              # all UWO users: read-attrs/ACL only, inherited
A::OWNER@                    : rwaDdxtTnNcCoy   # owner: full
A::GROUP@                    : rwaDxtTnNcy      # labgroup: full except delete-self & write-owner
A:fdg:Administrators@example.edu  : rwaDdxtTnNcCoy   # admins: full, inherited
A:fdi:OWNER@                 : rwaDdxtTnNcCoy   # whatever the future owner of a child is: full
```

Other labs (`/data/lab_*`) appear to use the **default** group-rwx with
similar inheritance: Core Lead only configured the strict templates for
`/data/lab_vm/raw` and `/data/lab_vm/refined/bc_brca`. The security
dashboard scopes the Tier 2 audit to `<lab_vm>` for now; other lab
trees aren't audited by us.

---

## Rule catalog

Every Tier 1 / Tier 2 finding carries a stable rule ID. Use the
anchors below to deep-link from the dashboard rows.

### Tier 1: unprivileged scanners

| Rule | Severity | Description |
|---|---|---|
| <a id="POSIX-NOT-AUTHORITATIVE-01"></a>`POSIX-NOT-AUTHORITATIVE-01` | info | The `/data/lab_vm` mount synthesizes POSIX bits over NFSv4 ACLs. POSIX-bit walks of `raw/`/`refined/` were skipped to avoid noise. Run the Tier 2 sudo snapshot for the real picture. |
| <a id="RAW-IMMUTABLE-01"></a>`RAW-IMMUTABLE-01` | block | File under `<lab_vm>/raw/<project>/` has a write bit set. **Only fires on filesystems where POSIX bits are authoritative**: see `POSIX-NOT-AUTHORITATIVE-01`. |
| <a id="RAW-LAB-ONLY-01"></a>`RAW-LAB-ONLY-01` | warn | File under `raw/` is world-readable. Same caveat. |
| <a id="REFINED-LAB-WRITE-01"></a>`REFINED-LAB-WRITE-01` | warn / block | File in `refined/` is world-readable (warn) or world-writable (block). Same caveat. |
| <a id="REFINED-NO-TOOLS-01"></a>`REFINED-NO-TOOLS-01` | info | Executable bit set on a `refined/` file: tools should live in `<lab_vm>/tools/` or `<lab_vm>/db/`, not refined. |
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

The Tier 2 audit diffs observed NFSv4 ACEs against the expected
templates above. Rules:

| Rule | Severity | Description |
|---|---|---|
| <a id="RAW-DENY-DELETE-MISSING-01"></a>`RAW-DENY-DELETE-MISSING-01` | block | A directory under `raw/` is missing the `D:fdi:OWNER@:Dd` or `D:fdi:GROUP@:Dd` ACE: files there COULD be deleted. |
| <a id="RAW-FILE-WRITABLE-01"></a>`RAW-FILE-WRITABLE-01` | block | A file under `raw/` has an OWNER@ or GROUP@ allow-ACE granting `w` or `a` (the raw template caps these at `rxtTcy`). |
| <a id="REFINED-PATTERN-DRIFT-01"></a>`REFINED-PATTERN-DRIFT-01` | warn | The `refined/` ACL drifts from the canonical pattern (missing UWO Users read, missing Administrators-full, etc.). |
| <a id="REFINED-EXCEPTION-DETECTED-01"></a>`REFINED-EXCEPTION-DETECTED-01` | info | A subdir of `refined/` has the locked-down pattern (GROUP@ stripped, named principals only). Surfaced for PI to vet whether intentional, like `bc_brca/`. |
| <a id="ACL-UNEXPECTED-PRINCIPAL-01"></a>`ACL-UNEXPECTED-PRINCIPAL-01` | info | An ACE names a principal not in the expected template's allowlist. Could be a legitimate access grant or drift. |
| <a id="SSHD-PWAUTH-01"></a>`SSHD-PWAUTH-01` | block | `sshd_config`'s `PasswordAuthentication` is not `no` (from `sshd -T`). |
| <a id="SSHD-ROOTLOGIN-01"></a>`SSHD-ROOTLOGIN-01` | warn | `PermitRootLogin` is not `no` or `prohibit-password`. |
| <a id="AUTH-PWD-ATTEMPTS-01"></a>`AUTH-PWD-ATTEMPTS-01` | warn | Any successful password-auth login in last 30 days (`auth.log` summary). |
| <a id="AUTH-WEAK-KEYS-LAB-01"></a>`AUTH-WEAK-KEYS-LAB-01` | warn | Any lab member's `authorized_keys` contains `ssh-rsa` or `ssh-dss` (lab-wide view, requires root walk). |

### Tier 2: per-core ACL diff (cores Phase 1c, script v7+)

The snapshot script's `acls_core_<core>_<kind>.txt` files are diffed
against the same templates as the lab tree, but with `CORE-`-prefixed
rule IDs so the dashboard can group findings per core. Each finding
carries the core's short id in its `project` field. Categories:
`core_raw` and `core_refined`.

| Rule | Severity | Description |
|---|---|---|
| <a id="CORE-RAW-DENY-DELETE-MISSING-01"></a>`CORE-RAW-DENY-DELETE-MISSING-01` | block | A directory under a core's `raw/` is missing the inherited Deny-delete ACE. Files there could be deleted. |
| <a id="CORE-RAW-FILE-WRITABLE-01"></a>`CORE-RAW-FILE-WRITABLE-01` | block | A file under a core's `raw/` has OWNER@/GROUP@ allow ACE granting `w`/`a`/`D`/`C`. |
| <a id="CORE-RAW-UNEXPECTED-PRINCIPAL-01"></a>`CORE-RAW-UNEXPECTED-PRINCIPAL-01` | info | A directory under a core's `raw/` has a named-principal ACE outside the standard allowlist. For the registrar to vet. |
| <a id="CORE-REFINED-PATTERN-DRIFT-01"></a>`CORE-REFINED-PATTERN-DRIFT-01` | warn | A core's `refined/` root drifts from the canonical template (missing OWNER+GROUP full, missing Users@example.edu read, etc.). |
| <a id="CORE-REFINED-EXCEPTION-DETECTED-01"></a>`CORE-REFINED-EXCEPTION-DETECTED-01` | info | A subdir of a core's `refined/` has the `bc_brca`-style locked-down pattern (GROUP@ stripped). Surfaced for the core leader to vet. |
| <a id="CORE-ACL-UNEXPECTED-PRINCIPAL-01"></a>`CORE-ACL-UNEXPECTED-PRINCIPAL-01` | info | A directory anywhere under a core's tree has a named-principal ACE outside the standard allowlist. |

---

## Tier 2 setup

Murmurent ships [`scripts/lab_sec_dump.sh`](https://github.com/hallettmiket/murmurent/blob/main/scripts/lab_sec_dump.sh)
(the root-owned snapshot script) and
[`scripts/sudoers.d/murmurent_sec_dump`](https://github.com/hallettmiket/murmurent/blob/main/scripts/sudoers.d/murmurent_sec_dump)
(the NOPASSWD grant template, currently authorising `the_pi` and
`core_lead`). One-time install on the target host:

```bash
# 1. SSH to the lab server.
ssh lab-server
cd ~/repos/murmurent
git pull

# 2. Verify the script's SHA256 matches what's recorded in the repo.
#    Defence-in-depth: detects in-flight tampering before the script
#    runs as root. Mismatch -> STOP, do not install.
(cd scripts && shasum -a 256 -c lab_sec_dump.sh.sha256)
(cd scripts/sudoers.d && shasum -a 256 -c murmurent_sec_dump.sha256)
# Expected (both):
#   lab_sec_dump.sh: OK
#   murmurent_sec_dump: OK

# 3. Install the root-owned snapshot script.
sudo install -m 0755 -o root -g root \
    scripts/lab_sec_dump.sh /opt/murmurent/lab_sec_dump.sh

# 4. Install the sudoers grant. Edit scripts/sudoers.d/murmurent_sec_dump
#    first if the authorised handles need to change.
sudo install -m 0440 -o root -g root \
    scripts/sudoers.d/murmurent_sec_dump /etc/sudoers.d/murmurent_sec_dump

# 5. Validate the sudoers file (REQUIRED — a bad sudoers file can lock
#    everyone out of sudo).
sudo visudo -c -f /etc/sudoers.d/murmurent_sec_dump
# Expected:
#   /etc/sudoers.d/murmurent_sec_dump: parsed OK

# 6. Smoke test — no password should be prompted.
sudo -n /opt/murmurent/lab_sec_dump.sh
# Expected: "lab_sec_dump: snapshot written to /var/lib/murmurent/.snapshot/<UTC-date>"
ls -la /var/lib/murmurent/.snapshot/latest/
# Expected files: manifest.json, acls_raw.txt, acls_refined.txt,
#                  sshd_runtime.txt, ssh_keys.jsonl, auth_summary.json

# 7. (Optional but recommended) Confirm the installed binary's hash
#    matches the source. Anyone with root could later modify
#    /opt/murmurent/lab_sec_dump.sh; running this periodically detects it.
sudo shasum -a 256 /opt/murmurent/lab_sec_dump.sh
diff <(sudo shasum -a 256 /opt/murmurent/lab_sec_dump.sh | awk '{print $1}') \
     <(awk '{print $1}' scripts/lab_sec_dump.sh.sha256) \
  && echo "installed binary matches source" \
  || echo "MISMATCH — investigate"
```

After step 5, the `/security` dashboard's **Run sudo dump** button works:
it SSHes to the host, runs `sudo -n /opt/murmurent/lab_sec_dump.sh`, and
the next live scan automatically ingests the snapshot (tarred + shipped
back, parsed locally) and merges Tier 2 findings into the table.

### What the script writes

Per-run directory at `/var/lib/murmurent/.snapshot/<UTC-date>/` on the
**local disk** of the host (NOT on the the NAS share: the NAS's NFSv4 ACLs
deny `root@<host>` write access since root isn't an AD principal there).
Owned by `root:labgroup`, mode 0750 (lab group reads; no one else).
Files:

| File | Contents |
|---|---|
| `manifest.json` | Script version, run timestamp, per-section status |
| `acls_raw.txt` | `nfs4_getfacl -R /srv/acl-view/lab_vm/raw` |
| `acls_refined.txt` | `nfs4_getfacl -R /srv/acl-view/lab_vm/refined` |
| `sshd_runtime.txt` | `sshd -T` (effective config, drop-ins resolved) |
| `ssh_keys.jsonl` | Per (member, key) row: type, comment, mtime, mode. **NO key bodies.** |
| `auth_summary.json` | 30-day per-user counts of publickey / password / failed auth + **distinct /16 subnet count** (raw IPs deliberately redacted: file is lab-group readable, so home networks etc. must not leak). For raw-IP detail, read `auth.log` directly on the host. |

The dashboard consumer parses each section independently: missing
sections only suppress that section's findings, never the whole audit.

A `latest` symlink in the same parent dir always points at the newest
snapshot, so consumers don't need to date-arithmetic.

### Retention

All snapshots are kept. Each is ~MB-scale, so a year of daily runs is
≈400 MB, negligible against the data volumes the lab handles. The
audit trail lets the PI answer "when did this ACL change?" by diffing
two snapshot dates. If storage ever becomes an issue, add a simple
cron to prune `.snapshot/` entries older than N months.

### Authorising more people

Edit `/etc/sudoers.d/murmurent_sec_dump` (via `sudo visudo -f`) and add a
line in the same form:

```
new_handle  ALL=(root) NOPASSWD: /opt/murmurent/lab_sec_dump.sh
```

Then run `sudo visudo -c -f /etc/sudoers.d/murmurent_sec_dump` to validate.

### Adjusting the lab tree being audited

The script has hardcoded paths (deliberate: narrows the sudo grant's
blast radius). To audit a different `<lab_vm>` root, edit the
constants at the top of `scripts/lab_sec_dump.sh` (`SNAPSHOT_BASE`,
`V4_ROOT`, `LAB_GROUP`), commit the change, re-pull on the host, and
re-run the `install` from step 2 above. The sudoers grant doesn't need
to change.

### When Tier 2 isn't available

If your cluster admin can't grant sudo (e.g. Chris can't expose a
non-sudo v4 mount or install the snippet), the dashboard runs in
**Tier 1 only mode**: the Tier 2 rule rows render with a yellow "?"
verdict and a one-line "ACL snapshot unavailable" note. POSIX-bit
scanners on `/data/lab_vm` stay skipped (per
`POSIX-NOT-AUTHORITATIVE-01`) to avoid noise. The dashboard remains
useful for `/home`, SSH keys, dotfiles, repos, and GitHub
visibility, just blind to the NAS ACLs.

---

## What the dashboard does *not* do

- **It never modifies any file on the target.** All suggested fixes
  are display-only strings. Specifically, **never** writes under
  `/data/lab_vm/raw/` or `/data/lab_vm/refined/`: even at the LLM
  agent-review layer, the `security_guard` agent's prompt forbids it.
- **It does not audit other labs' trees** (`/data/lab_*`). Scope is
  this lab's slice of the box.
- **It does not store credentials.** No SSH password prompts, no
  sudo password prompts. Sudo is either NOPASSWD-on-one-script or not
  available.

---

## Credits

The NFSv4 ACL primer and the per-directory template tables are based
on notes from **Dr. the core lead**, who configured the the NAS ACL
policy for the Hallett lab's `/data/lab_vm/` tree. Reproduced here
with her permission.
