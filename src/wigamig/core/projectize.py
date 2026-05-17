"""
Purpose: Single chokepoint for "make this clone a wigamig project".
Author: Mike Hallett (with Claude Code)
Date: 2026-05-17
Input: Path to a git working tree on this machine + project metadata
       (lead, members, sensitivity, choreography, agents) + the
       installation context (machine_type, hostname, username,
       lab_base, raw/refined/notebook paths, optional ssh_remote).
Output: ``ProjectizeResult`` — list of :class:`preflight.Probe` rows
        + paths to every artefact written.

Both ``POST /api/inventory/adopt`` and ``POST /api/workspace/initialize``
need the same four side effects, in this order:

  1. **CHARTER.md** at the clone root — skipped if present (refuses to
     overwrite hand-edited metadata).
  2. **Lab-mgmt registry** entry at ``lab_mgmt/projects/<name>.md`` —
     skipped if present. Writing the file does NOT commit it; the user
     decides when to publish to lab_mgmt.
  3. **Installation manifest** at ``~/.wigamig/installations/<name>.yaml``
     — written every time, carries member + paths + agents picked.
  4. **Layer-2 CC bootstrap** — ``.claude/agents/`` symlinks into the
     wigamig commons + ``CLAUDE.md`` stub.

This module exists so the two endpoints can't drift. Before it existed,
``adopt`` wrote (1) + (4) only — repos adopted from the Repos panel
never showed up in Projects or Installations. ``workspace_initialize``
wrote (3) + (4) but assumed (1) existed already (404'd otherwise), so
the Repos panel's "+ install" on a bare clone went nowhere.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import charter as _charter
from . import preflight as _pf
from . import project_cc_init as _cci
from .projects import (
    lab_mgmt_project_registry_path,
    render_registry_entry,
)
from .projects import ProjectSummary
from .repo import wigamig_repo_root


INSTALLATIONS_DIR_DEFAULT = Path.home() / ".wigamig" / "installations"


@dataclass
class ProjectizeResult:
    """What ``make_wigamig_project`` produced.

    ``probes`` carries one row per step so the UI can render the same
    green/yellow/red ladder the install wizard already uses. The
    ``*_path`` fields are absolute paths to artefacts the caller may
    want to surface in success messages (e.g. "wrote CHARTER.md at …").
    """

    probes: list[_pf.Probe] = field(default_factory=list)
    charter_path: Path | None = None
    registry_path: Path | None = None
    manifest_path: Path | None = None


def make_wigamig_project(
    *,
    clone_path: Path,
    project: str,
    lead: str,
    members: list[str],
    sensitivity: str = "standard",
    description: str = "",
    choreography: str | None = None,
    agents: list[str] | None = None,
    member: str = "",
    machine_type: str = "laptop",
    hostname: str = "",
    username: str = "",
    has_direct_access: bool = True,
    lab_base: str = "~/wigamig",
    raw_path: str = "~/wigamig/raw",
    refined_path: str = "~/wigamig/refined",
    notebook_path: str = "~/wigamig/lab_notebooks",
    ssh_remote: str | None = None,
    remote_home: str | None = None,
    mount_point: str | None = None,
    infra_components: list[str] | None = None,
    reb_number: str | None = None,
    reb_expires: str | None = None,
    data_residency: str | None = None,
    installations_dir: Path | None = None,
    today: str | None = None,
) -> ProjectizeResult:
    """Run all four projectize steps. Idempotent — re-running on a
    repo that already has CHARTER.md / lab_mgmt entry preserves them.

    The caller is responsible for path validation (clone_path exists,
    is under ~/repos, is a git working tree). This function trusts its
    input — the endpoint layer applies the policy guards.
    """
    today = today or _dt.date.today().isoformat()
    agents = list(agents or [])
    members = list(members)
    infra_components = list(infra_components or [])
    installations_dir = installations_dir or INSTALLATIONS_DIR_DEFAULT
    result = ProjectizeResult()

    # ---- 1. CHARTER.md --------------------------------------------------
    # Render upfront — both local and SSH paths need the same body. If
    # the metadata is invalid the schema check fires before we touch
    # any filesystem (local or remote).
    try:
        charter_text = _charter.render_charter(
            project=project,
            lead=lead,
            members=members,
            sensitivity=sensitivity,
            description=description or f"Adopted clone at {clone_path}.",
            choreography=choreography,
            reb_number=reb_number,
            reb_expires=reb_expires,
            data_residency=data_residency,
            created=today,
            repo_kind="github",
        )
    except _charter.CharterError as exc:
        result.probes.append(_pf.Probe(
            name="charter", status="fail",
            detail=str(exc), required=True,
        ))
        return result

    charter_path = clone_path / "CHARTER.md"
    result.charter_path = charter_path
    if ssh_remote:
        # SSH branch: CHARTER + bootstrap happen in one batched session
        # on the remote host. We collect those probes here so they
        # render in the same place the local branch's probes do.
        from . import hosts as _hosts_resolve
        from . import remote_adopt as _radopt
        try:
            host_obj = _hosts_resolve.resolve(ssh_remote)
        except _hosts_resolve.HostNotFound as exc:
            result.probes.append(_pf.Probe(
                name="ssh_host", status="fail",
                detail=str(exc), required=True,
            ))
            # Fall through so the local manifest + registry still land —
            # the user can re-run remote adopt after fixing the host.
        else:
            # When ``ssh_remote`` is set, ``clone_path`` is interpreted
            # as the path on the *remote host*, NOT the laptop. The
            # caller is responsible for synthesizing the right value
            # (typically ``<host.project_root>/<project>``). This keeps
            # projectize stateless about which side owns which path —
            # both branches treat ``clone_path`` as authoritative for
            # the target host.
            remote_probes = _radopt.adopt_remote_clone(
                host=host_obj,
                clone_path=str(clone_path),
                project=project,
                charter_text=charter_text,
                agents=agents,
            )
            result.probes.extend(remote_probes)
    elif charter_path.exists():
        result.probes.append(_pf.Probe(
            name="charter", status="ok",
            detail=f"{charter_path} (already exists, preserved)",
            required=True,
        ))
    else:
        charter_path.write_text(charter_text, encoding="utf-8")
        result.probes.append(_pf.Probe(
            name="charter", status="ok",
            detail=f"wrote {charter_path}", required=True,
        ))

    # ---- 2. Lab-mgmt registry ------------------------------------------
    # Build a synthesized ProjectSummary — we don't re-parse the CHARTER
    # we just wrote because we already have the source values.
    summary = ProjectSummary(
        name=project,
        path=clone_path,
        sensitivity=sensitivity,
        lead=lead,
        choreography=choreography,
        members=members,
    )
    try:
        registry_path = lab_mgmt_project_registry_path(project)
    except Exception as exc:
        # lab_mgmt repo not configured on this machine — skip silently
        # rather than fail. The user can still work locally.
        result.probes.append(_pf.Probe(
            name="lab_mgmt registry", status="warn",
            detail=f"skipped: {exc}", required=False,
        ))
        registry_path = None

    if registry_path is not None:
        result.registry_path = registry_path
        if registry_path.exists():
            result.probes.append(_pf.Probe(
                name="lab_mgmt registry", status="ok",
                detail=f"{registry_path} (already exists, preserved)",
                required=False,
            ))
        else:
            try:
                registry_path.parent.mkdir(parents=True, exist_ok=True)
                host_name = ssh_remote or "local"
                remote_path = ""
                if ssh_remote:
                    rh = (remote_home or "").rstrip("/")
                    # Match cmd_new_remote's convention: remote clones
                    # live at <project_root>/<name>; the project_root
                    # default is ~/repos which we expand against rh
                    # when known.
                    if rh:
                        remote_path = f"{rh}/repos/{project}"
                    else:
                        remote_path = f"~/repos/{project}"
                registry_path.write_text(
                    render_registry_entry(
                        summary, today=today,
                        host_name=host_name, remote_path=remote_path,
                    ),
                    encoding="utf-8",
                )
                result.probes.append(_pf.Probe(
                    name="lab_mgmt registry", status="ok",
                    detail=f"wrote {registry_path}", required=False,
                ))
            except OSError as exc:
                result.probes.append(_pf.Probe(
                    name="lab_mgmt registry", status="warn",
                    detail=f"write failed: {exc}", required=False,
                ))

    # ---- 3. Installation manifest --------------------------------------
    # Match the schema workspace_initialize used to write directly so
    # existing readers (snapshot.py, launchers) don't need updating.
    member_at = member if member.startswith("@") else f"@{member}" if member else f"@{lead.lstrip('@')}"
    manifest = {
        "member": member_at,
        "project": project,
        "machine_type": machine_type,
        "hostname": hostname,
        "username": username,
        "access": "direct" if has_direct_access else "ssh",
        "has_direct_access": has_direct_access,
        "lab_base": lab_base,
        "raw_path": raw_path,
        "refined_path": refined_path,
        "notebook_path": notebook_path,
        "ssh_remote": ssh_remote,
        "remote_home": remote_home,
        "mount_point": mount_point,
        "components": infra_components,
        "agents": agents,
        "status": "active",
        "created": today,
        "last_checked": today,
        "issues": [],
    }
    try:
        installations_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = installations_dir / f"{project}.yaml"
        manifest_path.write_text(
            yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )
        result.manifest_path = manifest_path
        result.probes.append(_pf.Probe(
            name="installation manifest", status="ok",
            detail=f"wrote {manifest_path}", required=False,
        ))
    except OSError as exc:
        result.probes.append(_pf.Probe(
            name="installation manifest", status="fail",
            detail=f"write failed: {exc}", required=False,
        ))

    # ---- 4. Layer-2 CC bootstrap (local only) --------------------------
    # Remote installs run the equivalent on the remote host via
    # core.remote_install.install — caller handles that separately.
    if not ssh_remote:
        for p in _cci.bootstrap_local(
            clone_path, wigamig_repo_root(),
            agents=agents,
            project_name=project,
            raw_path=raw_path,
            refined_path=refined_path,
            notebook_path=notebook_path,
        ):
            result.probes.append(p)

    return result


__all__ = ["ProjectizeResult", "make_wigamig_project"]
