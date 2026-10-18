"""
Purpose: ``murmurent project migrate`` (issue #151, step 0): find every
         repository and data folder that no project claims, and propose the
         project records that would claim them.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-16
Input: this machine's repositories folder; the folders directly under
       ``immutable/`` and ``append_only/`` in the data root; the project
       records in the lab records repository.
Output: a :class:`MigratePlan`, and, from :func:`apply`, the project records it
        proposes. Nothing else is ever written: no folder is moved, renamed or
        deleted, and no repository is touched.

How repositories are grouped is :func:`core.project_unit.project_for_repo`, the
same rule ``murmurent repo adopt`` uses: ``x``, ``x_manuscript`` and
``x_seminar`` become one project ``x``, with roles code, manuscript and
seminar; a repository inside a project folder ``<repositories>/x/`` belongs to
``x``. A repository that belongs by that rule to a project that already exists
is proposed as an addition to it, which changes only that project's list of
repositories.

A data folder is claimed when it is one of a project's data folders
(``immutable/<project>/`` and ``append_only/<project>/`` unless the record
names others). Only the folders directly under those two are listed, one
directory listing each, so the command is quick on any size of data drive.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from . import cert_projects as _cp
from . import lab_vm as _lab_vm
from . import project_unit as _pu

NEW, ADD = "new", "add"


class MigrateError(RuntimeError):
    """The plan cannot be made or applied; the message says why."""


@dataclass
class RepoRow:
    """One repository no project claims, and where it would go."""

    name: str
    path: Path
    project: str
    role: str
    sensitivity: str = ""
    has_charter: bool = False


@dataclass
class ProjectProposal:
    """One project record to write (``new``) or to add repositories to (``add``)."""

    name: str
    action: str
    repos: list[RepoRow] = field(default_factory=list)
    lab: str = ""
    lead: str = ""
    sensitivity: str = "standard"


@dataclass
class FolderRow:
    """One data folder no project claims. ``project`` is the project that would
    claim it once its proposed record is written, or ""."""

    path: Path
    area: str
    project: str = ""
    note: str = ""


@dataclass
class LeftOut:
    """A repository the plan does not touch, and why."""

    path: Path
    reason: str


@dataclass
class MigratePlan:
    repos_root: Path
    data_root: Path
    proposals: list[ProjectProposal] = field(default_factory=list)
    folders: list[FolderRow] = field(default_factory=list)
    left_out: list[LeftOut] = field(default_factory=list)
    unreadable: list[str] = field(default_factory=list)

    @property
    def new_projects(self) -> list[ProjectProposal]:
        return [p for p in self.proposals if p.action == NEW]

    @property
    def additions(self) -> list[ProjectProposal]:
        return [p for p in self.proposals if p.action == ADD]

    @property
    def repo_rows(self) -> list[RepoRow]:
        return [r for p in self.proposals for r in p.repos]

    def has_writes(self) -> bool:
        return bool(self.proposals)


def _norm(path: Path) -> str:
    return os.path.normpath(str(Path(path).expanduser()))


def _leave_out_reason(repo: Path, private: tuple[str, ...]) -> str:
    """Why a repository is not proposed for any project, or "" to propose it."""
    from .repo_inventory import is_excluded, is_murmurent_infra_repo
    if is_murmurent_infra_repo(repo.name):
        return "murmurent's own repository, not a project"
    if _pu.is_lab_records_clone(repo):
        return "a lab records repository, not a project"
    if is_excluded(str(repo), private):
        return "marked private (murmurent repo private)"
    return ""


def _data_children(root: Path, area: str, unreadable: list[str]) -> list[Path]:
    """The folders directly under ``root``. One listing; nothing below it."""
    if not root.is_dir():
        return []
    try:
        return sorted(c for c in root.iterdir()
                      if not c.name.startswith(".") and c.is_dir())
    except OSError as exc:
        unreadable.append(f"{root} ({area}): {exc.strerror or exc}")
        return []


def plan(*, env: dict | None = None, lab: str | None = None,
         lead: str | None = None) -> MigratePlan:
    """Work out what ``project migrate`` would write. Reads only.

    ``lab`` and ``lead`` go into new records; by default this machine's lab
    and the person using it (from local settings, never a network call).
    """
    from .repo import repos_root
    from .repo_inventory import load_exclusions

    root = repos_root()
    result = MigratePlan(repos_root=root, data_root=_lab_vm.data_root(env))
    try:
        projects = _cp.iter_projects(env)
    except Exception as exc:  # noqa: BLE001
        raise MigrateError(f"could not read the project records: {exc}") from exc
    if lab is None:
        lab = _pu.this_machine_lab()
    if lead is None:
        lead = _pu.local_handle()
    lead = lead.strip().lstrip("@")

    claimed_repos = {(r.name or "").casefold() for p in projects for r in p.repos}
    by_name = {p.name.casefold(): p for p in projects}
    private = load_exclusions()

    # --- repositories -----------------------------------------------------
    candidates: list[Path] = []
    every_repo = _pu.local_repositories(root)
    for repo in every_repo:
        if repo.name.casefold() in claimed_repos:
            continue
        reason = _leave_out_reason(repo, private)
        if reason:
            result.left_out.append(LeftOut(path=repo, reason=reason))
        else:
            candidates.append(repo)
    here = {p.name for p in every_repo}
    groups: dict[str, ProjectProposal] = {}
    for repo in candidates:
        project, role = _pu.project_for_repo(repo, project_names={p.name for p in projects},
                                             repo_names=here, root=root)
        existing = by_name.get(project.casefold())
        key = (existing.name if existing else project).casefold()
        if key not in groups:
            groups[key] = ProjectProposal(
                name=existing.name if existing else project,
                action=ADD if existing else NEW,
                lab="" if existing else lab, lead="" if existing else lead)
        groups[key].repos.append(RepoRow(
            name=repo.name, path=repo, project=groups[key].name, role=role,
            sensitivity=_pu.marker_sensitivity(repo),
            has_charter=(repo / "CHARTER.md").is_file()))
    for proposal in groups.values():
        if proposal.action == NEW:
            proposal.sensitivity = _pu.most_sensitive([r.sensitivity for r in proposal.repos])
    result.proposals = sorted(groups.values(), key=lambda p: p.name.casefold())

    # --- data folders -----------------------------------------------------
    claimed_folders = {_norm(f) for p in projects for f in _pu.effective_data_folders(p, env)}
    new_names = {p.name.casefold(): p.name for p in result.new_projects}
    for area, area_root in (("immutable", _lab_vm.immutable_root(env)),
                            ("append_only", _lab_vm.append_only_root(env))):
        for child in _data_children(area_root, area, result.unreadable):
            if _norm(child) in claimed_folders:
                continue
            match = new_names.get(child.name.casefold())
            if match:
                result.folders.append(FolderRow(
                    path=child, area=area, project=match,
                    note=f"claimed by the new project {match} once it is written"))
                continue
            owner = by_name.get(child.name.casefold())
            if owner is not None:
                note = (f"project {owner.name} exists, but its record names other "
                        "data folders")
            else:
                note = "no project claims it; it stays listed as unclaimed"
            result.folders.append(FolderRow(path=child, area=area, note=note))
    return result


def apply(migrate_plan: MigratePlan, *, env: dict | None = None,
          today: str | None = None) -> list[str]:
    """Write the records in ``migrate_plan``. Returns one line per change.

    Checks each record again just before writing it, so a project or a
    repository that appeared since the plan was made is left alone rather than
    overwritten.
    """
    done: list[str] = []
    for proposal in migrate_plan.proposals:
        current = _cp.get(proposal.name, env)
        listed = {(r.name or "").casefold()
                  for p in _cp.iter_projects(env) for r in p.repos}
        rows = [r for r in proposal.repos if r.name.casefold() not in listed]
        if not rows:
            continue
        if proposal.action == NEW:
            if current is not None:
                done.append(f"skipped {proposal.name}: a project of that name appeared "
                            "since the plan was made, and was left alone")
                continue
            refs = [_cp.RepoRef(name=r.name, role=r.role, host="local", path=str(r.path))
                    for r in rows]
            _cp.upsert(proposal.name, lab=proposal.lab,
                       lead=f"@{proposal.lead}" if proposal.lead else None,
                       member=proposal.lead or None,
                       sensitivity=proposal.sensitivity, repos=refs,
                       today=today, env=env)
            names = ", ".join(r.name for r in rows)
            done.append(f"wrote project {proposal.name} ({names})")
            continue
        if current is None:
            done.append(f"skipped {proposal.name}: the project is no longer there")
            continue
        for r in rows:
            _cp.add_repo(proposal.name, role=r.role, repo_name=r.name,
                         host="local", path=str(r.path), env=env)
            done.append(f"added {r.name} to project {proposal.name} as its {r.role} repository")
    return done


__all__ = ["NEW", "ADD", "MigrateError", "RepoRow", "ProjectProposal", "FolderRow",
           "LeftOut", "MigratePlan", "plan", "apply"]
