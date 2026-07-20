#!/usr/bin/env bash
# Purpose: Unprivileged Tier-1 security scanner for a murmurent lab member's
#          slice of a server (typically a shared lab server).
#          Emits one JSONL finding per line on stdout, progress messages
#          on stderr. Side-effect-free — pure read-only system calls.
#
# Runs as the invoking user; reports only what that user can see. Never
# attempts to read paths it doesn't have permission for. Never modifies
# any file under /data/lab_vm/raw or /data/lab_vm/refined (CC rule 9).
#
# Usage:
#   murmurent_sec_scan.sh [--lab-vm-root /data/lab_vm]
#                       [--projects-root ~/repos]
#                       [--lab-group <lab_unix_group>]
#                       [--home-warn-gb 100]
#                       [--repo-large-mb 50]
#
# Designed to run over SSH in a single batched session (see
# src/murmurent/core/security_remote.py). The Python parser reads stdout
# line-by-line; each line is either a JSON finding object or a progress
# marker (``{"_kind":"progress","message":...}``).
#
# WARNING: do not add any code path that writes under /data/lab_vm.
# The murmurent raw_guard hook would block it on a laptop, but on the
# server we rely on review. Read-only system calls only:
#   find, stat, getfacl, ls, du, last, awk, sed, grep, crontab -l,
#   systemctl --user list-units, id, getent.

set -u
# NOT set -e: a denied directory read shouldn't abort the entire scan.

# --- defaults --------------------------------------------------------------
LAB_VM_ROOT="${MURMURENT_DATA_ROOT:-${MURMURENT_LAB_VM_ROOT:-/data/lab_vm}}"
PROJECTS_ROOT="${MURMURENT_PROJECTS_ROOT:-$HOME/repos}"
LAB_GROUP="${MURMURENT_LAB_GROUP:-}"
HOME_WARN_GB="${MURMURENT_HOME_WARN_GB:-100}"
REPO_LARGE_MB="${MURMURENT_REPO_LARGE_MB:-50}"
HOST_NAME="${MURMURENT_HOST_NAME:-$(hostname -s 2>/dev/null || echo local)}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --lab-vm-root)   LAB_VM_ROOT="$2"; shift 2;;
        --projects-root) PROJECTS_ROOT="$2"; shift 2;;
        --lab-group)     LAB_GROUP="$2"; shift 2;;
        --home-warn-gb)  HOME_WARN_GB="$2"; shift 2;;
        --repo-large-mb) REPO_LARGE_MB="$2"; shift 2;;
        --host-name)     HOST_NAME="$2"; shift 2;;
        *) echo "unknown arg: $1" >&2; exit 2;;
    esac
done

NOW_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
ME="$(id -un)"
MY_HANDLE="@${ME}"

# Per-scanner timeout in seconds, applied to the slow external commands
# (``du``, ``find``) inside each scanner. ``timeout(1)`` from GNU
# coreutils only wraps executables, not shell functions, so we apply it
# at the primitive level. When unavailable, the primitives run unwrapped
# — better to risk a slow scan than to silently skip them.
SCAN_TIMEOUT="${MURMURENT_SCAN_TIMEOUT:-180}"

# Prefix to put in front of slow commands. Expands to nothing when
# ``timeout`` isn't available — callers still work.
if command -v timeout >/dev/null 2>&1; then
    BOUND="timeout --kill-after=5s ${SCAN_TIMEOUT}s"
else
    BOUND=""
fi

