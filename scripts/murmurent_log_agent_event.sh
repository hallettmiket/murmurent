#!/usr/bin/env bash
# Hook handler invoked by Claude Code on subagent lifecycle events.
# Writes one ANSI-coloured line per event to ~/.murmurent/agents.log so a
# `tail -F` pane (the BR quadrant of the murmurent VSCode layout) can show
# live "who is doing what" without flooding the user with raw tool
# transcripts.
#
# Wired up via .claude/settings.json:
#   PreToolUse(Agent) → "<agent>: starting — <description>"
#   SubagentStop      → "<agent>: done"
#
# Spoken verdicts (macOS only): when ~/.murmurent/speak exists, each
# SubagentStop line is also read aloud with the built-in `say` command, one
# voice per agent. The file is both the on switch and the voice table: empty
# means the defaults below; a line "<agent> <voice>" overrides one agent.
# MURMURENT_SPEAK=0 mutes everything for one session; MURMURENT_SPEAK=1 turns
# it on without the file. The main session never speaks: only a dispatched
# subagent carries an agent type, and nothing else reaches this branch.
#
# Input: JSON on stdin from the CC hook runner. We use jq if present
# (clean) and fall back to a python one-liner so the hook still works
# on machines without jq. Output to stderr is what CC may surface to
# the user; we keep it silent on success and only complain on parse
# failure so the hook itself is invisible.

set -euo pipefail
LOG="${MURMURENT_AGENT_LOG:-$HOME/.murmurent/agents.log}"
mkdir -p "$(dirname "$LOG")"
touch "$LOG"

# Read stdin once into a variable — we may parse several fields out of
# the same JSON blob.
INPUT="$(cat || true)"
[[ -z "$INPUT" ]] && exit 0

# Debug: when MURMURENT_AGENT_HOOK_DEBUG=1, dump the raw payload + an
# "EVENT" marker so we can see what fields each hook event provides.
# Off by default — flip on to investigate schema drift.
if [[ "${MURMURENT_AGENT_HOOK_DEBUG:-0}" == "1" ]]; then
    DEBUG_LOG="${MURMURENT_AGENT_HOOK_DEBUG_LOG:-$HOME/.murmurent/agents_debug.log}"
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
#
# There is deliberately NO generic "agent" fallback. If neither field
# resolves, the event did not come from a genuinely-dispatched subagent
# (e.g. a main-context message, or a payload without an agent type). Writing
# a nameless "agent: <whatever the main loop last said>" line is the exact
# "fake out" the dashboard must never show — a real subagent always carries
# its type. When we cannot name the agent, we skip the line entirely (below),
# rather than inventing one.
AGENT="$(get tool_input.subagent_type)"
[[ -z "$AGENT" ]] && AGENT="$(get agent_type)"

DESC="$(get tool_input.description)"
LAST_MSG="$(get last_assistant_message)"

# In the Claude desktop app a subagent returns its report through a
# SubagentHandback tool call rather than a plain text message, so
# last_assistant_message arrives empty and the line (and the spoken verdict)
# would be a bare "done". Fall back to the agent's own transcript: the
# message in its last SubagentHandback call, else its last text message.
verdict_from_transcript() {
    local path="$1"
    [[ -n "$path" && -f "$path" ]] || return 0
    /usr/bin/python3 - "$path" <<'PY' 2>/dev/null
import json, sys
best = ""
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    try:
        d = json.loads(line)
    except ValueError:
        continue
    m = d.get("message") if isinstance(d.get("message"), dict) else None
    if not m or m.get("role") != "assistant":
        continue
    c = m.get("content")
    if isinstance(c, str):
        if c.strip():
            best = c
        continue
    for part in c or []:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "tool_use" and part.get("name") == "SubagentHandback":
            txt = str((part.get("input") or {}).get("message") or "")
            if txt.strip():
                best = txt
        elif part.get("type") == "text" and str(part.get("text") or "").strip():
            best = part["text"]
print(best)
PY
}

