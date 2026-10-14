#!/usr/bin/env bash
# Purpose: Create the "Murmurent Dashboard" applications-menu entry. Kept so older
#          instructions still work; the work is done by `murmurent launcher`
#          (issue #156), which also works for a PyPI install.
# Author:  Mike Hallett
# Date:    2026-07-14 (reduced to a wrapper 2026-10-14)
# Usage:   bash scripts/create_linux_launcher.sh
exec murmurent launcher "$@"