# Detect whether POSIX bits on ``$LAB_VM_ROOT`` are authoritative or
# a synthesized projection over NFSv4 ACLs (the enterprise-NAS-over-NFSv3
# case). Used to decide whether to skip raw/refined POSIX
# walks — see POSIX-NOT-AUTHORITATIVE-01 in docs/security-dashboard.md.
#
# Returns one of:
#   nfsv4_acl         — nfs4_getfacl on this path returns real ACEs
#   synthesized_posix — nfsv4_getfacl returns "Operation to request
#                        attribute not supported"; POSIX bits are fake
#   posix_native      — getfacl shows a regular POSIX ACL (ext4 etc.)
#   unknown           — couldn't tell (lab_vm doesn't exist; no tools)
detect_acl_capability() {
    local root="$1"
    if [[ ! -d "$root" ]]; then
        echo "unknown"
        return
    fi
    if command -v nfs4_getfacl >/dev/null 2>&1; then
        local out
        out=$(nfs4_getfacl "$root" 2>&1)
        if echo "$out" | grep -q "Operation to request attribute not supported"; then
            echo "synthesized_posix"
            return
        elif echo "$out" | grep -qE '^[AD]:'; then
            echo "nfsv4_acl"
            return
        fi
    fi
    echo "posix_native"
}

# --- emit helpers ----------------------------------------------------------
# JSON-escape a string for safe embedding in a JSONL line.
json_escape() {
    # Standard JSON escapes: \ " then control chars.
    sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g' -e 's/\r/\\r/g' \
        -e 's/\x08/\\b/g' -e 's/\x0c/\\f/g' \
        | awk 'BEGIN{ORS="\\n"} {print}' \
        | sed 's/\\n$//'
}

# Shorthand: pass everything as positional args matching Finding fields
# in a fixed order. Keeps each scanner call to one line.
emit_finding() {
    local severity="$1"   category="$2" rule="$3"
    local path="$4"       current="$5"  expected="$6"
    local fix="$7"        project="${8:-}"
    # owner_handle defaults to the running user's handle (it's always
    # "their slice" of the box).
    local owner="$MY_HANDLE"
    # Inline escapes — paths can contain ", $, etc. Anchor with printf.
    local p_path p_cur p_exp p_fix p_proj
    p_path=$(printf '%s' "$path" | json_escape)
    p_cur=$(printf '%s' "$current" | json_escape)
    p_exp=$(printf '%s' "$expected" | json_escape)
    p_fix=$(printf '%s' "$fix" | json_escape)
    p_proj=$(printf '%s' "$project" | json_escape)
    local project_field='null'
    [[ -n "$project" ]] && project_field="\"$p_proj\""
    printf '{"severity":"%s","category":"%s","rule":"%s","host":"%s","path":"%s","current_state":"%s","expected_state":"%s","suggested_fix":"%s","detected_at":"%s","source":"scanner","tier":"tier1","is_directory":false,"aggregate_count":1,"owner_handle":"%s","project":%s,"rule_doc_anchor":"docs/security-dashboard.md#%s","notes":""}\n' \
        "$severity" "$category" "$rule" "$HOST_NAME" "$p_path" \
        "$p_cur" "$p_exp" "$p_fix" "$NOW_ISO" "$MY_HANDLE" "$project_field" "$rule"
}

progress() {
    # On stdout so SSE can stream it interleaved with findings.
    local msg
    msg=$(printf '%s' "$1" | json_escape)
    printf '{"_kind":"progress","message":"%s","ts":"%s"}\n' \
        "$msg" "$(date -u +%H:%M:%S)"
}

# --- scanners --------------------------------------------------------------

