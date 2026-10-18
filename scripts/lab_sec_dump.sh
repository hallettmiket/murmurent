#!/usr/bin/env bash
# Purpose: Root-owned snapshot script for the murmurent Tier-2 security
#          audit. Reads the real NFSv4 ACLs on the lab data tree
#          (immutable, append_only, modifiable, and the legacy raw and
#          refined) via a sudo-only root ACL view, the
#          authoritative sshd policy (`sshd -T`), and a lab-wide
#          authorized_keys summary. Writes one timestamped directory per
#          run; never overwrites history.
# Install: root:root mode 0755 at /opt/murmurent/lab_sec_dump.sh.
#          Granted via /etc/sudoers.d/murmurent_sec_dump (see template).
# Invoke:  `sudo -n /opt/murmurent/lab_sec_dump.sh`
#          REFUSES ARGUMENTS — keeps the sudo grant a single fixed
#          command with no parameter-injection surface.
#
# Configuration (all site-specific values come from /etc/default/murmurent,
# which scripts/install_security_snapshot.sh writes, so this script is
# institution-agnostic):
#   MURMURENT_ACL_ROOT      REQUIRED. The sudo-only root ACL view that
#                           exposes the real NFSv4 ACLs, e.g. a
#                           root-restricted NFSv4 re-export of the data
#                           tree, containing the governed data folders.
#   MURMURENT_LAB_GROUP     REQUIRED. Unix group that owns the snapshot
#                           dir; the lab group that may read it.
#   MURMURENT_SNAPSHOT_BASE Where snapshots are written (LOCAL disk).
#                           Default: /var/lib/murmurent/.snapshot
#   MURMURENT_DATA_ROOT     Lab data root (for member-handle discovery).
#                           (legacy: MURMURENT_LAB_VM_ROOT, still honoured)
#                           Default: /data/lab_vm
#   MURMURENT_HOME_GLOBS    Space-separated globs of member home dirs for
#                           the authorized_keys walk. Default: "/home/*"
#
# Output:  $MURMURENT_SNAPSHOT_BASE/<UTC-date>/
#            manifest.json       (script version, run timestamp, attempts)
#            acls_<folder>.txt   (nfs4_getfacl -R $MURMURENT_ACL_ROOT/<folder>,
#                                 one per governed data folder present)
#            sshd_runtime.txt    (sshd -T)
#            ssh_keys.jsonl      (per-member parsed authorized_keys; NO key bodies)
#            auth_summary.json   (last 30 days auth.log: pubkey/password counts)
#
# Output mode: dir 0750 owned by root:$MURMURENT_LAB_GROUP, files 0640 —
# readable by the lab group, never world-readable. Hard rule: this script
# is read-only with respect to the governed data content. It only
# writes into its own snapshot base directory.
#
# Versioned: bump SCRIPT_VERSION on any output-schema change so the
# dashboard consumer can detect/refuse old snapshots.

set -euo pipefail

# -- Site settings ------------------------------------------------------------
# sudo clears the environment, so the settings below cannot come from the
# caller. Read them from /etc/default/murmurent, written once by
# scripts/install_security_snapshot.sh. Only a root-owned file that no one
# else can change is trusted, because this script runs as root.
SITE_SETTINGS=/etc/default/murmurent
if [[ -f "$SITE_SETTINGS" ]]; then
    settings_owner=$(stat -c '%u' "$SITE_SETTINGS")
    settings_mode=$(stat -c '%a' "$SITE_SETTINGS")
    if [[ "$settings_owner" != 0 || "${settings_mode: -2:1}" =~ [2367] || "${settings_mode: -1}" =~ [2367] ]]; then
        echo "lab_sec_dump.sh: refusing $SITE_SETTINGS (must be owned by root and writable only by root)" >&2
        exit 78
    fi
    set -a
    # shellcheck disable=SC1090
    . "$SITE_SETTINGS"
    set +a
fi

