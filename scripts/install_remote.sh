#!/usr/bin/env bash
# Purpose: Idempotent install of `uv` + murmurent on a remote SSH host so the
#          centre's biodatsci server (or any equivalent host) can run
#          `murmurent project new` etc. directly. The laptop dashboard then
#          drives the remote host over SSH; this script just ensures the
#          binaries are in place.
# Author:  Mike Hallett (with Claude Code)
# Date:    2026-05-13
# Usage:   bash scripts/install_remote.sh <ssh-host> [--branch <git-branch>]
#
# Example: bash scripts/install_remote.sh biodatsci
#          bash scripts/install_remote.sh biodatsci --branch main
#
# Pre-reqs on the laptop:
#   - ~/.ssh/config has an alias for <ssh-host> with key auth working
#     (the script refuses to prompt for a password — if `ssh biodatsci
#     true` doesn't succeed silently, fix the SSH config first).
#   - git available on the remote host (Ubuntu: `apt install git`).
#
# Pre-reqs on the remote host (`biodatsci`):
#   - bash, curl, git available
#   - /data/lab_vm/{raw,refined} mounted (warned-only if missing — murmurent
#     project new will create them inside whatever exists).
#
# What this script does (idempotent — re-run safely):
#   1. ssh true                        → fails fast if auth/host is wrong.
#   2. Ensure ~/.local/bin/uv on host  → installs via the official one-liner
#                                        if missing; skips otherwise.
#   3. Clone (or pull) the murmurent repo into ~/repos/wigamig on host.
#   4. uv tool install --reinstall .   → registers `murmurent` on the host's
#                                        PATH at ~/.local/bin/murmurent.
#   5. Sanity probes: murmurent --version, ls /data/lab_vm/{raw,refined},
#      gh auth status, mkdir -p ~/.wigamig.
#
# Stdout is human-readable; any failure prints a clear "FAILED:" line and
# the script exits non-zero so callers (e.g. `murmurent host add`) can react.

set -euo pipefail

SCRIPT_NAME="$(basename "$0")"
LAPTOP_REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WIGAMIG_REPO_URL="https://github.com/hallettmiket/murmurent.git"
BRANCH="main"
HOST=""

# ── argv parse ───────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --branch) BRANCH="$2"; shift 2 ;;
    --help|-h)
      sed -n '2,30p' "$0"
      exit 0
      ;;
    *)
      if [[ -z "$HOST" ]]; then HOST="$1"; shift
      else echo "unexpected argument: $1" >&2; exit 2
      fi
      ;;
  esac
done

if [[ -z "$HOST" ]]; then
  echo "usage: $SCRIPT_NAME <ssh-host> [--branch <git-branch>]" >&2
  exit 2
fi

# Disable any password / keyboard-interactive fallback so a failure is loud.
SSH_OPTS=(
  -o BatchMode=yes
  -o ConnectTimeout=10
  -o ServerAliveInterval=15
)

ssh_run() {
  # Wrap the remote command in `bash -lc` so the user's login PATH is
  # active (matters for `uv` after first install).
  local cmd="$1"
  ssh "${SSH_OPTS[@]}" "$HOST" "bash -lc $(printf %q "$cmd")"
}

step() { printf "→ %s\n" "$*"; }
ok()   { printf "  ✓ %s\n" "$*"; }
warn() { printf "  ! %s\n" "$*" >&2; }
fail() { printf "FAILED: %s\n" "$*" >&2; exit 1; }

# ── Step 1: connectivity ─────────────────────────────────────────────────────
step "1/5 SSH connectivity to ${HOST}"
if ! ssh "${SSH_OPTS[@]}" "$HOST" true 2>/dev/null; then
  fail "cannot ssh to ${HOST}. Check ~/.ssh/config and that key auth works (no password prompt allowed)."
fi
REMOTE_USER="$(ssh_run 'echo "$USER"')"
REMOTE_HOSTNAME="$(ssh_run 'hostname -f 2>/dev/null || hostname')"
ok "connected as ${REMOTE_USER}@${REMOTE_HOSTNAME}"

# ── Step 2: uv installed? ────────────────────────────────────────────────────
step "2/5 uv installed on ${HOST}"
if ssh_run 'command -v uv >/dev/null 2>&1'; then
  UV_VERSION="$(ssh_run 'uv --version' | head -1)"
  ok "uv present: ${UV_VERSION}"
else
  step "  installing uv via the official installer"
  ssh_run 'curl -LsSf https://astral.sh/uv/install.sh | sh'
  if ! ssh_run 'command -v uv >/dev/null 2>&1 || [ -x "$HOME/.local/bin/uv" ]'; then
    fail "uv install did not place a binary on PATH or in ~/.local/bin"
  fi
  UV_VERSION="$(ssh_run 'export PATH=$HOME/.local/bin:$PATH; uv --version' | head -1)"
  ok "uv installed: ${UV_VERSION}"
