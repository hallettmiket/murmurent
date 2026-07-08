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
from dataclasses import dataclass, field, replace
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


class CollaborationAlreadyExists(RegistrarError):
    """Refused: a collaboration with this short ID is already registered."""


class CollaborationNotFound(RegistrarError):
    """Refused: no collaboration with that short ID is registered."""


class InvalidCollaboration(RegistrarError):
    """Refused: collaboration violates an invariant (>=2 PIs/groups, etc.)."""

# -----------------------------------------------------------------
# Identity
# -----------------------------------------------------------------

def _wig_home() -> Path:
    """This machine's ``~/.wigamig`` root, honouring ``WIGAMIG_HOME`` so tools,
    scripts, and tests that isolate it never write into the real home."""
    return Path(os.environ.get("WIGAMIG_HOME", str(Path.home() / ".wigamig")))


# Per-machine sentinel. Honours WIGAMIG_HOME (evaluated per process), so e.g. the
# identity smoke test — which sets WIGAMIG_HOME — cannot clobber the real one.
REGISTRAR_SENTINEL = _wig_home() / "registrar"
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

    The file contains the Western netname on the first non-blank line.
    This is the **per-machine sentinel** — the human at this laptop says
    "I am one of the centre's registrars." Whether the claim is honoured
    is decided by :func:`is_registrar`, which cross-checks the
    authoritative list in ``_registry.yaml:registrars:``.

    Used for git commit identity on the lab_info root (audit trail).
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


def registrars(env: dict[str, str] | None = None) -> list[str]:
    """Return the authoritative registrar handles from ``_registry.yaml``.

    The centre may have more than one registrar (e.g. a director + a
    backup admin). The list lives in the registry — committed,
    git-tracked, audited — not in any per-machine file. Returns an empty
    list if the registry is missing or has no ``registrars:`` key.
    """
    path = registry_path(env)
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("registrars") or []
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        norm = _normalize(str(item))
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def is_registrar(handle: str, env: dict[str, str] | None = None) -> bool:
    """Return True iff ``handle`` is an authoritative centre registrar.

    Truth lives in ``_registry.yaml:registrars:`` (committed, git-tracked).
    If that list is empty (fresh install, pre-Phase-A), fall back — in order — to
    a ``<lab_info>/registrar`` file (git-tracked, scoped to this centre's data
    root, so it isolates cleanly) and then the per-machine
    ``~/.wigamig/registrar`` sentinel, for backward compat with single-registrar
    installs.
    """
    norm = _normalize(handle)
    if not norm:
        return False
    declared = registrars(env)
    if declared:
        return norm in declared
    # Fallback 1: a registrar declared in the centre's own lab_info root (scoped
    # to WIGAMIG_LAB_INFO_ROOT, so it only exists for a configured centre).
    scoped = _lab_info_registrar(env)
    if scoped is not None:
        return norm == scoped
    # Fallback 2: the legacy per-MACHINE sentinel (~/.wigamig/registrar) is only
    # meaningful once a centre actually exists on this machine. A fresh or
    # centre-less install must grant NOBODY registrar access — otherwise a stale
    # sentinel left behind by a removed centre silently confers registrar powers.
    if not _centre_initialised(env):
        return False
    legacy = registrar_handle()
    if legacy is None:
        return False
    return norm == legacy


def _centre_initialised(env: dict[str, str] | None = None) -> bool:
    """True iff a centre is bootstrapped on this machine (``centre.md`` present).
    Lazy import avoids a circular dependency with ``centre_init``."""
    try:
        from . import centre_init as _ci
        return _ci.is_initialised(env)
    except Exception:  # noqa: BLE001
        return False


def _lab_info_registrar(env: dict[str, str] | None = None) -> str | None:
    """The single registrar handle declared in ``<lab_info>/registrar``, or None.

    Scoped to ``WIGAMIG_LAB_INFO_ROOT`` (unlike the machine sentinel), so it is
    naturally isolated per install/test."""
    p = lab_info_root(env) / "registrar"
    if not p.is_file():
        return None
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    for line in text.splitlines():
        if line.strip():
            return _normalize(line)
    return None


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
    slack_channel_id: str | None = None    # the lab's private Slack channel
    github_org: str | None = None
    oracle_vault: str | None = None


@dataclass(frozen=True)
class CoreEntry:
    """One core facility in ``_registry.yaml``.

    A core has the same registry shape as a lab — same components, same
    full agent fleet, projects, and SEAs. The primary differences are
    behavioural (cores OFFER rather than REQUEST SEAs, must be extra
    secure, and have an accountant tracking SEA costs + inventory) and
    these are layered on in later phases. Terminology: a core's lead is
    called the **core leader**, not PI. We keep the internal field name
    ``pi`` for shared registry plumbing; the UI labels appropriately.
    """

    name: str
    pi: str                                # the core leader's @handle
    lab_mgmt_path: str
    status: str = "active"
    created: str | None = None
    slack_workspace: str | None = None
    slack_channel_id: str | None = None    # the core's private Slack channel
    github_org: str | None = None
    oracle_vault: str | None = None


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
    registrars: list[str] = field(default_factory=list)


