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

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

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
