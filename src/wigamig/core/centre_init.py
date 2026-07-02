"""
Purpose: First-time centre bootstrap ("mayor" flow). One person clones
         wigamig, runs ``wigamig centre-init``, ends up as the centre's
         first registrar.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-26

The mayor is **bootstrap-only**: after ``init_centre()`` succeeds, the
same handle is the first registrar. There is no permanent "mayor"
role with extra runtime powers — the title survives only as
``founding_mayor:`` in ``centre.md`` frontmatter for audit.

Storage (single source of truth = ``<lab_info>/centre.md`` frontmatter):

  <lab_info>/centre.md
    ---
    name: 'Western Bioconvergence Centre'
    institution: 'Western University'
    unique_name: 'western'            # non-institution-specific install id
    slack_workspace: 'T0XXXXX'        # Slack team/workspace id
    github_org: 'centre-westernu'     # canonical centre github org
    data_server: 'lab-server.example.edu'   # legacy alias of server_host
    server_host: 'lab-server.example.edu'   # the "wigamig server" hostname/IP
    server_account: 'wigamig'         # ssh login account on the server
    cc_install_path: '/opt/claude'    # where Claude Code lives on the server
    obsidian_vault: '/mayor/obsidian' # centre-level markdown pool
    mayor_root: '/mayor/wigamig'      # high-level centre dir (mirrorable)
    public_hub: 'github.com/hallettmiket/wigamig_public#western'
    raw_root: '/data/lab_vm/raw'
    refined_root: '/data/lab_vm/refined'
    created: '2026-05-26'
    founding_mayor: '@tbrowne'
    ---

  ``unique_name`` is the institution's install identifier used to name the
  ``wigamig_<name>`` repo, Slack channels, and ``wgm_<project>`` groups. It is
  deliberately distinct from ``name`` (display) and ``institution`` so a
  deployment is never hardcoded to one university. ``server_host`` (with
  ``data_server`` kept as a back-compat alias) names the always-online
  "wigamig server"; the remaining fields drive the mayor's server-setup form.

We deliberately do NOT bloat ``_registry.yaml`` with a centre block —
``write_registry()`` doesn't preserve unknown keys and the analogue
with ``registrar.md`` is the cleaner pattern. ``init_centre()`` does
however register the founding mayor as a centre registrar in
``_registry.yaml:registrars:`` so ``is_registrar()`` honours them
without falling back to the per-machine sentinel.

Re-running ``init_centre()`` after a successful bootstrap raises
``CentreAlreadyInitialised`` (the CLI maps this to an exit code).
This guards against accidental overwrites of a live centre.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .frontmatter import parse_file
from . import registrar as _R
from .registrar import (
    _git_commit_all, _git_init_if_needed,
    _normalize,
    lab_info_root,
    read_registry, write_registry,
)


CENTRE_FILENAME = "centre.md"

# Required keys for a complete centre profile.
REQUIRED_KEYS = ("name", "institution", "founding_mayor")

# All recognised keys (anything else is preserved but ignored by readers).
KNOWN_KEYS = (
    "name", "institution", "unique_name", "slack_workspace", "github_org",
    "data_server", "server_host", "server_account", "cc_install_path",
    "obsidian_vault", "mayor_root", "public_hub",
    "raw_root", "refined_root",
    "created", "founding_mayor",
)


class CentreInitError(RuntimeError):
    """Centre bootstrap failed."""


class CentreAlreadyInitialised(CentreInitError):
    """``centre.md`` already exists; refuse to overwrite."""


@dataclass
class CentreProfile:
    """In-memory representation of ``centre.md`` frontmatter."""

    name: str
    institution: str
    founding_mayor: str                    # @handle (no leading @)
    unique_name: str = ""                  # non-institution-specific install id
    slack_workspace: str = ""
    github_org: str = ""
    data_server: str = ""                  # legacy alias of server_host
    server_host: str = ""                  # the "wigamig server" hostname/IP
    server_account: str = ""               # ssh login account on the server
    cc_install_path: str = ""              # where Claude Code lives on the server
    obsidian_vault: str = ""               # centre-level markdown pool
    mayor_root: str = ""                   # high-level centre dir (mirrorable)
    public_hub: str = ""                   # global wigamig_public + this centre's label
    raw_root: str = ""
    refined_root: str = ""
    created: str = ""
    path: Path | None = None

    @property
    def server(self) -> str:
        """The wigamig server hostname, preferring ``server_host`` and
        falling back to the legacy ``data_server`` alias."""
        return self.server_host or self.data_server

    @property
    def install_id(self) -> str:
        """The install identifier used to name repos/channels/groups.
        Falls back to a slug-ish ``institution`` when ``unique_name`` is
        unset so older centres still resolve to *something* deterministic."""
        return self.unique_name or self.institution


# ---------------------------------------------------------------------------
# Paths + reader
# ---------------------------------------------------------------------------

def centre_path(env: dict[str, str] | None = None) -> Path:
    """``<lab_info>/centre.md``."""
    return lab_info_root(env) / CENTRE_FILENAME


def read_centre(env: dict[str, str] | None = None) -> CentreProfile | None:
    """Return the centre profile or ``None`` if no centre is initialised.

    Malformed file also returns ``None`` (callers treat both states as
    "no centre yet" and trigger the mayor wizard).
    """
    p = centre_path(env)
    if not p.is_file():
        return None
    try:
        parsed = parse_file(p)
    except Exception:
        return None
    meta = parsed.meta or {}
    name = str(meta.get("name") or "").strip()
    institution = str(meta.get("institution") or "").strip()
    mayor = _normalize(str(meta.get("founding_mayor") or ""))
    if not (name and institution and mayor):
        return None
    return CentreProfile(
        name=name,
        institution=institution,
        founding_mayor=mayor,
        unique_name=str(meta.get("unique_name") or "").strip(),
        slack_workspace=str(meta.get("slack_workspace") or "").strip(),
        github_org=str(meta.get("github_org") or "").strip(),
        data_server=str(meta.get("data_server") or "").strip(),
        server_host=str(meta.get("server_host") or "").strip(),
        server_account=str(meta.get("server_account") or "").strip(),
        cc_install_path=str(meta.get("cc_install_path") or "").strip(),
        obsidian_vault=str(meta.get("obsidian_vault") or "").strip(),
        mayor_root=str(meta.get("mayor_root") or "").strip(),
        public_hub=str(meta.get("public_hub") or "").strip(),
        raw_root=str(meta.get("raw_root") or "").strip(),
        refined_root=str(meta.get("refined_root") or "").strip(),
        created=str(meta.get("created") or "").strip(),
        path=p,
    )


def is_initialised(env: dict[str, str] | None = None) -> bool:
    """True iff ``centre.md`` exists AND has all required fields."""
    return read_centre(env) is not None


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def _render_centre(profile: CentreProfile) -> str:
    meta: dict[str, Any] = {
        "name": profile.name,
        "institution": profile.institution,
        "unique_name": profile.unique_name,
        "slack_workspace": profile.slack_workspace,
        "github_org": profile.github_org,
        "data_server": profile.data_server,
        "server_host": profile.server_host,
        "server_account": profile.server_account,
        "cc_install_path": profile.cc_install_path,
        "obsidian_vault": profile.obsidian_vault,
        "mayor_root": profile.mayor_root,
        "public_hub": profile.public_hub,
        "raw_root": profile.raw_root,
        "refined_root": profile.refined_root,
        "created": profile.created,
        "founding_mayor": f"@{profile.founding_mayor.lstrip('@')}",
    }
    # Strip empty optionals to keep the file readable.
    meta = {k: v for k, v in meta.items()
            if k in ("name", "institution", "founding_mayor", "created")
            or v}
    yaml_text = yaml.safe_dump(meta, sort_keys=False).rstrip()
    body = (
        "# Centre profile\n\n"
        f"This file declares the wigamig centre at **{profile.institution}**.\n"
        "Edit through the `/registrar` profile editor or hand-edit this "
        "frontmatter directly.\n"
    )
    return f"---\n{yaml_text}\n---\n\n{body}"


def init_centre(
    *,
    name: str,
    institution: str,
    founding_mayor: str,
    unique_name: str = "",
    slack_workspace: str = "",
    github_org: str = "",
    data_server: str = "",
    server_host: str = "",
    server_account: str = "",
    cc_install_path: str = "",
    obsidian_vault: str = "",
    mayor_root: str = "",
    public_hub: str = "",
    raw_root: str = "",
    refined_root: str = "",
    env: dict[str, str] | None = None,
    write_sentinel: bool = True,
) -> CentreProfile:
    """Idempotency-checked bootstrap. Refuses if a centre exists.

    Side effects (in order, transactional via the git commit at the
    end — a partial write that fails mid-way leaves an inconsistent
    state but the lab_info git ledger will reflect what landed):

    1. Write ``<lab_info>/centre.md`` with the profile.
    2. Add ``@founding_mayor`` to ``_registry.yaml:registrars:``.
    3. Write the per-machine sentinel ``~/.wigamig/registrar`` with the
       mayor's handle (used for git commit identity on this machine
       only — does NOT gate auth). Skipped when
       ``write_sentinel=False`` (useful in tests).
    4. ``git init`` the lab_info root if needed and commit
       "centre initialised: <name>".
    """
    if not name.strip():
        raise CentreInitError("centre name is required")
    if not institution.strip():
        raise CentreInitError("centre institution is required")
    mayor_clean = _normalize(founding_mayor)
    if not mayor_clean:
        raise CentreInitError(
            "founding_mayor is required (@handle of the bootstrapper)"
        )
    if is_initialised(env):
        raise CentreAlreadyInitialised(
            f"centre is already initialised at {centre_path(env)}; "
            "refusing to overwrite (re-edit via the /registrar profile editor)."
        )

    today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    profile = CentreProfile(
        name=name.strip(),
        institution=institution.strip(),
        founding_mayor=mayor_clean,
        unique_name=unique_name.strip(),
        slack_workspace=slack_workspace.strip(),
        github_org=github_org.strip(),
        data_server=data_server.strip(),
        server_host=server_host.strip(),
        server_account=server_account.strip(),
        cc_install_path=cc_install_path.strip(),
        obsidian_vault=obsidian_vault.strip(),
        mayor_root=mayor_root.strip(),
        public_hub=public_hub.strip(),
        raw_root=raw_root.strip(),
        refined_root=refined_root.strip(),
        created=today,
    )

    # 1. Write centre.md.
    p = centre_path(env)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_render_centre(profile), encoding="utf-8")
    profile.path = p

    # 2. Add mayor to _registry.yaml:registrars:.
    existing = read_registry(env)
    if mayor_clean not in existing.registrars:
        existing.registrars.append(mayor_clean)
        write_registry(existing, env)

    # 3. Per-machine sentinel (best-effort; failure is non-fatal).
    # Look up the sentinel path via the registrar module at call time
    # so tests can monkeypatch it after import.
    if write_sentinel:
        try:
            sentinel = _R.REGISTRAR_SENTINEL
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text(mayor_clean + "\n", encoding="utf-8")
        except OSError:
            pass

    # 4. Audit-trail commit.
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root, f"centre initialised: {profile.name}")
    return profile


def update_centre(
    updates: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> CentreProfile:
    """Partial update on an existing centre profile. Used by the
    /registrar profile editor; refuses if no centre is initialised."""
    current = read_centre(env)
    if current is None:
        raise CentreInitError(
            "no centre initialised yet; run `wigamig centre-init` first."
        )
    # Founding mayor is immutable post-init (audit value).
    updates = {k: v for k, v in updates.items()
               if k in KNOWN_KEYS and k != "founding_mayor"}
    for k, v in updates.items():
        if v is None:
            continue
        setattr(current, k, str(v).strip())
    p = centre_path(env)
    p.write_text(_render_centre(current), encoding="utf-8")
    root = lab_info_root(env)
    _git_init_if_needed(root)
    changed = ", ".join(sorted(updates.keys())) or "no-op"
    _git_commit_all(root, f"centre: update profile ({changed})")
    return current


__all__ = [
    "CENTRE_FILENAME", "REQUIRED_KEYS", "KNOWN_KEYS",
    "CentreInitError", "CentreAlreadyInitialised",
    "CentreProfile",
    "centre_path", "read_centre", "is_initialised",
    "init_centre", "update_centre",
]
