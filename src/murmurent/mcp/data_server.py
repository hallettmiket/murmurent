"""
Purpose: Murmurent murmurent-data MCP server. Exposes the ``murmurent_data/``
         reference folder of the personal Obsidian vault and the lab-mgmt
         (group) vault as a pair of read tools, so any CC agent can Glob/Read
         arbitrary reference files (PDFs, spreadsheets, protocols, images,
         text) on demand to inform its work.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-20
Input: stdio MCP protocol (the canonical CC integration), or direct calls
       into ``tool_list`` / ``tool_read`` for the test harness.
Output: JSON-serialisable dicts the MCP client renders for the model.

Run as a server::

    python -m murmurent.mcp.data_server

The CLI never calls this server directly; ``murmurent install --hooks``
registers it under ``mcpServers`` alongside ``murmurent-oracle`` and
``murmurent-inventory``.

Design notes:
  - ``murmurent_data/`` is deliberately NOT the Oracle. The Oracle is short,
    schema-validated markdown facts (see rules/oracle_schema.md); this folder
    is arbitrary reference material with no schema. So these tools do no
    frontmatter parsing — they list + read files as-is.
  - Folder resolution mirrors the oracle server: personal from the machine's
    vault pin, lab from the lab-mgmt repo root. A missing / unregistered
    vault degrades to an empty list rather than raising (symmetric with the
    oracle server's ``_safe_*_dir`` helpers).
  - Every read stays inside the resolved ``murmurent_data/`` root — a
    path-traversal guard rejects any path that escapes it, matching how the
    other servers stay inside their roots.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from ..core import obsidian as _obsidian
from ..core import repo as _repo

# Env override so the personal murmurent_data dir is resolvable without a
# machine.yaml (tests + power users) — symmetric with the oracle server's
# MURMURENT_PERSONAL_ORACLE_DIR / MURMURENT_NOTEBOOK_DIR.
ENV_DATA = "MURMURENT_DATA_DIR"
DATA_SUBFOLDER = "murmurent_data"

VALID_VAULTS: tuple[str, ...] = ("personal", "lab")

# Extensions returned inline as text by ``data_read``; everything else is a
# binary the caller reads directly with its own file tools.
TEXT_SUFFIXES: frozenset[str] = frozenset(
    {".md", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml"}
)

# Byte cap for inline text reads — keep responses out of runaway context.
MAX_TEXT_BYTES = 1_000_000


# ---------------------------------------------------------------------------
# Folder resolution (missing vault → None, never raises)
# ---------------------------------------------------------------------------


def _dir_if_exists(p: Path) -> Path | None:
    """Return ``p`` if it exists, else ``None`` (OSError reads as absent)."""
    try:
        return p if p.exists() else None
    except OSError:
        return None


def _safe_personal_dir() -> Path | None:
    """Resolve ``<personal-vault>/murmurent_data`` on this machine.

    Fallback chain (mirrors the oracle server's tiers):
      1. ``$MURMURENT_DATA_DIR`` — explicit override, trusted verbatim.
      2. ``machine.yaml`` ``obsidian_vault_path`` + ``murmurent_data``.
      3. The most-recently-opened Obsidian vault + ``murmurent_data``.

    Returns ``None`` when no vault resolves, or the resolved dir is absent.
    """
    pin = os.environ.get(ENV_DATA, "").strip()
    if pin:
        return _dir_if_exists(Path(pin).expanduser())

    vault_root: Path | None = None
    try:
        from ..dashboard import machine_settings as _ms
        s = _ms.load()
        if s.obsidian_vault_path:
            vault_root = Path(s.obsidian_vault_path).expanduser()
    except Exception:  # noqa: BLE001 — best-effort; fall through to discovery
        pass

    if vault_root is None:
        try:
            v = _obsidian.preferred_vault()
        except Exception:  # noqa: BLE001
            v = None
        if v is None:
            return None
        vault_root = v.path

    return _dir_if_exists(vault_root / DATA_SUBFOLDER)


def _safe_lab_dir() -> Path | None:
    """Resolve ``<lab-mgmt>/murmurent_data``, or ``None`` when unresolvable."""
    try:
        root = _repo.lab_mgmt_repo_root()
    except Exception:  # noqa: BLE001
        return None
    return _dir_if_exists(root / DATA_SUBFOLDER)


def _resolve_root(vault: str) -> Path | None:
    if vault == "personal":
        return _safe_personal_dir()
    if vault == "lab":
        return _safe_lab_dir()
    raise ValueError(f"vault must be one of {VALID_VAULTS}, got {vault!r}")


# ---------------------------------------------------------------------------
# Path-traversal guard
# ---------------------------------------------------------------------------


def _safe_resolve(root: Path, relpath: str) -> Path:
    """Resolve ``relpath`` under ``root``, refusing anything that escapes it.

    Accepts a path relative to ``root`` (the shape ``data_list`` emits) or an
    absolute path that already lives under ``root``. Raises ``ValueError`` on
    a traversal attempt so a malicious/relative ``..`` can't read outside the
    reference folder."""
    root = root.resolve()
    candidate = Path(relpath)
    target = (candidate if candidate.is_absolute() else root / candidate).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"path escapes murmurent_data root: {relpath!r}")
    return target


# ---------------------------------------------------------------------------
# Tools (also called directly by tests)
# ---------------------------------------------------------------------------


def tool_list(vault: str = "personal") -> list[dict[str, Any]]:
    """List every file under the resolved ``murmurent_data/`` for ``vault``.

    ``vault`` is ``"personal"`` (default) or ``"lab"``. Each row carries the
    path relative to the folder root, its size in bytes, and its extension.
    A missing / unregistered vault degrades to an empty list.
    """
    root = _resolve_root(vault)
    if root is None or not root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    try:
        for f in sorted(root.rglob("*")):
            if not f.is_file() or f.name == ".gitkeep":
                continue
            try:
                size = f.stat().st_size
            except OSError:
                continue
            rows.append({
                "path": str(f.relative_to(root)),
                "size_bytes": size,
                "type": f.suffix.lower().lstrip("."),
            })
    except (OSError, PermissionError):
        # A sandbox / Full-Disk-Access denial reads as an empty folder rather
        # than crashing the whole tool.
        return rows
    return rows


def tool_read(path: str, vault: str = "personal") -> dict[str, Any]:
    """Read one file from ``murmurent_data/``.

    For a text-like file (``.md/.txt/.csv/.tsv/.json/.yaml/.yml``) return its
    text content, capped at :data:`MAX_TEXT_BYTES` with a truncation note. For
    a binary file (PDF, image, xlsx, …) return its absolute path + metadata and
    a note that the caller should open it directly with its own file tools.

    ``path`` may be relative to the folder root (the shape ``data_list``
    emits) or an absolute path under it; anything escaping the root is refused.
    """
    root = _resolve_root(vault)
    if root is None or not root.is_dir():
        return {"ok": False, "error": f"no murmurent_data folder for vault {vault!r} "
                                      "on this machine"}
    try:
        target = _safe_resolve(root, path)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    if not target.is_file():
        return {"ok": False, "error": f"file not found: {path}"}
    try:
        size = target.stat().st_size
    except OSError as exc:
        return {"ok": False, "error": str(exc)}

    relpath = str(target.relative_to(root))
    suffix = target.suffix.lower()
    if suffix not in TEXT_SUFFIXES:
        return {
            "ok": True,
            "vault": vault,
            "path": relpath,
            "abs_path": str(target),
            "size_bytes": size,
            "type": suffix.lstrip("."),
            "is_text": False,
            "note": ("binary / non-text reference file — open it directly with "
                     "your own file tools using abs_path."),
        }

    try:
        raw = target.read_bytes()
    except (OSError, PermissionError) as exc:
        return {"ok": False, "error": str(exc)}
    truncated = len(raw) > MAX_TEXT_BYTES
    text = raw[:MAX_TEXT_BYTES].decode("utf-8", errors="replace")
    result: dict[str, Any] = {
        "ok": True,
        "vault": vault,
        "path": relpath,
        "abs_path": str(target),
        "size_bytes": size,
        "type": suffix.lstrip("."),
        "is_text": True,
        "content": text,
        "truncated": truncated,
    }
    if truncated:
        result["note"] = (f"content truncated to first {MAX_TEXT_BYTES} bytes of "
                          f"{size}; read the file directly with abs_path for the rest.")
    return result


# ---------------------------------------------------------------------------
# MCP server wiring (lazy SDK import; only needed to run as server)
# ---------------------------------------------------------------------------


def _build_server():  # pragma: no cover - exercised only when mcp is installed
    """Construct the MCP server. Imports the SDK lazily."""
    from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]

    server = FastMCP(
        name="murmurent-data",
        instructions=(
            "Murmurent reference-file store. Lists + reads arbitrary files "
            "under a vault's `murmurent_data/` folder (PDFs, spreadsheets, "
            "protocols, images, text) — NOT the Oracle, and NOT "
            "schema-validated. Two vaults: `personal` (your Obsidian vault "
            "`murmurent_data/`, default) and `lab` (lab-mgmt repo "
            "`murmurent_data/`). `data_list(vault)` returns each file's "
            "relative path, size, and type. `data_read(path, vault)` returns "
            "text for text-like files (byte-capped) or, for binaries, the "
            "absolute path + metadata so you open them with your own file "
            "tools. A missing/unregistered vault lists empty."
        ),
    )

    @server.tool(name="data_list",
                 description="List files under a vault's murmurent_data/ (personal|lab).")
    def _list(vault: str = "personal") -> str:
        return json.dumps(tool_list(vault))

    @server.tool(name="data_read",
                 description="Read one murmurent_data/ file: text inline (capped) or "
                             "abs-path metadata for binaries. Path-traversal guarded.")
    def _read(path: str, vault: str = "personal") -> str:
        return json.dumps(tool_read(path, vault=vault))

    return server


def main() -> int:  # pragma: no cover - run only as MCP server
    server = _build_server()
    server.run()
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())


__all__ = [
    "ENV_DATA", "DATA_SUBFOLDER", "VALID_VAULTS", "TEXT_SUFFIXES",
    "MAX_TEXT_BYTES", "tool_list", "tool_read",
]
