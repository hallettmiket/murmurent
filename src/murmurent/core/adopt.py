"""
Purpose: Single chokepoint for "adopt this existing clone as a murmurent
        project" + "has this repo been adopted yet?" — shared by the
        dashboard endpoint (``POST /api/inventory/adopt``) and the CLI
        (``murmurent repo adopt`` / ``murmurent repo status``).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-14
Input: Path to a git clone (local or on a registered SSH host) + project
       metadata (lead, members, sensitivity, agents, …).
Output: :class:`AdoptOutcome` wrapping the :class:`projectize.ProjectizeResult`,
        or :class:`AdoptionStatus` for the read-only check.

Before this module existed the validation + host-branching lived inline
in the dashboard endpoint, so the CLI had no way to adopt a repo without
going through HTTP. The endpoint and the CLI now both call
:func:`adopt_clone`; errors are raised as :class:`AdoptError` with a
machine-readable ``code`` that the endpoint maps onto HTTP statuses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from . import hosts as _hosts
from . import projectize as _proj
from . import remote as _remote

# code → the HTTP status the dashboard endpoint responds with. Kept here
# so the mapping can't drift from the codes adopt_clone() raises.
ERROR_HTTP_STATUS = {
    "host_not_found": 404,
    "bad_request": 400,
    "conflict": 409,
    "charter_failed": 422,
    "ssh_failed": 502,
    "internal": 500,
}


class AdoptError(Exception):
    """Adoption refused or failed. ``code`` is one of ERROR_HTTP_STATUS."""

    def __init__(self, message: str, *, code: str = "internal") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class AdoptOutcome:
    """What :func:`adopt_clone` produced, host-agnostic."""

    project: str
    host: str
    clone_path: str
    result: _proj.ProjectizeResult

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "project": self.project,
            "host": self.host,
            "clone_path": self.clone_path,
            "registry_path": (
                str(self.result.registry_path) if self.result.registry_path else None
            ),
            "manifest_path": (
                str(self.result.manifest_path) if self.result.manifest_path else None
            ),
            "probes": [p.to_dict() for p in self.result.probes],
        }


def _local_wigamig_base() -> str:
    """This machine's wigamig base (raw/refined/notebook parent).

    Read via the dashboard's machine-settings loader so we honour the
    same ``~/.murmurent/machine.yaml`` + legacy fallbacks the adopt
    endpoint always used. Lazy import — core shouldn't pull the
    dashboard package in at import time.
    """
    try:
        from ..dashboard import machine_settings as _ms

        ms = _ms.load()
        return (ms.wigamig_base or "~/wigamig").rstrip("/")
    except Exception:
        return "~/wigamig"


def adopt_clone(
    *,
    clone_path: str,
    project: str,
    lead: str,
    members: list[str],
    sensitivity: str = "standard",
    description: str = "",
    choreography: str | None = None,
    agents: list[str] | None = None,
    host: str = "local",
    reb_number: str | None = None,
    reb_expires: str | None = None,
    data_residency: str | None = None,
    actor: str = "",
    installations_dir: Path | None = None,
) -> AdoptOutcome:
    """Adopt an existing git clone as a murmurent project.

    ``host == "local"`` validates the path against ``~/repos/`` and
    writes everything on this filesystem. Any other value must name a
    registered SSH host: CHARTER + bootstrap are written on the remote
    over one batched SSH session, while the local-side artefacts
    (cert-project registry, installation manifest with ``ssh_remote``)
    still land on this machine.

    Raises :class:`AdoptError`; never touches HTTP.
    """
    installations_dir = installations_dir or _proj.INSTALLATIONS_DIR_DEFAULT
    actor = (actor or os.environ.get("MURMURENT_USER", "")).strip().lstrip("@") \
        or lead.lstrip("@")

    if host and host != "local":
        return _adopt_remote(
            clone_path=clone_path, project=project, lead=lead, members=members,
            sensitivity=sensitivity, description=description,
            choreography=choreography, agents=agents, host=host,
            reb_number=reb_number, reb_expires=reb_expires,
            data_residency=data_residency, actor=actor,
            installations_dir=installations_dir,
        )

    # ---- Local adopt ----
    clone = Path(clone_path).expanduser().resolve()
    repos_root = (Path.home() / "repos").resolve()
    try:
        clone.relative_to(repos_root)
    except ValueError:
        raise AdoptError(
            f"clone_path must live under {repos_root} (got {clone})",
            code="bad_request",
        )
    if not (clone / ".git").exists():
        raise AdoptError(f"not a git working tree: {clone}", code="bad_request")
    if (clone / "CHARTER.md").exists():
        raise AdoptError(
            f"{clone / 'CHARTER.md'} already exists — "
            "edit by hand instead of re-adopting",
            code="conflict",
        )

    wb = _local_wigamig_base()
    try:
        result = _proj.make_wigamig_project(
            clone_path=clone,
            project=project,
            lead=lead,
            members=members,
            sensitivity=sensitivity,
            description=description,
            choreography=choreography,
            agents=list(agents or []),
            reb_number=reb_number,
            reb_expires=reb_expires,
            data_residency=data_residency,
            member=actor,
            machine_type="laptop",
            hostname=os.uname().nodename,
            username=os.environ.get("USER", ""),
            has_direct_access=True,
            lab_base=wb,
            raw_path=f"{wb}/raw",
            refined_path=f"{wb}/refined",
            notebook_path=f"{wb}/lab_notebooks",
            installations_dir=installations_dir,
        )
    except Exception as exc:
        raise AdoptError(f"projectize failed: {exc}", code="internal") from exc

    _raise_if_charter_failed(result)
    return AdoptOutcome(project=project, host="local",
                        clone_path=str(clone), result=result)


def _adopt_remote(
    *,
    clone_path: str,
    project: str,
    lead: str,
    members: list[str],
    sensitivity: str,
    description: str,
    choreography: str | None,
    agents: list[str] | None,
    host: str,
    reb_number: str | None,
    reb_expires: str | None,
    data_residency: str | None,
    actor: str,
    installations_dir: Path,
) -> AdoptOutcome:
    """SSH-host branch of :func:`adopt_clone`."""
    try:
        host_obj = _hosts.resolve(host)
    except _hosts.HostNotFound as exc:
        raise AdoptError(str(exc), code="host_not_found") from exc
    if host_obj.kind != "ssh":
        raise AdoptError(f"host {host!r} is not an SSH host", code="bad_request")

    # Probe: does the path exist on the remote and have .git? One SSH
    # round-trip; the remote-adopt script itself handles the CHARTER-
    # already-exists case (emits ``charter:ok:already exists…`` instead
    # of overwriting), so no second probe for it here.
    rem = _remote.Remote(host_obj)
    qpath = clone_path.replace("'", "'\\''")
    try:
        res = rem.run(
            f"if [ -d '{qpath}/.git' ]; then echo OK; "
            f"elif [ -d '{qpath}' ]; then echo NOGIT; "
            f"else echo NOPATH; fi",
            check=False, timeout=20,
        )
    except _remote.RemoteError as exc:
        raise AdoptError(
            f"ssh probe to {host} failed: {(exc.stderr or str(exc)).strip()}",
            code="ssh_failed",
        ) from exc
    verdict = (res.stdout or "").strip().splitlines()[-1] if res.stdout else ""
    if verdict == "NOPATH":
        raise AdoptError(
            f"path does not exist on {host}: {clone_path}", code="bad_request"
        )
    if verdict == "NOGIT":
        raise AdoptError(
            f"not a git working tree on {host}: {clone_path}", code="bad_request"
        )
    if verdict != "OK":
        raise AdoptError(
            f"unexpected probe verdict {verdict!r}: {res.stderr or ''}",
            code="ssh_failed",
        )

    wb = (host_obj.lab_vm_root or "~/wigamig").rstrip("/")
    try:
        result = _proj.make_wigamig_project(
            clone_path=Path(clone_path),
            project=project,
            lead=lead,
            members=members,
            sensitivity=sensitivity,
            description=description,
            choreography=choreography,
            agents=list(agents or []),
            reb_number=reb_number,
            reb_expires=reb_expires,
            data_residency=data_residency,
            member=actor,
            machine_type="lab_server",
            hostname=host_obj.ssh_host or host,
            username=host_obj.remote_user or "",
            has_direct_access=False,
            lab_base=wb,
            raw_path=f"{wb}/raw",
            refined_path=f"{wb}/refined",
            notebook_path=f"{wb}/lab_notebooks",
            ssh_remote=host,
            mount_point=host_obj.mount_point or None,
            installations_dir=installations_dir,
        )
    except Exception as exc:
        raise AdoptError(f"projectize failed: {exc}", code="internal") from exc

    _raise_if_charter_failed(result)
    return AdoptOutcome(project=project, host=host,
                        clone_path=clone_path, result=result)


def _raise_if_charter_failed(result: _proj.ProjectizeResult) -> None:
    """A failed charter probe means the adopt didn't take — surface it
    as a hard error (422 on the endpoint side)."""
    charter_probe = next((p for p in result.probes if p.name == "charter"), None)
    if charter_probe and charter_probe.status == "fail":
        raise AdoptError(charter_probe.detail, code="charter_failed")


# ---------------------------------------------------------------------------
# Read-only: has this repo been adopted yet?
# ---------------------------------------------------------------------------


@dataclass
class AdoptionStatus:
    """Adoption state of one clone on one host.

    ``adopted`` matches the Repos panel's ``✓ murmurent`` signal
    (CHARTER.md + ``.claude/agents/`` in the working tree).
    ``manifest_path`` additionally reports the local-side installation
    manifest, when one references this clone.
    """

    host: str
    path: str
    exists: bool
    is_git: bool
    has_charter: bool
    has_claude_agents: bool
    manifest_path: str | None = None

    @property
    def adopted(self) -> bool:
        return self.exists and self.is_git and self.has_charter and self.has_claude_agents

    @property
    def verdict(self) -> str:
        """One-word-ish summary for tables + headlines."""
        if not self.exists:
            return "missing"
        if not self.is_git:
            return "not a git repo"
        if self.adopted:
            return "adopted"
        if self.has_charter or self.has_claude_agents:
            return "partial"
        return "plain clone"

    def to_dict(self) -> dict:
        return {
            "host": self.host,
            "path": self.path,
            "exists": self.exists,
            "is_git": self.is_git,
            "has_charter": self.has_charter,
            "has_claude_agents": self.has_claude_agents,
            "manifest_path": self.manifest_path,
            "adopted": self.adopted,
            "verdict": self.verdict,
        }


def find_manifest_for(clone_path: str, *, host: str = "local",
                      installations_dir: Path | None = None) -> Path | None:
    """Return the installation manifest that references ``clone_path``
    on ``host``, if any. Manifests always live on THIS machine (remote
    installs carry ``ssh_remote``), so this is a local scan either way.
    """
    installations_dir = installations_dir or _proj.INSTALLATIONS_DIR_DEFAULT
    if not installations_dir.is_dir():
        return None
    if host == "local":
        want = str(Path(clone_path).expanduser().resolve())
    else:
        want = clone_path.rstrip("/")
    # Fallback when no manifest records this exact path: manifests are
    # keyed <project>.yaml and adopt defaults project = basename, so a
    # same-named manifest on the same host is almost certainly this
    # clone (recorded from a different mount/home prefix).
    name_match: Path | None = None
    want_name = Path(clone_path).name
    for mf in sorted(installations_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(mf.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        remote = data.get("ssh_remote") or "local"
        if remote != host:
            continue
        if name_match is None and str(data.get("project") or "") == want_name:
            name_match = mf
        for repo in data.get("repos") or []:
            if not isinstance(repo, dict):
                continue
            raw = str(repo.get("path") or "").rstrip("/")
            if not raw:
                continue
            if host == "local":
                try:
                    got = str(Path(raw).expanduser().resolve())
                except OSError:
                    got = raw
            else:
                got = raw
            if got == want:
                return mf
    return name_match


def adoption_status(clone_path: str, *, host: str = "local",
                    installations_dir: Path | None = None) -> AdoptionStatus:
    """Report whether the clone at ``clone_path`` on ``host`` has been
    adopted (murmurent-ready). Read-only; safe on any directory.

    Local hosts are checked on the filesystem; SSH hosts with a single
    batched probe. Raises :class:`AdoptError` (``host_not_found`` /
    ``ssh_failed``) only for host-resolution or connection problems —
    a missing path is a normal ``exists=False`` answer, not an error.
    """
    if host == "local":
        p = Path(clone_path).expanduser().resolve()
        exists = p.is_dir()
        st = AdoptionStatus(
            host="local",
            path=str(p),
            exists=exists,
            is_git=exists and (p / ".git").is_dir(),
            has_charter=exists and (p / "CHARTER.md").is_file(),
            has_claude_agents=exists and (p / ".claude" / "agents").is_dir(),
        )
    else:
        try:
            host_obj = _hosts.resolve(host)
        except _hosts.HostNotFound as exc:
            raise AdoptError(str(exc), code="host_not_found") from exc
        rem = _remote.Remote(host_obj)
        qpath = clone_path.replace("'", "'\\''")
        script = (
            f"p='{qpath}'; "
            'e=0; [ -d "$p" ] && e=1; '
            'g=0; [ -d "$p/.git" ] && g=1; '
            'c=0; [ -f "$p/CHARTER.md" ] && c=1; '
            'a=0; [ -d "$p/.claude/agents" ] && a=1; '
            'echo "$e|$g|$c|$a"'
        )
        try:
            res = rem.run(script, check=False, timeout=20)
        except _remote.RemoteError as exc:
            raise AdoptError(
                f"ssh probe to {host} failed: {(exc.stderr or str(exc)).strip()}",
                code="ssh_failed",
            ) from exc
        line = (res.stdout or "").strip().splitlines()[-1] if res.stdout else ""
        parts = line.split("|")
        if len(parts) != 4:
            raise AdoptError(
                f"unexpected probe output from {host}: {line!r}", code="ssh_failed"
            )
        e, g, c, a = (x == "1" for x in parts)
        st = AdoptionStatus(
            host=host, path=clone_path, exists=e, is_git=g,
            has_charter=c, has_claude_agents=a,
        )

    mf = find_manifest_for(st.path, host=host, installations_dir=installations_dir)
    st.manifest_path = str(mf) if mf else None
    return st
