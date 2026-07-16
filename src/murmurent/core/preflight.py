"""
Purpose: Shared traffic-light preflight probes for the dashboard.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-15
Input: Filesystem paths and remote host objects.
Output: ``Probe`` records that the UI renders as green/yellow/red rows.

A probe is a single check: did the folder exist, can we ssh, did the
GitHub repo exist? Each probe carries a ``status`` (``ok`` /
``warn`` / ``fail``), human-readable ``detail``, and a ``required``
flag the UI uses to decide whether to block the overall action.

Two callers today: ``POST /api/machine/settings`` (wigamig_base
subfolder creation + Obsidian vault check) and the project-approve /
workspace-initialize endpoints (repo create, collaborator sync, host
probes). Keeping the dataclass and helpers in one place means every
panel can show the same status pill style.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

# Subpaths under /data/lab_vm that must never be used as wigamig_base
# (these are the lab's protected roots; writes into them are blocked by
# the raw_guard / protected_paths hooks). Picking them as wigamig_base
# would defeat that protection by re-routing writes through murmurent.
_LAB_VM_BLOCKED_PREFIXES: tuple[str, ...] = (
    "/data/lab_vm/raw",
    "/data/lab_vm/refined",
    "/data/lab_vm/wigamig/raw",
    "/data/lab_vm/wigamig/refined",
)

# Subfolders that auto-materialize under wigamig_base when the machine
# settings are saved. Working clones of project repos live under
# ``~/repos/`` (per generic_cc convention) — *not* under wigamig_base —
# so there is no ``repos/`` subfolder here. wigamig_base is strictly
# for data + lab-shared notebooks.
MURMURENT_SUBDIRS: tuple[str, ...] = ("raw", "refined", "lab_notebooks")


@dataclass
class Probe:
    """One check + its outcome.

    ``status`` is ``ok`` (green), ``warn`` (yellow), or ``fail`` (red).
    ``required`` tells the UI whether the overall action should fail
    when this probe fails. Non-required failures show red but don't
    block.
    """

    name: str
    status: str
    detail: str
    required: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize(path: str) -> Path:
    """Expand ``~`` + ``$ENV`` and collapse trailing slashes."""
    expanded = os.path.expanduser(os.path.expandvars(path))
    return Path(expanded.rstrip("/") or expanded)


def is_lab_vm_protected(path: str | Path) -> str | None:
    """Return the matched blocked prefix if ``path`` lives under a
    protected lab-VM subtree, else ``None``.

    ``/data/lab_vm`` itself is fine — it's the parent that holds raw +
    refined alongside everything else. Only the specific protected
    subtrees are rejected.
    """
    if not path:
        return None
    target = str(_normalize(str(path)))
    for prefix in _LAB_VM_BLOCKED_PREFIXES:
        if target == prefix or target.startswith(prefix + "/"):
            return prefix
    return None


def _is_na(value: str | None) -> bool:
    """True when the user explicitly typed a not-applicable marker.

    Lets someone say "this machine has no Obsidian vault / no SSH host" on
    purpose, so the check reads as a deliberate N/A rather than a warning about
    a forgotten field.
    """
    return str(value or "").strip().lower() in {"na", "n/a", "none", "n.a.", "not applicable"}


def probe_wigamig_base(wigamig_base: str | None) -> list[Probe]:
    """Run the per-machine large-file-location checks.

    Steps (in order):
      1. ``large-file location set`` — was a value provided at all?
      2. ``not protected`` — guard against ``/data/lab_vm/raw|refined``.
      3. ``large-file location exists`` — create with mkdir -p if missing.
      4. For each of :data:`MURMURENT_SUBDIRS`: create if missing.

    Returns one ``Probe`` per step. The caller decides whether to
    abort after a failure; this helper always runs as much as it can.
    """
    probes: list[Probe] = []
    if not wigamig_base or not str(wigamig_base).strip():
        probes.append(Probe(
            name="large-file location set",
            status="fail",
            detail="No large-file location set — enter one before saving.",
            required=True,
        ))
        return probes
    probes.append(Probe(
        name="large-file location set",
        status="ok",
        detail=wigamig_base,
        required=True,
    ))

    blocked = is_lab_vm_protected(wigamig_base)
    if blocked:
        probes.append(Probe(
            name="not protected",
            status="fail",
            detail=(
                f"{wigamig_base} sits under {blocked} — the lab's read-only / "
                "write-once area. Use the parent (/data/lab_vm) or another "
                "directory and let murmurent manage raw/ + refined/ underneath."
            ),
            required=True,
        ))
        return probes
    probes.append(Probe(
        name="not protected",
        status="ok",
        detail="not under /data/lab_vm/{raw,refined}",
        required=True,
    ))

    base = _normalize(str(wigamig_base))
    probes.append(_ensure_dir(base, label="large-file location exists", required=True))

    # If base couldn't be created, skip subfolders — they'll all fail
    # for the same reason and noise drowns the actual cause.
    if probes[-1].status == "fail":
        return probes

    for sub in MURMURENT_SUBDIRS:
        probes.append(_ensure_dir(base / sub, label=sub, required=False))
    return probes


def probe_obsidian_vault(vault_path: str | None) -> Probe:
    """Check that the Obsidian vault path exists.

    The vault is **not** auto-created — Obsidian itself manages the
    directory and the user might be pointing at a yet-to-be-mounted
    iCloud Drive folder. Missing → warn (yellow), present → green.
    Empty/unset → warn telling the user notes will fall back to
    ``wigamig_base/lab_notebooks``.
    """
    if _is_na(vault_path):
        return Probe(
            name="obsidian vault",
            status="ok",
            detail="not applicable — no Obsidian vault on this machine.",
            required=False,
        )
    if not vault_path or not str(vault_path).strip():
        return Probe(
            name="obsidian vault",
            status="warn",
            detail=(
                "No vault path set — notebooks fall back to the large-file "
                "location's lab_notebooks/ folder. Enter NA if this machine "
                "has no vault."
            ),
            required=False,
        )
    target = _normalize(str(vault_path))
    if target.is_dir():
        return Probe(
            name="obsidian vault",
            status="ok",
            detail=str(target),
            required=False,
        )
    if target.exists():
        return Probe(
            name="obsidian vault",
            status="fail",
            detail=f"{target} exists but is not a directory.",
            required=False,
        )
    return Probe(
        name="obsidian vault",
        status="warn",
        detail=(
            f"{target} does not exist. Create it from Obsidian (File → New "
            "vault) — murmurent will not create vault folders on your behalf."
        ),
        required=False,
    )


def _ensure_dir(path: Path, *, label: str, required: bool) -> Probe:
    """``mkdir -p`` ``path``, returning a Probe describing what happened.

    Distinguishes three end-states for the UI:
      - green ``already exists`` — no-op
      - green ``created`` — we made it
      - red ``cannot create`` — permission denied / parent missing
    """
    try:
        if path.is_dir():
            return Probe(
                name=label,
                status="ok",
                detail=f"{path} (already exists)",
                required=required,
            )
        if path.exists():
            return Probe(
                name=label,
                status="fail",
                detail=f"{path} exists but is not a directory.",
                required=required,
            )
        path.mkdir(parents=True, exist_ok=True)
        return Probe(
            name=label,
            status="ok",
            detail=f"{path} (created)",
            required=required,
        )
    except PermissionError as exc:
        return Probe(
            name=label,
            status="fail",
            detail=f"permission denied: {path} ({exc.strerror or exc})",
            required=required,
        )
    except OSError as exc:
        return Probe(
            name=label,
            status="fail",
            detail=f"could not create {path}: {exc}",
            required=required,
        )


def overall_status(probes: list[Probe]) -> str:
    """Roll-up: ``fail`` if any required probe failed, else ``warn`` if
    any probe is warn/fail, else ``ok``.
    """
    if any(p.status == "fail" and p.required for p in probes):
        return "fail"
    if any(p.status in ("fail", "warn") for p in probes):
        return "warn"
    return "ok"
