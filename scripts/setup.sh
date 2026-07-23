#!/usr/bin/env bash
# Purpose: One-shot per-machine wiring of murmurent into ~/.claude/.
#          Makes murmurent the default Claude Code commons for every
#          project on this machine — re-points ~/.claude/agents/ at
#          murmurent's commons, links the murmurent CLAUDE.md as the
#          global default, and installs murmurent's hooks + MCP servers
#          into ~/.claude/settings.json.
# Author:  Mike Hallett (with Claude Code)
# Date:    2026-05-15
# Usage:   bash scripts/setup.sh
#
# Idempotent. Re-running:
#   - Replaces existing murmurent symlinks (no-op when target unchanged).
#   - Replaces generic_cc symlinks at the same path (legacy migration).
#   - SKIPS files in ~/.claude/agents/ that aren't symlinks
#     (preserves user-authored agent files).
#   - SKIPS ~/.claude/CLAUDE.md if it exists and isn't a symlink
#     (preserves a hand-written global context).
#
# Side effects:
#   - ~/.claude/agents/<agent>.md       → <repo>/agents/<agent>.md
#   - ~/.claude/CLAUDE.md               → <repo>/CLAUDE.md          (if absent)
#   - ~/.claude/settings.json           ← murmurent hooks + MCP merged in

set -euo pipefail

# Ensure ~/.local/bin (where `uv tool install` puts the murmurent shim) is
# on PATH — non-login shells (this script's default invocation) don't
# source ~/.profile, so murmurent won't be findable without this.
export PATH="$HOME/.local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CC_DIR="$HOME/.claude"
AGENTS_SRC="$REPO_DIR/agents"
RULES_SRC="$REPO_DIR/rules"
SKILLS_SRC="$REPO_DIR/skills"
CLAUDE_MD_SRC="$REPO_DIR/CLAUDE.md"

# Traffic-light helpers — match the dashboard's probe pill semantics
# so output reads the same way as the install flow.
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail() { printf '  \033[31m✗\033[0m %s\n' "$*"; }

if [[ ! -d "$AGENTS_SRC" ]]; then
  fail "murmurent commons not found at $AGENTS_SRC"
  fail "run this script from inside a murmurent clone (or fix REPO_DIR resolution)"
  exit 1
fi

mkdir -p "$CC_DIR/agents"

echo "[1/5] Wiring ~/.claude/agents/ → $AGENTS_SRC/"
swept_legacy=0
created=0
preserved=0
for src in "$AGENTS_SRC"/*.md; do
  [[ -f "$src" ]] || continue
  name="$(basename "$src")"
  dest="$CC_DIR/agents/$name"
  # Three cases for the destination:
  #   (a) symlink → already a murmurent/generic_cc commons link: replace
  #   (b) regular file → user-authored agent override: leave alone
  #   (c) absent → create symlink
  if [[ -L "$dest" ]]; then
    target="$(readlink "$dest")"
    case "$target" in
      */repos/generic_cc/agents/*)
        ln -sfn "$src" "$dest"
        ok "migrated $name (generic_cc → murmurent)"
        swept_legacy=$((swept_legacy + 1))
        ;;
      "$src")
        ok "$name already murmurent"
        ;;
      *)
        ln -sfn "$src" "$dest"
        ok "re-pointed $name → murmurent"
        ;;
    esac
  elif [[ -f "$dest" ]]; then
    warn "preserved user-authored $name (not a symlink) — delete it manually if you want murmurent's version"
    preserved=$((preserved + 1))
  else
    ln -sfn "$src" "$dest"
    ok "created $name → murmurent"
    created=$((created + 1))
  fi
done
echo "  -- migrated $swept_legacy generic_cc symlinks, created $created new, preserved $preserved user files."

echo
echo "[2/5] Wiring ~/.claude/rules/ → $RULES_SRC/"
# Same idempotent pattern as agents: replace existing murmurent symlinks,
# preserve user-authored .md files, create missing ones. Skips the step
# entirely when murmurent has no rules/ dir yet (back-compat with older
# clones that pre-date the rules layer).
if [[ -d "$RULES_SRC" ]]; then
  mkdir -p "$CC_DIR/rules"
  rules_created=0
  rules_preserved=0
  for src in "$RULES_SRC"/*.md; do
    [[ -f "$src" ]] || continue
    name="$(basename "$src")"
    dest="$CC_DIR/rules/$name"
    if [[ -L "$dest" ]]; then
      ln -sfn "$src" "$dest"
      ok "re-pointed rules/$name → murmurent"
    elif [[ -f "$dest" ]]; then
      warn "preserved user-authored rules/$name (not a symlink) — delete to use murmurent's version"
      rules_preserved=$((rules_preserved + 1))
    else
      ln -sfn "$src" "$dest"
      ok "created rules/$name → murmurent"
      rules_created=$((rules_created + 1))
    fi
  done
  echo "  -- created $rules_created new rules, preserved $rules_preserved user files."
else
  warn "no rules/ dir in murmurent — skipping"
fi

echo
echo "[3/5] Wiring ~/.claude/CLAUDE.md → $CLAUDE_MD_SRC"
if [[ ! -e "$CLAUDE_MD_SRC" ]]; then
  warn "$CLAUDE_MD_SRC is missing — skipping global CLAUDE.md link"
elif [[ -L "$CC_DIR/CLAUDE.md" ]]; then
  ln -sfn "$CLAUDE_MD_SRC" "$CC_DIR/CLAUDE.md"
  ok "re-pointed ~/.claude/CLAUDE.md → murmurent CLAUDE.md"
elif [[ -f "$CC_DIR/CLAUDE.md" ]]; then
  warn "~/.claude/CLAUDE.md is a regular file — preserved. Delete or rename it if you want murmurent's version."
else
  ln -sfn "$CLAUDE_MD_SRC" "$CC_DIR/CLAUDE.md"
  ok "created ~/.claude/CLAUDE.md → murmurent CLAUDE.md"
fi

echo
echo "[4/5] Installing murmurent hooks + MCP into ~/.claude/settings.json"
# Prefer the user's murmurent binary if on PATH; fall back to module
# invocation through the repo's venv. The --hooks flag is the only
# phase implemented so far.
if command -v murmurent >/dev/null 2>&1; then
  murmurent install --hooks && ok "hooks installed"
else
  warn "murmurent CLI not on PATH; trying repo-relative invocation"
  if [[ -x "$REPO_DIR/.venv/bin/murmurent" ]]; then
    "$REPO_DIR/.venv/bin/murmurent" install --hooks && ok "hooks installed (via .venv)"
  else
    fail "murmurent binary not found — run \`uv tool install --python 3.12 -e .\` from $REPO_DIR first"
    exit 2
  fi
fi

echo
echo "[5/5] Wiring ~/.claude/skills/ → $SKILLS_SRC/"
# Skills are directories (each contains SKILL.md), so we symlink the
# DIRECTORY itself rather than per-file. Same idempotent pattern as
# agents/rules: replace existing murmurent symlinks, preserve
# user-authored skill directories (don't clobber a hand-written
# skill that happens to share a name).
if [[ -d "$SKILLS_SRC" ]]; then
  mkdir -p "$CC_DIR/skills"
  skills_created=0
  skills_preserved=0
  for src_dir in "$SKILLS_SRC"/*/; do
    [[ -d "$src_dir" ]] || continue
    src_dir="${src_dir%/}"
    name="$(basename "$src_dir")"
    dest="$CC_DIR/skills/$name"
    if [[ -L "$dest" ]]; then
      ln -sfn "$src_dir" "$dest"
      ok "re-pointed skills/$name → murmurent"
    elif [[ -e "$dest" ]]; then
      warn "preserved user-authored skills/$name (not a symlink) — delete to use murmurent's version"
      skills_preserved=$((skills_preserved + 1))
    else
      ln -sfn "$src_dir" "$dest"
      ok "created skills/$name → murmurent"
      skills_created=$((skills_created + 1))
    fi
  done
  echo "  -- created $skills_created new skills, preserved $skills_preserved user dirs."
