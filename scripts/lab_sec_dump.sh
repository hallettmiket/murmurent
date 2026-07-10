#!/usr/bin/env bash
# Purpose: Root-owned snapshot script for the wigamig Tier-2 security
#          audit. Reads the real NFSv4 ACLs on /data/lab_vm/{raw,refined}
#          via the sudo-only /srv/acl-view mount, the authoritative sshd
#          policy (`sshd -T`), and a lab-wide authorized_keys summary.
#          Writes one timestamped directory per run; never overwrites
#          history.
# Install: root:root mode 0755 at /opt/wigamig/lab_sec_dump.sh.
#          Granted via /etc/sudoers.d/murmurent_sec_dump (see template).
# Invoke:  `sudo -n /opt/wigamig/lab_sec_dump.sh`
#          REFUSES ARGUMENTS — keeps the sudo grant a single fixed
#          command with no parameter-injection surface.
#
# Output:  /data/lab_vm/wigamig/.snapshot/<UTC-date>/
#            manifest.json       (script version, run timestamp, attempts)
#            acls_raw.txt        (nfs4_getfacl -R /srv/acl-view/lab_vm/raw)
#            acls_refined.txt    (nfs4_getfacl -R /srv/acl-view/lab_vm/refined)
#            sshd_runtime.txt    (sshd -T)
#            ssh_keys.jsonl      (per-member parsed authorized_keys; NO key bodies)
#            auth_summary.json   (last 30 days auth.log: pubkey/password counts)
#
# Output mode: dir 0750 owned by root:labgroup, files 0640 — readable
# by the lab group via /data, never world-readable. Hard rule: this script
# is read-only with respect to /data/lab_vm/{raw,refined} content. It only
# writes into the .snapshot/ subdirectory.
#
# Versioned: bump SCRIPT_VERSION on any output-schema change so the
# dashboard consumer can detect/refuse old snapshots.

set -euo pipefail

SCRIPT_VERSION="7"   # v7: cores Phase 1c — also walks $V4_ROOT/core/<core>/
                     # {raw,refined}/ for each core present on the lab
                     # server. Emits acls_core_<core>_{raw,refined}.txt
                     # so the consumer can route per-core findings.
LAB_GROUP="labgroup"     # owner group on snapshot dir; readers
# Snapshot output is on LOCAL DISK (ext4) rather than the NAS:
#  - Root on lab-server isn't a principal in the the NAS ACLs, so even on
#    the v4 mount we can't ``mkdir`` under /srv/acl-view/lab_vm/wigamig/.
#  - Local /var/lib/wigamig is plain POSIX — root writes freely; chgrp
#    + chmod 0750 give the lab group real read access.
# The v4 mount is still READ-only for our purposes: nfs4_getfacl needs
# it to enumerate ACLs on raw/refined for the Tier-2 audit.
WRITE_BASE="/var/lib/wigamig/.snapshot"
READ_BASE="$WRITE_BASE"   # same path on local disk — no NFS view to map.
V4_ROOT="/srv/acl-view/lab_vm"  # the sudo-only NFSv4 mount (for ACL reads)
LAB_MEMBERS_DIR="/data/lab_vm/wigamig"   # used for member-handle discovery
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

# -- Sanity: the v4 mount must be present -----------------------------------
# Without the v4 mount, root on v3 is squashed to nobody and we can't
# write the snapshot anywhere under /data/lab_vm. Fail with an explicit
# message rather than a cryptic mkdir error.
if [[ ! -d "/srv/acl-view/lab_vm" ]]; then
    echo "lab_sec_dump: /srv/acl-view/lab_vm not mounted (the sudo-only NFSv4 mount)." >&2
    echo "  Ask the sysadmin to add it to /etc/fstab — the script needs real root" >&2
    echo "  permissions on the the NAS export, and the v3 /data mount squashes root." >&2
    exit 78
fi

# -- Prepare output dir -----------------------------------------------------
# Ensure the parent ``/var/lib/wigamig/.snapshot`` exists with the right
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

