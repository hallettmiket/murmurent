#!/usr/bin/env bash
# Hook handler invoked by Claude Code on subagent lifecycle events.
# Writes one ANSI-coloured line per event to ~/.wigamig/agents.log so a
# `tail -F` pane (the BR quadrant of the wigamig VSCode layout) can show
# live "who is doing what" without flooding the user with raw tool
# transcripts.
#
# Wired up via .claude/settings.json:
#   PreToolUse(Agent) → "<agent>: starting — <description>"
#   SubagentStop      → "<agent>: done"
#
# Input: JSON on stdin from the CC hook runner. We use jq if present
# (clean) and fall back to a python one-liner so the hook still works
# on machines without jq. Output to stderr is what CC may surface to
# the user; we keep it silent on success and only complain on parse
# failure so the hook itself is invisible.

set -euo pipefail
LOG="${WIGAMIG_AGENT_LOG:-$HOME/.wigamig/agents.log}"
mkdir -p "$(dirname "$LOG")"
touch "$LOG"

# Read stdin once into a variable — we may parse several fields out of
# the same JSON blob.
INPUT="$(cat || true)"
[[ -z "$INPUT" ]] && exit 0

# Debug: when WIGAMIG_AGENT_HOOK_DEBUG=1, dump the raw payload + an
# "EVENT" marker so we can see what fields each hook event provides.
# Off by default — flip on to investigate schema drift.
if [[ "${WIGAMIG_AGENT_HOOK_DEBUG:-0}" == "1" ]]; then
    DEBUG_LOG="${WIGAMIG_AGENT_HOOK_DEBUG_LOG:-$HOME/.wigamig/agents_debug.log}"
    mkdir -p "$(dirname "$DEBUG_LOG")"
    {
        echo "=== $(date '+%H:%M') ==="
        echo "$INPUT"
        echo
    } >> "$DEBUG_LOG"
fi

# Tiny JSON getter. Prefers jq; falls back to a Python one-liner that
# tolerates missing keys (returns empty string).
get() {
    local key="$1"
    if command -v jq >/dev/null 2>&1; then
        echo "$INPUT" | jq -r --arg k "$key" '. | getpath($k | split(".")) // ""' 2>/dev/null
    else
        echo "$INPUT" | /usr/bin/python3 -c "
import json, sys
try:
    d = json.loads(sys.stdin.read())
    for part in '$key'.split('.'):
        d = d.get(part, '') if isinstance(d, dict) else ''
    print(d if d is not None else '')
except Exception:
    print('')
"
    fi
}

EVENT="$(get hook_event_name)"
TOOL="$(get tool_name)"

# Agent name lives in different fields depending on the event:
#   PreToolUse(Agent) → tool_input.subagent_type
#   SubagentStop      → agent_type
# Plus the agent's final message (only on SubagentStop) so the "done"
# line can echo the agent in its own voice instead of a bare "done".
AGENT="$(get tool_input.subagent_type)"
[[ -z "$AGENT" ]] && AGENT="$(get agent_type)"
[[ -z "$AGENT" ]] && AGENT="agent"

DESC="$(get tool_input.description)"
LAST_MSG="$(get last_assistant_message)"

# Deterministic colour per agent name. Hash the name → 1 of N ANSI
# palette entries. Same agent always gets the same colour across runs,
# which is the whole point of the dashboard.
PALETTE=(32 33 34 35 36 91 92 93 94 95 96)
HASH=$(printf '%s' "$AGENT" | cksum | awk '{print $1}')
COLOR=${PALETTE[$(( HASH % ${#PALETTE[@]} ))]}

ts="$(date '+%H:%M')"

# Compose one line per event. Truncate description to 100 chars so a
# verbose orchestrator prompt doesn't wrap and break the column.
case "$EVENT" in
    PreToolUse)
        # Only fire for the Agent tool — other tools share PreToolUse
        # but aren't agent events.
        [[ "$TOOL" != "Agent" ]] && exit 0
        short="${DESC:0:100}"
        # Trailing blank line keeps the BR pane visually airy — easier
        # to scan one event at a time than a dense wall of text.
        printf '\033[%sm[%s] %s: starting — %s\033[0m\n\n' \
            "$COLOR" "$ts" "$AGENT" "$short" >> "$LOG"
        ;;
    SubagentStop)
        # Echo back the agent's own final message (truncated, newlines
        # collapsed) so the BR pane shows "<agent>: <summary in their
        # own voice>" instead of a bare "<agent>: done". Empty message
        # falls back to "done" so the line is never empty.
        msg=$(printf '%s' "$LAST_MSG" | tr '\n' ' ' | tr -s ' ')
        # Cap at 200 chars. Pairs with the "Headline first" rule
        # (rules/headline_first.md) which asks every agent to lead with
        # a single ≤200-char verdict line — so the cap rarely truncates
        # in practice.
        msg="${msg:0:200}"
        [[ -z "$msg" ]] && msg="done"
        printf '\033[%sm[%s] %s: %s\033[0m\n\n' \
            "$COLOR" "$ts" "$AGENT" "$msg" >> "$LOG"
        ;;
    *)
        # Unrecognised event — log a single dim line so the user knows
        # we saw something but didn't know what to do with it. Helps
        # debug if CC adds new hook event names.
        printf '\033[90m[%s] (unhandled hook: %s)\033[0m\n\n' "$ts" "$EVENT" >> "$LOG"
        ;;
esac