fi

# ── Step 3: clone or update the murmurent repo ─────────────────────────────────
step "3/5 murmurent source at ~/repos/wigamig on ${HOST}"
ssh_run 'mkdir -p ~/repos'
if ssh_run 'test -d ~/repos/wigamig/.git'; then
  ssh_run "cd ~/repos/wigamig && git fetch origin && git checkout ${BRANCH} && git pull --ff-only origin ${BRANCH}"
  REMOTE_COMMIT="$(ssh_run 'cd ~/repos/wigamig && git rev-parse --short HEAD')"
  ok "repo updated to ${REMOTE_COMMIT} (${BRANCH})"
else
  ssh_run "git clone --branch ${BRANCH} ${WIGAMIG_REPO_URL} ~/repos/wigamig"
  REMOTE_COMMIT="$(ssh_run 'cd ~/repos/wigamig && git rev-parse --short HEAD')"
  ok "repo cloned to ~/repos/wigamig at ${REMOTE_COMMIT}"
fi

# ── Step 4: `uv tool install` the murmurent CLI ────────────────────────────────
step "4/5 murmurent CLI installation on ${HOST}"
# --reinstall is idempotent and makes upgrades behave the same as fresh installs.
# -e (editable) + --python 3.12: a non-editable install relocates the package
# away from the clone, breaking the dashboard's static assets; py3.12 is required.
ssh_run 'export PATH=$HOME/.local/bin:$PATH; cd ~/repos/wigamig && uv tool install --reinstall --python 3.12 -e .'
WIGAMIG_VERSION="$(ssh_run 'export PATH=$HOME/.local/bin:$PATH; murmurent --version 2>/dev/null || true')"
if [[ -z "$WIGAMIG_VERSION" ]]; then
  fail "murmurent --version returned no output on the remote host"
fi
ok "murmurent installed: ${WIGAMIG_VERSION}"

# ── Step 4b: wire murmurent into the remote ~/.claude/ as the default ─────────
# Same script that runs locally — re-points ~/.claude/agents at the
# murmurent commons, links ~/.claude/CLAUDE.md, runs `murmurent install
# --hooks`. Idempotent. Preserves any user-authored agents (non-symlinks).
step "4b/5 wiring ~/.claude/ on ${HOST}"
ssh_run 'export PATH=$HOME/.local/bin:$PATH; bash ~/repos/wigamig/scripts/setup.sh' \
  && ok "~/.claude/ wired into murmurent commons on ${HOST}" \
  || warn "setup.sh on ${HOST} reported issues — inspect manually if needed"

# ── Step 5: sanity probes ────────────────────────────────────────────────────
step "5/5 sanity probes on ${HOST}"
ssh_run 'mkdir -p $HOME/.wigamig'
ok "~/.wigamig present"

# Lab-VM data directories — warn but don't fail.
if ssh_run 'test -d /data/lab_vm/wigamig/raw && test -d /data/lab_vm/wigamig/refined'; then
  ok "/data/lab_vm/{raw,refined} present"
else
  warn "/data/lab_vm/{raw,refined} not found on ${HOST}. murmurent will fall back"
  warn "to \$WIGAMIG_LAB_VM_ROOT (default ~/lab_vm/data) — set it on the remote"
  warn "user's shell or via the host's murmurent settings before creating projects."
fi

# gh auth status — warn but don't fail.
if ssh_run 'command -v gh >/dev/null 2>&1'; then
  if ssh_run 'gh auth status 2>&1 | grep -q "Logged in"'; then
    ok "gh CLI is authenticated"
  else
    warn "gh CLI is installed but not authenticated. Run on ${HOST}:"
    warn "    gh auth login"
    warn "before creating projects with --repo-kind github."
  fi
else
  warn "gh CLI not found on ${HOST}. Install via apt (Ubuntu): sudo apt install gh"
fi

echo
echo "Install complete."
echo "  host:         ${HOST}"
echo "  remote user:  ${REMOTE_USER}@${REMOTE_HOSTNAME}"
echo "  murmurent:      ${WIGAMIG_VERSION}"
echo "  uv:           ${UV_VERSION}"
echo "  repo commit:  ${REMOTE_COMMIT}"
echo
echo "Next: register this host with murmurent so the dashboard knows about it:"
echo "    murmurent host add ${HOST} --remote-user ${REMOTE_USER}"
echo "Then test:"
echo "    murmurent host test ${HOST}"
