"""
Purpose: Per-machine settings storage for wigamig.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-12
Input: ``~/.wigamig/machine.yaml`` (written by the dashboard's Machine
       Settings modal); falls back to the legacy ``obsidian:`` block in
       ``<lab-mgmt>/members/<handle>.md`` so existing installs keep
       working until users save once and migrate forward.
Output: A :class:`~wigamig.dashboard.contract.MachineSettings` payload
        for the dashboard contract, and a writer for the same path.

The point of this module is to keep per-machine paths (where Obsidian
lives on *this* laptop) out of the git-synced ``lab-mgmt`` repo. The
member profile in lab-mgmt follows the user across machines; this file
does not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from . import contract as C

MACHINE_FILE = Path.home() / ".wigamig" / "machine.yaml"


def _read_yaml(path: Path) -> dict[str, Any]:
    """Best-effort read; return ``{}`` on missing or malformed files."""
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def load(*, legacy_obsidian: dict | None = None) -> C.MachineSettings:
    """Return the current machine settings.

    Resolution order: ``~/.wigamig/machine.yaml`` → legacy ``obsidian:``
    block on the member profile (one-time migration on first save). The
    key names differ between the two sources because the legacy block
    lived under an ``obsidian:`` parent and used short keys; this helper
    bridges them.
    """
    data = _read_yaml(MACHINE_FILE)
    legacy = legacy_obsidian or {}

    def _pick(machine_key: str, legacy_key: str, default: Any = None) -> Any:
        value = data.get(machine_key)
        if value not in (None, ""):
            return value
        value = legacy.get(legacy_key)
        if value not in (None, ""):
            return value
        return default

    return C.MachineSettings(
        obsidian_vault_path=_pick("obsidian_vault_path", "vault_path"),
        obsidian_vault_name=_pick("obsidian_vault_name", "vault_name"),
        notebook_subfolder=_pick("notebook_subfolder", "notebook_subfolder", "lab-notebook"),
        oracle_subfolder=_pick("oracle_subfolder", "oracle_subfolder", "oracle"),
        # ``lab_base`` has no legacy source — it was previously only
        # collected per-installation. ``None`` here is fine; the
        # dashboard surfaces the install-wizard value as a fallback.
        lab_base=data.get("lab_base") or None,
    )


def write(settings: C.MachineSettings) -> Path:
    """Persist ``settings`` to ``~/.wigamig/machine.yaml`` (creating dirs).

    Returns the path written. The on-disk format is plain YAML so a user
    can hand-edit it without going through the dashboard.
    """
    MACHINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "obsidian_vault_path": settings.obsidian_vault_path,
        "obsidian_vault_name": settings.obsidian_vault_name,
        "notebook_subfolder": settings.notebook_subfolder,
        "oracle_subfolder": settings.oracle_subfolder,
        "lab_base": settings.lab_base,
    }
    MACHINE_FILE.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return MACHINE_FILE