# -- 1. NFSv4 ACLs on raw + refined -----------------------------------------
# nfs4_getfacl produces a multi-line block per file; -R recurses. On a
# tree with thousands of files this is the slowest step (seconds-to-minutes).
acls_raw_file="$OUT_DIR/acls_raw.txt"
if [[ -d "$V4_ROOT/raw" ]]; then
    log "nfs4_getfacl -R raw (budget ${TIMEOUT_ACL}s) — may take minutes on large trees"
    start=$SECONDS
    if bounded "$TIMEOUT_ACL" nfs4_getfacl -R "$V4_ROOT/raw" > "$acls_raw_file" 2>"$OUT_DIR/acls_raw.stderr"; then
        chmod 0640 "$acls_raw_file"
        chgrp "$LAB_GROUP" "$acls_raw_file" 2>/dev/null || true
        record_attempt "acls_raw" "ok" "$(wc -l < "$acls_raw_file") lines in $((SECONDS-start))s"
    else
        rc=$?
        if [[ $rc -eq 124 || $rc -eq 137 ]]; then
            record_attempt "acls_raw" "timeout" "exceeded ${TIMEOUT_ACL}s; bump LAB_SEC_DUMP_TIMEOUT_ACL"
            log "  TIMEOUT — partial output may be in $acls_raw_file"
        else
            record_attempt "acls_raw" "fail" "nfs4_getfacl rc=$rc"
        fi
    fi
else
    record_attempt "acls_raw" "skip" "$V4_ROOT/raw not present (mount missing?)"
fi

