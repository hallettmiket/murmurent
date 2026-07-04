#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Purpose: One-command administrator (mayor) install for wigamig. Chains the
#          five manual setup steps into a single idempotent run and lands the
#          mayor at the centre-setup form.
# Author:  Mike Hallett (with Claude Code)
#
# Two ways to run it:
#
#   A. Convenience one-liner (repo is public — no clone needed first):
#        curl -fsSL https://raw.githubusercontent.com/hallettmiket/wigamig/main/scripts/bootstrap.sh | bash
#
#   B. Inspect-then-run (recommended): clone first, read this file, then:
#        git clone https://github.com/hallettmiket/wigamig ~/repos/wigamig
#        cd ~/repos/wigamig && ./scripts/bootstrap.sh
#
# What it does (each step is idempotent — safe to re-run):
#   1. Checks prerequisites (git, uv — installs uv if missing; warns about
#      Claude Code + gh, which need interactive login and can't be automated).
#   2. Clones or updates ~/repos/wigamig (skipped if run from inside a clone).
#   3. Installs the wigamig CLI (`uv tool install`).
#   4. Wires the commons into ~/.claude/ (agents, rules, skills) via setup.sh.
#   5. Registers the data-governance hooks + MCP servers (`wigamig install --hooks`).
#   6. Prints the next step: launch the dashboard and fill the centre-setup form.
#
# What it deliberately does NOT do (out of scope / needs a human):
#   - Install or log in to Claude Code (separate binary, interactive OAuth).
#   - Run `gh auth login` (interactive GitHub auth).
#   - Fill the centre-setup form (that's the mayor's actual input).
#
# Env overrides:
#   WIGAMIG_REPO_DIR   where to clone/expect the repo (default ~/repos/wigamig)
#   WIGAMIG_BRANCH     branch to clone/checkout (default main)
#   NO_LAUNCH=1        skip the offer to launch the dashboard at the end
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

REPO_URL="https://github.com/hallettmiket/wigamig.git"
REPO_DIR="${WIGAMIG_REPO_DIR:-$HOME/repos/wigamig}"
BRANCH="${WIGAMIG_BRANCH:-main}"

step() { printf "\n→ %s\n" "$*"; }
ok()   { printf "  ✓ %s\n" "$*"; }
warn() { printf "  ! %s\n" "$*" >&2; }
fail() { printf "FAILED: %s\n" "$*" >&2; exit 1; }

# If this script lives inside an existing clone, install that clone in place
# rather than cloning a second copy elsewhere.
SELF="${BASH_SOURCE[0]:-}"
if [[ -n "$SELF" && -f "$SELF" ]]; then
  MAYBE_REPO="$(cd "$(dirname "$SELF")/.." 2>/dev/null && pwd || true)"
  if [[ -n "${MAYBE_REPO:-}" && -f "$MAYBE_REPO/pyproject.toml" && -d "$MAYBE_REPO/agents" ]]; then
    REPO_DIR="$MAYBE_REPO"
    RUN_FROM_CLONE=1
  fi
fi

echo "wigamig administrator (mayor) install"
echo "repo dir: $REPO_DIR   branch: $BRANCH"

# ── 1. Prerequisites ─────────────────────────────────────────────────────────
step "1/6 checking prerequisites"

command -v git >/dev/null 2>&1 || fail "git is required — install it and re-run."
ok "git: $(git --version | awk '{print $3}')"

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    ok "uv: $(uv --version | awk '{print $2}')"
    return
  fi
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    export PATH="$HOME/.local/bin:$PATH"
    ok "uv: $(uv --version | awk '{print $2}') (added ~/.local/bin to PATH)"
    return
  fi
  step "  uv not found — installing via the official installer"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || fail "uv install did not put a binary on PATH"
  ok "uv installed: $(uv --version | awk '{print $2}')"
}
ensure_uv

# Claude Code + gh are interactive-login tools we can detect but not automate.
if command -v claude >/dev/null 2>&1; then
  ok "Claude Code: present"
else
  warn "Claude Code CLI not found. Install it from https://claude.com/claude-code"
  warn "and run it once to log in (OAuth). wigamig agents need it, but this"
  warn "installer will still finish; you can add Claude Code afterwards."
fi

if command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  ok "gh: authenticated"
else
  warn "GitHub CLI (gh) not authenticated. Run 'gh auth login' before creating"
  warn "the centre's GitHub org / repos. Not required to finish this install."
fi

# ── 2. Source ────────────────────────────────────────────────────────────────
step "2/6 wigamig source at $REPO_DIR"
if [[ "${RUN_FROM_CLONE:-0}" == "1" ]]; then
  ok "running from an existing clone — not re-cloning"
elif [[ -d "$REPO_DIR/.git" ]]; then
  git -C "$REPO_DIR" fetch --quiet origin "$BRANCH"
  git -C "$REPO_DIR" checkout --quiet "$BRANCH"
  git -C "$REPO_DIR" pull --quiet --ff-only origin "$BRANCH" || \
    warn "could not fast-forward $REPO_DIR (local changes?) — continuing with what's there"
  ok "updated existing clone"
else
  mkdir -p "$(dirname "$REPO_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$REPO_DIR"
  ok "cloned $REPO_URL"
fi

# ── 3. CLI ───────────────────────────────────────────────────────────────────
step "3/6 installing the wigamig CLI"
# Install EDITABLE (-e) from the working clone: a non-editable `uv tool install .`
# relocates the package into site-packages, where the dashboard's static assets
# (docs/designer_dashboard/, not shipped in the wheel) can't be found -> the
# hi-fi dashboard 500s. Pin 3.12 (wigamig needs >=3.12). Dashboard/Slack/MCP
# deps are hard deps in pyproject, so they come along automatically.
( cd "$REPO_DIR" && uv tool install --reinstall --python 3.12 -e . >/dev/null )
export PATH="$HOME/.local/bin:$PATH"
command -v wigamig >/dev/null 2>&1 || fail "wigamig not on PATH after install (check ~/.local/bin)"
ok "wigamig: $(wigamig --version 2>/dev/null | head -1)"

# ── 4. Commons ───────────────────────────────────────────────────────────────
step "4/6 wiring the commons into ~/.claude/ (agents, rules, skills)"
bash "$REPO_DIR/scripts/setup.sh"

# ── 5. Hooks + MCP ───────────────────────────────────────────────────────────
step "5/6 registering data-governance hooks + MCP servers"
wigamig install --hooks

# ── 6. Bootstrap the centre ──────────────────────────────────────────────────
step "6/6 ready to bootstrap the centre"
cat <<'EOF'
  The commons is installed. You are ready to become the founding registrar.

  Launch the dashboard and fill in the one-time centre-setup form:

      wigamig dashboard --hifi --port 8771
      # then open http://localhost:8771/registrar

  ...or bootstrap headlessly from the CLI:

      wigamig centre-init --mayor @<your-handle> \
        --name "<Centre name>" --institution "<Institution>" \
        --unique-name <short-id> --server-host <wigamig-server-host>

  Confirm with:  wigamig centre-status
EOF

if [[ "${NO_LAUNCH:-0}" != "1" && -t 0 ]]; then
  printf "\nLaunch the dashboard now? [y/N] "
  read -r reply
  if [[ "$reply" == "y" || "$reply" == "Y" ]]; then
    exec wigamig dashboard --hifi --port 8771
  fi
fi

ok "done."