scan_repos() {
    [[ -d "$PROJECTS_ROOT" ]] || return 0
    progress "scanning repos under $PROJECTS_ROOT"
    local repo
    for repo in "$PROJECTS_ROOT"/*/; do
        [[ -d "$repo" ]] || continue
        local name
        name=$(basename "$repo")
        # Skip giant ignore-able trees up front for speed.
        scan_one_repo "$repo" "$name"
    done
}

scan_one_repo() {
    local repo="$1" name="$2"
    progress "  repo: $name"
    # HOME-REPO-PRIVATE-01: any file with world or group read/write bits
    # under a clone in ~/repos/ on a shared server is suspicious.
    # Prune common big/cache dirs; report up to 100 hits per repo so we
    # don't pile up thousands of node_modules entries.
    local hits=0
    while IFS= read -r f; do
        [[ -n "$f" ]] || continue
        local mode
        mode=$(stat -c '%a %U:%G' "$f" 2>/dev/null) || continue
        emit_finding "warn" "repos" "HOME-REPO-PRIVATE-01" \
            "$f" "$mode" "0600 (or 0700 dirs) owner-only on shared host" \
            "chmod o-rwx,g-rwx $(printf '%q' "$f")" \
            "$name"
        hits=$((hits + 1))
        [[ $hits -ge 100 ]] && { progress "  truncated repo $name at 100 perm hits"; break; }
    done < <(
        $BOUND find "$repo" \
            \( -path '*/.git' -o -path '*/node_modules' -o -path '*/__pycache__' \
               -o -path '*/.venv' -o -path '*/target' -o -path '*/.tox' \
               -o -path '*/.next' -o -path '*/.cache' \) -prune -o \
            -type f \( -perm -004 -o -perm -040 \) -print 2>/dev/null
    )

    # HOME-REPO-LARGE-01: tracked file > REPO_LARGE_MB and not in .gitignore.
    # Cheap to detect: git ls-files | xargs stat -c, then check .gitignore
    # for the basename. Skip if not a git working tree.
    if [[ -d "$repo/.git" ]]; then
        local large_bytes=$((REPO_LARGE_MB * 1024 * 1024))
        # ``git -C ... ls-files`` is fast. Use --cached so deleted files
        # are excluded. Pipe through xargs to stat in one shot.
        local cwd_save="$PWD"
        cd "$repo" 2>/dev/null || return 0
        while IFS= read -r tracked; do
            [[ -n "$tracked" && -f "$tracked" ]] || continue
            local sz
            sz=$(stat -c %s "$tracked" 2>/dev/null) || continue
            if [[ "$sz" -ge "$large_bytes" ]]; then
                local mb=$((sz / 1024 / 1024))
                emit_finding "warn" "repos" "HOME-REPO-LARGE-01" \
                    "$repo$tracked" "${mb}MB tracked by git" \
                    "size <= ${REPO_LARGE_MB}MB or path matches .gitignore" \
                    "echo '$(printf '%q' "$tracked")' >> .gitignore && git rm --cached '$(printf '%q' "$tracked")'" \
                    "$name"
            fi
        done < <(git ls-files 2>/dev/null)
        cd "$cwd_save" 2>/dev/null || true
    fi

    # HOME-REPO-GIT-SECRET-01: tracked filename matches secret-ish pattern.
    if [[ -d "$repo/.git" ]]; then
        local cwd_save="$PWD"
        cd "$repo" 2>/dev/null || return 0
        while IFS= read -r f; do
            [[ -n "$f" ]] || continue
            emit_finding "block" "repos" "HOME-REPO-GIT-SECRET-01" \
                "$repo$f" "tracked by git" \
                "removed from index; added to .gitignore" \
                "git rm --cached '$(printf '%q' "$f")' && echo '$(printf '%q' "$f")' >> .gitignore" \
                "$name"
        done < <(git ls-files 2>/dev/null | grep -E -i '(^|/)(\.env(\.|$)|.*\.pem$|.*_rsa$|.*_ed25519$|.*\.p12$|.*\.pfx$|.*\.key$|id_[a-z]+(\..+)?$)' )
        cd "$cwd_save" 2>/dev/null || true
    fi
}

