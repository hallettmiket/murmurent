#!/bin/zsh -l
# Double-click this file in Finder to open your wigamig dashboard.
#
# Username resolution (first match wins):
#   1. $WIGAMIG_USER if already set in the environment
#   2. ~/.wigamig/user (single line containing your Western username, e.g.
#      "mhallet")
#
# If neither is set, the dashboard opens with no member selected and
# prompts you in the Streamlit sidebar to type a handle. The handle you
# enter there is saved to ~/.wigamig/user automatically. There is no
# fallback to your Mac login name (`$USER`) because that almost always
# disagrees with the Western username and produced confusing dashboards.

set -e

REPO_DIR="${0:A:h}"
cd "$REPO_DIR"

if [[ -z "$WIGAMIG_USER" ]]; then
  if [[ -r "$HOME/.wigamig/user" ]]; then
    WIGAMIG_USER="$(head -n1 "$HOME/.wigamig/user" | tr -d '[:space:]')"
  fi
fi
export WIGAMIG_USER

if ! command -v uv >/dev/null 2>&1; then
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    if [[ -x "$candidate" ]]; then
      export PATH="${candidate:h}:$PATH"
      break
    fi
  done
fi

if ! command -v uv >/dev/null 2>&1; then
  print -u2 "ERROR: 'uv' was not found on PATH."
  print -u2 "Install uv (https://docs.astral.sh/uv/) and try again."
  print -u2 ""
  print -u2 "Press any key to close this window."
  read -k1 _
  exit 1
fi

if [[ -n "$WIGAMIG_USER" ]]; then
  print "Launching wigamig dashboard for: $WIGAMIG_USER"
else
  print "Launching wigamig dashboard (no saved user — pick one in the sidebar)."
fi
print "Repo: $REPO_DIR"
print "Press Ctrl+C in this window to stop the dashboard."
print ""

exec uv run wigamig dashboard