if [[ "$EVENT" == "SubagentStop" && -z "$(printf '%s' "$LAST_MSG" | tr -d '[:space:]')" ]]; then
    AGENT_TRANSCRIPT="$(get agent_transcript_path)"
    if [[ -z "$AGENT_TRANSCRIPT" ]]; then
        # Derive it: <session transcript dir>/<session id>/subagents/agent-<id>.jsonl
        SESSION_T="$(get transcript_path)"; AGENT_ID="$(get agent_id)"
        if [[ -n "$SESSION_T" && -n "$AGENT_ID" ]]; then
            AGENT_TRANSCRIPT="$(dirname "$SESSION_T")/$(basename "${SESSION_T%.jsonl}")/subagents/agent-${AGENT_ID}.jsonl"
        fi
    fi
    LAST_MSG="$(verdict_from_transcript "$AGENT_TRANSCRIPT")"
fi

# Deterministic colour per agent name. Hash the name → 1 of N ANSI
# palette entries. Same agent always gets the same colour across runs,
# which is the whole point of the dashboard.
PALETTE=(32 33 34 35 36 91 92 93 94 95 96)
HASH=$(printf '%s' "$AGENT" | cksum | awk '{print $1}')
COLOR=${PALETTE[$(( HASH % ${#PALETTE[@]} ))]}

# Include the date, not just HH:MM — the dashboard shows a "today / yesterday /
# Jul 10" day label so days-old activity doesn't read as if it just happened.
# The parser (snapshot._AGENT_LINE_RE) still accepts old time-only lines.
ts="$(date '+%Y-%m-%d %H:%M')"

# ---------------------------------------------------------------------------
# Spoken verdicts
# ---------------------------------------------------------------------------

SPEAK_FILE="${MURMURENT_SPEAK_FILE:-$HOME/.murmurent/speak}"

# The default voice per agent. Each is a distinct, natural English voice on a
# stock macOS install (`say -v '?'` lists them), so you know who finished
# without looking. Override any of them with a line in $SPEAK_FILE.
default_voice() {
    case "$1" in
        adversary)         echo "Tessa" ;;
        conscience)        echo "Moira" ;;
        judge)             echo "Daniel" ;;
        bookworm)          echo "Karen" ;;
        oracle)            echo "Samantha" ;;
        lab_oracle)        echo "Shelley" ;;
        blacksmith)        echo "Fred" ;;
        artist)            echo "Flo" ;;
        teacher)           echo "Grandpa" ;;
        scribe)            echo "Reed" ;;
        lawyer)            echo "Aman" ;;
        millwright)        echo "Eddy" ;;
        centre_millwright) echo "Rocko" ;;
        registrar)         echo "Sandy" ;;
        security_guard)    echo "Rishi" ;;
        *)                 echo "" ;;        # the system default voice
    esac
}

# The voice for an agent: the override line in $SPEAK_FILE if there is one
# ("<agent> <voice name, may contain spaces>"), else the default above.
voice_for() {
    local agent="$1" line
    if [[ -f "$SPEAK_FILE" ]]; then
        line="$(grep -E "^[[:space:]]*${agent}[[:space:]]+" "$SPEAK_FILE" 2>/dev/null | tail -n 1 || true)"
        if [[ -n "$line" ]]; then
            printf '%s' "$line" | sed -E "s/^[[:space:]]*${agent}[[:space:]]+//; s/[[:space:]]*$//"
            return 0
        fi
    fi
    default_voice "$agent"
}

