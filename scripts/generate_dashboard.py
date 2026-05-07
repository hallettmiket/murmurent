"""
Purpose: Regenerate per-member dashboard snapshots into ``lab-mgmt/dashboards/``.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: All local project repos + the lab-mgmt repo.
Output: ``<lab-mgmt>/dashboards/<handle>.md`` for every member listed in
        ``<lab-mgmt>/members/``. Idempotent.

Run as ``python scripts/generate_dashboard.py``. Also invoked by the
GitHub Action ``.github/workflows/dashboard.yml`` on every PR merge to main.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from wigamig.commands import dashboard_cmd  # noqa: E402


def main() -> int:
    targets = dashboard_cmd.cmd_generate_all()
    if not targets:
        print("[dashboard] no member files found in lab-mgmt/members/")
        return 0
    for path in targets:
        print(f"[dashboard] wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
