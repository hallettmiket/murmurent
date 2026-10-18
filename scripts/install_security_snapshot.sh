#!/usr/bin/env bash
# Purpose: Install (or update) the murmurent Tier-2 security snapshot on a lab
#          server, and retire an older install made under the project's
#          previous name, wigamig.
# Author:  Mike Hallett (with Claude Code)
# Date:    2026-10-18
# Input:   Run from a murmurent checkout, as root via sudo:
#            sudo bash scripts/install_security_snapshot.sh            # install
#            sudo bash scripts/install_security_snapshot.sh --dry-run  # preview
#          Optional: --acl-root <dir> --lab-group <unix group>. Without them,
#          the values are read from the existing install (new or old name).
# Output:  /opt/murmurent/lab_sec_dump.sh         the snapshot script
#          /etc/default/murmurent                 this server's settings
#          /etc/sudoers.d/murmurent_sec_dump      lets the invoking user run it
#          /var/lib/murmurent/.snapshot/          snapshot results (old ones copied over)
#          /var/backups/wigamig_retired_<date>/   the old wigamig pieces, moved aside
#
# Safe to run more than once. The sudoers file is checked with `visudo -c`
# before it is put in place, so a mistake cannot lock anyone out of sudo.
# Nothing is deleted: old pieces are moved into the backup folder.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_SCRIPT="$HERE/lab_sec_dump.sh"

INSTALL_DIR=/opt/murmurent
INSTALLED_SCRIPT="$INSTALL_DIR/lab_sec_dump.sh"
SETTINGS_FILE=/etc/default/murmurent
SUDOERS_FILE=/etc/sudoers.d/murmurent_sec_dump
SNAPSHOT_PARENT=/var/lib/murmurent
SNAPSHOT_BASE="$SNAPSHOT_PARENT/.snapshot"

OLD_SCRIPT=/opt/wigamig/lab_sec_dump.sh
OLD_SUDOERS=/etc/sudoers.d/wigamig_sec_dump
OLD_SNAPSHOT_PARENT=/var/lib/wigamig
BACKUP_DIR="/var/backups/wigamig_retired_$(date +%Y-%m-%d)"

DRY_RUN=0
ACL_ROOT=""
LAB_GROUP=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dry-run)   DRY_RUN=1; shift;;
        --acl-root)  ACL_ROOT="$2"; shift 2;;
        --lab-group) LAB_GROUP="$2"; shift 2;;
        -h|--help)   sed -n '2,21p' "$0"; exit 0;;
        *) echo "unknown option: $1 (try --help)" >&2; exit 2;;
    esac
done

say()  { echo "  $*"; }
step() { echo; echo "== $*"; }
# run <command...>: do it, or only print it in --dry-run.
run() {
    if [[ $DRY_RUN -eq 1 ]]; then echo "  would run: $*"; else "$@"; fi
}

if [[ $DRY_RUN -eq 0 && "$(id -u)" -ne 0 ]]; then
    echo "Run this with sudo:  sudo bash $0" >&2
    echo "To preview without changing anything:  bash $0 --dry-run" >&2
    exit 1
fi
[[ -f "$SOURCE_SCRIPT" ]] || { echo "cannot find $SOURCE_SCRIPT" >&2; exit 1; }

OPERATOR="${SUDO_USER:-$(id -un)}"
if [[ "$OPERATOR" == root ]]; then
    echo "Run this as yourself with sudo (not from a root shell), so the" >&2
    echo "permission is granted to your login." >&2
    exit 1
fi

# -- 1. Work out this server's settings ---------------------------------------
# Order: command line, then an existing /etc/default/murmurent, then the old
# wigamig script, which had them written inside it.
value_from_settings() {
    [[ -r "$SETTINGS_FILE" ]] || return 0
    sed -n "s/^$1=[\"']\{0,1\}\([^\"']*\)[\"']\{0,1\}\$/\1/p" "$SETTINGS_FILE" | tail -1
}
value_from_old_script() {
    [[ -r "$OLD_SCRIPT" ]] || return 0
    sed -n "s/^$1=\"\([^\"]*\)\".*/\1/p" "$OLD_SCRIPT" | head -1
}
[[ -n "$ACL_ROOT" ]]  || ACL_ROOT="$(value_from_settings MURMURENT_ACL_ROOT)"
[[ -n "$LAB_GROUP" ]] || LAB_GROUP="$(value_from_settings MURMURENT_LAB_GROUP)"
[[ -n "$ACL_ROOT" ]]  || ACL_ROOT="$(value_from_old_script V4_ROOT)"
[[ -n "$LAB_GROUP" ]] || LAB_GROUP="$(value_from_old_script LAB_GROUP)"

step "Settings for this server"
if [[ -z "$ACL_ROOT" || -z "$LAB_GROUP" ]]; then
    echo "  Could not find this server's settings. Give them explicitly:" >&2
    echo "    sudo bash $0 --acl-root <root-only view of the data folder> --lab-group <lab unix group>" >&2
    exit 1
fi
say "data folder seen by root (ACL view): $ACL_ROOT"
say "lab unix group (may read results):   $LAB_GROUP"
say "permission granted to:               $OPERATOR"
if [[ "$(id -u)" -ne 0 ]]; then
    say "(preview without sudo cannot look inside $ACL_ROOT; the real run checks it)"