def _coerce_lab(name: str, data: dict[str, Any]) -> LabEntry:
    return LabEntry(
        name=name,
        pi=str(data.get("pi") or ""),
        lab_mgmt_path=str(data.get("lab_mgmt_path") or ""),
        status=str(data.get("status") or "active"),
        created=_opt_str(data.get("created")),
        slack_workspace=_opt_str(data.get("slack_workspace")),
        slack_channel_id=_opt_str(data.get("slack_channel_id")),
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
        slack_workspace=_opt_str(data.get("slack_workspace")),
        slack_channel_id=_opt_str(data.get("slack_channel_id")),
        github_org=_opt_str(data.get("github_org")),
        oracle_vault=_opt_str(data.get("oracle_vault")),
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

    raw_registrars = data.get("registrars") or []
    registrar_list: list[str] = []
    if isinstance(raw_registrars, list):
        seen: set[str] = set()
        for item in raw_registrars:
            norm = _normalize(str(item))
            if norm and norm not in seen:
                seen.add(norm)
                registrar_list.append(norm)

    return Registry(
        labs=_walk(labs_dict, _coerce_lab),
        cores=_walk(cores_dict, _coerce_core),
        collaborations=_walk(collabs_dict, _coerce_collab),
        registrars=registrar_list,
    )


def lab_mgmt_path_for_handle(handle: str, env: dict[str, str] | None = None) -> tuple[str, str] | None:
    """Look up which lab/core a handle belongs to and return its lab-mgmt path.

    Walks every lab and core in ``_registry.yaml``: a handle counts as
    "belonging to" a group if (a) it is the PI/leader of the group, or
    (b) ``members/<handle>.md`` exists under that group's lab_mgmt_path.
    The first match wins; PIs match first because they're checked
    before the member-file check.

    Returns ``(group_name, lab_mgmt_path)`` on a hit, or ``None`` if the
    handle isn't claimed by any registered group. Callers that don't
    care about the group_name can ignore the first element. ``None``
    typically means the dashboard should fall back to its default
    resolution (the legacy single-lab install).
    """
    norm = _normalize(handle)
    if not norm:
        return None
    reg = read_registry(env)
    entries: list[tuple[str, str, str]] = []
    for lab in reg.labs:
        entries.append((lab.name, _normalize(lab.pi), lab.lab_mgmt_path))
    for core in reg.cores:
        entries.append((core.name, _normalize(core.pi), core.lab_mgmt_path))
    # PI match first (cheap).
    for name, pi, path in entries:
        if pi == norm and path:
            return (name, path)
    # Member-file probe (one disk stat per group).
    for name, _pi, path in entries:
        if not path:
            continue
        member_file = Path(path).expanduser() / "members" / f"{norm}.md"
        if member_file.is_file():
            return (name, path)
    return None


def write_registry(reg: Registry, env: dict[str, str] | None = None) -> Path:
    """Serialise ``reg`` to ``_registry.yaml``. Creates parent dirs.

    Phase A doesn't expose a write endpoint, but tests and the bootstrap
    helper use this to seed the registry on a fresh install.
    """
    path = registry_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "version": 1,
        "registrars": list(reg.registrars),
        "labs": {},
        "cores": {},
        "collaborations": {},
    }
    for lab in reg.labs:
        payload["labs"][lab.name] = {
            k: v for k, v in {
                "pi": lab.pi,
                "lab_mgmt_path": lab.lab_mgmt_path,
                "status": lab.status,
                "created": lab.created,
                "slack_workspace": lab.slack_workspace,
                "slack_channel_id": lab.slack_channel_id,
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
                "slack_workspace": core.slack_workspace,
                "slack_channel_id": core.slack_channel_id,
                "github_org": core.github_org,
                "oracle_vault": core.oracle_vault,
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
    reg = Registry(labs=other_labs, cores=existing.cores,
                    collaborations=existing.collaborations,
                    registrars=existing.registrars)
    write_registry(reg, env)
    return reg


# -----------------------------------------------------------------
# Registrar profile — centre-level contact / location for the role itself
# -----------------------------------------------------------------


PROFILE_FILENAME = "registrar.md"


def profile_path(env: dict[str, str] | None = None) -> Path:
    """Return ``<lab_info_root>/registrar.md`` — the registrar's own profile."""
    return lab_info_root(env) / PROFILE_FILENAME


def read_profile(env: dict[str, str] | None = None) -> dict:
    """Return the registrar's profile frontmatter as a plain dict.

    Missing file returns ``{}`` — that's the legitimate "fresh install,
    not yet filled in" state. Malformed files also return ``{}`` so the
    dashboard never breaks on a hand-edit typo.
    """
    from .frontmatter import parse_file as _pf

    path = profile_path(env)
    if not path.is_file():
        return {}
    try:
        parsed = _pf(path)
    except Exception:
        return {}
    return dict(parsed.meta or {})


def write_profile(
    updates: dict,
    *,
    env: dict[str, str] | None = None,
) -> Path:
    """Apply ``updates`` to ``registrar.md`` frontmatter and commit.

    ``updates`` is a partial dict — keys present get set / cleared
    (empty string clears, ``None`` is skipped); keys absent are
    preserved. The file body is left alone if it exists, or seeded with
    a minimal header if the file is being created.
    """
    from .frontmatter import dump_document as _dump, parse_file as _pf

    path = profile_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.is_file():
        parsed = _pf(path)
        meta = dict(parsed.meta or {})
        body = parsed.body or ""
    else:
        meta = {}
        body = (
            "# Registrar profile\n\n"
            "Centre-level contact for the wigamig registrar role. Edit through "
            "the `/registrar` dashboard's profile button, or hand-edit this "
            "frontmatter directly.\n"
        )

    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            meta.pop(key, None)
        else:
            meta[key] = value

    path.write_text(_dump(meta, body), encoding="utf-8")

    # Audit trail commit.
    root = lab_info_root(env)
    _git_init_if_needed(root)
    changed = ", ".join(sorted(updates.keys())) or "no-op"
    _git_commit_all(root, f"registrar: update profile ({changed})")
    return path


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


def _invalid_name_message(kind: str, name: str | None) -> str:
    """Return a precise explanation of why ``name`` doesn't fit ``_NAME_RE``.

    The earlier "must be lowercase alphanumeric + underscore, starting with
    a letter" wording was easy to misread as "must contain an underscore."
    This helper identifies the *actual* offending character so the user can
    fix it directly. The dashboard's create forms now also auto-lowercase
    inputs so casing errors usually never reach the server.
    """
    if not name:
        return f"{kind} name is required"
    reasons: list[str] = []
    if not name[0].isalpha() or not name[0].islower():
        reasons.append(f"must start with a lowercase letter (got {name[0]!r})")
    bad = sorted({c for c in name if not (c.islower() or c.isdigit() or c == "_")})
    if bad:
        reasons.append(
            f"only lowercase letters, digits, and underscores are allowed "
            f"(found: {', '.join(repr(c) for c in bad)})"
        )
    if not reasons:
        reasons.append("name does not match the required form ^[a-z][a-z0-9_]*$")
    return f"{kind} name {name!r} is invalid: " + "; ".join(reasons)


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
        raise InvalidLabName(_invalid_name_message("lab", name))
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
    pi_email: str = "",
) -> str:
    """Render ``members/<pi>.md`` for the initial PI."""
    meta: dict[str, Any] = {
        "handle": pi_at,
        "full_name": pi_full_name or pi_at.lstrip("@").title(),
        "role": "pi",
        "status": "active",
        "lab": lab_name,
    }
    if pi_email:
        meta["email"] = pi_email
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    return f"---\n{yaml_text}---\n\n# {pi_at}\n"


def create_lab(
    *,
    name: str,
    display_name: str,
    pi_handle: str,
    pi_full_name: str | None = None,
    pi_email: str = "",
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
            pi_email=pi_email,
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
        registrars=existing.registrars,
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
    return Registry(labs=new_labs, cores=reg.cores, collaborations=reg.collaborations, registrars=reg.registrars)


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


def set_group_slack_channel(
    name: str, channel_id: str, *, env: dict[str, str] | None = None,
) -> bool:
    """Stamp a lab or core's ``slack_channel_id`` in ``_registry.yaml``.

    Returns True if a group named ``name`` was found and updated. Best-effort
    for the provisioning path (a missing group is a no-op returning False)."""
    reg = read_registry(env)
    for i, lab in enumerate(reg.labs):
        if lab.name == name:
            labs = list(reg.labs)
            labs[i] = replace(lab, slack_channel_id=channel_id or None)
            write_registry(replace(reg, labs=labs), env)
            return True
    for i, core in enumerate(reg.cores):
        if core.name == name:
            cores = list(reg.cores)
            cores[i] = replace(core, slack_channel_id=channel_id or None)
            write_registry(replace(reg, cores=cores), env)
            return True
    return False


def group_exists(name: str, *, env: dict[str, str] | None = None) -> bool:
    """True iff a lab or core named ``name`` is registered at the centre."""
    reg = read_registry(env)
    return any(g.name == name for g in [*reg.labs, *reg.cores])


def group_pi(name: str, *, env: dict[str, str] | None = None) -> str | None:
    """The ``@handle`` of a lab/core's PI (leader), or None if no such group."""
    reg = read_registry(env)
    entry = next((g for g in [*reg.labs, *reg.cores] if g.name == name), None)
    return entry.pi if entry else None


def add_group_member(
    name: str,
    *,
    handle: str,
    email: str = "",
    full_name: str = "",
    role: str = "member",
    env: dict[str, str] | None = None,
) -> bool:
    """Add (or update) a member of an existing lab/core, addressed by group name.

    Writes ``<group>/lab-mgmt/members/<handle>.md`` with an ``email`` so the
    member can be resolved for the group's Slack-channel invite. Idempotent.
    Returns False if no group named ``name`` exists (or it has no lab_mgmt_path).
    """
    reg = read_registry(env)
    entry = next((g for g in [*reg.labs, *reg.cores] if g.name == name), None)
    if entry is None or not entry.lab_mgmt_path:
        return False
    norm = _normalize(handle)
    if not norm:
        return False
    members_dir = Path(entry.lab_mgmt_path).expanduser() / "members"
    members_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {
        "handle": f"@{norm}",
        "full_name": full_name or norm.replace("_", " ").title(),
        "role": role,
        "status": "active",
        "lab": name,
    }
    if (email or "").strip():
        meta["email"] = email.strip()
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    (members_dir / f"{norm}.md").write_text(
        f"---\n{yaml_text}---\n\n# @{norm}\n", encoding="utf-8")
    return True


def read_group_member(
    name: str, handle: str, *, env: dict[str, str] | None = None,
) -> dict | None:
    """Return a group member's key details (``handle``, ``email``, ``github``
    login, ``status``, ``role``) from ``<group>/lab-mgmt/members/<handle>.md``,
    or None if the group or member file doesn't exist. Used before removing a
    member so we know which Slack account + GitHub login to deprovision."""
    reg = read_registry(env)
    entry = next((g for g in [*reg.labs, *reg.cores] if g.name == name), None)
    if entry is None or not entry.lab_mgmt_path:
        return None
    norm = _normalize(handle)
    if not norm:
        return None
    mf = Path(entry.lab_mgmt_path).expanduser() / "members" / f"{norm}.md"
    if not mf.is_file():
        return None
    from . import git_providers as _gp
    from .frontmatter import parse_file as _pf
    try:
        meta = _pf(mf).meta or {}
    except Exception:  # noqa: BLE001
        meta = {}
    return {
        "handle": norm,
        "email": str(meta.get("email") or "").strip(),
        "github": _gp.parse_logins(meta).get("github", ""),
        "status": str(meta.get("status") or "active"),
        "role": str(meta.get("role") or "member"),
    }


def remove_group_member(
    name: str, handle: str, *,
    env: dict[str, str] | None = None, delete: bool = False,
) -> bool:
    """Remove a member from a group's roster. By default marks their file
    ``status: removed`` (keeps it for the audit trail); ``delete=True`` unlinks
    the file entirely. Returns False if the group or member file doesn't exist.

    Roster-only — the caller handles Slack/GitHub deprovisioning."""
    reg = read_registry(env)
    entry = next((g for g in [*reg.labs, *reg.cores] if g.name == name), None)
    if entry is None or not entry.lab_mgmt_path:
        return False
    norm = _normalize(handle)
    if not norm:
        return False
    mf = Path(entry.lab_mgmt_path).expanduser() / "members" / f"{norm}.md"
    if not mf.is_file():
        return False
    if delete:
        mf.unlink()
        return True
    from .frontmatter import parse_file as _pf
    try:
        parsed = _pf(mf)
        meta = dict(parsed.meta or {})
        body = parsed.body or f"\n# @{norm}\n"
    except Exception:  # noqa: BLE001
        meta, body = {"handle": f"@{norm}", "lab": name}, f"\n# @{norm}\n"
    meta["status"] = "removed"
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    mf.write_text(f"---\n{yaml_text}---\n{body}", encoding="utf-8")
    return True


# --- group profile (PI fills these in AFTER the group is created) ----------
# Kept on the group's OWN lab.md (in its lab-mgmt repo), which the PI controls
# and backs up — distinct from the centre registry the mayor holds.
GROUP_PROFILE_FIELDS: tuple[str, ...] = (
    "github",           # the group's GitHub repo, e.g. "org/mh_lab"
    "notebook_host",    # a machine (in the host registry) where lab notebooks live
    "notebook_path",    # path on that host
    "slack_workspace",  # the group's OWN Slack workspace/team id (per-group workspace)
    "slack_invite_url", # its join link (the PI manages this workspace)
    "data_host",        # machine holding large datasets (e.g. lab-server)
    "data_raw",         # e.g. /data/lab_vm/raw/<group>
    "data_refined",     # e.g. /data/lab_vm/refined/<group>
)


def _group_lab_md(name: str, *, env: dict[str, str] | None = None) -> Path | None:
    reg = read_registry(env)
    entry = next((g for g in [*reg.labs, *reg.cores] if g.name == name), None)
    if entry is None or not entry.lab_mgmt_path:
        return None
    return Path(entry.lab_mgmt_path).expanduser() / "lab.md"


def read_group_profile(name: str, *, env: dict[str, str] | None = None) -> dict[str, str]:
    """Return the group's profile fields from its ``lab.md`` (empty if unset)."""
    from .frontmatter import parse_file as _pf
    p = _group_lab_md(name, env=env)
    if p is None or not p.is_file():
        return {}
    meta = _pf(p).meta or {}
    return {k: str(meta[k]) for k in GROUP_PROFILE_FIELDS if meta.get(k)}


def update_group_profile(
    name: str, fields: dict[str, str], *, env: dict[str, str] | None = None,
) -> bool:
    """Merge ``fields`` into the group's ``lab.md`` frontmatter.

    Only known GROUP_PROFILE_FIELDS are written; an empty value clears a field.
    Returns False if there is no such group (or it has no lab.md).
    """
    from .frontmatter import parse_file as _pf, dump_document as _dump
    p = _group_lab_md(name, env=env)
    if p is None or not p.is_file():
        return False
    doc = _pf(p)
    meta = dict(doc.meta or {})
    for k, v in fields.items():
        if k not in GROUP_PROFILE_FIELDS:
            continue
        val = str(v).strip() if v is not None else ""
        if val:
            meta[k] = val
        else:
            meta.pop(k, None)
    p.write_text(_dump(meta, doc.body), encoding="utf-8")
    return True


def group_email_map(
    name: str, *, env: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return ``{handle: email}`` for a lab/core's members that have an email
    on file (reads ``<group>/lab-mgmt/members/*.md``). Feeds the Slack invite
    engine. Members without an email are omitted."""
    from .frontmatter import parse_file as _pf
    reg = read_registry(env)
    entry = next((g for g in [*reg.labs, *reg.cores] if g.name == name), None)
    if entry is None or not entry.lab_mgmt_path:
        return {}
    members_dir = Path(entry.lab_mgmt_path) / "members"
    if not members_dir.is_dir():
        return {}
    out: dict[str, str] = {}
    for mf in sorted(members_dir.glob("*.md")):
        try:
            meta = _pf(mf).meta or {}
        except Exception:  # noqa: BLE001
            continue
        if str(meta.get("status") or "active") != "active":
            continue
        email = str(meta.get("email") or "").strip()
        if email:
            out[_normalize(str(meta.get("handle") or mf.stem))] = email
    return out


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


# -----------------------------------------------------------------
# Phase E: cores (same shape as labs, different terminology)
# -----------------------------------------------------------------


def _render_core_md(
    *,
    name: str,
    display_name: str,
    leader_at: str,
    slack_workspace: str | None,
    github_org: str | None,
    oracle_vault: str | None,
    institution: str | None,
    department: str | None,
    created: str,
) -> str:
    """Render the canonical metadata file for a freshly-scaffolded core.

    Format mirrors lab.md so shared snapshot plumbing keeps working;
    the UI labels render this as "core leader" rather than "PI", but
    the field name in YAML stays ``pi:`` (the registry's internal
    "lead handle" notion).
    """
    meta: dict[str, Any] = {
        "core": name,         # short ID
        "name": display_name,
        "pi": leader_at,       # core leader's @handle
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
        f"# {display_name} — core config\n\n"
        f"This file is the canonical declaration of the **{display_name}** "
        f"core. Cores share the lab data model (same components, same agent "
        f"fleet, same projects) but their primary purpose is to OFFER SEAs "
        f"to the rest of the centre. An accountant agent (future phase) "
        f"tracks the costs and inventory associated with each SEA fulfilled.\n"
    )
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    return f"---\n{yaml_text}---\n\n{body}"


def _render_core_leader_member_md(
    *,
    leader_at: str,
    leader_full_name: str | None,
    core_name: str,
    leader_email: str = "",
) -> str:
    """Render members/<leader>.md with role 'core_leader' for the initial lead."""
    meta: dict[str, Any] = {
        "handle": leader_at,
        "full_name": leader_full_name or leader_at.lstrip("@").title(),
        "role": "core_leader",
        "status": "active",
        "lab": core_name,  # the group field; "lab" key kept for shared plumbing
    }
    if leader_email:
        meta["email"] = leader_email
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    return f"---\n{yaml_text}---\n\n# {leader_at}\n"


def _find_core(name: str, env: dict[str, str] | None = None) -> tuple[Registry, int]:
    reg = read_registry(env)
    for i, c in enumerate(reg.cores):
        if c.name == name:
            return reg, i
    raise LabNotFound(f"no core registered with short id: {name!r}")


def _replace_core(reg: Registry, idx: int, new_entry: CoreEntry) -> Registry:
    new_cores = list(reg.cores)
    new_cores[idx] = new_entry
    return Registry(labs=reg.labs, cores=new_cores, collaborations=reg.collaborations, registrars=reg.registrars)


def _enforce_core_create_invariants(
    *,
    name: str,
    leader_at: str,
    existing: Registry,
) -> None:
    """Validate a core-create spec. Same one-lead-per-active-group rule
    as labs (lab and core leads share the same namespace)."""
    if not name or not _NAME_RE.match(name):
        raise InvalidLabName(_invalid_name_message("core", name))
    # Cores share the name namespace with labs to avoid confusion in
    # collaborations and Slack channel naming.
    if any(c.name == name for c in existing.cores):
        raise LabAlreadyExists(f"core already registered: {name}")
    if any(l.name == name for l in existing.labs):
        raise LabAlreadyExists(f"name collides with an existing lab: {name}")
    if not leader_at or leader_at == "@":
        raise RegistrarError("leader_handle is required")
    for l in existing.labs:
        if l.status == "active" and _normalize_pi(l.pi) == leader_at:
            raise PIAlreadyLeadsAnother(
                f"{leader_at} already leads lab {l.name!r}. "
                f"A leader can run at most one active lab or core."
            )
    for c in existing.cores:
        if c.status == "active" and _normalize_pi(c.pi) == leader_at:
            raise PIAlreadyLeadsAnother(
                f"{leader_at} already leads core {c.name!r}. "
                f"A leader can run at most one active lab or core."
            )


def create_core(
    *,
    name: str,
    display_name: str,
    leader_handle: str,
    leader_full_name: str | None = None,
    leader_email: str = "",
    slack_workspace: str | None = None,
    github_org: str | None = None,
    oracle_vault: str | None = None,
    institution: str | None = None,
    department: str | None = None,
    today: _dt.date | None = None,
    env: dict[str, str] | None = None,
) -> CoreEntry:
    """Scaffold a new core and register it.

    Side effects parallel ``create_lab``: directory tree under
    ``<lab_info_root>/cores/<name>/lab-mgmt/`` with ``lab.md``,
    ``members/<leader>.md``, plus empty ``projects/``, ``requests/``,
    ``audit/``. Registry entry added. Audit-trail commit.

    Idempotency: refuses on duplicate name OR if the leader already
    runs another active group.
    """
    today_d = today or _dt.date.today()
    leader_at = _normalize_pi(leader_handle)
    existing = read_registry(env)
    _enforce_core_create_invariants(
        name=name, leader_at=leader_at, existing=existing,
    )

    root = lab_info_root(env)
    root.mkdir(parents=True, exist_ok=True)
    core_dir = root / "cores" / name
    lab_mgmt_dir = core_dir / "lab-mgmt"
    for sub in ("members", "projects", "requests", "audit"):
        (lab_mgmt_dir / sub).mkdir(parents=True, exist_ok=True)
        gitkeep = lab_mgmt_dir / sub / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

    # ``lab.md`` filename kept (shared snapshot reads this name); the
    # frontmatter declares ``core: <name>`` instead of ``lab: <name>``.
    lab_md = lab_mgmt_dir / "lab.md"
    lab_md.write_text(
        _render_core_md(
            name=name, display_name=display_name, leader_at=leader_at,
            slack_workspace=slack_workspace, github_org=github_org,
            oracle_vault=oracle_vault, institution=institution,
            department=department, created=today_d.isoformat(),
        ),
        encoding="utf-8",
    )
    leader_md = lab_mgmt_dir / "members" / f"{leader_at.lstrip('@')}.md"
    leader_md.write_text(
        _render_core_leader_member_md(
            leader_at=leader_at, leader_full_name=leader_full_name,
            core_name=name, leader_email=leader_email,
        ),
        encoding="utf-8",
    )

    entry = CoreEntry(
        name=name, pi=leader_at, lab_mgmt_path=str(lab_mgmt_dir),
        status="active", created=today_d.isoformat(),
        slack_workspace=slack_workspace, github_org=github_org,
        oracle_vault=oracle_vault,
    )
    new_reg = Registry(
        labs=existing.labs,
        cores=[*existing.cores, entry],
        collaborations=existing.collaborations,
        registrars=existing.registrars,
    )
    write_registry(new_reg, env)

    _git_init_if_needed(root)
    _git_commit_all(
        root, f"registrar: create core {name} (leader: {leader_at})",
    )
    return entry


def _set_core_status(
    name: str, status: str, env: dict[str, str] | None = None,
) -> CoreEntry:
    reg, idx = _find_core(name, env)
    current = reg.cores[idx]
    if current.status == status:
        return current
    updated = CoreEntry(
        name=current.name, pi=current.pi, lab_mgmt_path=current.lab_mgmt_path,
        status=status, created=current.created,
        slack_workspace=current.slack_workspace, github_org=current.github_org,
        oracle_vault=current.oracle_vault,
    )
    new_reg = _replace_core(reg, idx, updated)
    write_registry(new_reg, env)
    root = lab_info_root(env)
    _git_init_if_needed(root)
    verb = "archive" if status == "archived" else "unarchive" if status == "active" else f"set {status}"
    _git_commit_all(root, f"registrar: {verb} core {name}")
    return updated


def archive_core(name: str, env: dict[str, str] | None = None) -> CoreEntry:
    """Soft-delete a core. Files preserved; leader freed for a new group."""
    return _set_core_status(name, "archived", env)


def unarchive_core(name: str, env: dict[str, str] | None = None) -> CoreEntry:
    """Restore an archived core. Refuses if the leader now runs another
    active group (lab OR core)."""
    reg, idx = _find_core(name, env)
    current = reg.cores[idx]
    if current.status != "archived":
        return current
    leader_at = _normalize_pi(current.pi)
    for l in reg.labs:
        if l.status == "active" and _normalize_pi(l.pi) == leader_at:
            raise PIAlreadyLeadsAnother(
                f"cannot unarchive {name}: {leader_at} now leads active lab {l.name!r}."
            )
    for j, c in enumerate(reg.cores):
        if j == idx:
            continue
        if c.status == "active" and _normalize_pi(c.pi) == leader_at:
            raise PIAlreadyLeadsAnother(
                f"cannot unarchive {name}: {leader_at} now leads active core {c.name!r}."
            )
    return _set_core_status(name, "active", env)


def update_core_metadata(
    name: str,
    *,
    display_name: str | None = None,
    leader_handle: str | None = None,
    leader_full_name: str | None = None,
    slack_workspace: str | None = None,
    github_org: str | None = None,
    oracle_vault: str | None = None,
    institution: str | None = None,
    department: str | None = None,
    env: dict[str, str] | None = None,
) -> CoreEntry:
    """Modify a core's metadata at the registrar level.

    Mirrors ``update_lab_metadata``. Leader handoff re-enforces the
    one-leader-per-active-group invariant. Renaming the short ID is
    not supported.
    """
    from .frontmatter import dump_document as _dump, parse_file as _pf

    reg, idx = _find_core(name, env)
    current = reg.cores[idx]

    new_leader_at: str | None = None
    if leader_handle is not None:
        new_leader_at = _normalize_pi(leader_handle)
        if not new_leader_at or new_leader_at == "@":
            raise RegistrarError("leader_handle cannot be blank")
        if new_leader_at != _normalize_pi(current.pi):
            for l in reg.labs:
                if l.status == "active" and _normalize_pi(l.pi) == new_leader_at:
                    raise PIAlreadyLeadsAnother(
                        f"{new_leader_at} already leads lab {l.name!r}"
                    )
            for j, c in enumerate(reg.cores):
                if j == idx:
                    continue
                if c.status == "active" and _normalize_pi(c.pi) == new_leader_at:
                    raise PIAlreadyLeadsAnother(
                        f"{new_leader_at} already leads core {c.name!r}"
                    )

    updated = CoreEntry(
        name=current.name,
        pi=new_leader_at if new_leader_at is not None else current.pi,
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

    # Update lab.md frontmatter (filename shared with labs for snapshot plumbing).
    lab_md = Path(current.lab_mgmt_path) / "lab.md"
    if lab_md.is_file():
        parsed = _pf(lab_md)
        meta = dict(parsed.meta or {})
        if display_name is not None:
            if display_name:
                meta["name"] = display_name
            else:
                meta.pop("name", None)
        if new_leader_at is not None:
            meta["pi"] = new_leader_at
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

    # New leader gets a members file (old leader's file is the core's
    # roster decision, not the registrar's; left untouched).
    if new_leader_at is not None and new_leader_at != _normalize_pi(current.pi):
        members_dir = Path(current.lab_mgmt_path) / "members"
        new_leader_member = members_dir / f"{new_leader_at.lstrip('@')}.md"
        if members_dir.is_dir() and not new_leader_member.exists():
            new_leader_member.write_text(
                _render_core_leader_member_md(
                    leader_at=new_leader_at,
                    leader_full_name=leader_full_name,
                    core_name=current.name,
                ),
                encoding="utf-8",
            )

    new_reg = _replace_core(reg, idx, updated)
    write_registry(new_reg, env)

    root = lab_info_root(env)
    _git_init_if_needed(root)
    changed: list[str] = []
    if display_name is not None: changed.append("display_name")
    if new_leader_at is not None and new_leader_at != _normalize_pi(current.pi):
        changed.append(f"leader -> {new_leader_at}")
    if slack_workspace is not None: changed.append("slack_workspace")
    if github_org is not None: changed.append("github_org")
    if oracle_vault is not None: changed.append("oracle_vault")
    if institution is not None: changed.append("institution")
    if department is not None: changed.append("department")
    summary = ", ".join(changed) or "no-op"
    _git_commit_all(root, f"registrar: update core {name} ({summary})")
    return updated


# -----------------------------------------------------------------
# Phase D: collaborations (multi-PI, multi-group)
# -----------------------------------------------------------------


def _find_collaboration(
    name: str, env: dict[str, str] | None = None,
) -> tuple[Registry, int]:
    reg = read_registry(env)
    for i, c in enumerate(reg.collaborations):
        if c.name == name:
            return reg, i
    raise CollaborationNotFound(f"no collaboration with short id: {name!r}")


def _replace_collaboration(
    reg: Registry, idx: int, new_entry: CollaborationEntry,
) -> Registry:
    new_collabs = list(reg.collaborations)
    new_collabs[idx] = new_entry
    return Registry(labs=reg.labs, cores=reg.cores, collaborations=new_collabs, registrars=reg.registrars)


def _normalize_handles(handles: list[str]) -> list[str]:
    """Strip, lowercase, ensure leading @ on each handle. Dedupe."""
    out: list[str] = []
    for h in handles or []:
        norm = f"@{str(h).strip().lstrip('@').lower()}"
        if norm == "@" or norm in out:
            continue
        out.append(norm)
    return out


def _normalize_subset(subset: dict | None) -> dict[str, list[str]]:
    """Apply ``_normalize_handles`` to every list in the subset dict."""
    if not isinstance(subset, dict):
        return {}
    out: dict[str, list[str]] = {}
    for group_id, handles in subset.items():
        if not isinstance(handles, list):
            continue
        out[str(group_id)] = _normalize_handles(handles)
    return out


def _group_members_handles(lab_mgmt_path: Path) -> set[str]:
    """Return the set of ``@handle``s present in ``<lab_mgmt>/members/*.md``.

    Used to validate that a collaboration's ``member_subset`` only
    references real members of the contributing groups.
    """
    from .frontmatter import parse_file as _pf

    members_dir = lab_mgmt_path / "members"
    if not members_dir.is_dir():
        return set()
    out: set[str] = set()
    for md in members_dir.glob("*.md"):
        try:
            meta = _pf(md).meta or {}
        except Exception:
            continue
        handle = str(meta.get("handle") or f"@{md.stem}").strip().lower()
        if not handle.startswith("@"):
            handle = f"@{handle.lstrip('@')}"
        out.add(handle)
    return out


def _enforce_collab_invariants(
    *,
    name: str,
    pis: list[str],
    groups: list[str],
    member_subset: dict[str, list[str]],
    existing: Registry,
    check_duplicate: bool = True,
) -> tuple[dict[str, LabEntry | CoreEntry], dict[str, set[str]]]:
    """Validate a collaboration spec. Returns (group_lookup, members_lookup).

    - Name is lowercase alphanumeric + _ and (when ``check_duplicate``)
      not already taken.
    - At least 2 groups; each must be an ACTIVE lab or core in the registry.
    - At least 2 PIs; each contributing group's PI must appear in ``pis``.
    - ``member_subset`` keys must be a subset of ``groups``; every handle
      listed must be a real member of that group.
    """
    if not name or not _NAME_RE.match(name):
        raise InvalidLabName(
            _invalid_name_message("collaboration", name)
        )
    if check_duplicate and any(c.name == name for c in existing.collaborations):
        raise CollaborationAlreadyExists(f"collaboration already registered: {name}")

    if len(groups) < 2:
        raise InvalidCollaboration("collaboration must span at least 2 groups (labs/cores)")
    if len(pis) < 2:
        raise InvalidCollaboration("collaboration must have at least 2 PIs")

    # Resolve each group to its registry entry; reject unknown/archived.
    group_lookup: dict[str, LabEntry | CoreEntry] = {}
    for g in groups:
        found = next((l for l in existing.labs if l.name == g), None)
        kind = "lab"
        if found is None:
            found = next((c for c in existing.cores if c.name == g), None)
            kind = "core"
        if found is None:
            raise InvalidCollaboration(f"unknown group: {g!r} (no lab or core registered)")
        if found.status != "active":
            raise InvalidCollaboration(
                f"group {g!r} is {found.status}; collaborations require active groups"
            )
        group_lookup[g] = found

    # Each group's PI must be in ``pis``.
    missing_pis: list[str] = []
    for g, entry in group_lookup.items():
        pi_at = _normalize_pi(entry.pi)
        if pi_at not in pis:
            missing_pis.append(f"{pi_at} (PI of {g})")
    if missing_pis:
        raise InvalidCollaboration(
            "every contributing group's PI must be listed in pis; missing: "
            + ", ".join(missing_pis)
        )

    # member_subset must be a subset of groups; every handle must exist.
    members_lookup: dict[str, set[str]] = {}
    for g in member_subset.keys():
        if g not in group_lookup:
            raise InvalidCollaboration(
                f"member_subset references unknown group {g!r}"
            )
    for g, entry in group_lookup.items():
        members_lookup[g] = _group_members_handles(Path(entry.lab_mgmt_path))
        for handle in member_subset.get(g, []):
            if handle not in members_lookup[g]:
                raise InvalidCollaboration(
                    f"@{handle.lstrip('@')} is not a member of group {g!r}"
                )

    # Each PI must appear in their group's subset.
    for g, entry in group_lookup.items():
        pi_at = _normalize_pi(entry.pi)
        subset_for_g = set(member_subset.get(g, []))
        if pi_at not in subset_for_g:
            raise InvalidCollaboration(
                f"member_subset[{g!r}] must include the group's PI {pi_at}"
            )

    return group_lookup, members_lookup


def _render_collaboration_md(
    *,
    name: str,
    pis: list[str],
    groups: list[str],
    member_subset: dict[str, list[str]],
    oracle_vault: str | None,
    created: str,
) -> str:
    meta: dict[str, Any] = {
        "collaboration": name,
        "pis": pis,
        "groups": groups,
        "member_subset": member_subset,
    }
    if oracle_vault:
        meta["oracle_vault"] = oracle_vault
    meta["created"] = created
    body = (
        f"# Collaboration: {name}\n\n"
        f"Cross-group collaboration tracked by the registrar. "
        f"PIs: {', '.join(pis)}. Groups: {', '.join(groups)}.\n\n"
        f"Project files live in `projects/` here; the collaboration's own "
        f"Obsidian vault is rooted at `oracle/`. The lab dashboard never "
        f"surfaces collaboration content — only the collaboration's own "
        f"dashboard does (Phase D follow-on).\n"
    )
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    return f"---\n{yaml_text}---\n\n{body}"


def create_collaboration(
    *,
    name: str,
    pis: list[str],
    groups: list[str],
    member_subset: dict[str, list[str]] | None = None,
    oracle_vault: str | None = None,
    today: _dt.date | None = None,
    env: dict[str, str] | None = None,
) -> CollaborationEntry:
    """Register a new collaboration and scaffold its directory.

    Side effects:
      1. Validates invariants (see ``_enforce_collab_invariants``).
      2. Creates ``<lab_info_root>/collaborations/<name>/`` with
         ``collaboration.md``, ``projects/``, and ``oracle/``.
      3. Adds the entry to ``_registry.yaml``.
      4. Audit-trail commit.
    """
    today_d = today or _dt.date.today()
    norm_pis = _normalize_handles(pis)
    norm_subset = _normalize_subset(member_subset or {})

    existing = read_registry(env)
    _enforce_collab_invariants(
        name=name, pis=norm_pis, groups=groups,
        member_subset=norm_subset, existing=existing,
    )

    root = lab_info_root(env)
    collab_dir = root / "collaborations" / name
    (collab_dir / "projects").mkdir(parents=True, exist_ok=True)
    (collab_dir / "oracle").mkdir(parents=True, exist_ok=True)
    for sub in ("projects", "oracle"):
        gitkeep = collab_dir / sub / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")

    vault = oracle_vault or f"wigamig_collab_{name}"
    (collab_dir / "collaboration.md").write_text(
        _render_collaboration_md(
            name=name, pis=norm_pis, groups=list(groups),
            member_subset=norm_subset, oracle_vault=vault,
            created=today_d.isoformat(),
        ),
        encoding="utf-8",
    )

    entry = CollaborationEntry(
        name=name,
        pis=norm_pis,
        groups=list(groups),
        member_subset=norm_subset,
        oracle_vault=vault,
        status="active",
        created=today_d.isoformat(),
    )
    new_reg = Registry(
        labs=existing.labs, cores=existing.cores,
        collaborations=[*existing.collaborations, entry],
        registrars=existing.registrars,
    )
    write_registry(new_reg, env)

    _git_init_if_needed(root)
    _git_commit_all(
        root,
        f"registrar: create collaboration {name} "
        f"(PIs: {', '.join(norm_pis)}; groups: {', '.join(groups)})",
    )
    return entry


def _set_collab_status(
    name: str, status: str, env: dict[str, str] | None = None,
) -> CollaborationEntry:
    reg, idx = _find_collaboration(name, env)
    current = reg.collaborations[idx]
    if current.status == status:
        return current
    updated = CollaborationEntry(
        name=current.name, pis=list(current.pis), groups=list(current.groups),
        member_subset=dict(current.member_subset),
        oracle_vault=current.oracle_vault, status=status, created=current.created,
    )
    new_reg = _replace_collaboration(reg, idx, updated)
    write_registry(new_reg, env)
    root = lab_info_root(env)
    _git_init_if_needed(root)
    verb = "archive" if status == "archived" else "unarchive" if status == "active" else f"set {status}"
    _git_commit_all(root, f"registrar: {verb} collaboration {name}")
    return updated


def archive_collaboration(name: str, env: dict[str, str] | None = None) -> CollaborationEntry:
    """Soft-delete: ``status -> archived``. Files preserved."""
    return _set_collab_status(name, "archived", env)


def unarchive_collaboration(name: str, env: dict[str, str] | None = None) -> CollaborationEntry:
    """Restore: ``status -> active``. Re-validates invariants against
    the current registry (groups may have been archived in the meantime)."""
    reg, idx = _find_collaboration(name, env)
    current = reg.collaborations[idx]
    if current.status == "active":
        return current
    # Re-validate against current registry but skip the duplicate-name
    # check (this collaboration's own entry is in ``existing``).
    _enforce_collab_invariants(
        name=current.name,
        pis=current.pis, groups=current.groups,
        member_subset=current.member_subset,
        existing=reg, check_duplicate=False,
    )
    return _set_collab_status(name, "active", env)


def update_collaboration(
    name: str,
    *,
    pis: list[str] | None = None,
    groups: list[str] | None = None,
    member_subset: dict[str, list[str]] | None = None,
    oracle_vault: str | None = None,
    env: dict[str, str] | None = None,
) -> CollaborationEntry:
    """Modify a collaboration. ``None`` means "don't touch" per field.

    Renaming is not supported. Invariants are re-enforced on the merged
    spec.
    """
    from .frontmatter import dump_document as _dump, parse_file as _pf

    reg, idx = _find_collaboration(name, env)
    current = reg.collaborations[idx]
    merged_pis = _normalize_handles(pis) if pis is not None else list(current.pis)
    merged_groups = list(groups) if groups is not None else list(current.groups)
    merged_subset = (
        _normalize_subset(member_subset) if member_subset is not None
        else dict(current.member_subset)
    )
    merged_vault = oracle_vault if oracle_vault is not None else current.oracle_vault
    if isinstance(merged_vault, str) and not merged_vault.strip():
        merged_vault = None

    _enforce_collab_invariants(
        name=current.name, pis=merged_pis, groups=merged_groups,
        member_subset=merged_subset, existing=reg, check_duplicate=False,
    )

    updated = CollaborationEntry(
        name=current.name, pis=merged_pis, groups=merged_groups,
        member_subset=merged_subset, oracle_vault=merged_vault,
        status=current.status, created=current.created,
    )

    # Update on-disk collaboration.md too.
    collab_md = lab_info_root(env) / "collaborations" / name / "collaboration.md"
    if collab_md.is_file():
        parsed = _pf(collab_md)
        meta = dict(parsed.meta or {})
        if pis is not None:
            meta["pis"] = merged_pis
        if groups is not None:
            meta["groups"] = merged_groups
        if member_subset is not None:
            meta["member_subset"] = merged_subset
        if oracle_vault is not None:
            if merged_vault is None:
                meta.pop("oracle_vault", None)
            else:
                meta["oracle_vault"] = merged_vault
        collab_md.write_text(_dump(meta, parsed.body or ""), encoding="utf-8")

    new_reg = _replace_collaboration(reg, idx, updated)
    write_registry(new_reg, env)

    root = lab_info_root(env)
    _git_init_if_needed(root)
    changed: list[str] = []
    if pis is not None: changed.append("pis")
    if groups is not None: changed.append("groups")
    if member_subset is not None: changed.append("member_subset")
    if oracle_vault is not None: changed.append("oracle_vault")
    summary = ", ".join(changed) or "no-op"
    _git_commit_all(root, f"registrar: update collaboration {name} ({summary})")
    return updated


# ---------------------------------------------------------------------------
# Per-core member management (cores Phase 1d)
#
# Add/remove members + rotate the leader of an existing core. The
# centre registrar drives these via /api/registrar/core/<name>/...
# endpoints; the storage layer is the per-core lab-mgmt dir at
# <lab_info_root>/cores/<name>/lab-mgmt/members/. See
# docs/cores_plan.md §11 (Phase 1) for the rollout context.
# ---------------------------------------------------------------------------


def _render_core_member_md(
    *,
    handle_at: str,
    full_name: str | None,
    role: str,
    core_name: str,
    status: str = "active",
) -> str:
    """Render members/<handle>.md for a (non-leader) core staff member."""
    meta: dict[str, Any] = {
        "handle": handle_at,
        "full_name": full_name or handle_at.lstrip("@").title(),
        "role": role,
        "status": status,
        "lab": core_name,
    }
    yaml_text = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True).rstrip() + "\n"
    return f"---\n{yaml_text}---\n\n# {handle_at}\n"


def add_core_member(
    *,
    core_name: str,
    handle: str,
    full_name: str | None = None,
    role: str = "staff",
    env: dict[str, str] | None = None,
) -> Path:
    """Add a member to ``core_name``. Writes the member's .md file in
    the core's lab-mgmt/members/ dir + commits via the registrar's
    audit-trail git. Idempotent: re-adding an existing handle is a
    no-op (returns the existing path) rather than an error.

    Raises:
      LabNotFound — no such core.
      MembershipError — handle is empty or invalid shape.
    """
    handle_at = _normalize_pi(handle)
    plain = handle_at.lstrip("@")
    if not plain:
        from .membership import MembershipError
        raise MembershipError("handle is required")
    reg, idx = _find_core(core_name, env)
    core = reg.cores[idx]
    members_dir = Path(core.lab_mgmt_path) / "members"
    members_dir.mkdir(parents=True, exist_ok=True)
    member_path = members_dir / f"{plain}.md"
    if member_path.is_file():
        return member_path
    member_path.write_text(
        _render_core_member_md(
            handle_at=handle_at, full_name=full_name,
            role=role, core_name=core_name,
        ),
        encoding="utf-8",
    )
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root,
        f"registrar: add member {handle_at} ({role}) to core {core_name}")
    return member_path


def remove_core_member(
    *,
    core_name: str,
    handle: str,
    env: dict[str, str] | None = None,
) -> bool:
    """Soft-remove a member from ``core_name`` by flipping their
    frontmatter ``status:`` to ``inactive``. The file is preserved so
    historical references (audit log, past job manifests) keep
    resolving.

    Refuses to remove the current leader: rotate first via
    :func:`rotate_core_leader`, then remove the displaced handle.

    Returns True if a change occurred, False if the member wasn't found
    or was already inactive.
    """
    from .frontmatter import dump_document, parse_file
    handle_at = _normalize_pi(handle)
    plain = handle_at.lstrip("@")
    reg, idx = _find_core(core_name, env)
    core = reg.cores[idx]
    if _normalize_pi(core.pi) == handle_at:
        raise PIAlreadyLeadsAnother(
            f"cannot remove {handle_at}: they are the leader of core {core_name!r}. "
            "Rotate the leader first via rotate_core_leader()."
        )
    member_path = Path(core.lab_mgmt_path) / "members" / f"{plain}.md"
    if not member_path.is_file():
        return False
    parsed = parse_file(member_path)
    meta = dict(parsed.meta or {})
    if str(meta.get("status") or "active") == "inactive":
        return False
    meta["status"] = "inactive"
    member_path.write_text(
        dump_document(meta, parsed.body or ""), encoding="utf-8",
    )
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root,
        f"registrar: deactivate member {handle_at} in core {core_name}")
    return True


def rotate_core_leader(
    *,
    core_name: str,
    new_handle: str,
    new_full_name: str | None = None,
    env: dict[str, str] | None = None,
) -> CoreEntry:
    """Replace the leader of ``core_name`` with ``new_handle``.

    Effects:
      1. ``_registry.yaml``: ``cores.<name>.pi`` becomes the new handle.
      2. ``cores/<name>/lab-mgmt/lab.md`` frontmatter ``pi:`` updated.
      3. The new leader's member file (members/<new>.md) is created
         with role ``core_leader`` if absent; if present, their role
         is upgraded to ``core_leader``.
      4. The old leader's member file (members/<old>.md) is kept; their
         role is demoted to ``staff`` so they remain a regular core
         member. Caller can subsequently :func:`remove_core_member`
         them if they're leaving the core entirely.

    Refuses if ``new_handle`` already leads another active group (lab
    or core) — single-lead-per-group rule per ``_enforce_core_create_invariants``.

    Returns the updated CoreEntry.
    """
    from .frontmatter import dump_document, parse_file
    new_at = _normalize_pi(new_handle)
    reg, idx = _find_core(core_name, env)
    core = reg.cores[idx]
    old_at = _normalize_pi(core.pi)
    if new_at == old_at:
        return core   # no-op
    # Single-lead-per-group rule (matches create_core).
    for l in reg.labs:
        if l.status == "active" and _normalize_pi(l.pi) == new_at:
            raise PIAlreadyLeadsAnother(
                f"cannot rotate {core_name} to {new_at}: they lead active lab {l.name!r}."
            )
    for j, c in enumerate(reg.cores):
        if j == idx:
            continue
        if c.status == "active" and _normalize_pi(c.pi) == new_at:
            raise PIAlreadyLeadsAnother(
                f"cannot rotate {core_name} to {new_at}: they lead active core {c.name!r}."
            )
    # Update the in-memory registry + persist.
    updated = CoreEntry(
        name=core.name, pi=new_at,
        lab_mgmt_path=core.lab_mgmt_path,
        status=core.status, created=core.created,
        slack_workspace=core.slack_workspace,
        github_org=core.github_org,
        oracle_vault=core.oracle_vault,
    )
    new_reg = _replace_core(reg, idx, updated)
    write_registry(new_reg, env)
    # Update lab.md frontmatter.
    lab_md = Path(core.lab_mgmt_path) / "lab.md"
    if lab_md.is_file():
        parsed = parse_file(lab_md)
        meta = dict(parsed.meta or {})
        meta["pi"] = new_at
        lab_md.write_text(dump_document(meta, parsed.body or ""), encoding="utf-8")
    members_dir = Path(core.lab_mgmt_path) / "members"
    members_dir.mkdir(parents=True, exist_ok=True)
    # New leader's member file.
    new_plain = new_at.lstrip("@")
    new_path = members_dir / f"{new_plain}.md"
    if new_path.is_file():
        parsed = parse_file(new_path)
        meta = dict(parsed.meta or {})
        meta["role"] = "core_leader"
        meta["status"] = "active"
        new_path.write_text(dump_document(meta, parsed.body or ""), encoding="utf-8")
    else:
        new_path.write_text(
            _render_core_leader_member_md(
                leader_at=new_at, leader_full_name=new_full_name,
                core_name=core.name,
            ),
            encoding="utf-8",
        )
    # Old leader demoted to staff (kept on the roster; not deleted).
    old_plain = old_at.lstrip("@")
    old_path = members_dir / f"{old_plain}.md"
    if old_path.is_file():
        parsed = parse_file(old_path)
        meta = dict(parsed.meta or {})
        if meta.get("role") == "core_leader":
            meta["role"] = "staff"
            old_path.write_text(dump_document(meta, parsed.body or ""), encoding="utf-8")
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root,
        f"registrar: rotate core {core_name} leader: {old_at} -> {new_at}")
    return updated
