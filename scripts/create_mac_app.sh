#!/usr/bin/env bash
# Purpose: Create "Murmurent Dashboard.app" in ~/Applications. Kept so older
#          instructions still work; the work is done by `murmurent launcher`
#          (issue #156), which also works for a PyPI install.
# Author:  Mike Hallett
# Date:    2026-05-11 (reduced to a wrapper 2026-10-14)
# Usage:   bash scripts/create_mac_app.sh
exec murmurent launcher "$@"