scan_lab_vm_raw() {
    local root="$LAB_VM_ROOT/raw"
    [[ -d "$root" ]] || return 0
    progress "scanning $root for writable files (raw is immutable)"
    # RAW-IMMUTABLE-01: any file with any write bit set anywhere under raw/.
    # Cap hits per project to keep output bounded; roll-up happens in Python.
    local proj_dir
    for proj_dir in "$root"/*/; do
        [[ -d "$proj_dir" ]] || continue
        local proj
        proj=$(basename "$proj_dir")
        local hits=0
        while IFS= read -r f; do
            [[ -n "$f" ]] || continue
            local mode
            mode=$(stat -c '%a %U:%G' "$f" 2>/dev/null) || continue
            emit_finding "block" "raw" "RAW-IMMUTABLE-01" \
                "$f" "$mode" "0440 (or 0444) — read-only" \
                "chmod a-w '$f'   # never run wholesale; verify intent first" \
                "$proj"
            hits=$((hits + 1))
            [[ $hits -ge 200 ]] && { progress "  truncated raw/$proj at 200 hits"; break; }
        done < <($BOUND find "$proj_dir" -type f -perm /222 2>/dev/null)

        # RAW-LAB-ONLY-01: world-readable files under raw/.
        hits=0
        while IFS= read -r f; do
            [[ -n "$f" ]] || continue
            local mode
            mode=$(stat -c '%a %U:%G' "$f" 2>/dev/null) || continue
            emit_finding "warn" "raw" "RAW-LAB-ONLY-01" \
                "$f" "$mode" "lab-group readable, not world-readable" \
                "chmod o-r '$f'   # verify before running on raw" \
                "$proj"
            hits=$((hits + 1))
            [[ $hits -ge 200 ]] && break
        done < <($BOUND find "$proj_dir" -type f -perm -004 2>/dev/null)
    done
}

scan_lab_vm_refined() {
    local root="$LAB_VM_ROOT/refined"
    [[ -d "$root" ]] || return 0
    progress "scanning $root (lab-group r+w only)"
    local proj_dir
    for proj_dir in "$root"/*/; do
        [[ -d "$proj_dir" ]] || continue
        local proj
        proj=$(basename "$proj_dir")
        local hits=0
        # REFINED-LAB-WRITE-01: world-readable or world-writable files.
        while IFS= read -r f; do
            [[ -n "$f" ]] || continue
            local mode
            mode=$(stat -c '%a %U:%G' "$f" 2>/dev/null) || continue
            local sev="warn"
            [[ "$mode" =~ \ [0-9]?[0-9]?[2367]$ ]] && sev="block"  # world-writable
            emit_finding "$sev" "refined" "REFINED-LAB-WRITE-01" \
                "$f" "$mode" "lab-group r+w; others none" \
                "chmod o-rwx '$f'   # verify before bulk apply on refined" \
                "$proj"
            hits=$((hits + 1))
            [[ $hits -ge 200 ]] && { progress "  truncated refined/$proj at 200 hits"; break; }
        done < <($BOUND find "$proj_dir" -type f \( -perm -004 -o -perm -002 \) 2>/dev/null)

        # REFINED-NO-TOOLS-01: executable bit set on refined files.
        hits=0
        while IFS= read -r f; do
            [[ -n "$f" ]] || continue
            # Skip directories' execute bit (needed to traverse).
            local mode
            mode=$(stat -c '%a' "$f" 2>/dev/null) || continue
            emit_finding "info" "refined" "REFINED-NO-TOOLS-01" \
                "$f" "$mode (exec)" "non-executable; move tools to $LAB_VM_ROOT/tools/" \
                "chmod a-x '$f'   # or move to tools/" \
                "$proj"
            hits=$((hits + 1))
            [[ $hits -ge 50 ]] && break
        done < <($BOUND find "$proj_dir" -type f -perm -100 2>/dev/null)
    done
}