# Read "<agent>. <verdict>" aloud, in the background, one voice at a time.
# Returns at once so the hook never holds Claude Code up; a verdict that
# arrives while another is being spoken waits its turn rather than talking
# over it. Silent unless enabled (see the header), and on anything but a Mac.
speak_verdict() {
    local agent="$1" text="$2" voice clean name
    [[ "${MURMURENT_SPEAK:-}" == "0" ]] && return 0
    [[ "${MURMURENT_SPEAK:-}" != "1" && ! -f "$SPEAK_FILE" ]] && return 0
    command -v say >/dev/null 2>&1 || return 0
    # The stop event can fire twice for one agent; say each verdict once.
    local stamp="$HOME/.murmurent/.last_spoken" now key
    now="$(date +%s)"; key="$(printf '%s|%s' "$agent" "$text" | cksum | awk '{print $1}')"
    if [[ -f "$stamp" ]]; then
        read -r prev_t prev_k < "$stamp" || true
        if [[ "${prev_k:-}" == "$key" && $(( now - ${prev_t:-0} )) -lt 60 ]]; then
            return 0
        fi
    fi
    printf '%s %s\n' "$now" "$key" > "$stamp"
    voice="$(voice_for "$agent")"
    name="${agent//_/ }"
    # What is read: the headline only (the first sentence of the first line),
    # with web addresses, file paths, identifiers and markdown marks removed.
    # A verdict is a sentence for the ear; anything a person would need to
    # read stays in the log.
    clean="$(printf '%s' "$text" | /usr/bin/python3 -c '
import re, sys
t = sys.stdin.read().strip().splitlines()
t = t[0] if t else ""
t = re.sub(r"https?://\S+|www\.\S+", "", t)            # web addresses
t = re.sub(r"(?<![\w])~?/[\w./-]+", "", t)               # file paths
t = re.sub(r"\b(doi|pmid|arxiv)\s*:?\s*\S+", "", t, flags=re.I)
t = re.sub(r"[*_`#>\[\]()]", "", t)
m = re.match(r"(.+?[.!?])(\s|$)|(.+?)(\s+-\s+)", t)                    # first sentence, before dashes become commas
t = (m.group(1) or m.group(3)) if m else t
t = re.sub(r"\s*[—–]\s*|\s+-\s+", ", ", t)
t = re.sub(r"\s+", " ", t)
t = re.sub(r"\s*,(\s*,)+", ",", t)                                   # doubled commas
t = re.sub(r"\b(in|at|see|from|to|of|under|on)\s*([,.]|$)", r"\2", t)   # word left dangling by a removed path
t = re.sub(r"\s+([,.])", r"\1", t)                                  # space before punctuation
t = re.sub(r"\s+", " ", t).strip(" ,;:")
print(t[:200])
')"
    [[ -z "$clean" ]] && clean="done"
    (
        while pgrep -xq say; do sleep 0.3; done
        if [[ -n "$voice" ]]; then
            say -v "$voice" -- "$name. $clean"
        else
            say -- "$name. $clean"
        fi
    ) </dev/null >/dev/null 2>&1 &
    disown 2>/dev/null || true
}

# Compose one line per event. Truncate description to 100 chars so a
# verbose orchestrator prompt doesn't wrap and break the column.
case "$EVENT" in
    PreToolUse)
        # Only fire for the Agent tool — other tools share PreToolUse
        # but aren't agent events.
        [[ "$TOOL" != "Agent" ]] && exit 0
        # No subagent_type → not a real dispatch. Skip rather than log a
        # nameless line (see the AGENT-resolution note above).
        [[ -z "$AGENT" ]] && exit 0
        short="${DESC:0:100}"
        # Trailing blank line keeps the BR pane visually airy — easier
        # to scan one event at a time than a dense wall of text.
        printf '\033[%sm[%s] %s: starting — %s\033[0m\n\n' \
            "$COLOR" "$ts" "$AGENT" "$short" >> "$LOG"
        ;;
    SubagentStop)
        # No agent_type → this stop did not come from a dispatched subagent,
        # so its last message is main-context text, not an agent verdict.
        # Skip it — logging it as "agent: …" is the fake-out we forbid.
        [[ -z "$AGENT" ]] && exit 0
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
        speak_verdict "$AGENT" "$msg"
        ;;
    *)
        # Unrecognised event — log a single dim line so the user knows
        # we saw something but didn't know what to do with it. Helps
        # debug if CC adds new hook event names.
        printf '\033[90m[%s] (unhandled hook: %s)\033[0m\n\n' "$ts" "$EVENT" >> "$LOG"
        ;;
esac
