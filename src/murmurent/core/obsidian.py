"""
Purpose: Discover the user's registered Obsidian vaults so murmurent can
         put notebook files where Obsidian already knows about them
         (instead of a freestanding ~/lab-notebook/ directory whose
         ``obsidian://`` URL would silently fail).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: Obsidian's ``obsidian.json`` registry. Path varies per OS:
       macOS:   ~/Library/Application Support/obsidian/obsidian.json
       Linux:   ~/.config/obsidian/obsidian.json
       Windows: %APPDATA%/obsidian/obsidian.json (not implemented)
Output: ``Vault`` dataclasses + ``preferred_vault()`` picker.

Resolution order for the *preferred* vault:
  1. ``$WIGAMIG_OBSIDIAN_VAULT`` — match by vault name (case-sensitive).
  2. The most-recently-opened vault (``ts`` field, descending).
  3. None when the registry is missing or has no vaults.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Vault:
    """One Obsidian vault, normalised."""

    name: str
    path: Path
    ts: int  # last-opened millis since epoch

    @property
    def url_safe_name(self) -> str:
        """The string used in ``obsidian://open?vault=...`` URLs."""
        return self.name


def registry_path() -> Path | None:
    """Return the platform-appropriate obsidian.json path, or ``None``."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    if sys.platform.startswith("linux"):
        return Path.home() / ".config" / "obsidian" / "obsidian.json"
    return None


def discover_vaults() -> list[Vault]:
    """Read obsidian.json and return every registered vault.

    Returns an empty list if the registry is missing or unparseable.
    """
    cfg = registry_path()
    if cfg is None or not cfg.is_file():
        return []
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    raw = data.get("vaults") or {}
    if not isinstance(raw, dict):
        return []
    out: list[Vault] = []
    for entry in raw.values():
        if not isinstance(entry, dict):
            continue
        path_str = entry.get("path")
        if not path_str:
            continue
        path = Path(path_str)
        out.append(Vault(name=path.name, path=path, ts=int(entry.get("ts") or 0)))
    out.sort(key=lambda v: v.ts, reverse=True)
    return out


def preferred_vault() -> Vault | None:
    """Pick the user's preferred vault.

    ``$WIGAMIG_OBSIDIAN_VAULT`` (vault name) wins; otherwise the
    most-recently-opened vault.
    """
    vaults = discover_vaults()
    if not vaults:
        return None
    pin = os.environ.get("WIGAMIG_OBSIDIAN_VAULT", "").strip()
    if pin:
        for v in vaults:
            if v.name == pin:
                return v
        # If pinned name doesn't match any registered vault, fall back
        # rather than failing — the user will see the wrong vault open
        # and can correct the env var.
    return vaults[0]


def vault_for_path(path: Path, *, vaults: list[Vault] | None = None) -> Vault | None:
    """Return the vault that contains ``path`` (or ``None``).

    Used to decide whether to use the ``obsidian://`` URL for a given
    file or to fall through to a different editor.
    """
    if vaults is None:
        vaults = discover_vaults()
    target = path.resolve()
    best: Vault | None = None
    best_len = -1
    for v in vaults:
        try:
            target.relative_to(v.path.resolve())
        except ValueError:
            continue
        # Prefer the deepest matching vault (in case of nested paths).
        L = len(str(v.path.resolve()))
        if L > best_len:
            best, best_len = v, L
    return best


def relative_inside_vault(path: Path, vault: Vault) -> str | None:
    """Return ``path``'s location relative to ``vault.path``, no ``.md``.

    The relative path is suitable for an ``obsidian://open?file=…`` URL.
    Returns ``None`` if ``path`` is not inside the vault.
    """
    try:
        rel = path.resolve().relative_to(vault.path.resolve())
    except ValueError:
        return None
    s = rel.as_posix()
    if s.endswith(".md"):
        s = s[:-3]
    return s
