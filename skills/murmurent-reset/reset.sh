#!/usr/bin/env bash
# reset.sh — back up, then reset murmurent machine state to a fresh start.
#
# Levels (default: centre):
#   centre   remove ~/.murmurent/lab_info only  ->  `murmurent centre-init` is
#            first-run again. Nothing else touched.
#   install  centre + reinstall the tool from the repo (force, py3.12, extras)
#            + re-run scripts/setup.sh + `murmurent install --hooks`.
#   full     install + remove machine-local CACHES (workspaces/, *.log,
#            dashboard.pid, security/ agent cache). Still KEEPS credentials,
#            installations/, decommissions/, audit logs, hosts/machine yaml.
#   data     wipe ALL data you entered into ~/.murmurent (lab_info, profile.yaml,
#            hosts/machine yaml, inventory/, cores/, onboarding/,
#            decommissions/, security/, identity/cards/trust/revocation, logs,
#            …) — everything EXCEPT your key material. KEEPS keys/, age/,
#            installations/ (other projects), and ~/.config/murmurent. Robust: it
#            keeps an allowlist and removes the rest, so new data files are
#            caught automatically. No reinstall.
#
# Destructive extras (never happen without the explicit flag):
#   --nuke-installations   also remove ~/.murmurent/installations (other projects)
#   --nuke-credentials     also remove ~/.config/murmurent (slack-tokens + keys)
#   --nuke-keys            with --level data, ALSO remove ~/.murmurent/keys + age
#                          (a fully fresh identity; default keeps them)
#   --nuke-labs            ALSO remove this machine's murmurent lab-management repos
#                          (~/repos/murmurent_lab_mgmt_*, legacy wigamig_* — they hold the roster). Backed up
#                          into the tarball first; REFUSES any repo with
#                          uncommitted or unpushed commits (push it, or don't nuke
#                          it). Default: labs are only LISTED and left untouched.
#   --uninstall            first completely REMOVE the existing murmurent
#                          install(s) — the uv-tool one AND stray conda/pipx
#                          copies — before any reinstall. With --level centre
#                          (default) this leaves NO murmurent on the machine; with
#                          --level install/full it removes-then-reinstalls clean.
#
# Completely remove the old install (leave nothing):
#   reset.sh --level centre --uninstall --yes
# Remove the old install, then put back a clean one:
#   reset.sh --level install --uninstall --yes
#
# Safety:
#   * ALWAYS writes a timestamped backup tarball to ~/.murmurent_backups/ FIRST
#     (outside ~/.murmurent, so a full wipe can't take the backup with it).
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
NUKE_KEYS=0
NUKE_LABS=0
UNINSTALL=0

WIG="$HOME/.murmurent"
CFG="$HOME/.config/murmurent"
CFG_LEGACY="$HOME/.config/wigamig"        # pre-rename config dir on older machines
BACKUPS="$HOME/.murmurent_backups"
REPO="${MURMURENT_REPO:-$HOME/repos/murmurent}"
REPOS_ROOT="${MURMURENT_REPOS_ROOT:-$HOME/repos}"

usage() { grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --level) LEVEL="${2:-}"; shift 2 ;;
    --level=*) LEVEL="${1#*=}"; shift ;;
    centre|install|full|data) LEVEL="$1"; shift ;;   # bare level as convenience
    --dry-run|-n) DRY=1; shift ;;
    --yes|-y) YES=1; shift ;;
    --nuke-installations) NUKE_INSTALL=1; shift ;;
    --nuke-credentials) NUKE_CREDS=1; shift ;;
    --nuke-keys) NUKE_KEYS=1; shift ;;
    --nuke-labs) NUKE_LABS=1; shift ;;
    --uninstall) UNINSTALL=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown arg: $1" >&2; usage 1 ;;
  esac
done

case "$LEVEL" in centre|install|full|data) ;; *) echo "bad --level: $LEVEL" >&2; exit 2 ;; esac

say()  { printf '%s\n' "$*"; }
run()  { if [ "$DRY" = 1 ]; then say "  DRY: $*"; else eval "$*"; fi; }
rmrf() { # rmrf <path> <label>
  if [ -e "$1" ]; then
    if [ "$DRY" = 1 ]; then say "  DRY: would remove $2  ($1)";
    else say "  removing $2"; rm -rf "$1"; fi
  else say "  (skip) $2 not present"; fi
}

say "=== murmurent reset — level: $LEVEL${DRY:+ }$([ "$DRY" = 1 ] && echo '(dry-run)')"
say "    repo:        $REPO"
say "    nuke creds:  $([ "$NUKE_CREDS" = 1 ] && echo yes || echo NO)"
say "    nuke installs: $([ "$NUKE_INSTALL" = 1 ] && echo yes || echo NO)"
say "    nuke labs:   $([ "$NUKE_LABS" = 1 ] && echo yes || echo NO)"
[ "$LEVEL" = data ] && say "    nuke keys:   $([ "$NUKE_KEYS" = 1 ] && echo yes || echo NO)"
say ""