elif [[ ! -d "$ACL_ROOT" ]]; then
    say "WARNING: $ACL_ROOT is not a folder on this machine; the snapshot will fail until it is mounted."
fi
getent group "$LAB_GROUP" >/dev/null || { echo "  unix group $LAB_GROUP does not exist" >&2; exit 1; }

# -- 2. Settings file -----------------------------------------------------------
step "Writing $SETTINGS_FILE"
settings_text="# murmurent Tier-2 security snapshot settings for this server.
# Written by scripts/install_security_snapshot.sh. Read by $INSTALLED_SCRIPT.
MURMURENT_ACL_ROOT=\"$ACL_ROOT\"
MURMURENT_LAB_GROUP=\"$LAB_GROUP\"
MURMURENT_SNAPSHOT_BASE=\"$SNAPSHOT_BASE\""
if [[ $DRY_RUN -eq 1 ]]; then
    echo "$settings_text" | sed 's/^/  would write: /'
else
    printf '%s\n' "$settings_text" > "$SETTINGS_FILE"
    chown root:root "$SETTINGS_FILE"
    chmod 0644 "$SETTINGS_FILE"
fi

# -- 3. The snapshot script -------------------------------------------------------
step "Installing $INSTALLED_SCRIPT"
# Check the script against its recorded fingerprint before installing it to
# run as root. A mismatch means the file changed after it was released: stop.
( cd "$HERE" && sha256sum -c --quiet lab_sec_dump.sh.sha256 ) \
    || { echo "  lab_sec_dump.sh does not match lab_sec_dump.sh.sha256; NOT installing." >&2; exit 1; }
say "fingerprint matches lab_sec_dump.sh.sha256"
run install -d -m 0755 -o root -g root "$INSTALL_DIR"
run install -m 0755 -o root -g root "$SOURCE_SCRIPT" "$INSTALLED_SCRIPT"

# -- 4. Permission to run it without a password ------------------------------------
step "Granting $OPERATOR permission in $SUDOERS_FILE"
grant_line="$OPERATOR ALL=(root) NOPASSWD: $INSTALLED_SCRIPT"
existing=""
[[ -r "$SUDOERS_FILE" ]] && existing="$(cat "$SUDOERS_FILE")"
if grep -qxF "$grant_line" <<<"$existing"; then
    say "already granted"
else
    new_text="$existing"
    [[ -n "$new_text" ]] || new_text="# Lets these users run the murmurent security snapshot (one fixed command)."
    new_text="$new_text
$grant_line"
    if [[ $DRY_RUN -eq 1 ]]; then
        say "would add: $grant_line"
    else
        tmp="$(mktemp)"
        printf '%s\n' "$new_text" > "$tmp"
        visudo -c -q -f "$tmp" || { rm -f "$tmp"; echo "  sudoers check failed; nothing changed" >&2; exit 1; }
        install -m 0440 -o root -g root "$tmp" "$SUDOERS_FILE"
        rm -f "$tmp"
    fi
fi

# -- 5. Results folder, with the old results copied over ---------------------------
step "Results folder $SNAPSHOT_BASE"
run install -d -m 0750 -o root -g "$LAB_GROUP" "$SNAPSHOT_PARENT"
if [[ -d "$OLD_SNAPSHOT_PARENT/.snapshot" && ! -e "$SNAPSHOT_BASE" ]]; then
    say "copying earlier results from $OLD_SNAPSHOT_PARENT/.snapshot"
    run cp -a "$OLD_SNAPSHOT_PARENT/.snapshot" "$SNAPSHOT_BASE"
else
    run install -d -m 0750 -o root -g "$LAB_GROUP" "$SNAPSHOT_BASE"
fi

# -- 6. Retire the old wigamig install -----------------------------------------------
step "Moving the old wigamig pieces to $BACKUP_DIR"
found_old=0
for old in "$OLD_SCRIPT" "$OLD_SUDOERS" "$OLD_SNAPSHOT_PARENT"; do
    if [[ -e "$old" ]]; then
        found_old=1
        run install -d -m 0700 -o root -g root "$BACKUP_DIR"
        run mv "$old" "$BACKUP_DIR/"
    fi
done
# The old script's folder is empty once the script has moved out of it.
if [[ -d /opt/wigamig ]]; then
    run rmdir /opt/wigamig || say "left /opt/wigamig in place (it holds other files)"
fi
[[ $found_old -eq 1 ]] || say "none found"

# -- 7. Final check ---------------------------------------------------------------------
step "Checking"
if [[ $DRY_RUN -eq 1 ]]; then
    say "dry run: nothing was changed"
else
    visudo -c -q && say "sudo configuration is valid"
    sudo -n -l -U "$OPERATOR" 2>/dev/null | grep -qF "$INSTALLED_SCRIPT" \
        && say "$OPERATOR may run $INSTALLED_SCRIPT"
    echo
    echo "Done. To take a snapshot, press 'Run sudo dump' on the dashboard's"
    echo "security audit page, or run:  sudo -n $INSTALLED_SCRIPT"
fi
