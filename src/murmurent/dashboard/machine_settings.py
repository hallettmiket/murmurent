"""
Purpose: Per-machine settings storage for murmurent.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-12
Input: ``~/.murmurent/machine.yaml`` (written by the dashboard's Machine
       Settings modal); falls back to the legacy ``obsidian:`` block in
       ``<lab-mgmt>/members/<handle>.md`` so existing installs keep
       working until users save once and migrate forward.
Output: A :class:`~murmurent.dashboard.contract.MachineSettings` payload
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

MACHINE_FILE = Path.home() / ".murmurent" / "machine.yaml"


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

    Resolution order: ``~/.murmurent/machine.yaml`` → legacy ``obsidian:``
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
        machine_name=data.get("machine_name") or None,
        wigamig_base=data.get("wigamig_base") or None,
        obsidian_vault_path=_pick("obsidian_vault_path", "vault_path"),
        obsidian_vault_name=_pick("obsidian_vault_name", "vault_name"),
        notebook_subfolder=_pick("notebook_subfolder", "notebook_subfolder", "lab-notebook"),
        oracle_subfolder=_pick("oracle_subfolder", "oracle_subfolder", "oracle"),
        # ``lab_base`` has no legacy source — it was previously only
        # collected per-installation. ``None`` here is fine; the
        # dashboard surfaces the install-wizard value as a fallback.
        lab_base=data.get("lab_base") or None,
    )


def _derive_vault_name(vault_path: str | None) -> str | None:
    """The vault name (for ``obsidian://`` URLs) is the last path segment.

    Always derived from the path so the UI doesn't ask the user to type the
    same string twice. Returns ``None`` if the path is empty or unset.
    """
    if not vault_path:
        return None
    # "NA" (any casing) is an explicit "no vault on this machine" marker, not a
    # real path — don't derive a bogus vault name from it.
    if str(vault_path).strip().lower() in {"na", "n/a", "none", "n.a.", "not applicable"}:
        return None
    tail = Path(str(vault_path).rstrip("/")).name
    return tail or None


def write(settings: C.MachineSettings) -> Path:
    """Persist ``settings`` to ``~/.murmurent/machine.yaml`` (creating dirs).

    Returns the path written. The on-disk format is plain YAML so a user
    can hand-edit it without going through the dashboard. The
    ``obsidian_vault_name`` is always re-derived from the path so the two
    fields stay in sync; the client may send an explicit name (legacy) but
    it's ignored.
    """
    MACHINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Undo shell-escaping / quotes people paste from a terminal, so the stored
    # path matches the real directory (and folder checks stop false-negativing).
    from ..core.preflight import clean_pasted_path as _clean
    vault_path = _clean(settings.obsidian_vault_path) or None
    base_path = _clean(settings.wigamig_base) or None
    derived_name = _derive_vault_name(vault_path)
    payload = {
        "machine_name": settings.machine_name,
        "wigamig_base": base_path,
        "obsidian_vault_path": vault_path,
        "obsidian_vault_name": derived_name,
        "notebook_subfolder": settings.notebook_subfolder,
        "oracle_subfolder": settings.oracle_subfolder,
        "lab_base": settings.lab_base,
    }
    MACHINE_FILE.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    # Mirror THIS machine's own entry to the synced per-machine registry in the
    # personal vault (issue #80). Single-writer-per-machine, conflict-free. The
    # local machine.yaml above stays the authoritative source; the mirror is for
    # persistence + the dashboard's read-only cross-machine view. Best-effort:
    # a no-op when no vault is registered, and never fails the save.
    try:
        from ..core import machine_registry as _mr

        # Mirror the cleaned/derived values (what we actually persisted), not
        # the raw request, so the synced entry matches machine.yaml.
        _mr.mirror_this_machine(C.MachineSettings(
            machine_name=settings.machine_name,
            wigamig_base=base_path,
            obsidian_vault_path=vault_path,
            obsidian_vault_name=derived_name,
            notebook_subfolder=settings.notebook_subfolder,
            oracle_subfolder=settings.oracle_subfolder,
            lab_base=settings.lab_base,
        ))
    except Exception:  # noqa: BLE001 — mirror is a convenience, never load-bearing
        pass
    return MACHINE_FILE