if [ "$YES" != 1 ] && [ "$DRY" != 1 ]; then
  echo "refusing to run without --yes (or use --dry-run to preview)" >&2
  exit 3
fi

# 1. stop any running dashboards --------------------------------------------
say "1. stopping any running dashboards"
if [ "$DRY" = 1 ]; then say "  DRY: would pkill -f 'murmurent dashboard'";
else pkill -f "murmurent dashboard" 2>/dev/null || true; sleep 1; fi

# 2. ALWAYS back up first ---------------------------------------------------
say "2. backing up (~/.murmurent + ~/.config/murmurent)"
TS="$(date +%Y%m%d-%H%M%S)"
BK="$BACKUPS/reset_${LEVEL}_${TS}.tgz"
if [ "$DRY" = 1 ]; then
  say "  DRY: would write backup -> $BK"
else
  mkdir -p "$BACKUPS"; chmod 700 "$BACKUPS"
  tar -czf "$BK" \
    -C "$HOME" "$(basename "$WIG")" \
    $( [ -d "$CFG" ] && printf -- '-C %s %s ' "$(dirname "$CFG")" "$(basename "$CFG")" ) \
    $( [ -d "$CFG_LEGACY" ] && printf -- '-C %s %s' "$(dirname "$CFG_LEGACY")" "$(basename "$CFG_LEGACY")" ) \
    2>/dev/null || tar -czf "$BK" -C "$HOME" "$(basename "$WIG")" 2>/dev/null || true
  chmod 600 "$BK" 2>/dev/null || true
  say "  backup: $BK  ($(du -h "$BK" 2>/dev/null | cut -f1))"
fi

# 3. centre reset (all levels) ----------------------------------------------
say "3. centre state"
rmrf "$WIG/lab_info" "centre registry (lab_info/)"
# The per-machine registrar sentinel is a claim to be a registrar OF the centre;
# once the centre is gone it's meaningless and must not linger (a stale sentinel
# used to still read as 'registrar' on the next install). The saved netname goes
# too, so the next install resolves a fresh identity.
rmrf "$WIG/registrar" "registrar sentinel (~/.murmurent/registrar)"
rmrf "$WIG/user" "saved netname (~/.murmurent/user)"

