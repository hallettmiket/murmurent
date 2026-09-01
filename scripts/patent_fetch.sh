#!/usr/bin/env bash
# Purpose: Cached, IP-rate-limited fetcher for patent sources. Safe to call from
#          several lawyer agents at once -- they share one request budget through
#          a lock file, because the rate limit is per-IP and the agents are not
#          aware of each other.
# Author:  Mike Hallett (with Claude Code)
# Usage:   scripts/patent_fetch.sh <url> <cache-key> [min-interval-seconds]
# Output:  path to the cached file on stdout; HTTP status on stderr.
set -uo pipefail

URL="${1:?usage: patent_fetch.sh <url> <cache-key> [min-interval]}"
KEY="${2:?cache key, e.g. us9968579.pdf}"
# Per-host default gap. Google Patents is the only source that blocks under load
# (503, ~1h to recover) and its budget is shared by every agent on this machine,
# so it gets a much wider gap than the sources that never refuse.
case "$1" in
  *patents.google.com*) DEFAULT_INTERVAL=30 ;;
  *)                    DEFAULT_INTERVAL=6  ;;
esac
MIN_INTERVAL="${3:-$DEFAULT_INTERVAL}"      # seconds between requests to one host

CACHE="${MURMURENT_LAWYER_CACHE:-$HOME/.murmurent/lawyer_cache}"
mkdir -p "$CACHE"
OUT="$CACHE/$KEY"

# 1. Cache hit -- patent documents are immutable, so never re-fetch one.
if [ -s "$OUT" ]; then echo "$OUT"; echo "cache-hit" >&2; exit 0; fi

# 2. Shared per-host throttle. flock serialises every agent on this machine.
HOST=$(printf '%s' "$URL" | awk -F/ '{print $3}')
LOCK="$CACHE/.lock.$HOST"; STAMP="$CACHE/.last.$HOST"
exec 9>"$LOCK"
flock 9
now=$(date +%s); last=$(cat "$STAMP" 2>/dev/null || echo 0)
wait=$(( MIN_INTERVAL - (now - last) ))
[ "$wait" -gt 0 ] && sleep "$wait"
date +%s > "$STAMP"

UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
code=$(curl -sL -A "$UA" --max-time 45 -o "$OUT.part" -w '%{http_code}' "$URL")
flock -u 9

# 3. A block is not a document. Never cache one -- it would poison the cache.
if [ "$code" = "200" ] && [ -s "$OUT.part" ]; then
  mv "$OUT.part" "$OUT"; echo "$OUT"; echo "$code" >&2; exit 0
fi
rm -f "$OUT.part"
echo "$code" >&2
exit 22
