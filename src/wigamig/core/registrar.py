"""
Purpose: Registrar — the administrative layer above any single lab.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-12
Input: ``~/.wigamig/registrar`` (sentinel containing the registrar's
       Western netname), ``$WIGAMIG_LAB_INFO_ROOT`` (default
       ``~/.wigamig/lab_info/``), and per-lab ``lab.md`` files at
       the paths declared in ``_registry.yaml``.
Output: Helpers for identity (``is_registrar``) and registry I/O
        (``read_registry``, ``write_registry``) plus dataclasses for
        the rows the dashboard renders.

The registrar tracks labs, cores, and collaborations across a
bioconvergence centre. It is intentionally a thin layer:
``_registry.yaml`` is just an index; the authoritative source for each
lab is still that lab's own ``lab.md`` + ``lab-mgmt`` repo. The
registrar follows pointers from the registry to read each lab's
metadata at request time.

Phase A is **read-only** — no create/archive operations land here.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class RegistrarError(ValueError):
    """Base class for registrar invariant violations."""


class LabAlreadyExists(RegistrarError):
    """Refused: a lab with this short ID is already registered."""


class PIAlreadyLeadsAnother(RegistrarError):
    """Refused: this PI handle already leads another lab or core."""


class InvalidLabName(RegistrarError):
    """Refused: lab name violates the alphanumeric + underscore rule."""


class LabNotFound(RegistrarError):
    """Refused: no lab with that short ID is registered."""

# -----------------------------------------------------------------
# Identity
# -----------------------------------------------------------------

REGISTRAR_SENTINEL = Path.home() / ".wigamig" / "registrar"
LAB_INFO_ENV_VAR = "WIGAMIG_LAB_INFO_ROOT"
DEFAULT_LAB_INFO_ROOT = Path.home() / ".wigamig" / "lab_info"
REGISTRY_FILENAME = "_registry.yaml"


def lab_info_root(env: dict[str, str] | None = None) -> Path:
    """Return the registrar's data root.

    Production setting: ``/data/lab_info/``. Development default:
    ``~/.wigamig/lab_info/``. Override via ``$WIGAMIG_LAB_INFO_ROOT``.
    """
    source = os.environ if env is None else env
    return Path(source.get(LAB_INFO_ENV_VAR, DEFAULT_LAB_INFO_ROOT)).expanduser()


def registry_path(env: dict[str, str] | None = None) -> Path:
    """Return ``<lab_info_root>/_registry.yaml``."""
    return lab_info_root(env) / REGISTRY_FILENAME


def _normalize(handle: str) -> str:
    return handle.strip().lstrip("@").lower()


def registrar_handle() -> str | None:
    """Return the registrar's handle from ``~/.wigamig/registrar``, or ``None``.

    The file contains exactly the Western netname on the first non-blank
    line. Absent file means no one on this machine has been declared
    the registrar yet — every ``is_registrar`` check then returns False.
    """
    if not REGISTRAR_SENTINEL.is_file():
        return None
    try:
        text = REGISTRAR_SENTINEL.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return _normalize(stripped)
    return None


def is_registrar(handle: str) -> bool:
    """Return True iff ``handle`` matches the declared registrar."""
    declared = registrar_handle()
    if declared is None:
        return False
    return _normalize(handle) == declared


# -----------------------------------------------------------------
# Registry data model + I/O
# -----------------------------------------------------------------


@dataclass(frozen=True)
class LabEntry:
    """One lab in ``_registry.yaml``."""

    name: str                              # short ID, e.g. "hallett"
    pi: str                                # ``@handle``
    lab_mgmt_path: str                     # filesystem path to the lab-mgmt repo
    status: str = "active"                 # "active" | "archived"
    created: str | None = None
    slack_workspace: str | None = None
    github_org: str | None = None
    oracle_vault: str | None = None


@dataclass(frozen=True)
class CoreEntry:
    """One core facility in ``_registry.yaml``. Phase E will add fields."""

    name: str
    pi: str
    lab_mgmt_path: str
    status: str = "active"
    created: str | None = None


@dataclass(frozen=True)
class CollaborationEntry:
    """One cross-lab collaboration in ``_registry.yaml``."""

    name: str
    pis: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    member_subset: dict[str, list[str]] = field(default_factory=dict)
    oracle_vault: str | None = None
    status: str = "active"
    created: str | None = None


@dataclass(frozen=True)
class Registry:
    """The whole registry — what the registrar reads to render the dashboard."""

    labs: list[LabEntry] = field(default_factory=list)
    cores: list[CoreEntry] = field(default_factory=list)
    collaborations: list[CollaborationEntry] = field(default_factory=list)


def _coerce_lab(name: str, data: dict[str, Any]) -> LabEntry:
    return LabEntry(
        name=name,
        pi=str(data.get("pi") or ""),
        lab_mgmt_path=str(data.get("lab_mgmt_path") or ""),
        status=str(data.get("status") or "active"),
        created=_opt_str(data.get("created")),
        slack_workspace=_opt_str(data.get("slack_workspace")),
        github_org=_opt_str(data.get("github_org")),
        oracle_vault=_opt_str(data.get("oracle_vault")),
    )


def _coerce_core(name: str, data: dict[str, Any]) -> CoreEntry:
    return CoreEntry(
        name=name,
        pi=str(data.get("pi") or ""),
        lab_mgmt_path=str(data.get("lab_mgmt_path") or ""),
        status=str(data.get("status") or "active"),
        created=_opt_str(data.get("created")),
    )


def _coerce_collab(name: str, data: dict[str, Any]) -> CollaborationEntry:
    pis = data.get("pis") or []
    groups = data.get("groups") or []
    member_subset = data.get("member_subset") or {}
    return CollaborationEntry(
        name=name,
        pis=list(pis) if isinstance(pis, list) else [],
        groups=list(groups) if isinstance(groups, list) else [],
        member_subset=dict(member_subset) if isinstance(member_subset, dict) else {},
        oracle_vault=_opt_str(data.get("oracle_vault")),
        status=str(data.get("status") or "active"),
        created=_opt_str(data.get("created")),
    )


def _opt_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def read_registry(env: dict[str, str] | None = None) -> Registry:
    """Load ``_registry.yaml`` and coerce into a :class:`Registry`.

    Missing file returns an empty :class:`Registry` — that's the
    legitimate "fresh install, no labs yet" state, not an error.
    Malformed sections are silently skipped (one bad lab shouldn't
    blank the whole registrar dashboard).
    """
    path = registry_path(env)
    if not path.is_file():
        return Registry()
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return Registry()
    if not isinstance(data, dict):
        return Registry()

    labs_dict = data.get("labs") or {}
    cores_dict = data.get("cores") or {}
    collabs_dict = data.get("collaborations") or {}

    def _walk(group: Any, coerce):
        out = []
        if not isinstance(group, dict):
            return out
        for name, payload in group.items():
            if not isinstance(payload, dict):
                continue
            try:
                out.append(coerce(str(name), payload))
            except Exception:
                continue
        return out

    return Registry(
        labs=_walk(labs_dict, _coerce_lab),
        cores=_walk(cores_dict, _coerce_core),
        collaborations=_walk(collabs_dict, _coerce_collab),
    )


def write_registry(reg: Registry, env: dict[str, str] | None = None) -> Path:
    """Serialise ``reg`` to ``_registry.yaml``. Creates parent dirs.

    Phase A doesn't expose a write endpoint, but tests and the bootstrap
    helper use this to seed the registry on a fresh install.
    """
    path = registry_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"version": 1, "labs": {}, "cores": {}, "collaborations": {}}
    for lab in reg.labs:
        payload["labs"][lab.name] = {
            k: v for k, v in {
                "pi": lab.pi,
                "lab_mgmt_path": lab.lab_mgmt_path,
                "status": lab.status,
                "created": lab.created,
                "slack_workspace": lab.slack_workspace,
                "github_org": lab.github_org,
                "oracle_vault": lab.oracle_vault,
            }.items() if v is not None
        }
    for core in reg.cores:
        payload["cores"][core.name] = {
            k: v for k, v in {
                "pi": core.pi,
                "lab_mgmt_path": core.lab_mgmt_path,
                "status": core.status,
                "created": core.created,
            }.items() if v is not None
        }
    for col in reg.collaborations:
        payload["collaborations"][col.name] = {
            k: v for k, v in {
                "pis": col.pis or None,
                "groups": col.groups or None,
                "member_subset": col.member_subset or None,
                "oracle_vault": col.oracle_vault,
                "status": col.status,
                "created": col.created,
            }.items() if v is not None
        }
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


# -----------------------------------------------------------------
# Bootstrap helper — Phase A migration of an existing single-lab install
# -----------------------------------------------------------------


def bootstrap_from_existing_lab_mgmt(
    *,
    lab_mgmt_path: Path | str,
    pi: str | None = None,
    env: dict[str, str] | None = None,
) -> Registry:
    """Seed ``_registry.yaml`` with a pointer to an existing lab-mgmt repo.

    Reads ``<lab_mgmt_path>/lab.md`` to fill in name, PI, etc. This is
    the one-shot migration path for a pre-Phase-16 install whose entire
    universe is one lab — it lets the registrar dashboard light up
    without scaffolding a brand-new ``/data/lab_info/`` layout from
    scratch. Idempotent: re-running with the same lab does not
    duplicate the entry, just refreshes it.
    """
    from .frontmatter import parse_file

    lab_path = Path(lab_mgmt_path).expanduser()
    lab_file = lab_path / "lab.md"
    if not lab_file.is_file():
        raise FileNotFoundError(f"no lab.md at {lab_file}")
    meta = parse_file(lab_file).meta or {}
    name = str(meta.get("lab") or lab_path.name.replace("-lab-mgmt", "")).strip()
    resolved_pi = pi or str(meta.get("pi") or "").strip()
    if not name:
        raise ValueError(f"could not determine lab name from {lab_file}")

    existing = read_registry(env)
    other_labs = [l for l in existing.labs if l.name != name]
    other_labs.append(
        LabEntry(
            name=name,
            pi=resolved_pi,
            lab_mgmt_path=str(lab_path),
            status="active",
            created=_opt_str(meta.get("created")),
            slack_workspace=_opt_str(meta.get("slack_workspace")),
            github_org=_opt_str(meta.get("github_org")),
            oracle_vault=_opt_str(meta.get("lab_oracle_vault")),
        )
    )
    reg = Registry(labs=other_labs, cores=existing.cores, collaborations=existing.collaborations)
    write_registry(reg, env)
    return reg


# -----------------------------------------------------------------
# Git-backed audit trail for the registrar data directory
# -----------------------------------------------------------------


def _git_init_if_needed(root: Path) -> None:
    """Idempotent ``git init -b main`` on ``root``.

    The registrar's data directory is its own git repo (separate from
    the wigamig code repo). Every mutation auto-commits so the centre
    has a cryptographic audit trail of who created / archived which lab
    when, with no extra effort. Push to a private remote when ready.
    """
    if (root / ".git").is_dir():
        return
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", "main"], cwd=str(root),
        check=False, capture_output=True,
    )
    # Best-effort identity if the user has no global git config.
    handle = registrar_handle() or "wigamig-registrar"
    for cfg in (("user.name", f"wigamig registrar ({handle})"),
                ("user.email", f"{handle}@wigamig.local")):
        # Only set repo-local if not already inherited from global.
        existing = subprocess.run(
            ["git", "-C", str(root), "config", "--get", cfg[0]],
            check=False, capture_output=True,
        )
        if existing.returncode != 0 or not existing.stdout.strip():
            subprocess.run(
                ["git", "-C", str(root), "config", cfg[0], cfg[1]],
                check=False, capture_output=True,
            )


def _git_commit_all(root: Path, message: str) -> None:
    """Stage every change in ``root`` and commit. Silent if nothing changed.

    Best-effort: never raises. A failed audit commit must not break
    the user-visible operation it was recording.
    """
    try:
        subprocess.run(
            ["git", "-C", str(root), "add", "-A"],
            check=False, capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(root), "commit", "-m", message],
            check=False, capture_output=True,
        )
    except OSError:
        pass


# -----------------------------------------------------------------
# Phase B: create_lab
# -----------------------------------------------------------------


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _normalize_pi(handle: str) -> str:
    """Return ``@<lowered, stripped, no leading @>``."""
    stripped = handle.strip().lstrip("@").lower()
    return f"@{stripped}" if stripped else ""


def _enforce_create_invariants(
    *,
    name: str,
    pi_at: str,
    existing: Registry,
) -> None:
    if not name or not _NAME_RE.match(name):
        raise InvalidLabName(
            f"lab name must be lowercase alphanumeric + underscore, "
            f"starting with a letter; got {name!r}"
        )
    if any(l.name == name for l in existing.labs):
        raise LabAlreadyExists(f"lab already registered: {name}")
    if any(c.name == name for c in existing.cores):
        raise LabAlreadyExists(f"name collides with an existing core: {name}")
    if not pi_at or pi_at == "@":
        raise RegistrarError("pi_handle is required")
    # The one-PI-per-lab/core invariant only applies to ACTIVE entries.
    # Archiving a lab frees its PI to lead a different one; this is how
    # PI handover at retirement / lab closure is supposed to work.
    for l in existing.labs:
        if l.status == "active" and _normalize_pi(l.pi) == pi_at:
            raise PIAlreadyLeadsAnother(
                f"{pi_at} already leads lab {l.name!r}. "
                f"A PI can lead at most one active lab or core."
            )
    for c in existing.cores:
        if c.status == "active" and _normalize_pi(c.pi) == pi_at:
            raise PIAlreadyLeadsAnother(
                f"{pi_at} already leads core {c.name!r}. "
                f"A PI can lead at most one active lab or core."
            )


def _render_lab_md(
    *,
    name: str,
    display_name: str,
    pi_at: str,
    slack_workspace: str | None,
    github_org: str | None,
    oracle_vault: str | None,
    institution: str | None,
    department: str | None,
    created: str,
) -> str:
    """Render lab.md frontmatter for a freshly-scaffolded lab.

    Mirrors the shape the snapshot reader already understands. Only
    optional fields with a value are emitted, so the file stays clean.
    """
    meta: dict[str, Any] = {
        "lab": name,
        "name": display_name,
        "pi": pi_at,
    }
    if institution:
        meta["institution"] = institution
    if department:
        meta["department"] = department
    if slack_workspace:
        meta["slack_workspace"] = slack_workspace
    if github_org:
        meta["github_org"] = github_org
    if oracle_vault:
        meta["lab_oracle_vault"] = oracle_vault
    meta["created"] = created

    body = (
        f"# {display_name} — group config\n\n"
        f"This file is the canonical declaration of the **{display_name}** "
        f"group. Edit through the lab's own dashboard; the registrar's "
        f"audit log records every modification it sees.\n"
    )
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    return f"---\n{yaml_text}---\n\n{body}"


def _render_pi_member_md(
    *,
    pi_at: str,
    pi_full_name: str | None,
    lab_name: str,
) -> str:
    """Render ``members/<pi>.md`` for the initial PI."""
    meta: dict[str, Any] = {
        "handle": pi_at,
        "full_name": pi_full_name or pi_at.lstrip("@").title(),
        "role": "pi",
        "status": "active",
        "lab": lab_name,
    }
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    return f"---\n{yaml_text}---\n\n# {pi_at}\n"


def create_lab(
    *,
    name: str,
    display_name: str,
    pi_handle: str,
    pi_full_name: str | None = None,
    slack_workspace: str | None = None,
    github_org: str | None = None,
    oracle_vault: str | None = None,
    institution: str | None = None,
    department: str | None = None,
    today: _dt.date | None = None,
    env: dict[str, str] | None = None,
) -> LabEntry:
    """Scaffold a new lab and register it.

    Side effects:
      1. Creates ``<lab_info_root>/labs/<name>/lab-mgmt/`` with ``lab.md``,
         ``members/<pi>.md``, and empty ``projects/``, ``requests/``,
         ``audit/`` directories.
      2. Adds an entry to ``_registry.yaml``.
      3. ``git init`` on ``<lab_info_root>`` if needed and commits the
         change with an audit-trail message.

    Idempotency: refuses if the lab name is already registered or if
    the PI already leads another lab/core. There is no implicit
    overwrite — duplicates are a registrar error, not a no-op.
    """
    today_d = today or _dt.date.today()
    pi_at = _normalize_pi(pi_handle)

    existing = read_registry(env)
    _enforce_create_invariants(name=name, pi_at=pi_at, existing=existing)

    root = lab_info_root(env)
    root.mkdir(parents=True, exist_ok=True)
    lab_dir = root / "labs" / name
    lab_mgmt_dir = lab_dir / "lab-mgmt"
    for sub in ("members", "projects", "requests", "audit"):
        (lab_mgmt_dir / sub).mkdir(parents=True, exist_ok=True)
        gitkeep = lab_mgmt_dir / sub / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

    lab_md = lab_mgmt_dir / "lab.md"
    lab_md.write_text(
        _render_lab_md(
            name=name,
            display_name=display_name,
            pi_at=pi_at,
            slack_workspace=slack_workspace,
            github_org=github_org,
            oracle_vault=oracle_vault,
            institution=institution,
            department=department,
            created=today_d.isoformat(),
        ),
        encoding="utf-8",
    )

    pi_member_md = lab_mgmt_dir / "members" / f"{pi_at.lstrip('@')}.md"
    pi_member_md.write_text(
        _render_pi_member_md(
            pi_at=pi_at, pi_full_name=pi_full_name, lab_name=name,
        ),
        encoding="utf-8",
    )

    entry = LabEntry(
        name=name,
        pi=pi_at,
        lab_mgmt_path=str(lab_mgmt_dir),
        status="active",
        created=today_d.isoformat(),
        slack_workspace=slack_workspace,
        github_org=github_org,
        oracle_vault=oracle_vault,
    )
    updated_registry = Registry(
        labs=[*existing.labs, entry],
        cores=existing.cores,
        collaborations=existing.collaborations,
    )
    write_registry(updated_registry, env)

    # Audit trail: every mutation lands as its own commit.
    _git_init_if_needed(root)
    _git_commit_all(
        root,
        f"registrar: create lab {name} (PI: {pi_at})",
    )

    return entry


# -----------------------------------------------------------------
# Phase C: archive + update lab metadata
# -----------------------------------------------------------------


def _find_lab(name: str, env: dict[str, str] | None = None) -> tuple[Registry, int]:
    """Return (registry, index_of_lab) or raise :class:`LabNotFound`."""
    reg = read_registry(env)
    for i, l in enumerate(reg.labs):
        if l.name == name:
            return reg, i
    raise LabNotFound(f"no lab registered with short id: {name!r}")


def _replace_lab(reg: Registry, idx: int, new_entry: LabEntry) -> Registry:
    """Return a copy of ``reg`` with ``new_entry`` at ``labs[idx]``."""
    new_labs = list(reg.labs)
    new_labs[idx] = new_entry
    return Registry(labs=new_labs, cores=reg.cores, collaborations=reg.collaborations)


def _set_status(name: str, status: str, env: dict[str, str] | None = None) -> LabEntry:
    """Flip a lab's status in the registry. Files are preserved either way."""
    reg, idx = _find_lab(name, env)
    current = reg.labs[idx]
    if current.status == status:
        return current  # no-op
    updated = LabEntry(
        name=current.name, pi=current.pi, lab_mgmt_path=current.lab_mgmt_path,
        status=status, created=current.created,
        slack_workspace=current.slack_workspace, github_org=current.github_org,
        oracle_vault=current.oracle_vault,
    )
    new_reg = _replace_lab(reg, idx, updated)
    write_registry(new_reg, env)
    root = lab_info_root(env)
    _git_init_if_needed(root)
    verb = "archive" if status == "archived" else "unarchive" if status == "active" else f"set {status}"
    _git_commit_all(root, f"registrar: {verb} lab {name}")
    return updated