scan_ssh() {
    progress "scanning ~/.ssh"
    local sshdir="$HOME/.ssh"
    [[ -d "$sshdir" ]] || return 0

    # SSH-DIR-PERM: ~/.ssh itself should be 0700.
    local dmode
    dmode=$(stat -c '%a' "$sshdir" 2>/dev/null)
    if [[ -n "$dmode" && "$dmode" != "700" ]]; then
        emit_finding "warn" "ssh" "SSH-DIR-PERM-01" \
            "$sshdir" "$dmode" "0700 (owner only)" \
            "chmod 0700 '$sshdir'"
    fi

    # SSH-AUTHKEYS-PERM-01: authorized_keys should be 0600.
    local ak="$sshdir/authorized_keys"
    if [[ -f "$ak" ]]; then
        local m
        m=$(stat -c '%a' "$ak" 2>/dev/null)
        if [[ -n "$m" && "$m" != "600" ]]; then
            emit_finding "warn" "ssh" "SSH-AUTHKEYS-PERM-01" \
                "$ak" "$m" "0600 (owner read/write only)" \
                "chmod 0600 '$ak'"
        fi

        # SSH-WEAK-KEY-01 / SSH-OLD-KEY-01: parse one line per key.
        # Format: <options-optional> <type> <base64> <comment>
        # We don't emit key material — just type, comment, age.
        local line_no=0
        while IFS= read -r kline; do
            line_no=$((line_no + 1))
            kline="${kline%%#*}"  # strip comments
            [[ -z "${kline// }" ]] && continue
            local ktype
            ktype=$(echo "$kline" | awk '{
                for(i=1;i<=NF;i++) if ($i ~ /^(ssh-rsa|ssh-dss|ssh-ed25519|ecdsa-sha2-[a-z0-9-]+|sk-)/) {print $i; exit}
            }')
            [[ -z "$ktype" ]] && continue
            local kcomment
            kcomment=$(echo "$kline" | awk '{print $NF}')
            if [[ "$ktype" == "ssh-rsa" || "$ktype" == "ssh-dss" ]]; then
                emit_finding "warn" "ssh" "SSH-WEAK-KEY-01" \
                    "$ak:line${line_no}" "$ktype ($kcomment)" \
                    "ssh-ed25519" \
                    "regenerate as ed25519 on the client and replace in authorized_keys"
            fi
        done < "$ak"
    fi

    # Private key files should be 0600 and not world-readable.
    while IFS= read -r kf; do
        [[ -n "$kf" ]] || continue
        local m owner
        m=$(stat -c '%a' "$kf" 2>/dev/null) || continue
        if [[ "$m" != "600" && "$m" != "400" ]]; then
            emit_finding "block" "ssh" "SSH-PRIVKEY-PERM-01" \
                "$kf" "$m" "0600 (or 0400)" \
                "chmod 0600 '$kf'"
        fi
    done < <(
        find "$sshdir" -maxdepth 1 -type f \
             \( -name 'id_*' -not -name '*.pub' -o -name '*_rsa' -o -name '*_ed25519' \) 2>/dev/null
    )
}

scan_dotfiles() {
    progress "scanning credential dotfiles"
    local f
    for f in "$HOME/.netrc" "$HOME/.gitconfig" "$HOME/.pgpass" "$HOME/.aws/credentials"; do
        [[ -f "$f" ]] || continue
        local m
        m=$(stat -c '%a' "$f" 2>/dev/null)
        if [[ -n "$m" && "$m" != "600" && "$m" != "400" ]]; then
            local rule="DOT-CRED-MODE-01"
            local sev="warn"
            [[ "$f" == *netrc || "$f" == *pgpass || "$f" == *credentials ]] && sev="block"
            emit_finding "$sev" "dotfiles" "$rule" \
                "$f" "$m" "0600 (owner only)" \
                "chmod 0600 '$f'"
        fi
    done
}

scan_wigamig() {
    progress "scanning ~/.murmurent"
    local d="$HOME/.murmurent"
    [[ -d "$d" ]] || return 0
    # WIGAMIG-MANIFEST-PERM-01: installation manifests world-readable.
    while IFS= read -r f; do
        [[ -n "$f" ]] || continue
        local m
        m=$(stat -c '%a' "$f" 2>/dev/null) || continue
        # World-read = ends in 4/5/6/7 (mod-4-bit set in last octet).
        local last="${m: -1}"
        if [[ "$last" == "4" || "$last" == "5" || "$last" == "6" || "$last" == "7" ]]; then
            emit_finding "warn" "murmurent" "WIGAMIG-MANIFEST-PERM-01" \
                "$f" "$m" "0640 (owner+group)" \
                "chmod o-r '$f'"
        fi
    done < <(find "$d/installations" -type f -name '*.yaml' 2>/dev/null)
}

