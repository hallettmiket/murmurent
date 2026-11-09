#!/usr/bin/env bash
#
# Purpose: install Piper, a free neural text-to-speech engine that runs on
#          the machine itself, and fetch one voice per murmurent agent, so
#          spoken verdicts (scripts/murmurent_log_agent_event.sh) sound like
#          people rather than a 1990s screen reader. Mac and Linux.
# Author: Mike Hallett (with Claude Code)
# Date: 2026-11-02
# Input:  none. Optional first argument: `audition` plays every voice once,
#         each introducing the agent it speaks for; `list` prints the table;
#         `languages` prints the languages verdicts can be spoken in (#279).
#         When ~/.murmurent/speak holds a "language <code>" line (set with
#         `murmurent config speak-language`), that language's voice is fetched
#         as well.
# Output: the `piper` command (uv tool, else pipx), the voices under
#         ~/.murmurent/voices (about 60 MB each, 1 GB in all; a voice that is
#         already there is kept), and ~/.murmurent/speak, the on switch.
#
# Voices come from the Piper project's public voice set (MIT licence, the
# individual voices carry their own open licences, recorded in each
# voice's .onnx.json). Nothing leaves the machine when a verdict is spoken.
#
# To change an agent's voice, add a line "<agent> <voice>" to
# ~/.murmurent/speak; `piper` voice names are the file names below without
# `.onnx`. To go back to the Mac's own voices, add the line "engine say".

set -euo pipefail

VOICES_DIR="${MURMURENT_VOICES_DIR:-$HOME/.murmurent/voices}"
SPEAK_FILE="${MURMURENT_SPEAK_FILE:-$HOME/.murmurent/speak}"
HOOK="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/murmurent_log_agent_event.sh"

say_() { printf '  \033[32m✓\033[0m %s\n' "$*"; }
die()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; exit 1; }

# The agent → voice table lives in the hook; read it from there so the two
# can never disagree.
agent_voices() {
    sed -n '/^default_piper_voice()/,/^}/p' "$HOOK" \
      | grep -E '^[[:space:]]+[a-z_*]+\)[[:space:]]+echo' \
      | sed -E 's/^[[:space:]]+([a-z_*]+)\)[[:space:]]+echo "([^"]+)".*/\1 \2/'
}

# The language → voice table lives in the hook too: "<code> <English name>
# <piper voice> <mac voice>", one line per language.
language_voices() {
    sed -n '/^language_voice()/,/^}/p' "$HOOK" \
      | grep -E '^[[:space:]]+[a-z]{2}_[A-Z]{2}\)[[:space:]]+echo' \
      | sed -E 's/^[[:space:]]+([a-z_A-Z]+)\)[[:space:]]+echo "([^"|]+)\|([^"|]+)\|([^"|]+)".*/\1 \2 \3 \4/'
}

# The voice the spoken language needs, if one is set: a "voice" line in the
# speak file, else the table's voice for the "language" line. Empty for English.
language_voice_wanted() {
    local lang v
    [[ -f "$SPEAK_FILE" ]] || return 0
    lang="$(grep -E '^[[:space:]]*language[[:space:]]+' "$SPEAK_FILE" | tail -n 1 | awk '{print $2}')"
    case "$lang" in ""|en|en_*|english|English) return 0 ;; esac
    v="$(grep -E '^[[:space:]]*voice[[:space:]]+' "$SPEAK_FILE" | tail -n 1 | awk '{print $2}')"
    [[ -n "$v" ]] && { echo "$v"; return 0; }
    language_voices | awk -v l="$lang" '$1 == l {print $3}'
}

case "${1:-}" in
    list)
        agent_voices | sed 's/^\*/default/' | column -t
        exit 0 ;;
    languages)
        language_voices | column -t
        exit 0 ;;
    audition)
        command -v piper >/dev/null || die "piper is not installed; run this script with no argument first"
        agent_voices | while read -r agent voice; do
            [[ "$agent" == "*" ]] && agent="default"
            model="$VOICES_DIR/$voice.onnx"
            [[ -f "$model" ]] || { echo "  (no model for $agent: $voice)"; continue; }
            wav="$(mktemp "${TMPDIR:-/tmp}/audition.XXXXXX").wav"
            printf 'Hello. I am the %s, speaking as %s.\n' "${agent//_/ }" "${voice%-*}" \
              | piper -m "$model" -f "$wav" >/dev/null 2>&1
            if command -v afplay >/dev/null; then afplay "$wav"
            elif command -v paplay >/dev/null; then paplay "$wav"
            elif command -v aplay >/dev/null; then aplay -q "$wav"
            else echo "  no wav player found (afplay, paplay or aplay)"; rm -f "$wav"; exit 1; fi
            rm -f "$wav"
        done
        exit 0 ;;
    "") ;;
    *) die "usage: $0 [list|languages|audition]" ;;