def archive_lab(name: str, env: dict[str, str] | None = None) -> LabEntry:
    """Soft-delete a lab: ``status -> archived``.

    The lab's files (``labs/<name>/lab-mgmt/``) are preserved untouched.
    Archival is reversible via :func:`unarchive_lab`. Once archived,
    the lab's PI handle is freed up — a different lab can claim that PI.
    """
    return _set_status(name, "archived", env)


def unarchive_lab(name: str, env: dict[str, str] | None = None) -> LabEntry:
    """Bring an archived lab back. ``status -> active``.

    Refuses if the lab's PI now leads a different active lab/core —
    the one-PI-per-active-lab invariant must hold post-unarchival too.
    """
    reg, idx = _find_lab(name, env)
    current = reg.labs[idx]
    if current.status != "archived":
        return current
    pi_at = _normalize_pi(current.pi)
    for j, l in enumerate(reg.labs):
        if j == idx:
            continue
        if l.status == "active" and _normalize_pi(l.pi) == pi_at:
            raise PIAlreadyLeadsAnother(
                f"cannot unarchive {name}: {pi_at} now leads active lab {l.name!r}. "
                f"Reassign one before unarchiving."
            )
    for c in reg.cores:
        if c.status == "active" and _normalize_pi(c.pi) == pi_at:
            raise PIAlreadyLeadsAnother(
                f"cannot unarchive {name}: {pi_at} now leads active core {c.name!r}."
            )
    return _set_status(name, "active", env)