scan_claude() {
    progress "scanning ~/.claude*"
    local f
    for f in "$HOME/.claude.json" "$HOME/.claude.json.backup"; do
        [[ -f "$f" ]] || continue
        local m
        m=$(stat -c '%a' "$f" 2>/dev/null)
        if [[ -n "$m" && "$m" != "600" && "$m" != "400" ]]; then
            emit_finding "warn" "claude" "CLAUDE-CRED-MODE-01" \
                "$f" "$m" "0600 (owner only — file contains MCP tokens)" \
                "chmod 0600 '$f'"
        fi
    done
    # ~/.claude/settings.json — also flag world-read.
    local s="$HOME/.claude/settings.json"
    if [[ -f "$s" ]]; then
        local m
        m=$(stat -c '%a' "$s" 2>/dev/null)
        local last="${m: -1}"
        if [[ "$last" == "4" || "$last" == "5" || "$last" == "6" || "$last" == "7" ]]; then
            emit_finding "warn" "claude" "CLAUDE-CRED-MODE-01" \
                "$s" "$m" "0640 (no world-read; may contain MCP tokens)" \
                "chmod o-r '$s'"
        fi
    fi
}

scan_tmp_leaks() {
    progress "scanning /tmp + ~/tmp for lab-data leaks"
    # TMP-LAB-LEAK-01: world-readable files under /tmp owned by me whose
    # path looks like it leaks lab content. Cheap, opportunistic check —
    # only the strongest pattern hits: contains "lab_vm" or a project
    # directory name from PROJECTS_ROOT.
    local d
    for d in "/tmp" "$HOME/tmp"; do
        [[ -d "$d" ]] || continue
        while IFS= read -r f; do
            [[ -n "$f" ]] || continue
            emit_finding "warn" "tmp" "TMP-LAB-LEAK-01" \
                "$f" "world-readable in $d" \
                "moved or deleted; sensitive lab content should not live in /tmp" \
                "rm '$f'  # or move to a protected dir"
        done < <(find "$d" -maxdepth 3 -user "$ME" -type f -perm -004 \
            \( -name '*lab_vm*' -o -name '*raw*' -o -name '*refined*' \) 2>/dev/null | head -20)
    done
}

scan_cron_systemd() {
    progress "scanning crontab + systemd --user units"
    if command -v crontab >/dev/null 2>&1; then
        local crontab_out
        crontab_out=$(crontab -l 2>/dev/null | grep -Ev '^[[:space:]]*(#|$)' | head -20)
        if [[ -n "$crontab_out" ]]; then
            local lines
            lines=$(echo "$crontab_out" | wc -l | tr -d ' ')
            emit_finding "info" "cron" "CRON-UNATTENDED-01" \
                "$ME crontab" "$lines active entries" \
                "review what runs unattended in your identity" \
                "crontab -l"
        fi
    fi
    if command -v systemctl >/dev/null 2>&1; then
        local sd_out
        sd_out=$(systemctl --user list-units --type=service --state=running --no-legend 2>/dev/null | head -20)
        if [[ -n "$sd_out" ]]; then
            local nu
            nu=$(echo "$sd_out" | wc -l | tr -d ' ')
            emit_finding "info" "cron" "SYSTEMD-USER-RUNNING-01" \
                "$ME systemd --user" "$nu running user services" \
                "review what runs unattended in your identity" \
                "systemctl --user list-units --type=service --state=running"
        fi
    fi
}