acls_refined_file="$OUT_DIR/acls_refined.txt"
: > "$acls_refined_file"
# Per-project budget for refined. User report (v5): a global ``-R``
# over refined timed out at 600s — refined has many large project
# subdirs and we don't want one giant project to block the rest. Walk
# each top-level subdir separately so each gets its own budget and one
# slow project only times itself out. Budget is per-project, not global.
TIMEOUT_ACL_PER_PROJECT="${LAB_SEC_DUMP_TIMEOUT_ACL_PER_PROJECT:-300}"  # 5 min default
if [[ -d "$V4_ROOT/refined" ]]; then
    log "nfs4_getfacl -R refined — per-project walk (${TIMEOUT_ACL_PER_PROJECT}s each)"
    refined_ok=0
    refined_timeout=0
    refined_fail=0
    refined_total_start=$SECONDS
    # First, dump the refined root ACL itself (cheap, no recursion).
    nfs4_getfacl "$V4_ROOT/refined" >> "$acls_refined_file" 2>"$OUT_DIR/acls_refined.stderr" || true
    # Then walk each project subdir under its own timeout.
    for proj_dir in "$V4_ROOT/refined"/*/; do
        [[ -d "$proj_dir" ]] || continue
        proj=$(basename "$proj_dir")
        log "  refined/$proj"
        proj_start=$SECONDS
        if bounded "$TIMEOUT_ACL_PER_PROJECT" nfs4_getfacl -R "$proj_dir" \
           >> "$acls_refined_file" 2>>"$OUT_DIR/acls_refined.stderr"; then
            refined_ok=$((refined_ok + 1))
            log "    ok ($((SECONDS-proj_start))s)"
        else
            rc=$?
            if [[ $rc -eq 124 || $rc -eq 137 ]]; then
                refined_timeout=$((refined_timeout + 1))
                log "    TIMEOUT — partial output kept"
            else
                refined_fail=$((refined_fail + 1))
                log "    FAIL rc=$rc"
            fi
        fi
    done
    chmod 0640 "$acls_refined_file"
    chgrp "$LAB_GROUP" "$acls_refined_file" 2>/dev/null || true
    if [[ $refined_timeout -eq 0 && $refined_fail -eq 0 ]]; then
        status="ok"
    elif [[ $refined_ok -gt 0 ]]; then
        status="partial"
    else
        status="fail"
    fi
    record_attempt "acls_refined" "$status" \
        "$refined_ok ok, $refined_timeout timeout, $refined_fail fail (total $((SECONDS-refined_total_start))s)"
else
    record_attempt "acls_refined" "skip" "$V4_ROOT/refined not present"
fi

# -- 1c. Per-core ACL walks (cores Phase 1c) -------------------------------
# Each registered core's data tree lives at $V4_ROOT/core/<core>/{raw,refined}/.
# We walk every core present on the filesystem (no centre-registry
# lookup required — the directory is authoritative for what's actually
# on disk on the server). Each core gets its own pair of dump files
# named acls_core_<core>_raw.txt + acls_core_<core>_refined.txt so the
# Python consumer can route per-core findings without splitting one
# giant blob. Same per-project budget applies to refined/ subdirs.
CORE_ROOT="$V4_ROOT/core"
if [[ -d "$CORE_ROOT" ]]; then
    log "scanning per-core trees under $CORE_ROOT"
    core_count=0
    for core_dir in "$CORE_ROOT"/*/; do
        [[ -d "$core_dir" ]] || continue
        core=$(basename "$core_dir")
        core_count=$((core_count + 1))
        log "  core: $core"
        # core/<core>/raw — same shape as lab raw: walk recursively
        cr_file="$OUT_DIR/acls_core_${core}_raw.txt"
        if [[ -d "$core_dir/raw" ]]; then
            start=$SECONDS
            if bounded "$TIMEOUT_ACL" nfs4_getfacl -R "$core_dir/raw" \
               > "$cr_file" 2>"$OUT_DIR/acls_core_${core}_raw.stderr"; then
                chmod 0640 "$cr_file"
                chgrp "$LAB_GROUP" "$cr_file" 2>/dev/null || true
                record_attempt "acls_core_${core}_raw" "ok" \
                    "$(wc -l < "$cr_file") lines in $((SECONDS-start))s"
            else
                rc=$?
                if [[ $rc -eq 124 || $rc -eq 137 ]]; then
                    record_attempt "acls_core_${core}_raw" "timeout" "exceeded ${TIMEOUT_ACL}s"
                else
                    record_attempt "acls_core_${core}_raw" "fail" "rc=$rc"
                fi
            fi
        else
            record_attempt "acls_core_${core}_raw" "skip" "$core_dir/raw not present"
        fi
        # core/<core>/refined — same per-project per-project walk.
        cf_file="$OUT_DIR/acls_core_${core}_refined.txt"
        : > "$cf_file"
        if [[ -d "$core_dir/refined" ]]; then
            cf_ok=0; cf_timeout=0; cf_fail=0
            cf_start=$SECONDS
            nfs4_getfacl "$core_dir/refined" >> "$cf_file" \
                2>"$OUT_DIR/acls_core_${core}_refined.stderr" || true
            for proj_dir in "$core_dir/refined"/*/; do
                [[ -d "$proj_dir" ]] || continue
                proj=$(basename "$proj_dir")
                if bounded "$TIMEOUT_ACL_PER_PROJECT" nfs4_getfacl -R "$proj_dir" \
                   >> "$cf_file" 2>>"$OUT_DIR/acls_core_${core}_refined.stderr"; then
                    cf_ok=$((cf_ok + 1))
                else
                    rc=$?
                    if [[ $rc -eq 124 || $rc -eq 137 ]]; then
                        cf_timeout=$((cf_timeout + 1))
                    else
                        cf_fail=$((cf_fail + 1))
                    fi
                fi
            done
            chmod 0640 "$cf_file"
            chgrp "$LAB_GROUP" "$cf_file" 2>/dev/null || true
            if [[ $cf_timeout -eq 0 && $cf_fail -eq 0 ]]; then
                cf_status="ok"
            elif [[ $cf_ok -gt 0 ]]; then
                cf_status="partial"
            else
                cf_status="fail"
            fi
            record_attempt "acls_core_${core}_refined" "$cf_status" \
                "$cf_ok ok, $cf_timeout timeout, $cf_fail fail (total $((SECONDS-cf_start))s)"
        else
            record_attempt "acls_core_${core}_refined" "skip" "$core_dir/refined not present"
        fi
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

# Member discovery: iterate /home/UWO/ (lab-server LDAP convention).
# Adjust the glob if your site puts homes elsewhere.
for home in /home/UWO/* /home/*; do
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
# Privacy hygiene: this file lands at /data/lab_vm/wigamig/.snapshot/...
# with group labgroup readable. We emit ONLY counts + a small
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
