#!/usr/bin/env bash
# reset.sh — back up, then reset wigamig machine state to a fresh start.
#
# Levels (default: centre):
#   centre   remove ~/.wigamig/lab_info only  ->  `wigamig centre-init` is
#            first-run again. Nothing else touched.
#   install  centre + reinstall the tool from the repo (force, py3.12, extras)
#            + re-run scripts/setup.sh + `wigamig install --hooks`.
#   full     install + remove machine-local CACHES (workspaces/, *.log,
#            dashboard.pid, security/ agent cache). Still KEEPS credentials,
#            installations/, decommissions/, audit logs, hosts/machine yaml.
#
# Destructive extras (never happen without the explicit flag):
#   --nuke-installations   also remove ~/.wigamig/installations (other projects)
#   --nuke-credentials     also remove ~/.config/wigamig (slack-token + keys)
#
# Safety:
#   * ALWAYS writes a timestamped backup tarball to ~/.wigamig_backups/ FIRST
#     (outside ~/.wigamig, so a full wipe can't take the backup with it).
#   * --dry-run prints exactly what would happen and changes nothing.
#   * Never touches ~/repos/* clones, ~/.claude/CLAUDE.md, ~/.claude/memory,
#     or ~/.claude/projects.
#   * Refuses to run unless --yes is passed (the skill passes it after the
#     human has confirmed).
set -euo pipefail

LEVEL="centre"
DRY=0
YES=0
NUKE_INSTALL=0
NUKE_CREDS=0

WIG="$HOME/.wigamig"
CFG="$HOME/.config/wigamig"
BACKUPS="$HOME/.wigamig_backups"
REPO="${WIGAMIG_REPO:-$HOME/repos/wigamig}"

usage() { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --level) LEVEL="${2:-}"; shift 2 ;;
    --level=*) LEVEL="${1#*=}"; shift ;;
    centre|install|full) LEVEL="$1"; shift ;;   # bare level as convenience
    --dry-run|-n) DRY=1; shift ;;
    --yes|-y) YES=1; shift ;;
    --nuke-installations) NUKE_INSTALL=1; shift ;;
    --nuke-credentials) NUKE_CREDS=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown arg: $1" >&2; usage 1 ;;
  esac
done

case "$LEVEL" in centre|install|full) ;; *) echo "bad --level: $LEVEL" >&2; exit 2 ;; esac

say()  { printf '%s\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then say "  DRY: $*"; else eval "$*"; fi; }
rmrf() { # rmrf <path> <label>
  if [ -e "$1" ]; then
    if [ "$DRY" = 1 ]; then say "  DRY: would remove $2  ($1)";
    else say "  removing $2"; rm -rf "$1"; fi
  else say "  (skip) $2 not present"; fi
}

say "=== wigamig reset — level: $LEVEL${DRY:+ }$([ "$DRY" = 1 ] && echo '(dry-run)')"
say "    repo:        $REPO"
say "    nuke creds:  $([ "$NUKE_CREDS" = 1 ] && echo yes || echo NO)"
say "    nuke installs: $([ "$NUKE_INSTALL" = 1 ] && echo yes || echo NO)"
say ""

if [ "$YES" != 1 ] && [ "$DRY" != 1 ]; then
  echo "refusing to run without --yes (or use --dry-run to preview)" >&2
  exit 3
fi

# 1. stop any running dashboards --------------------------------------------
say "1. stopping any running dashboards"
if [ "$DRY" = 1 ]; then say "  DRY: would pkill -f 'wigamig dashboard'";
else pkill -f "wigamig dashboard" 2>/dev/null || true; sleep 1; fi

# 2. ALWAYS back up first ---------------------------------------------------
say "2. backing up (~/.wigamig + ~/.config/wigamig)"
TS="$(date +%Y%m%d-%H%M%S)"
BK="$BACKUPS/reset_${LEVEL}_${TS}.tgz"
if [ "$DRY" = 1 ]; then
  say "  DRY: would write backup -> $BK"
else
  mkdir -p "$BACKUPS"; chmod 700 "$BACKUPS"
  tar -czf "$BK" \
    -C "$HOME" "$(basename "$WIG")" \
    $( [ -d "$CFG" ] && printf -- '-C %s %s' "$(dirname "$CFG")" "$(basename "$CFG")" ) \
    2>/dev/null || tar -czf "$BK" -C "$HOME" "$(basename "$WIG")" 2>/dev/null || true
  chmod 600 "$BK" 2>/dev/null || true
  say "  backup: $BK  ($(du -h "$BK" 2>/dev/null | cut -f1))"
fi

# 3. centre reset (all levels) ----------------------------------------------
say "3. centre state"
rmrf "$WIG/lab_info" "centre registry (lab_info/)"

# 4. install reset (install + full) -----------------------------------------
if [ "$LEVEL" = install ] || [ "$LEVEL" = full ]; then
  say "4. reinstall from repo"
  if [ ! -d "$REPO" ]; then
    say "  !! repo not found at $REPO — set WIGAMIG_REPO. Skipping reinstall."
  else
    run "cd '$REPO' && uv tool install --force --python 3.12 -e '.[dashboard,slack,mcp]'"
    run "cd '$REPO' && bash scripts/setup.sh"
    run "wigamig install --hooks"
  fi
else
  say "4. (skip reinstall — level '$LEVEL')"
fi

# 5. full: machine-local caches ---------------------------------------------
if [ "$LEVEL" = full ]; then
  say "5. machine-local caches (kept: installations, decommissions, audit, creds)"
  rmrf "$WIG/workspaces"        "workspaces/ cache"
  rmrf "$WIG/security/agent_cache" "security/agent_cache"
  rmrf "$WIG/dashboard.pid"     "dashboard.pid"
  for f in dashboard.log agents.log agents_debug.log; do
    rmrf "$WIG/$f" "$f"
  done
  rmrf "$WIG/RESUME.md"         "RESUME.md (stale handoff note)"
else
  say "5. (skip caches — level '$LEVEL')"
fi

# 6. explicit nukes (opt-in only) -------------------------------------------
say "6. opt-in nukes"
if [ "$NUKE_INSTALL" = 1 ]; then rmrf "$WIG/installations" "installations/ (OTHER PROJECTS)"; else say "  (keep) installations/"; fi
if [ "$NUKE_CREDS" = 1 ];   then rmrf "$CFG" "credentials (~/.config/wigamig: slack-token + keys)"; else say "  (keep) credentials"; fi

say ""
say "=== done (level: $LEVEL$([ "$DRY" = 1 ] && echo ', dry-run — nothing changed'))"
[ "$DRY" != 1 ] && say "restore if needed:  tar -xzf $BK -C \$HOME"
say "next:  wigamig centre-status   (should say 'no centre initialised')"
