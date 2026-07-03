#!/usr/bin/env sh
# wigamig-join.sh — the one script a prospective member runs to join a wigamig
# institution. It:
#   1. installs `age` (encryption) if you don't have it,
#   2. asks you a few questions (no file to edit),
#   3. encrypts your answers to your registrar's public key,
#   4. opens your email app, pre-addressed, with the encrypted request ready
#      to send (also saved as join-request.age and copied to your clipboard).
#
# Nothing leaves your computer until YOU press Send. Only your registrar can
# read the result.
#
#   Download + run:
#     curl -fsSL -O https://raw.githubusercontent.com/hallettmiket/wigamig_public/main/join/wigamig-join.sh
#     sh wigamig-join.sh
set -eu

HUB_RAW="https://raw.githubusercontent.com/hallettmiket/wigamig_public/main"

say()  { printf '%s\n' "$*"; }
ask()  { # ask "prompt" -> echoes the answer
  printf '%s' "$1" >&2; IFS= read -r _a || _a=""; printf '%s' "$_a"; }

# --- 1. ensure age ---------------------------------------------------------
ensure_age() {
  command -v age >/dev/null 2>&1 && return 0
  say ""
  say "You need 'age' (a small, standard encryption tool). Let me install it."
  if command -v brew >/dev/null 2>&1; then
    case "$(ask 'Install age with Homebrew now? [Y/n] ')" in
      n*|N*) : ;; *) brew install age && return 0 ;;
    esac
  elif command -v apt-get >/dev/null 2>&1; then
    case "$(ask 'Install age with apt (needs sudo) now? [Y/n] ')" in
      n*|N*) : ;; *) sudo apt-get update && sudo apt-get install -y age && return 0 ;;
    esac
  elif command -v dnf >/dev/null 2>&1; then
    case "$(ask 'Install age with dnf (needs sudo) now? [Y/n] ')" in
      n*|N*) : ;; *) sudo dnf install -y age && return 0 ;;
    esac
  elif command -v pacman >/dev/null 2>&1; then
    case "$(ask 'Install age with pacman (needs sudo) now? [Y/n] ')" in
      n*|N*) : ;; *) sudo pacman -S --noconfirm age && return 0 ;;
    esac
  fi
  command -v age >/dev/null 2>&1 && return 0
  say ""
  say "Couldn't install age automatically. Please install it from"
  say "  https://age-encryption.org   (macOS: 'brew install age')"
  say "then run this script again."
  exit 1
}

# --- 2. choose institution (from the directory) ----------------------------
choose_institution() {
  DIR="$(mktemp)"; trap 'rm -f "$DIR"' EXIT
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$HUB_RAW/join/directory.tsv" -o "$DIR" 2>/dev/null || : > "$DIR"
  fi
  # keep only "live" rows (non-comment, with email + key)
  LIVE="$(mktemp)"
  awk -F '\t' '!/^#/ && NF>=3 && $2!="" && $3!="" {print}' "$DIR" > "$LIVE" 2>/dev/null || : > "$LIVE"
  n=$(wc -l < "$LIVE" | tr -d ' ')
  if [ "$n" -gt 0 ]; then
    say ""; say "Which institution are you joining?"
    i=0; while IFS="$(printf '\t')" read -r inst email key; do
      i=$((i+1)); say "  $i) $inst"
    done < "$LIVE"
    say "  0) mine isn't listed / enter manually"
    sel="$(ask 'Number: ')"
    if [ "${sel:-0}" -gt 0 ] 2>/dev/null && [ "${sel:-0}" -le "$i" ]; then
      row="$(sed -n "${sel}p" "$LIVE")"
      INSTITUTION="$(printf '%s' "$row" | cut -f1)"
      EMAIL="$(printf '%s' "$row" | cut -f2)"
      RECIPIENT="$(printf '%s' "$row" | cut -f3)"
      rm -f "$LIVE"; return 0
    fi
  fi
  rm -f "$LIVE"
  say ""; say "Enter your institution's details (from the directory README):"
  INSTITUTION="$(ask 'Institution: ')"
  EMAIL="$(ask 'Registrar email: ')"
  RECIPIENT="$(ask 'Registrar age key (age1...): ')"
}

# --- 3. the form (interactive) ---------------------------------------------
fill_form() {
  say ""; say "A few questions — press Enter after each:"
  KIND="$(ask '  What do you want? (lab / core / pi / member): ')"
  NAME="$(ask '  Lab/core name (or the lab you want to join): ')"
  PI="$(ask '  Your handle = your netname (e.g. @jsmith): ')"
  RQEMAIL="$(ask '  Your email (how the registrar reaches you): ')"
  JUST="$(ask '  One sentence: who are you / why join?: ')"
}

# --- 4. encrypt ------------------------------------------------------------
main() {
  ensure_age
  choose_institution
  case "$RECIPIENT" in age1*) : ;; *) say "That doesn't look like an age key (age1...). Stopping."; exit 1 ;; esac
  fill_form
  OUT="join-request.age"
  age -a -r "$RECIPIENT" -o "$OUT" <<EOF
kind: $KIND
institution: $INSTITUTION
name: $NAME
pi: $PI
email: $RQEMAIL
justification: $JUST
EOF
  say ""; say "✓ Encrypted your request to $OUT (only $EMAIL can read it)."

  # --- 5. hand off to email ---
  BODY="$(cat "$OUT")"
  if command -v pbcopy >/dev/null 2>&1;   then printf '%s' "$BODY" | pbcopy;   COPIED=1
  elif command -v wl-copy >/dev/null 2>&1; then printf '%s' "$BODY" | wl-copy;  COPIED=1
  elif command -v xclip >/dev/null 2>&1;   then printf '%s' "$BODY" | xclip -selection clipboard; COPIED=1
  else COPIED=0; fi

  SUBJECT="wigamig join request"
  OPEN=""
  command -v open >/dev/null 2>&1 && OPEN="open"
  command -v xdg-open >/dev/null 2>&1 && OPEN="xdg-open"
  say ""
  if [ -n "$OPEN" ]; then
    say "Opening your email app, addressed to ${EMAIL} ..."
    $OPEN "mailto:${EMAIL}?subject=${SUBJECT}" >/dev/null 2>&1 || true
  else
    say "Email this to: ${EMAIL}   (subject: ${SUBJECT})"
  fi
  if [ "$COPIED" = 1 ]; then
    say "Your encrypted request is on the clipboard — paste it (Cmd/Ctrl-V) into"
    say "the email body, OR attach the file $OUT. Then press Send."
  else
    say "Attach the file $OUT to the email (or paste its contents), then Send."
  fi
  say ""; say "That's it — the registrar will reply."
}

main "$@"