SCRIPT_VERSION="8"   # v8 (#185): walks immutable/, append_only/ and
                     # modifiable/ as well as the legacy raw/ and refined/,
                     # for the lab and each core. Files are named
                     # acls_<folder>.txt and acls_core_<core>_<folder>.txt.
                     # v7: cores Phase 1c (per-core walks).
# Owner group on snapshot dir; readers. REQUIRED — no safe generic
# default (chgrp to the wrong group could leak the snapshot).
LAB_GROUP="${MURMURENT_LAB_GROUP:?set MURMURENT_LAB_GROUP to the lab unix group that may read the snapshot}"
# Snapshot output is on LOCAL DISK (ext4) rather than the network ACL
# store:
#  - Root on the lab server may not be a principal in the enterprise-NAS
#    ACLs, so even on the root ACL view we can't reliably ``mkdir`` under
#    the data tree.
#  - A local base dir is plain POSIX — root writes freely; chgrp + chmod
#    0750 give the lab group real read access.
# The root ACL view is still READ-only for our purposes: nfs4_getfacl
# needs it to enumerate ACLs on the data folders for the Tier-2 audit.
WRITE_BASE="${MURMURENT_SNAPSHOT_BASE:-/var/lib/murmurent/.snapshot}"
READ_BASE="$WRITE_BASE"   # same path on local disk — no NFS view to map.
# The sudo-only root ACL view that exposes the real NFSv4 ACLs (for ACL
# reads). REQUIRED — site-specific, no safe generic default.
V4_ROOT="${MURMURENT_ACL_ROOT:?set MURMURENT_ACL_ROOT to the sudo-only root ACL view of the data tree}"
LAB_MEMBERS_DIR="${MURMURENT_DATA_ROOT:-${MURMURENT_LAB_VM_ROOT:-/data/lab_vm}}"   # used for member-handle discovery
SSHD_CONFIG="/etc/ssh/sshd_config"
AUTH_LOG="/var/log/auth.log"
TODAY_UTC="$(date -u +%Y-%m-%d)"
NOW_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# -- Reject arguments -------------------------------------------------------
# The sudoers grant is for the script with no parameters. Anything extra
# is a sign of misuse or attempted exploit. Refuse early.
if [[ $# -gt 0 ]]; then
    echo "lab_sec_dump.sh refuses arguments (sudo grant is parameter-less)" >&2
    exit 64
fi

# -- Require root -----------------------------------------------------------
if [[ "$(id -u)" -ne 0 ]]; then
    echo "lab_sec_dump.sh must run as root (invoke via sudo)" >&2
    exit 77
fi

# -- Sanity: the root ACL view must be present ------------------------------
# Without the root ACL view, root on the ordinary (squashing) mount can't
# read the real ACLs. Fail with an explicit message rather than a cryptic
# nfs4_getfacl error.
if [[ ! -d "$V4_ROOT" ]]; then
    echo "lab_sec_dump: $V4_ROOT not mounted (the sudo-only root ACL view)." >&2
    echo "  Ask the sysadmin to add it to /etc/fstab — the script needs real root" >&2
    echo "  permissions on the ACL store, and the ordinary data mount squashes root." >&2
    exit 78
fi

# -- Prepare output dir -----------------------------------------------------
# Ensure the parent ``/var/lib/murmurent/.snapshot`` exists with the right
# ownership (root:LAB_GROUP, mode 0750). First-run-friendly: idempotent
# on re-installs.
mkdir -p "$WRITE_BASE"
chgrp "$LAB_GROUP" "$(dirname "$WRITE_BASE")" "$WRITE_BASE" 2>/dev/null || true
chmod 0750 "$(dirname "$WRITE_BASE")" "$WRITE_BASE"

OUT_DIR="${WRITE_BASE}/${TODAY_UTC}"
mkdir -p "$OUT_DIR"
# Group ownership so the lab can read the snapshot through the v3 mount
# (where they don't have sudo). The dir itself is 0750 — readable by
# group but not world.
chgrp "$LAB_GROUP" "$OUT_DIR" 2>/dev/null || true
chmod 0750 "$OUT_DIR"

manifest_attempts=()
echo "[$(date -u +%H:%M:%S)] lab_sec_dump v${SCRIPT_VERSION} starting; out_dir=$OUT_DIR" >&2
record_attempt() {
    # Append a small JSON-fragment line to the attempts list. We flatten
    # to JSON at the end.
    manifest_attempts+=("{\"step\":\"$1\",\"status\":\"$2\",\"detail\":\"$3\"}")
}

# Per-step progress goes to stderr so the user sees what's running even
# when they ssh into the script. Without this the script could appear to
# hang for many minutes while nfs4_getfacl walks a million files.
log() { echo "[$(date -u +%H:%M:%S)] $*" >&2; }

# Per-step timeouts. ACL walks can be slow on huge trees — give them a
# generous budget but bound the worst case. Each step also gets its own
# wall-clock measurement so the manifest carries useful diagnostics.
TIMEOUT_ACL="${LAB_SEC_DUMP_TIMEOUT_ACL:-600}"      # 10 min per ACL walk
TIMEOUT_SSHD="${LAB_SEC_DUMP_TIMEOUT_SSHD:-30}"
TIMEOUT_JOURNAL="${LAB_SEC_DUMP_TIMEOUT_JOURNAL:-60}"
TIMEOUT_KEYS="${LAB_SEC_DUMP_TIMEOUT_KEYS:-60}"

# Run a command bounded by ``timeout(1)``. Returns 0 on success, 124 on
# timeout, the command's rc otherwise. Stderr is preserved so caller can
# capture diagnostics.
bounded() {
    local secs="$1"; shift
    timeout --kill-after=10s "${secs}s" "$@"
}

# -- 1. NFSv4 ACLs on the governed data folders ----------------------------
# The governed folders (rules/data-storage.md). Read-only folders are walked
# whole; lab-shared folders project by project. Old and new names are both
# walked during the migration, each only if present (#185).
READONLY_DIRS=(immutable raw)
SHARED_DIRS=(append_only refined modifiable)

# Per-project budget for lab-shared folders. User report (v5): a global ``-R``
# over refined timed out at 600s — it has many large project subdirs and we
# don't want one giant project to block the rest. Budget is per project.
TIMEOUT_ACL_PER_PROJECT="${LAB_SEC_DUMP_TIMEOUT_ACL_PER_PROJECT:-300}"  # 5 min default

# dump_acl_whole <src_dir> <attempt_name>: one recursive nfs4_getfacl over a
# folder into $OUT_DIR/<attempt_name>.txt. Records skip/ok/timeout/fail.
# nfs4_getfacl produces a multi-line block per file; on a tree with thousands
# of files this is the slowest step (seconds-to-minutes).
dump_acl_whole() {
    local src="$1" name="$2"
    local out="$OUT_DIR/$name.txt"
    if [[ ! -d "$src" ]]; then
        record_attempt "$name" "skip" "$src not present"
        return 0
    fi
    log "nfs4_getfacl -R $src (budget ${TIMEOUT_ACL}s) — may take minutes on large trees"
    local start=$SECONDS rc
    if bounded "$TIMEOUT_ACL" nfs4_getfacl -R "$src" > "$out" 2>"$OUT_DIR/$name.stderr"; then
        chmod 0640 "$out"
        chgrp "$LAB_GROUP" "$out" 2>/dev/null || true
        record_attempt "$name" "ok" "$(wc -l < "$out") lines in $((SECONDS-start))s"
    else
        rc=$?
        if [[ $rc -eq 124 || $rc -eq 137 ]]; then
            record_attempt "$name" "timeout" "exceeded ${TIMEOUT_ACL}s; bump LAB_SEC_DUMP_TIMEOUT_ACL"
            log "  TIMEOUT — partial output may be in $out"
        else
            record_attempt "$name" "fail" "nfs4_getfacl rc=$rc"
        fi
    fi
}

# dump_acl_per_project <src_dir> <attempt_name>: the folder's own ACL, then
# one recursive walk per top-level project, each under its own budget, so one
# slow project only times itself out.
dump_acl_per_project() {
    local src="$1" name="$2"
    local out="$OUT_DIR/$name.txt"
    if [[ ! -d "$src" ]]; then
        record_attempt "$name" "skip" "$src not present"
        return 0
    fi
    log "nfs4_getfacl -R $src — per-project walk (${TIMEOUT_ACL_PER_PROJECT}s each)"
    : > "$out"
    local n_ok=0 n_timeout=0 n_fail=0 total_start=$SECONDS proj_dir proj proj_start rc status
    nfs4_getfacl "$src" >> "$out" 2>"$OUT_DIR/$name.stderr" || true
    for proj_dir in "$src"/*/; do
        [[ -d "$proj_dir" ]] || continue
        proj=$(basename "$proj_dir")
        log "  $proj"
        proj_start=$SECONDS
        if bounded "$TIMEOUT_ACL_PER_PROJECT" nfs4_getfacl -R "$proj_dir" \
           >> "$out" 2>>"$OUT_DIR/$name.stderr"; then
            n_ok=$((n_ok + 1))
            log "    ok ($((SECONDS-proj_start))s)"
        else
            rc=$?
            if [[ $rc -eq 124 || $rc -eq 137 ]]; then
                n_timeout=$((n_timeout + 1))
                log "    TIMEOUT — partial output kept"
            else
                n_fail=$((n_fail + 1))
                log "    FAIL rc=$rc"
            fi
        fi
    done
    chmod 0640 "$out"
    chgrp "$LAB_GROUP" "$out" 2>/dev/null || true
    if [[ $n_timeout -eq 0 && $n_fail -eq 0 ]]; then
        status="ok"
    elif [[ $n_ok -gt 0 ]]; then
        status="partial"
    else
        status="fail"
    fi
    record_attempt "$name" "$status" \
        "$n_ok ok, $n_timeout timeout, $n_fail fail (total $((SECONDS-total_start))s)"
}

for kind in "${READONLY_DIRS[@]}"; do
    dump_acl_whole "$V4_ROOT/$kind" "acls_$kind"
done
for kind in "${SHARED_DIRS[@]}"; do
    dump_acl_per_project "$V4_ROOT/$kind" "acls_$kind"
done

# -- 1c. Per-core ACL walks (cores Phase 1c) -------------------------------
# Each registered core's data tree lives at $V4_ROOT/core/<core>/<folder>/.
# We walk every core present on the filesystem (no centre-registry
# lookup required — the directory is authoritative for what's actually
# on disk on the server). Each folder gets its own dump file named
# acls_core_<core>_<folder>.txt so the Python consumer can route per-core
# findings without splitting one giant blob.
CORE_ROOT="$V4_ROOT/core"
if [[ -d "$CORE_ROOT" ]]; then
    log "scanning per-core trees under $CORE_ROOT"
    core_count=0
    for core_dir in "$CORE_ROOT"/*/; do
        [[ -d "$core_dir" ]] || continue
        core=$(basename "$core_dir")
        core_count=$((core_count + 1))
        log "  core: $core"
        for kind in "${READONLY_DIRS[@]}"; do
            dump_acl_whole "$core_dir$kind" "acls_core_${core}_$kind"
        done
        for kind in "${SHARED_DIRS[@]}"; do
            dump_acl_per_project "$core_dir$kind" "acls_core_${core}_$kind"
        done
    done
    log "  walked $core_count cores"
else
    record_attempt "cores" "skip" "$CORE_ROOT not present (no cores deployed)"
fi

# -- 2. sshd policy (authoritative via `sshd -T`) ---------------------------
sshd_file="$OUT_DIR/sshd_runtime.txt"
if command -v sshd >/dev/null 2>&1; then
    log "sshd -T (budget ${TIMEOUT_SSHD}s)"
    if bounded "$TIMEOUT_SSHD" sshd -T -C "user=root,host=localhost,addr=127.0.0.1" 2>/dev/null \
       | sort > "$sshd_file"; then
        chmod 0640 "$sshd_file"
        chgrp "$LAB_GROUP" "$sshd_file" 2>/dev/null || true
        record_attempt "sshd_runtime" "ok" "$(wc -l < "$sshd_file") effective settings"
    else
        # Some sshd versions reject -C with their config; retry plain -T.
        if bounded "$TIMEOUT_SSHD" sshd -T > "$sshd_file" 2>/dev/null; then
            chmod 0640 "$sshd_file"
            chgrp "$LAB_GROUP" "$sshd_file" 2>/dev/null || true
            record_attempt "sshd_runtime" "ok" "$(wc -l < "$sshd_file") effective settings (no -C)"
        else
            record_attempt "sshd_runtime" "fail" "sshd -T returned non-zero"
        fi
    fi
else
    record_attempt "sshd_runtime" "skip" "sshd binary not in PATH"
fi

# -- 3. authorized_keys summary across lab members --------------------------
# For each lab member who has a real home directory, parse
# ~/.ssh/authorized_keys into structured rows (type, comment, mtime, mode).
# We NEVER emit the key body — only metadata. This keeps the snapshot
# safe to leave group-readable.
log "ssh_keys walk (budget ${TIMEOUT_KEYS}s)"
keys_start=$SECONDS
keys_file="$OUT_DIR/ssh_keys.jsonl"
: > "$keys_file"
key_count=0

# Member discovery: iterate the configured home-dir globs. Sites with an
# LDAP/AD home convention (e.g. /home/<REALM>/*) can set MURMURENT_HOME_GLOBS
# to match; the default covers the common /home/* layout.
# shellcheck disable=SC2086
for home in ${MURMURENT_HOME_GLOBS:-/home/*}; do
    # Cheap soft-stop if the whole walk runs over budget — homes can be
    # numerous on shared hosts and a single hung NFS-mounted home would
    # otherwise stall everything.
    [[ $((SECONDS - keys_start)) -ge $TIMEOUT_KEYS ]] && {
        log "  ssh_keys walk hit budget at $home — truncating"
        break
    }
    [[ -d "$home" ]] || continue
    ak="$home/.ssh/authorized_keys"
    [[ -f "$ak" ]] || continue
    user="$(basename "$home")"
    file_mode=$(stat -c '%a' "$ak" 2>/dev/null || echo "")
    file_mtime=$(stat -c '%Y' "$ak" 2>/dev/null || echo "0")
    # Parse one row per key line. NEVER include the base64 body.
    while IFS= read -r line; do
        # Strip comments and skip blank/option-only lines.
        line="${line%%#*}"
        [[ -z "${line// }" ]] && continue
        ktype=$(echo "$line" | awk '{
            for(i=1;i<=NF;i++) if ($i ~ /^(ssh-rsa|ssh-dss|ssh-ed25519|ecdsa-sha2-[a-z0-9-]+|sk-)/) {print $i; exit}
        }')
        [[ -z "$ktype" ]] && continue
        kcomment=$(echo "$line" | awk '{print $NF}')
        # JSON-encode the comment defensively (escape " and \).
        kcomment_esc="${kcomment//\\/\\\\}"
        kcomment_esc="${kcomment_esc//\"/\\\"}"
        printf '{"user":"%s","type":"%s","comment":"%s","authorized_keys_mode":"%s","authorized_keys_mtime":%s}\n' \
            "$user" "$ktype" "$kcomment_esc" "$file_mode" "$file_mtime" >> "$keys_file"
        key_count=$((key_count + 1))
    done < "$ak"
done
chmod 0640 "$keys_file"
chgrp "$LAB_GROUP" "$keys_file" 2>/dev/null || true
record_attempt "ssh_keys" "ok" "$key_count keys across lab members"

# -- 4. auth.log summary (last 30 days) -------------------------------------
# Per-user counts of: publickey accepts, password accepts, failed attempts,
# and the set of source IPs. Never emit raw log lines (they may contain
# usernames / IPs the user wants to keep in the box, not on the dashboard).
auth_file="$OUT_DIR/auth_summary.json"
if [[ -r "$AUTH_LOG" ]]; then
    # Window: last 30 days. journalctl is more reliable than parsing
    # syslog timestamps which span year boundaries; fall back to auth.log
    # if journald isn't there.
    log "auth.log/journal slice (budget ${TIMEOUT_JOURNAL}s)"
    if command -v journalctl >/dev/null 2>&1; then
        log_slice=$(bounded "$TIMEOUT_JOURNAL" journalctl --since="30 days ago" _COMM=sshd --no-pager 2>/dev/null || true)
    fi
    if [[ -z "${log_slice:-}" ]]; then
        log_slice="$(bounded "$TIMEOUT_JOURNAL" tail -n 100000 "$AUTH_LOG" 2>/dev/null || true)"
    fi
    # Pass the log slice via stdin (heredoc was conflicting with the
    # Python script source heredoc). Use ``python3 -c`` with the script
    # inline; sys.stdin reads the log.
    printf '%s' "${log_slice:-}" | python3 -c '
# Privacy hygiene: this file lands in the snapshot base dir with the lab
# group readable. We emit ONLY counts + a small
# subnet hint (/16 bucket count) per user — never raw IPs. A lab
# member reading the snapshot learns that user X had N publickey
# logins from K distinct /16 buckets in the last 30 days; they do NOT
# learn the IPs themselves (which would leak home networks, hotels,
# etc.). The dashboard surfaces the same anonymised summary.
import sys, json, re, collections
out_path = sys.argv[1]
text = sys.stdin.read()
per_user = collections.defaultdict(lambda: {"publickey":0, "password":0, "failed":0, "subnets":set()})
def _bucket(ip):
    # Coarse /16 bucket for IPv4; full address otherwise (rare in logs).
    parts = ip.split(".")
    return ".".join(parts[:2]) + ".0.0/16" if len(parts) == 4 else "non-v4"
for line in text.splitlines():
    m = re.search(r"Accepted (publickey|password) for (\S+) from (\S+)", line)
    if m:
        method, user, ip = m.group(1), m.group(2), m.group(3)
        per_user[user][method] += 1
        per_user[user]["subnets"].add(_bucket(ip))
        continue
    m = re.search(r"Failed (\S+) for (?:invalid user )?(\S+) from (\S+)", line)
    if m:
        user = m.group(2)
        per_user[user]["failed"] += 1
        per_user[user]["subnets"].add(_bucket(m.group(3)))
out = {u: {"publickey": d["publickey"], "password": d["password"],
            "failed": d["failed"],
            "distinct_subnets": len(d["subnets"])}
       for u, d in per_user.items()}
with open(out_path, "w") as fh:
    json.dump(out, fh, indent=2, sort_keys=True)
' "$auth_file"
    chmod 0640 "$auth_file"
    chgrp "$LAB_GROUP" "$auth_file" 2>/dev/null || true
    record_attempt "auth_summary" "ok" "30-day window"
else
    record_attempt "auth_summary" "skip" "auth.log not readable"
fi

# -- 5. manifest ------------------------------------------------------------
# Single source of truth for the consumer: which sections succeeded,
# script version, run timestamp.
manifest_file="$OUT_DIR/manifest.json"
attempts_json=$(IFS=,; echo "${manifest_attempts[*]}")
READ_DIR="${READ_BASE}/${TODAY_UTC}"
cat > "$manifest_file" <<EOF
{
  "script_version": "$SCRIPT_VERSION",
  "generated_at": "$NOW_ISO",
  "hostname": "$(hostname -s 2>/dev/null || echo unknown)",
  "write_dir": "$OUT_DIR",
  "read_dir": "$READ_DIR",
  "lab_group": "$LAB_GROUP",
  "v4_root": "$V4_ROOT",
  "attempts": [$attempts_json]
}
EOF
chmod 0640 "$manifest_file"
chgrp "$LAB_GROUP" "$manifest_file" 2>/dev/null || true

# -- 6. Refresh ``latest`` symlink for consumer convenience ----------------
# Symlink target is just the basename, so it resolves correctly when
# read via either mount.
ln -sfn "$TODAY_UTC" "$WRITE_BASE/latest"

echo "lab_sec_dump: snapshot written to $READ_DIR (via $OUT_DIR)"
exit 0
