#!/bin/bash
# scripts/start_workspace.sh
#
# Open a multi-pane workspace for a wigamig project:
#   Left ~65%:  VSCode at the project repo
#   Right ~35%: iTerm2 windows stacked vertically, one per selected
#               agent, each tailing outputs/<agent>/progress.log
#
# Usage:
#   ./scripts/start_workspace.sh <project-dir> <agents-csv> [sea-id]
#
# Examples:
#   ./scripts/start_workspace.sh ~/repos/dcis_sc_tutorial blacksmith,bookworm,oracle
#   ./scripts/start_workspace.sh ~/repos/dcis_sc_tutorial blacksmith,oracle 4
#
# Adapted from ~/repos/generic_cc/scripts/start_agents.sh — same pattern,
# but parameterised by project + agent list + optional SEA focus.
#
# Environment overrides for the display geometry (defaults to the
# primary display at 1920x1080 logical pts):
#   WIGAMIG_DISPLAY_X, _Y, _WIDTH, _HEIGHT — display rectangle
#   WIGAMIG_LEFT_PCT (default 65) — VSCode pane width as a percent

set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <project-dir> <agents-csv> [sea-id]" >&2
  exit 2
fi

PROJECT_DIR="$1"
AGENTS_CSV="$2"
SEA_ID="${3:-}"
PROJECT_DIR="$(cd "$PROJECT_DIR" && pwd)"
PROJECT_NAME="$(basename "$PROJECT_DIR")"

IFS=',' read -r -a AGENTS <<< "$AGENTS_CSV"
N_AGENTS="${#AGENTS[@]}"
if [[ "$N_AGENTS" -lt 1 ]]; then
  echo "error: at least one agent required" >&2
  exit 2
fi

CODE="/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
[[ -x "$CODE" ]] || CODE="code"   # fall back to PATH

DISPLAY_X="${WIGAMIG_DISPLAY_X:-0}"
DISPLAY_Y="${WIGAMIG_DISPLAY_Y:-0}"
DISPLAY_WIDTH="${WIGAMIG_DISPLAY_WIDTH:-1920}"
DISPLAY_HEIGHT="${WIGAMIG_DISPLAY_HEIGHT:-1080}"
LEFT_PCT="${WIGAMIG_LEFT_PCT:-65}"
MENU_BAR=25

# VSCode pane: left LEFT_PCT% of the display.
VSCODE_LEFT=$DISPLAY_X
VSCODE_TOP=$(( DISPLAY_Y + MENU_BAR ))
VSCODE_RIGHT=$(( DISPLAY_X + (DISPLAY_WIDTH * LEFT_PCT / 100) ))
VSCODE_BOTTOM=$(( DISPLAY_Y + DISPLAY_HEIGHT ))

# Agent column: right (100 - LEFT_PCT)% of the display.
AGENT_LEFT=$(( VSCODE_RIGHT + 3 ))
AGENT_RIGHT=$(( DISPLAY_X + DISPLAY_WIDTH ))
AGENT_TOP=$(( DISPLAY_Y + MENU_BAR ))
AGENT_BOTTOM=$(( DISPLAY_Y + DISPLAY_HEIGHT ))
USABLE_HEIGHT=$(( AGENT_BOTTOM - AGENT_TOP ))
ROW_H=$(( USABLE_HEIGHT / N_AGENTS ))

echo "=== wigamig workspace ==="
echo "project: $PROJECT_DIR"
echo "agents:  ${AGENTS[*]} ($N_AGENTS panes)"
[[ -n "$SEA_ID" ]] && echo "focus:   SEA #$SEA_ID"
echo ""

# Per-agent outputs/<name>/progress.log.
for A in "${AGENTS[@]}"; do
  mkdir -p "$PROJECT_DIR/outputs/$A"
  [[ -f "$PROJECT_DIR/outputs/$A/progress.log" ]] || touch "$PROJECT_DIR/outputs/$A/progress.log"
done

# 1. Open VSCode at the project repo, position it on the left.
"$CODE" "$PROJECT_DIR" &
sleep 3
osascript -e "tell application \"Visual Studio Code\" to activate"
sleep 1
osascript -e "tell application \"System Events\" to tell process \"Code\"
  set position of front window to {$VSCODE_LEFT, $VSCODE_TOP}
  set size of front window to {$(( VSCODE_RIGHT - VSCODE_LEFT )), $(( VSCODE_BOTTOM - VSCODE_TOP ))}
end tell"
sleep 1

# 2. Helper: iTerm2 window with header + tail -f.
open_agent_window() {
  local NAME="$1"
  local B_LEFT=$2 B_TOP=$3 B_RIGHT=$4 B_BOTTOM=$5
  local COLOR="$6"
  local LOG_FILE="$7"

  osascript -e "tell application \"iTerm2\"
    create window with default profile
    delay 0.3
    set bounds of front window to {$B_LEFT, $B_TOP, $B_RIGHT, $B_BOTTOM}
  end tell"
  sleep 0.3
  osascript -e "tell application \"iTerm2\"
    tell front window
      tell current session
        write text \"printf '\\\\033[${COLOR}m'; clear; echo '  $NAME'; echo '  ─────────────────────'; echo; tail -f $LOG_FILE\"
      end tell
    end tell
  end tell"
}

COLORS=(32 94 35 31 36 35 33 91 93 95 96)
EMOJI_blacksmith="⚒"
EMOJI_bookworm="📚"
EMOJI_artist="🎨"
EMOJI_adversary="⚔"
EMOJI_oracle="🔮"
EMOJI_conscience="⚖"
EMOJI_saul_goodman="⚖"
EMOJI_security_guard="🛡"
EMOJI_receptionist="📞"

for i in "${!AGENTS[@]}"; do
  A="${AGENTS[$i]}"
  ROW_TOP=$(( AGENT_TOP + i * ROW_H ))
  if (( i + 1 < N_AGENTS )); then
    ROW_BOTTOM=$(( AGENT_TOP + (i + 1) * ROW_H ))
  else
    ROW_BOTTOM=$AGENT_BOTTOM
  fi
  COLOR="${COLORS[$(( i % ${#COLORS[@]} ))]}"
  EMOJI_VAR="EMOJI_$A"
  EMOJI="${!EMOJI_VAR:-•}"
  open_agent_window "$EMOJI  ${A^^}" \
    "$AGENT_LEFT" "$ROW_TOP" "$AGENT_RIGHT" "$ROW_BOTTOM" \
    "$COLOR" "$PROJECT_DIR/outputs/$A/progress.log"
  sleep 0.4
done

echo ""
echo "Workspace ready for $PROJECT_NAME."
echo "  Left:  VSCode at $PROJECT_DIR"
echo "  Right: $(IFS='|'; echo "${AGENTS[*]}")"
[[ -n "$SEA_ID" ]] && echo "  Focus: SEA #$SEA_ID — open seas/$SEA_ID.md to start."
