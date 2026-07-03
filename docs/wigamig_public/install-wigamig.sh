#!/usr/bin/env sh
# install-wigamig.sh — one command that installs the wigamig software on your
# computer. It:
#   1. checks you have git (and installs 'uv', the Python installer, if needed),
#   2. downloads the public wigamig code to ~/repos/wigamig,
#   3. installs the `wigamig` command,
#   4. wires the shared agents + rules into ~/.claude/,
#   5. registers the wigamig hooks + tools.
#
# You do NOT need to be approved for a centre to run this — the code is public.
# This just gets your machine ready. Joining a lab/core still happens by email
# (see wigamig-join.sh) and the Mayor's reply.
#
#   Download + run:
#     curl -fsSL -O https://raw.githubusercontent.com/hallettmiket/wigamig_public/main/install-wigamig.sh
#     sh install-wigamig.sh
set -eu

REPO_URL="https://github.com/hallettmiket/wigamig.git"
DEST="$HOME/repos/wigamig"

say() { printf '%s\n' "$*"; }
ask() { printf '%s' "$1" >&2; IFS= read -r _a || _a=""; printf '%s' "$_a"; }

# --- 1. prerequisites: git + uv --------------------------------------------
need_git() {
  command -v git >/dev/null 2>&1 && return 0
  say "You need 'git' first."
  say "  macOS:  install the Command Line Tools with:  xcode-select --install"
  say "  Ubuntu/Debian:  sudo apt-get install -y git"
  say "Then run this script again."
  exit 1
}

need_uv() {
  command -v uv >/dev/null 2>&1 && return 0
  say ""
  say "wigamig installs with 'uv' (a small, standard Python tool). You don't"
  say "have it yet."
  case "$(ask 'Install uv now (from https://astral.sh, the official installer)? [Y/n] ')" in
    n*|N*) say "OK. Install uv from https://docs.astral.sh/uv/ then re-run."; exit 1 ;;
  esac
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- https://astral.sh/uv/install.sh | sh
  else
    say "Need curl or wget to install uv. Install one, then re-run."; exit 1
  fi
  # uv installs to ~/.local/bin (or ~/.cargo/bin) — make it visible now.
  [ -d "$HOME/.local/bin" ] && PATH="$HOME/.local/bin:$PATH"
  [ -d "$HOME/.cargo/bin" ] && PATH="$HOME/.cargo/bin:$PATH"
  export PATH
  command -v uv >/dev/null 2>&1 && return 0
  say ""
  say "uv was installed but isn't on your PATH in this shell. Close and reopen"
  say "your terminal, then run this script again."
  exit 1
}

# --- 2. get the code -------------------------------------------------------
get_code() {
  mkdir -p "$HOME/repos"
  if [ -d "$DEST/.git" ]; then
    say "Updating existing copy at $DEST ..."
    git -C "$DEST" pull --ff-only || say "  (couldn't fast-forward; leaving as-is)"
  else
    if [ -e "$DEST" ]; then
      say "$DEST exists but isn't a git clone. Move it aside and re-run."; exit 1
    fi
    say "Downloading wigamig to $DEST ..."
    git clone "$REPO_URL" "$DEST"
  fi
}

# --- 3. install + wire -----------------------------------------------------
main() {
  say "This installs the wigamig software on your computer. Nothing is sent"
  say "anywhere; it only sets up files under ~/repos/wigamig and ~/.claude/."
  say ""
  need_git
  need_uv
  get_code

  say ""; say "Installing the 'wigamig' command ..."
  ( cd "$DEST" && uv tool install -e . )

  say ""; say "Wiring shared agents + rules into ~/.claude/ ..."
  ( cd "$DEST" && bash scripts/setup.sh )

  say ""; say "Registering hooks + tools ..."
  if command -v wigamig >/dev/null 2>&1; then
    wigamig install --hooks
  else
    ( cd "$DEST" && uv tool run wigamig install --hooks ) || \
      say "  (run 'wigamig install --hooks' once 'wigamig' is on your PATH)"
  fi

  say ""
  say "──────────────────────────────────────────────────────────────────────"
  say "✓ wigamig is installed."
  say ""
  say "If 'wigamig' isn't found yet, close and reopen your terminal (uv adds"
  say "it to your PATH). Check it with:  wigamig --version"
  say ""
  say "Next: watch your email for the Mayor's reply + your Slack invite. Once"
  say "you're added to your lab/core, the rest of onboarding is walked through"
  say "for you there."
  say "──────────────────────────────────────────────────────────────────────"
}

main "$@"