# Set of fields editable via update_lab_metadata. ``name`` is NOT
# editable (renaming would invalidate every path that references it);
# ``status`` is reserved for archive/unarchive; ``created`` is history.
_EDITABLE_FIELDS = frozenset({
    "display_name",
    "pi_handle",
    "pi_full_name",
    "slack_workspace",
    "github_org",
    "oracle_vault",
    "institution",
    "department",
})


def update_lab_metadata(
    name: str,
    *,
    display_name: str | None = None,
    pi_handle: str | None = None,
    pi_full_name: str | None = None,
    slack_workspace: str | None = None,
    github_org: str | None = None,
    oracle_vault: str | None = None,
    institution: str | None = None,
    department: str | None = None,
    env: dict[str, str] | None = None,
) -> LabEntry:
    """Modify a lab's metadata at the registrar level.

    Updates ``_registry.yaml`` AND the lab's ``lab.md`` frontmatter.
    A ``None`` argument means "do not touch this field"; passing an
    empty string clears the field. The one-PI-per-active-lab invariant
    is re-enforced when ``pi_handle`` is supplied. Renaming the lab
    short ID is intentionally not supported.
    """
    from .frontmatter import parse_file as _pf, dump_document as _dump

    reg, idx = _find_lab(name, env)
    current = reg.labs[idx]

    # Validate PI change against active labs/cores.
    new_pi_at: str | None = None
    if pi_handle is not None:
        new_pi_at = _normalize_pi(pi_handle)
        if not new_pi_at or new_pi_at == "@":
            raise RegistrarError("pi_handle cannot be blank")
        if new_pi_at != _normalize_pi(current.pi):
            # Only enforce the invariant for active labs — archived ones
            # don't compete for a PI slot.
            for j, l in enumerate(reg.labs):
                if j == idx:
                    continue
                if l.status == "active" and _normalize_pi(l.pi) == new_pi_at:
                    raise PIAlreadyLeadsAnother(
                        f"{new_pi_at} already leads lab {l.name!r}"
                    )
            for c in reg.cores:
                if c.status == "active" and _normalize_pi(c.pi) == new_pi_at:
                    raise PIAlreadyLeadsAnother(
                        f"{new_pi_at} already leads core {c.name!r}"
                    )

    # Compose updated registry entry.
    updated = LabEntry(
        name=current.name,
        pi=new_pi_at if new_pi_at is not None else current.pi,
        lab_mgmt_path=current.lab_mgmt_path,
        status=current.status,
        created=current.created,
        slack_workspace=(slack_workspace if slack_workspace is not None
                         else current.slack_workspace) or None,
        github_org=(github_org if github_org is not None
                    else current.github_org) or None,
        oracle_vault=(oracle_vault if oracle_vault is not None
                      else current.oracle_vault) or None,
    )

    # Update lab.md frontmatter to match — preserve body + unknown keys.
    lab_md = Path(current.lab_mgmt_path) / "lab.md"
    if lab_md.is_file():
        parsed = _pf(lab_md)
        meta = dict(parsed.meta or {})
        if display_name is not None:
            if display_name:
                meta["name"] = display_name
            else:
                meta.pop("name", None)
        if new_pi_at is not None:
            meta["pi"] = new_pi_at
        for key, value in (
            ("slack_workspace", slack_workspace),
            ("github_org", github_org),
            ("lab_oracle_vault", oracle_vault),
            ("institution", institution),
            ("department", department),
        ):
            if value is None:
                continue
            if value:
                meta[key] = value
            else:
                meta.pop(key, None)
        lab_md.write_text(_dump(meta, parsed.body or ""), encoding="utf-8")

    # Optionally bump the PI member file if pi handle changed AND a new
    # member file doesn't already exist. We DO NOT delete the old PI's
    # member file — that's the lab's roster decision. Just create the new
    # one so the registrar dashboard sees a populated PI.
    if new_pi_at is not None and new_pi_at != _normalize_pi(current.pi):
        members_dir = Path(current.lab_mgmt_path) / "members"
        new_pi_member = members_dir / f"{new_pi_at.lstrip('@')}.md"
        if members_dir.is_dir() and not new_pi_member.exists():
            new_pi_member.write_text(
                _render_pi_member_md(
                    pi_at=new_pi_at, pi_full_name=pi_full_name,
                    lab_name=current.name,
                ),
                encoding="utf-8",
            )

    new_reg = _replace_lab(reg, idx, updated)
    write_registry(new_reg, env)

    root = lab_info_root(env)
    _git_init_if_needed(root)
    changed_summary: list[str] = []
    if display_name is not None: changed_summary.append("display_name")
    if new_pi_at is not None and new_pi_at != _normalize_pi(current.pi):
        changed_summary.append(f"pi -> {new_pi_at}")
    if slack_workspace is not None: changed_summary.append("slack_workspace")
    if github_org is not None: changed_summary.append("github_org")
    if oracle_vault is not None: changed_summary.append("oracle_vault")
    if institution is not None: changed_summary.append("institution")
    if department is not None: changed_summary.append("department")
    summary = ", ".join(changed_summary) or "no-op"
    _git_commit_all(root, f"registrar: update lab {name} ({summary})")

    return updated
