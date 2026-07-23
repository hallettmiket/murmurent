"""
Purpose: Per-machine synced registry mirror (issue #80, machine-config
simplification).

Each murmurent install resolves its own configuration LOCALLY and
authoritatively from ``~/.murmurent/machine.yaml`` (``save_machine_settings``).
On save, the machine *also* mirrors its OWN entry to the personal vault at
``<vault>/machines/<machine_id>.yaml``. Because every machine writes exactly
one file — its own — the files are disjoint and the mirror is conflict-free
(single-writer-per-machine within the single-writer-per-person vault). Reading
the cross-machine view = reading every ``<vault>/machines/*.yaml``.

This is *not* a config source: no machine ever resolves its paths from another
machine's mirror. The mirror exists purely for persistence + the dashboard's
read-only cross-machine VIEW (which foreign machines you own + where their
vaults/data roots live), replacing the retired foreign-machine param editor.

``"machines"`` is in :data:`vault_provision.MURMURENT_TRACKED_FOLDERS`, so the
folder syncs to the member's GitHub via ``vault_sync`` like ``oracle/`` etc.
Degrades gracefully: when no personal vault is registered on this machine the
mirror write is a no-op (``None``) and callers fall back to ``machine.yaml`` /
the hostname.
"""

from __future__ import annotations

import os
import platform
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

#: Folder under the personal vault holding one YAML per machine the member owns.
VAULT_MACHINES_SUBDIR = "machines"

#: Test/override pin for the vault machines dir (mirrors the agents-dir pins).
ENV_MACHINES_DIR = "MURMURENT_VAULT_MACHINES_DIR"

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def _short_hostname() -> str:
    """This machine's bare hostname (no domain), best-effort."""
    try:
        full = socket.gethostname()
    except OSError:
        full = platform.node() or ""
    return (full.split(".", 1)[0] if full else "").strip()


def _slug(value: str) -> str:
    """Filesystem-safe id slug: lowercase, ``[a-z0-9_-]`` only."""
    s = _SLUG_RE.sub("-", str(value).strip().lower()).strip("-_")
    return s or "local"


def machine_id(settings: Any | None = None) -> str:
    """A stable, filesystem-safe id for THIS machine.

    Prefers the user-chosen friendly name (``machine.yaml:machine_name``) so a
    renamed laptop keeps a readable file; falls back to the OS short hostname.
    Slugified so it is safe as a filename. ``settings`` may be a
    :class:`~murmurent.dashboard.contract.MachineSettings` (or any object with a
    ``machine_name`` attr); when omitted it is loaded from ``machine.yaml``.
    """
    name = ""
    if settings is not None:
        name = (getattr(settings, "machine_name", "") or "").strip()
    if not name:
        try:
            from ..dashboard import machine_settings as _ms  # deferred: optional dep

            name = (_ms.load().machine_name or "").strip()
        except Exception:  # noqa: BLE001 — no machine.yaml yet → hostname
            name = ""
    return _slug(name or _short_hostname())


def vault_machines_dir() -> Path | None:
    """``<vault>/machines/`` on this machine, or ``None`` when no vault is
    registered. ``$MURMURENT_VAULT_MACHINES_DIR`` overrides (for tests)."""
    pin = os.environ.get(ENV_MACHINES_DIR, "").strip()
    if pin:
        return Path(pin).expanduser()
    try:
        from . import vault_sync as _vs  # deferred: optional dashboard dep

        root = _vs.personal_vault_root()
    except Exception:  # noqa: BLE001
        root = None
    if root is None:
        return None
    return Path(root).expanduser() / VAULT_MACHINES_SUBDIR


def _entry_from_settings(settings: Any) -> dict[str, Any]:
    """The mirrored YAML body for this machine's own entry."""
    mid = machine_id(settings)
    return {
        "machine_id": mid,
        "machine_name": (getattr(settings, "machine_name", "") or "") or mid,
        "hostname": _short_hostname(),
        "platform": platform.system().lower(),
        "wigamig_base": getattr(settings, "wigamig_base", None) or None,
        "obsidian_vault_path": getattr(settings, "obsidian_vault_path", None) or None,
        "oracle_subfolder": getattr(settings, "oracle_subfolder", None) or "oracle",
        "notebook_subfolder": getattr(settings, "notebook_subfolder", None) or "lab-notebook",
        "lab_base": getattr(settings, "lab_base", None) or None,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def mirror_this_machine(settings: Any) -> Path | None:
    """Write THIS machine's own entry to ``<vault>/machines/<machine_id>.yaml``.

    Best-effort + non-raising: returns the path written, or ``None`` when there
    is nowhere to mirror to. Never touches another machine's file —
    single-writer-per-machine.

    Existence guard: when resolving the real personal vault, we only write if
    the vault root already exists on disk — we must NOT materialise a
    not-yet-cloned vault dir (that would fool ``vault_info``'s "no clone"
    probe). An explicit ``$MURMURENT_VAULT_MACHINES_DIR`` pin bypasses the
    guard (tests, or a deliberate override).
    """
    pin = os.environ.get(ENV_MACHINES_DIR, "").strip()
    if pin:
        d: Path | None = Path(pin).expanduser()
    else:
        try:
            from . import vault_sync as _vs  # deferred: optional dashboard dep

            root = _vs.personal_vault_root()
        except Exception:  # noqa: BLE001
            root = None
        # No vault registered, or the clone isn't on disk yet → nothing to do.
        if root is None or not Path(root).expanduser().is_dir():
            return None
        d = Path(root).expanduser() / VAULT_MACHINES_SUBDIR
    if d is None:
        return None
    try:
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{machine_id(settings)}.yaml"
        path.write_text(
            yaml.safe_dump(_entry_from_settings(settings), sort_keys=False,
                           allow_unicode=True),
            encoding="utf-8",
        )
        return path
    except OSError:
        return None


def read_registry() -> list[dict[str, Any]]:
    """Every mirrored machine entry (``<vault>/machines/*.yaml``), newest first.

    Read-only; tolerant of malformed files (skipped). Returns ``[]`` when no
    vault is registered or the folder is empty — the dashboard renders that as
    "no other machines mirrored yet".
    """
    d = vault_machines_dir()
    if d is None or not d.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for p in sorted(d.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict):
            data.setdefault("machine_id", p.stem)
            out.append(data)
    out.sort(key=lambda e: str(e.get("updated") or ""), reverse=True)
    return out


__all__ = [
    "VAULT_MACHINES_SUBDIR",
    "ENV_MACHINES_DIR",
    "machine_id",
    "vault_machines_dir",
    "mirror_this_machine",
    "read_registry",
]