else
  warn "no skills/ dir in murmurent — skipping"
fi

# ── Personal vault agents + forks (issue #80) ─────────────────────────────────
# After the commons symlinks, re-materialise this member's OWN agents from
# their personal vault: <vault>/agents/*.md (symlinked) and
# <vault>/agent_forks/*.md (hardlinked, so the loop above preserves them on
# re-runs). Covers the second-machine case: a vault pull brings the files,
# this step loads them into ~/.claude/agents/. Idempotent + best-effort; a
# machine with no registered vault just skips.
echo
echo "Personal vault agents:"
if command -v murmurent >/dev/null 2>&1; then
  if murmurent agent relink; then
    ok "re-linked personal vault agents + forks into ~/.claude/agents/"
  else
    warn "couldn't re-link personal vault agents (run \`murmurent agent relink\` manually)"
  fi
elif [[ -x "$REPO_DIR/.venv/bin/murmurent" ]]; then
  if "$REPO_DIR/.venv/bin/murmurent" agent relink; then
    ok "re-linked personal vault agents + forks into ~/.claude/agents/ (via .venv)"
  else
    warn "couldn't re-link personal vault agents (run \`murmurent agent relink\` manually)"
  fi
else
  warn "murmurent CLI not found — skipping personal-agent re-link"
fi

# ── One-click dashboard launcher (every member: mayor, PI, member) ────────────
# Gives anyone a menu/Dock icon that starts the dashboard and opens it in their
# browser. macOS gets a ~/Applications/*.app bundle; Linux gets a freedesktop
# .desktop entry in the applications menu — distro-agnostic, so it works on
# Linux Mint, Ubuntu, Fedora, and any XDG-compliant desktop. Best-effort;
# other platforms skip with a note.
echo
echo "Dashboard launcher:"
case "$(uname -s)" in
  Darwin)
    if bash "$REPO_DIR/scripts/create_mac_app.sh" >/dev/null 2>&1; then
      ok "created ~/Applications/Murmurent Dashboard.app — drag it to your Dock for one-click access"
    else
      warn "couldn't create the launcher app (run scripts/create_mac_app.sh manually)"
    fi
    ;;
  Linux)
    if bash "$REPO_DIR/scripts/create_linux_launcher.sh" >/dev/null 2>&1; then
      ok "added \"Murmurent Dashboard\" to your applications menu (search \"murmurent\")"
    else
      warn "couldn't create the launcher (run scripts/create_linux_launcher.sh manually)"
    fi
    ;;
  *)
    warn "unrecognised platform — skipping the launcher (create one for your OS manually)"
    ;;
esac

echo
echo "Done. Verify with:"
echo "  ls -la ~/.claude/agents/   # should show symlinks into $AGENTS_SRC"
echo "  ls -la ~/.claude/skills/   # should show symlinks into $SKILLS_SRC"
echo "  grep -c murmurent.hooks ~/.claude/settings.json   # should be > 0"