esac

echo "[1/4] The piper command"
if command -v piper >/dev/null 2>&1; then
    say_ "already installed: $(command -v piper)"
elif command -v uv >/dev/null 2>&1; then
    uv tool install --quiet piper-tts
    say_ "installed with uv tool (piper-tts)"
elif command -v pipx >/dev/null 2>&1; then
    pipx install --quiet piper-tts
    say_ "installed with pipx (piper-tts)"
else
    die "neither uv nor pipx is installed; install uv (https://docs.astral.sh/uv/) and rerun"
fi
command -v piper >/dev/null 2>&1 || die "piper is installed but not on PATH; add ~/.local/bin to PATH and rerun"

echo "[2/4] A player for the spoken verdicts"
player=""
for p in afplay paplay aplay pw-play ffplay; do
    command -v "$p" >/dev/null 2>&1 && { player="$p"; break; }
done
if [[ -n "$player" ]]; then
    say_ "$player"
else
    echo "  none found. On Ubuntu: sudo apt install alsa-utils (aplay) or pulseaudio-utils (paplay)."
fi

echo "[3/4] One voice per agent, under $VOICES_DIR"
mkdir -p "$VOICES_DIR"
PIPER_PY="$(dirname "$(readlink -f "$(command -v piper)")")/python"
[[ -x "$PIPER_PY" ]] || PIPER_PY="$(dirname "$(command -v piper)")/python"
[[ -x "$PIPER_PY" ]] || die "cannot find the Python that runs piper (looked beside $(command -v piper))"
wanted="$(agent_voices | awk '{print $2}' | sort -u)"
lang_voice="$(language_voice_wanted)"
if [[ -n "$lang_voice" ]]; then
    echo "  spoken language set in $SPEAK_FILE: adding its voice, $lang_voice"
    wanted="$(printf '%s\n%s\n' "$wanted" "$lang_voice" | sort -u)"
fi
missing=()
for v in $wanted; do
    [[ -f "$VOICES_DIR/$v.onnx" && -f "$VOICES_DIR/$v.onnx.json" ]] || missing+=("$v")
done
if [[ ${#missing[@]} -eq 0 ]]; then
    say_ "all $(echo "$wanted" | wc -l | tr -d ' ') voices already present"
else
    echo "  fetching ${#missing[@]} voice(s), about 60 MB each..."
    "$PIPER_PY" -m piper.download_voices --download-dir "$VOICES_DIR" "${missing[@]}" 2>&1 \
      | grep -i "downloaded\|error" | sed 's/^/  /' || true
    for v in "${missing[@]}"; do
        [[ -f "$VOICES_DIR/$v.onnx" ]] || die "voice $v did not download"
    done
    say_ "${#missing[@]} voice(s) fetched"
fi

echo "[4/4] The on switch"
if [[ -f "$SPEAK_FILE" ]]; then
    say_ "$SPEAK_FILE already exists; spoken verdicts stay as they were"
else
    mkdir -p "$(dirname "$SPEAK_FILE")"
    : > "$SPEAK_FILE"
    say_ "created $SPEAK_FILE (empty: default voices, Piper first)"
fi

echo
echo "Done. The next agent verdict will be spoken with Piper."
echo "Hear every voice:   bash $0 audition"
echo "Change one:         echo 'adversary en_GB-cori-medium' >> $SPEAK_FILE"
echo "Mac voices instead: echo 'engine say' >> $SPEAK_FILE"
echo "Another language:   murmurent config speak-language fr_FR   (list: bash $0 languages)"
echo "Mute:               rm $SPEAK_FILE   (or MURMURENT_SPEAK=0 for one session)"