# 3d. data reset — wipe ALL entered data, keep only key material -------------
if [ "$LEVEL" = data ]; then
  say "3d. wiping all entered data (keeping key material + other projects)"
  # Allowlist of what to KEEP under ~/.murmurent; everything else is removed, so
  # any data file — existing or added later — is caught without an explicit list.
  KEEP="keys age installations"
  [ "$NUKE_KEYS" = 1 ] && KEEP="installations"   # --nuke-keys: also wipe keys/ + age/
  for entry in "$WIG"/* "$WIG"/.[!.]*; do
    [ -e "$entry" ] || continue                  # skip an unmatched dotfile glob
    base="$(basename "$entry")"
    keepit=0
    for k in $KEEP; do [ "$base" = "$k" ] && keepit=1; done
    if [ "$keepit" = 1 ]; then say "  (keep) $base"; else rmrf "$entry" "$base"; fi
  done
fi

# 3b. uninstall the tool entirely (only with --uninstall) -------------------
# Completely removes every murmurent executable: the uv-tool install AND any
# stray copies pip-installed into conda envs / pipx that would shadow it.
if [ "$UNINSTALL" = 1 ]; then
  say "3b. removing existing murmurent install(s)"
  if [ "$DRY" = 1 ]; then say "  DRY: would uv tool uninstall murmurent"; else
    uv tool uninstall murmurent 2>/dev/null && say "  uv-tool murmurent removed" || say "  (no uv-tool murmurent)"
  fi
  # stray installs in conda base + envs and pipx
  for py in "$HOME"/anaconda3/bin/python "$HOME"/anaconda3/envs/*/bin/python \
            "$HOME"/miniconda3/bin/python "$HOME"/miniconda3/envs/*/bin/python; do
    [ -x "$py" ] || continue
    "$py" -c "import murmurent" >/dev/null 2>&1 || continue
    if [ "$DRY" = 1 ]; then say "  DRY: would pip-uninstall murmurent from $py";
    else "$py" -m pip uninstall -y murmurent >/dev/null 2>&1 && say "  removed stray install: $py"; fi
  done
  command -v pipx >/dev/null 2>&1 && { [ "$DRY" = 1 ] && say "  DRY: would pipx uninstall murmurent" || pipx uninstall murmurent >/dev/null 2>&1 || true; }
  if [ "$DRY" != 1 ]; then
    left="$(command -v murmurent 2>/dev/null || true)"
    [ -z "$left" ] && say "  ✓ no murmurent left on PATH" || say "  ! still on PATH: $left (check it manually)"
  fi
fi

# 4. install reset (install + full) -----------------------------------------
if [ "$LEVEL" = install ] || [ "$LEVEL" = full ]; then
  say "4. reinstall from repo"
  if [ ! -d "$REPO" ]; then
    say "  !! repo not found at $REPO — set MURMURENT_REPO. Skipping reinstall."
  else
    # Editable (-e) + py3.12. The dashboard/Slack/MCP deps are HARD deps in
    # pyproject, so a plain install carries them (no fragile extras/--with).
    # -e keeps the package in the clone so the dashboard's static assets resolve.
    run "cd '$REPO' && uv tool install --force --python 3.12 -e ."
    run "cd '$REPO' && bash scripts/setup.sh"
    run "murmurent install --hooks"
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
if [ "$NUKE_CREDS" = 1 ];   then
  rmrf "$CFG" "credentials (~/.config/murmurent: slack-tokens + keys)"
  [ -d "$CFG_LEGACY" ] && rmrf "$CFG_LEGACY" "legacy credentials (~/.config/wigamig)"
else say "  (keep) credentials"; fi

# 7. murmurent lab-management repos (~/repos/murmurent_lab_mgmt_*, legacy wigamig_*) ---
# These hold the lab ROSTER (members/*.md) — the source of truth for identity.
# They live under ~/repos, which reset otherwise NEVER touches, so by default we
# only LIST them (so you know they survive). --nuke-labs removes them, but only
# after backing each into the tarball and refusing any with uncommitted/unpushed
# work (losing the roster to a reset must be a deliberate, safe act).
say "7. murmurent lab repos ($REPOS_ROOT/murmurent_lab_mgmt_* + legacy wigamig_*)"
LAB_REPOS=()
if [ -d "$REPOS_ROOT" ]; then
  # Current convention is murmurent_lab_mgmt_<group>; wigamig_<group> is the
  # pre-rename legacy name still on older machines. Match both so a reset never
  # silently leaves a stale roster behind (a non-matching glob stays literal and
  # is filtered by the .git check below).
  for d in "$REPOS_ROOT"/murmurent_lab_mgmt_* "$REPOS_ROOT"/wigamig_*; do
    [ -d "$d/.git" ] || continue
    # the murmurent repo + its manuscript aren't lab-mgmt repos; skip by name
    case "$(basename "$d")" in murmurent|murmurent_manuscript|murmurent_public) continue ;; esac
    LAB_REPOS+=("$d")
  done
fi
if [ "${#LAB_REPOS[@]}" = 0 ]; then
  say "  (none found)"
else
  for d in "${LAB_REPOS[@]}"; do
    dirty=""; unpushed=""
    [ -n "$(git -C "$d" status --porcelain 2>/dev/null)" ] && dirty="uncommitted"
    # unpushed = commits with no upstream, or ahead of upstream
    if git -C "$d" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
      [ "$(git -C "$d" rev-list '@{u}..HEAD' --count 2>/dev/null || echo 0)" != 0 ] && unpushed="ahead-of-remote"
    else
      [ -n "$(git -C "$d" log -1 --oneline 2>/dev/null)" ] && unpushed="no-remote"
    fi
    flags="$dirty${dirty:+,}$unpushed"
    if [ "$NUKE_LABS" != 1 ]; then
      say "  (keep) $(basename "$d")${flags:+  [$flags]}   — use --nuke-labs to remove"
      continue
    fi
    if [ -n "$dirty" ] || [ -n "$unpushed" ]; then
      say "  !! REFUSING $(basename "$d")  [$flags] — push/commit it first, then re-run"
      continue
    fi
    # safe to remove: back it up into a tarball, then delete
    if [ "$DRY" = 1 ]; then
      say "  DRY: would back up + remove $(basename "$d")  ($d)"
    else
      mkdir -p "$BACKUPS"; chmod 700 "$BACKUPS"
      LBK="$BACKUPS/labrepo_$(basename "$d")_${TS}.tgz"
      tar -czf "$LBK" -C "$(dirname "$d")" "$(basename "$d")" 2>/dev/null && chmod 600 "$LBK" 2>/dev/null || true
      say "  backup: $LBK"
      rm -rf "$d"; say "  removed $(basename "$d")"
      # the pinned pointer is now dangling — drop it so pi-init is first-run again
      rmrf "$WIG/lab_mgmt_path" "lab_mgmt pointer (dangling)"
    fi
  done
fi

say ""
say "=== done (level: $LEVEL$([ "$DRY" = 1 ] && echo ', dry-run — nothing changed'))"
[ "$DRY" != 1 ] && say "restore if needed:  tar -xzf $BK -C \$HOME"
say "next:  murmurent centre-status   (should say 'no centre initialised')"
