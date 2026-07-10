#!/usr/bin/env sh
# install-murmurent.sh — one command that installs the murmurent software on your
# computer. It:
#   1. checks you have git (and installs 'uv', the Python installer, if needed),
#   2. downloads the public murmurent code to ~/repos/murmurent,
#   3. installs the `murmurent` command,
#   4. wires the shared agents + rules into ~/.claude/,
#   5. registers the murmurent hooks + tools.
#
# You do NOT need to be approved for a centre to run this — the code is public.
# This just gets your machine ready. What happens next depends on your role —
# `murmurent init` (offered at the end, or run any time) asks and walks you
# through it: members ask their PI for a membership ID over Slack (no email,
# no mayor involved), PIs can self-issue their own lab's ID immediately (no
# mayor needed) or register their lab with an institution's mayor by email
# (see murmurent-join.sh), and mayors bootstrap a whole new centre.
#
#   Download + run:
#     curl -fsSL -O https://raw.githubusercontent.com/hallettmiket/murmurent_public/main/install-murmurent.sh
#     sh install-murmurent.sh
set -eu

REPO_URL="https://github.com/hallettmiket/murmurent.git"
DEST="$HOME/repos/murmurent"

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
  say "murmurent installs with 'uv' (a small, standard Python tool). You don't"
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
    say "Downloading murmurent to $DEST ..."
    git clone "$REPO_URL" "$DEST"
  fi
}

# --- 3. install + wire -----------------------------------------------------
main() {
  say "This installs the murmurent software on your computer. Nothing is sent"
  say "anywhere; it only sets up files under ~/repos/murmurent and ~/.claude/."
  say ""
  need_git
  need_uv
  get_code

  say ""; say "Installing the 'murmurent' command ..."
  # Editable (-e) install from the clone, pinned to Python 3.12 (murmurent needs
  # >=3.12 — uv fetches a managed 3.12 if the system default is older). The
  # dashboard (fastapi/uvicorn), Slack, and MCP deps are HARD deps in pyproject,
  # so they install automatically. -e keeps the package in the clone so the
  # dashboard's static assets resolve. (Low-fi streamlit dashboard is the one
  # optional extra: add `'.[dashboard]'` if you want it.)
  ( cd "$DEST" && uv tool install --python 3.12 -e . )

  say ""; say "Wiring shared agents + rules into ~/.claude/ ..."
  ( cd "$DEST" && bash scripts/setup.sh )

  say ""; say "Registering hooks + tools ..."
  if command -v murmurent >/dev/null 2>&1; then
    murmurent install --hooks
  else
    ( cd "$DEST" && uv tool run murmurent install --hooks ) || \
      say "  (run 'murmurent install --hooks' once 'murmurent' is on your PATH)"
  fi

  say ""
  say "──────────────────────────────────────────────────────────────────────"
  say "✓ murmurent is installed."
  say ""
  say "If 'murmurent' isn't found yet, close and reopen your terminal (uv adds"
  say "it to your PATH). Check it with:  murmurent --version"
  say ""
  say "Run the one-time setup. It picks your role (member / PI / mayor) and"
  say "collects the info to initialise your session:"
  say ""
  say "    murmurent init"
  say ""
  say "(Members ask their PI for a membership ID — no mayor involved; PIs can"
  say "self-issue their own lab's ID immediately, or register it with a mayor;"
  say "only mayors bootstrap a centre. 'murmurent init' walks you through your"
  say "path.)"
  say "──────────────────────────────────────────────────────────────────────"

  if [ -t 0 ] && command -v murmurent >/dev/null 2>&1; then
    case "$(ask "Run 'murmurent init' now? [Y/n] ")" in
      n*|N*) say "OK. Run 'murmurent init' when you're ready." ;;
      *) murmurent init ;;
    esac
  else
    say "Run 'murmurent init' when you're ready."
  fi
}

main "$@"
