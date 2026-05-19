#!/usr/bin/env bash
# Purpose: Root-owned snapshot script for the wigamig Tier-2 security
#          audit. Reads the real NFSv4 ACLs on /data/lab_vm/{raw,refined}
#          via the sudo-only /srv/acl-view mount, the authoritative sshd
#          policy (`sshd -T`), and a lab-wide authorized_keys summary.
#          Writes one timestamped directory per run; never overwrites
#          history.
# Install: root:root mode 0755 at /opt/wigamig/lab_sec_dump.sh.
#          Granted via /etc/sudoers.d/wigamig_sec_dump (see template).
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

SCRIPT_VERSION="4"   # v4: snapshot lives on local disk (/var/lib/wigamig);
                     # the NAS NFSv4 ACLs deny root write under /data/lab_vm
                     # even via the v4 mount, so the snapshot can't live
                     # there. We still READ /srv/acl-view for ACL audits.
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
record_attempt() {
    # Append a small JSON-fragment line to the attempts list. We flatten
    # to JSON at the end.
    manifest_attempts+=("{\"step\":\"$1\",\"status\":\"$2\",\"detail\":\"$3\"}")
}

# -- 1. NFSv4 ACLs on raw + refined -----------------------------------------
# nfs4_getfacl produces a multi-line block per file; -R recurses. On a
# tree with thousands of files this is the slowest step (seconds-to-minutes).
acls_raw_file="$OUT_DIR/acls_raw.txt"
if [[ -d "$V4_ROOT/raw" ]]; then
    if nfs4_getfacl -R "$V4_ROOT/raw" > "$acls_raw_file" 2>/dev/null; then
        chmod 0640 "$acls_raw_file"
        chgrp "$LAB_GROUP" "$acls_raw_file" 2>/dev/null || true
        record_attempt "acls_raw" "ok" "$(wc -l < "$acls_raw_file") lines"
    else
        record_attempt "acls_raw" "fail" "nfs4_getfacl returned non-zero"
    fi
else
    record_attempt "acls_raw" "skip" "$V4_ROOT/raw not present (mount missing?)"
fi

acls_refined_file="$OUT_DIR/acls_refined.txt"
if [[ -d "$V4_ROOT/refined" ]]; then
    if nfs4_getfacl -R "$V4_ROOT/refined" > "$acls_refined_file" 2>/dev/null; then
        chmod 0640 "$acls_refined_file"
        chgrp "$LAB_GROUP" "$acls_refined_file" 2>/dev/null || true
        record_attempt "acls_refined" "ok" "$(wc -l < "$acls_refined_file") lines"
    else
        record_attempt "acls_refined" "fail" "nfs4_getfacl returned non-zero"
    fi
else
    record_attempt "acls_refined" "skip" "$V4_ROOT/refined not present"
fi

# -- 2. sshd policy (authoritative via `sshd -T`) ---------------------------
sshd_file="$OUT_DIR/sshd_runtime.txt"
if command -v sshd >/dev/null 2>&1; then
    if sshd -T -C "user=root,host=localhost,addr=127.0.0.1" 2>/dev/null \
       | sort > "$sshd_file"; then
        chmod 0640 "$sshd_file"
        chgrp "$LAB_GROUP" "$sshd_file" 2>/dev/null || true
        record_attempt "sshd_runtime" "ok" "$(wc -l < "$sshd_file") effective settings"
    else
        # Some sshd versions reject -C with their config; retry plain -T.
        if sshd -T > "$sshd_file" 2>/dev/null; then
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
keys_file="$OUT_DIR/ssh_keys.jsonl"
: > "$keys_file"
key_count=0

# Member discovery: iterate /home/UWO/ (lab-server LDAP convention).
# Adjust the glob if your site puts homes elsewhere.
for home in /home/UWO/* /home/*; do
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
    if command -v journalctl >/dev/null 2>&1; then
        log_slice=$(journalctl --since="30 days ago" _COMM=sshd --no-pager 2>/dev/null || true)
    fi
    if [[ -z "${log_slice:-}" ]]; then
        log_slice="$(tail -n 100000 "$AUTH_LOG" 2>/dev/null || true)"
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