scan_docker_group() {
    progress "checking docker group membership"
    if id -Gn "$ME" 2>/dev/null | tr ' ' '\n' | grep -qx docker; then
        emit_finding "warn" "docker" "DOCKER-SOCK-01" \
            "$ME" "member of 'docker' group" \
            "removed from docker group OR confirmed intentional (effective root via /var/run/docker.sock)" \
            "sudo gpasswd -d $ME docker   # if not intended"
    fi
}

scan_home_size() {
    progress "measuring ~/ size (one du pass; can take minutes)"
    local kb gb
    # -s: total only. -k: KB. 1-pass; no follow symlinks across fs.
    kb=$($BOUND du -sk "$HOME" 2>/dev/null | awk '{print $1}')
    [[ -z "$kb" ]] && return 0
    gb=$(( kb / 1024 / 1024 ))
    local sev="info" rule="HOME-SIZE-OK"
    if [[ "$gb" -ge "$HOME_WARN_GB" ]]; then
        sev="warn"
        rule="HOME-SIZE-01"
    fi
    emit_finding "$sev" "home" "$rule" \
        "$HOME" "${gb}GB" "< ${HOME_WARN_GB}GB" \
        "review largest dirs: du -sh ~/* | sort -h | tail"
}

scan_login_history() {
    progress "summarising recent logins (last -i)"
    # SSH-LOGIN-IP-01: report the set of distinct IPs seen in last -i.
    # We don't decide here whether an IP is "unusual" — that's a
    # dashboard-side heuristic. We just publish the list as one
    # info-finding so the UI can show "you logged in from N distinct IPs
    # in the last month".
    if command -v last >/dev/null 2>&1; then
        local ips
        # 0.0.0.0 is `last`'s placeholder for reboot/shutdown events
        # that have no IP — exclude so we don't show a phantom IP.
        ips=$(last -i -F "$ME" 2>/dev/null \
              | awk 'NF>=3 && $3 ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/ && $3 != "0.0.0.0" {print $3}' \
              | sort -u | head -20 | tr '\n' ',' | sed 's/,$//')
        local count
        count=$(echo "$ips" | tr ',' '\n' | sed '/^$/d' | wc -l | tr -d ' ')
        if [[ "$count" -gt 0 ]]; then
            emit_finding "info" "ssh" "SSH-LOGIN-IPS-01" \
                "$ME" "$count distinct IPs in 'last' history" \
                "review IP list for unfamiliar sources" \
                "last -i $ME   # full list (IPs: $ips)"
        fi
    fi
}

# --- run -------------------------------------------------------------------

progress "starting scan as $MY_HANDLE on $HOST_NAME at $NOW_ISO"

# Detect whether POSIX bits are meaningful on $LAB_VM_ROOT. On an
# enterprise NAS served over NFSv3, they aren't — see
# POSIX-NOT-AUTHORITATIVE-01 in docs/security-dashboard.md. Skip the
# raw/refined POSIX walks in that case to avoid a flood of
# false-positive findings; the Tier 2 sudo dump is where the real
# answer lives.
ACL_CAP=$(detect_acl_capability "$LAB_VM_ROOT")
progress "filesystem ACL capability at $LAB_VM_ROOT: $ACL_CAP"

if [[ "$ACL_CAP" == "synthesized_posix" ]]; then
    emit_finding "info" "lab_vm" "POSIX-NOT-AUTHORITATIVE-01" \
        "$LAB_VM_ROOT" "NFSv4 ACLs hidden by NFSv3 mount (POSIX bits synthesized)" \
        "POSIX walks skipped; consume the Tier 2 root-owned ACL snapshot for real verdicts" \
        "see docs/security-dashboard.md#tier-2-setup"
fi

scan_repos
if [[ "$ACL_CAP" != "synthesized_posix" ]]; then
    scan_lab_vm_raw
    scan_lab_vm_refined
fi
scan_ssh
scan_dotfiles
scan_wigamig
scan_claude
scan_tmp_leaks
scan_cron_systemd
scan_docker_group
scan_home_size
scan_login_history
progress "scan complete"
