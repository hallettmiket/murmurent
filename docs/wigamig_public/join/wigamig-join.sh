#!/usr/bin/env sh
# Encrypt your filled join-form.txt to a wigamig registrar's public key and
# produce join-request.age — an encrypted file you then email to the registrar.
# Only the registrar can read it. Needs `age` (https://age-encryption.org).
#
# Usage:
#   ./wigamig-join.sh [form-file] [age-recipient]
# With no args it uses ./join-form.txt and prompts for the recipient.
set -eu

FORM="${1:-join-form.txt}"
RECIPIENT="${2:-}"

if ! command -v age >/dev/null 2>&1; then
  echo "Please install age first: https://age-encryption.org  (e.g. 'brew install age')" >&2
  exit 1
fi
if [ ! -f "$FORM" ]; then
  echo "form not found: $FORM  (download join-form.txt and fill it in)" >&2
  exit 1
fi
if [ -z "$RECIPIENT" ]; then
  printf "Paste the registrar's age recipient (age1... from the directory): "
  read -r RECIPIENT
fi
case "$RECIPIENT" in
  age1*) : ;;
  *) echo "that doesn't look like an age recipient (should start with age1...)" >&2; exit 1 ;;
esac

age -a -r "$RECIPIENT" -o join-request.age "$FORM"
echo "✓ wrote join-request.age"
echo "Now email join-request.age to the registrar's address from the directory."
echo "It's encrypted — only the registrar can read it."
