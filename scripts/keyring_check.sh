#!/usr/bin/env bash
#
# keyring_check.sh — verify a machine's murmurent keyring setup.
#
# Thin wrapper around `murmurent keyring check`: confirms age is installed, this
# machine has an identity, it is authorised, every entitled secret opens and is
# unpacked, and every box it is NOT entitled to is refused. Exits 0 when healthy,
# non-zero otherwise — so it is safe to run from cron or a CI job on a server.
#
# Usage:
#   scripts/keyring_check.sh            # pull first, then check
#   scripts/keyring_check.sh --no-pull  # check the local state only
#
set -euo pipefail

if ! command -v murmurent >/dev/null 2>&1; then
  echo "✗ murmurent is not installed / not on PATH" >&2
  exit 2
fi

echo "== murmurent keyring health check =="
exec murmurent keyring check "$@"
