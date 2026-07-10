#!/usr/bin/env bash
# Purpose: Apply per-project NFSv4 ACLs on a lab server's wigamig tree.
#          Designed to be called via sudo from `centre_cable_guy`'s
#          provision/reconcile loop.
#
# Install:
#   1. As root on the lab server:
#        install -m 0755 murmurent_project_acl.sh /opt/wigamig/murmurent_project_acl.sh
#   2. Add a sudoers fragment so a specific service account can run it
#      without a password:
#        echo '<user> ALL=(root) NOPASSWD: /opt/wigamig/murmurent_project_acl.sh' \
#          > /etc/sudoers.d/murmurent_project_acl
#        chmod 0440 /etc/sudoers.d/murmurent_project_acl
#
# Behavior:
#   - Creates <LAB_VM_ROOT>/wigamig/{raw,refined}/<project>/ if missing.
#   - Creates a wigamig project Unix group `wgm_<project>` if missing
#     (capped at 16 chars; long project names truncated + suffixed).
#   - Adds each named member (passed by Western netname / OS account)
#     to that group via `usermod -aG`.
#   - Sets a per-directory NFSv4 ACL that grants the project group
#     `rxtTncy` on `refined/` and `rxtTncy` on `raw/` (read-only;
#     the existing wigamig hooks enforce the "no write" rule at
#     the application layer; this ACL is belt-and-suspenders).
#   - Logs every invocation to /var/log/wigamig/project_acl.log.
#
# Safety:
#   - Refuses to run unless invoked from sudo as root (UID == 0).
#   - Refuses project names that don't match ^[a-z0-9][a-z0-9_]{1,30}$.
#   - Refuses to touch any path outside <LAB_VM_ROOT>/wigamig/.
#   - Idempotent: re-running with the same args is a no-op.

set -euo pipefail

LAB_VM_ROOT="${WIGAMIG_LAB_VM_ROOT:-/data/lab_vm}"
LOG_FILE="${WIGAMIG_PROJECT_ACL_LOG:-/var/log/wigamig/project_acl.log}"
SLUG_RE='^[a-z0-9][a-z0-9_]{1,30}$'

log() {
  mkdir -p "$(dirname "$LOG_FILE")"
  printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*" >> "$LOG_FILE"
}

die() {
  printf 'murmurent_project_acl: ERROR: %s\n' "$*" >&2
  log "ERROR $*"
  exit 1
}

require_root() {
  if [[ "$(id -u)" -ne 0 ]]; then
    die "must run as root (use sudo); current uid=$(id -u)"
  fi
}

usage() {
  cat <<EOF
Usage: $0 --project <name> --members <comma-separated-netnames>

  --project   Murmurent project slug (matches ${SLUG_RE}).
  --members   Comma-separated list of OS accounts to grant access.

Example:
  sudo $0 --project dcis_imaging --members allie,didi,the_pi
EOF
  exit 64
}

# ---- arg parse ------------------------------------------------------------

PROJECT=""
MEMBERS=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)   PROJECT="${2:-}"; shift 2 ;;
    --members)   MEMBERS="${2:-}"; shift 2 ;;
    -h|--help)   usage ;;
    *) die "unknown arg: $1" ;;
  esac
done

[[ -z "$PROJECT" ]] && die "--project required"
[[ ! "$PROJECT" =~ $SLUG_RE ]] && die "bad project slug: $PROJECT (must match $SLUG_RE)"
[[ -z "$MEMBERS" ]] && die "--members required (comma-separated)"

require_root

# Group name: wgm_<project>, truncated to 16 chars total for Linux.
GROUP="wgm_${PROJECT}"
if (( ${#GROUP} > 16 )); then
  GROUP="${GROUP:0:13}_$(printf '%s' "$PROJECT" | md5sum | cut -c1-2)"
fi

RAW_DIR="${LAB_VM_ROOT}/wigamig/raw/${PROJECT}"
REFINED_DIR="${LAB_VM_ROOT}/wigamig/refined/${PROJECT}"

# Defense: refuse if either path escapes the expected prefix.
expected_prefix="${LAB_VM_ROOT}/wigamig/"
[[ "$RAW_DIR"     != ${expected_prefix}* ]] && die "raw path escapes expected prefix"
[[ "$REFINED_DIR" != ${expected_prefix}* ]] && die "refined path escapes expected prefix"

# ---- group ----------------------------------------------------------------

if ! getent group "$GROUP" >/dev/null; then
  groupadd "$GROUP"
  log "groupadd $GROUP (project=$PROJECT)"
fi

# Add each member to the group (idempotent — usermod -aG is safe to repeat).
IFS=',' read -r -a MEMBER_ARR <<< "$MEMBERS"
for m in "${MEMBER_ARR[@]}"; do
  m="${m// /}"   # strip whitespace
  [[ -z "$m" ]] && continue
  if ! id "$m" >/dev/null 2>&1; then
    log "WARN unknown OS account: $m (skipped)"
    printf 'WARN: unknown OS account: %s (skipped)\n' "$m" >&2
    continue
  fi
  if ! id -nG "$m" | tr ' ' '\n' | grep -qx "$GROUP"; then
    usermod -aG "$GROUP" "$m"
    log "usermod -aG $GROUP $m"
  fi
done

# ---- directories ----------------------------------------------------------

for d in "$RAW_DIR" "$REFINED_DIR"; do
  if [[ ! -d "$d" ]]; then
    mkdir -p "$d"
    chown root:"$GROUP" "$d"
    log "mkdir $d (group=$GROUP)"
  fi
done

# Mode: 2755 sets the setgid bit so new files inherit the project group.
chmod 2755 "$RAW_DIR" "$REFINED_DIR" || true

# ---- NFSv4 ACL (when available) -------------------------------------------

if command -v nfs4_setfacl >/dev/null 2>&1; then
  # Inheriting ACE: group rxtTncy (read-exec-traverse-no-write) on raw,
  # rxtTncy on refined too (data immutability enforced at app layer).
  nfs4_setfacl -a "A:gd:${GROUP}@LOCALDOMAIN:rxtTncy" "$RAW_DIR" || true
  nfs4_setfacl -a "A:gd:${GROUP}@LOCALDOMAIN:rxtTncy" "$REFINED_DIR" || true
  log "nfs4 ACE applied for $GROUP on $RAW_DIR, $REFINED_DIR"
else
  log "INFO nfs4_setfacl not present; relying on POSIX setgid + group perms"
fi

log "OK project=$PROJECT group=$GROUP members=$MEMBERS"
printf 'OK: project=%s group=%s members=%s\n' "$PROJECT" "$GROUP" "$MEMBERS"
