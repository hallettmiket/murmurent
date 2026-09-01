#!/bin/zsh -l
# Double-click this file in Finder to open your murmurent dashboard.
#
# Launches the hi-fi (FastAPI) dashboard at http://127.0.0.1:8770/ and
# opens it in your default browser.
#
# Username resolution (first match wins):
#   1. $MURMURENT_USER if already set in the environment
#   2. ~/.murmurent/user (single line containing your Western username, e.g.
#      "the_pi")
#
# If neither is set, the dashboard server still starts (the API will
# 400 on /api/dashboard until you append ?user=<handle> to the URL or
# set $MURMURENT_USER and re-launch).

set -e

REPO_DIR="${0:A:h}"
cd "$REPO_DIR"

if [[ -z "$MURMURENT_USER" ]]; then
  if [[ -r "$HOME/.murmurent/user" ]]; then
    MURMURENT_USER="$(head -n1 "$HOME/.murmurent/user" | tr -d '[:space:]')"
  fi
fi
export MURMURENT_USER

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

PORT="${MURMURENT_DASHBOARD_PORT:-8770}"
URL="http://127.0.0.1:${PORT}/"

if [[ -n "$MURMURENT_USER" ]]; then
  print "Launching murmurent dashboard for: $MURMURENT_USER"
else
  print "Launching murmurent dashboard (no saved user — set \$MURMURENT_USER or"
  print "add ?user=<handle> to the URL)."
fi
print "Repo:  $REPO_DIR"
print "URL:   $URL"
print "Press Ctrl+C in this window to stop the dashboard."
print ""

# Pop the browser once the server is listening, then hand the foreground
# to uvicorn. The subshell sleeps a beat for the server to bind.
( for i in {1..30}; do
    if curl -s "${URL}healthz" >/dev/null 2>&1; then
      open "$URL" >/dev/null 2>&1 || xdg-open "$URL" >/dev/null 2>&1 || true
      break
    fi
    sleep 0.2
  done ) &

exec uv run murmurent dashboard --hifi --port "$PORT"
