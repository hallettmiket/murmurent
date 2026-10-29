"""
Purpose: the project as the unit of work (issue #151, step 0). Works out a
         project's data folders, the folders it only reads, its keep-until
         date, when it was last used and whether it is active, quiet or
         dormant; and makes a one-repository project for a repository that
         belongs to none.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-16
Input: a project record (core.cert_projects.CertProject); this machine's
       repositories; the job records written by ``murmurent run`` under
       ``~/.murmurent/runs/``; the data scan's record of when each data folder
       last changed, ``~/.murmurent/space/data_dates.json``; the lab's policy
       file in the lab records repository.
Output: plain values (paths, dates, the activity word) and, from
        :func:`ensure_repo_project`, a new project record when a repository
        belongs to no project.

Every repository belongs to exactly one project, its owning project. Other
projects may name it, or any data folder, under ``reads_from``: they read it
but do not own it, so nothing there is ever offered to them for clean-up.

**Activity is worked out, never typed.** A project's ``status`` stays
``active`` or ``archived``, because much of murmurent reads any other status as
"no access" and would quietly lock members out. Activity is a separate word
(``active``, ``quiet`` or ``dormant``) computed from the last time the project
was used, with thresholds from the lab's policy (12 and 24 months unless the
policy says otherwise). It never changes who can reach a project.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path


from . import cert_projects as _cp
from . import lab_vm as _lab_vm
from . import repo as _repo
from . import sensitivity as _sens
from .preflight import Probe

_log = logging.getLogger(__name__)

#: The activity words. ``unknown`` means this machine holds no evidence of use
#: at all (no repository here, no job record, no data scan). Anything that
#: suggests clean-up must treat ``unknown`` like ``active``.
ACTIVE, QUIET, DORMANT, UNKNOWN = "active", "quiet", "dormant", "unknown"

#: Months without use before a project is quiet, then dormant (Mike Hallett,
#: issue #151, 2026-10-16). A lab's policy file may set its own.
DEFAULT_QUIET_AFTER_MONTHS = 12
DEFAULT_DORMANT_AFTER_MONTHS = 24

#: The lab's policy file is the millwright's, ``policy/millwright.yaml`` in the
#: lab records repository (:mod:`core.millwright_policy`), keys
#: ``project_quiet_months`` and ``project_dormant_months``. One file holds all
#: of the lab's numbers, so the written rules and the tools cannot drift apart.

#: Where ``murmurent run`` keeps one job record per job (step 1 of #151).
RUNS_SUBDIR = "runs"

#: Where the data scan (step 2 of #151) records when each data folder last
#: changed. Format, JSON::
#:
#:     {"schema": 1,
#:      "folders": {"<absolute folder path>": {"newest_change": "<ISO 8601>",
#:                                              "scanned_at": "<ISO 8601>"}}}
#:
#: A folder may be a project's data folder or any folder inside one.
SPACE_SUBDIR = "space"
DATA_DATES_FILENAME = "data_dates.json"
DATA_DATES_SCHEMA = 1

#: Largest job record or cache file read, in bytes. Anything bigger is not one
#: of ours and is skipped rather than parsed.
_MAX_RECORD_BYTES = 5 * 1024 * 1024

#: Seconds to wait for ``git log`` in one repository.
_GIT_TIMEOUT = 15

#: Roles a repository has when its name is ``<project>_<role>``.
SIBLING_ROLES: tuple[str, ...] = tuple(r for r in _cp.VALID_REPO_ROLES if r != "code")


# ---------------------------------------------------------------------------
# Where murmurent keeps this machine's own files
# ---------------------------------------------------------------------------


def murmurent_home() -> Path:
    """This machine's murmurent folder: ``$MURMURENT_HOME``, else ``~/.murmurent``."""
    return Path(os.environ.get("MURMURENT_HOME") or Path.home() / ".murmurent")


def runs_dir() -> Path:
    """The folder of job records written by ``murmurent run``."""
    return murmurent_home() / RUNS_SUBDIR


def data_dates_path() -> Path:
    """The data scan's record of when each data folder last changed."""
    return murmurent_home() / SPACE_SUBDIR / DATA_DATES_FILENAME


# ---------------------------------------------------------------------------
# Data folders, folders read, and the keep-until date
# ---------------------------------------------------------------------------


def _resolve_folder(entry: str, env: dict | None) -> Path:
    """A folder named in a record: in full, or relative to the data root."""
    p = Path(str(entry).strip()).expanduser()
    if not p.is_absolute():
        p = _lab_vm.data_root(env) / p
    return Path(os.path.normpath(p))


#: The lab folder protocol's other per-project folders (#206), counted as the
#: project's own when they exist on this machine.
OPTIONAL_PROJECT_FOLDERS = ("modifiable", "release", "mothballed")


def default_data_folders(name: str, env: dict | None = None) -> list[Path]:
    """``immutable/<project>/`` and ``append_only/<project>/`` under the data
    root, then ``modifiable/``, ``release/`` and ``mothballed/<project>/`` for
    each that exists."""
    out = [Path(os.path.normpath(_lab_vm.project_immutable_dir(name, env))),
           Path(os.path.normpath(_lab_vm.project_append_only_dir(name, env)))]
    root = _lab_vm.data_root(env)
    for tier in OPTIONAL_PROJECT_FOLDERS:
        folder = Path(os.path.normpath(root / tier / name))
        if folder.is_dir():
            out.append(folder)
    return out


def effective_data_folders(cp: _cp.CertProject, env: dict | None = None) -> list[Path]:
    """The folders a project owns.

    The record's ``data_folders`` when it names any, otherwise the default pair
    from :func:`default_data_folders`. A folder in the record is written in
    full or relative to the data root (``append_only/x_y``); the second form
    stays right on every machine whatever its data root is.
    """
    if not cp.data_folders:
        return default_data_folders(cp.name, env)
    out: list[Path] = []
    for entry in cp.data_folders:
        p = _resolve_folder(entry, env)
        if p not in out:
            out.append(p)
    return out


def _is_folder_entry(entry: str) -> bool:
    """A ``reads_from`` entry is a folder when written as a path, else a repository."""
    s = str(entry).strip()
    return "/" in s or s.startswith("~")


@dataclass(frozen=True)
class ReadsFrom:
    """What a project reads but does not own."""

    folders: tuple[Path, ...] = ()
    repos: tuple[str, ...] = ()


def resolve_reads_from(cp: _cp.CertProject, env: dict | None = None) -> ReadsFrom:
    """Split ``reads_from`` into folders and repository names.

    An entry written as a path (``append_only/bc_dcis``, ``/data/shared/x``) is
    a folder, resolved like a data folder. A bare name (``dcis_calculator``) is
    a repository owned by some other project.
    """
    folders: list[Path] = []
    repos: list[str] = []
    for entry in cp.reads_from:
        if _is_folder_entry(entry):
            p = _resolve_folder(entry, env)
            if p not in folders:
                folders.append(p)
        elif entry.strip() and entry.strip() not in repos:
            repos.append(entry.strip())
    return ReadsFrom(folders=tuple(folders), repos=tuple(repos))


def parse_iso_date(value: str) -> _dt.date | None:
    """``YYYY-MM-DD`` as a date, or None when it is empty or not a date."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return _dt.date.fromisoformat(text[:10]) if len(text) >= 10 else None
    except ValueError:
        return None


def retention_blocks_deletion(cp: _cp.CertProject, today: _dt.date | None = None) -> bool:
    """True while nothing in the project may be suggested for deletion.

    That is every day before ``retain_until``. A ``retain_until`` that is not
    a date counts as blocking, so a typing mistake keeps data rather than
    losing it.
    """
    if not str(cp.retain_until or "").strip():
        return False
    until = parse_iso_date(cp.retain_until)
    if until is None:
        return True
    return (today or _dt.date.today()) < until


# ---------------------------------------------------------------------------
# When a project was last used
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class UsageEvidence:
    """One sign that a project was used, and when.

    ``source`` is ``commit`` (a commit in one of its repositories), ``job``
    (a job record from ``murmurent run``) or ``data`` (a file changed in one of
    its data folders, as recorded by the data scan).
    """

    when: _dt.datetime
    source: str
    detail: str


def _parse_when(value: object) -> _dt.datetime | None:
    """A timestamp from a record, as a time in UTC, or None.

    Accepts ISO 8601 text (with or without a time zone, ``Z`` included), a
    date, or seconds since 1970. A time without a zone is read as local time.
    """
    if value is None or value == "":
        return None
    try:
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return _dt.datetime.fromtimestamp(float(value), tz=_dt.timezone.utc)
        if isinstance(value, _dt.datetime):
            when = value
        elif isinstance(value, _dt.date):
            when = _dt.datetime(value.year, value.month, value.day)
        else:
            text = str(value).strip()
            if text.endswith(("Z", "z")):
                text = f"{text[:-1]}+00:00"
            when = _dt.datetime.fromisoformat(text)
    except (ValueError, OverflowError, OSError, TypeError):
        return None
    return when.astimezone(_dt.timezone.utc)


def newest_commit(repo: Path) -> _dt.datetime | None:
    """The date of the newest commit on any branch of ``repo``, or None."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--all", "--format=%cI"],
            capture_output=True, text=True, timeout=_GIT_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return _parse_when(out.stdout.strip())


def repo_commit_evidence(cp: _cp.CertProject) -> list[UsageEvidence]:
    """The newest commit in each of the project's repositories on this machine."""
    found: list[UsageEvidence] = []
    for r in cp.repos:
        if (r.host or "local") != "local" or not r.path:
            continue
        path = Path(r.path).expanduser()
        if not (path / ".git").exists():
            continue
        when = newest_commit(path)
        if when is not None:
            found.append(UsageEvidence(when=when, source="commit",
                                       detail=f"newest commit in {r.name or path.name}"))
    return found


def _read_small_json(path: Path) -> object:
    """The JSON in ``path``, or None when it is missing, too big or not JSON."""
    try:
        if path.stat().st_size > _MAX_RECORD_BYTES:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def job_card_evidence(project: str, folder: Path | None = None) -> list[UsageEvidence]:
    """The newest job record for ``project`` written by ``murmurent run``.

    A job record is a JSON file naming its ``project`` and carrying
    ``started_at`` and, once it ends, ``ended_at``. A missing folder, an
    unreadable file or a record without those fields is passed over without
    complaint, since job records are new and other tools may share the folder.
    """
    folder = folder or runs_dir()
    if not folder.is_dir():
        return []
    want = str(project).strip().casefold()
    newest: UsageEvidence | None = None
    try:
        files = sorted(folder.glob("*.json"))
    except OSError:
        return []
    for f in files:
        card = _read_small_json(f)
        if not isinstance(card, dict):
            continue
        if str(card.get("project") or "").strip().casefold() != want:
            continue
        times = [t for t in (_parse_when(card.get("ended_at")),
                             _parse_when(card.get("started_at"))) if t is not None]
        if not times:
            continue
        when = max(times)
        if newest is None or when > newest.when:
            newest = UsageEvidence(when=when, source="job",
                                   detail=f"job record {f.name}")
    return [newest] if newest is not None else []


def read_data_dates(path: Path | None = None) -> dict[str, dict]:
    """The data scan's record, as {folder: entry}. Empty when there is none."""
    data = _read_small_json(path or data_dates_path())
    if not isinstance(data, dict):
        return {}
    folders = data.get("folders")
    if not isinstance(folders, dict):
        return {}
    out: dict[str, dict] = {}
    for key, entry in folders.items():
        if isinstance(entry, str):
            entry = {"newest_change": entry}
        if isinstance(entry, dict):
            out[str(key)] = entry
    return out


def _resolved(path: Path) -> Path:
    """``path`` with links followed, or as it is when that fails."""
    try:
        return path.resolve()
    except (OSError, RuntimeError):
        return path


def _within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
    except ValueError:
        return False
    return True


def data_change_evidence(cp: _cp.CertProject, env: dict | None = None,
                         path: Path | None = None) -> list[UsageEvidence]:
    """The newest change in the project's data folders, from the scan's record.

    Reads the record only. It never walks a data folder: those can hold
    hundreds of terabytes, and the scheduled scan (step 2 of #151) is the
    one place that walks them.
    """
    record = read_data_dates(path)
    if not record:
        return []
    mine = effective_data_folders(cp, env)
    # The scan may have written the data root through a link or without one;
    # match either spelling. resolve() follows links only, it lists nothing.
    mine += [_resolved(f) for f in mine if _resolved(f) not in mine]
    newest: UsageEvidence | None = None
    for key, entry in record.items():
        folder = Path(os.path.normpath(Path(key).expanduser()))
        if not any(_within(folder, f) for f in mine):
            continue
        when = _parse_when(entry.get("newest_change"))
        if when is None:
            continue
        if newest is None or when > newest.when:
            newest = UsageEvidence(when=when, source="data",
                                   detail=f"a file changed in {folder}")
    return [newest] if newest is not None else []


def usage_evidence(cp: _cp.CertProject, env: dict | None = None) -> list[UsageEvidence]:
    """Every sign of use this machine holds for the project, newest first."""
    found = (repo_commit_evidence(cp) + job_card_evidence(cp.name)
             + data_change_evidence(cp, env))
    return sorted(found, key=lambda e: e.when, reverse=True)


def last_used(cp: _cp.CertProject, env: dict | None = None) -> UsageEvidence | None:
    """When the project was last used, and the evidence for it; None if unknown.

    The newest of three things:

    1. the newest commit in each of its repositories that is on this machine;
    2. its newest job record from ``murmurent run``, if any exist;
    3. the newest change in its data folders, from the data scan's record,
       if that record exists.

    Reading data does not count, and cannot: the shared data drive does not
    record when a file was last read (checked on the lab's server,
    2026-10-16). That is why job records matter. They are the only sign that a
    project's data was used without being changed.
    """
    found = usage_evidence(cp, env)
    return found[0] if found else None


# ---------------------------------------------------------------------------
# Activity: active, quiet or dormant
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ActivityPolicy:
    """Months without use before a project counts as quiet, then dormant."""

    quiet_after_months: int = DEFAULT_QUIET_AFTER_MONTHS
    dormant_after_months: int = DEFAULT_DORMANT_AFTER_MONTHS


def load_activity_policy(env: dict | None = None) -> ActivityPolicy:
    """The lab's thresholds, from the millwright's policy file.

    Reads ``project_quiet_months`` and ``project_dormant_months`` through
    :func:`core.millwright_policy.load_policy`, which keeps the built-in 12 and
    24 months when the file is missing or a value makes no sense (not a whole
    number above zero, or dormant before quiet).
    """
    from .millwright_policy import load_policy
    policy = load_policy(env)
    for problem in policy.problems:
        _log.warning("%s", problem)
    return ActivityPolicy(quiet_after_months=policy.project_quiet_months,
                          dormant_after_months=policy.project_dormant_months)


def months_between(earlier: _dt.date, later: _dt.date) -> int:
    """Whole calendar months from ``earlier`` to ``later``; 0 if later is not later."""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return max(months, 0)


def activity_for(last: UsageEvidence | None, *, now: _dt.datetime | None = None,
                 policy: ActivityPolicy | None = None) -> str:
    """``active``, ``quiet``, ``dormant``, or ``unknown`` when nothing shows use."""
    if last is None:
        return UNKNOWN
    policy = policy or ActivityPolicy()
    now = now or _dt.datetime.now(_dt.timezone.utc)
    months = months_between(last.when.date(), now.astimezone(_dt.timezone.utc).date())
    if months >= policy.dormant_after_months:
        return DORMANT
    if months >= policy.quiet_after_months:
        return QUIET
    return ACTIVE


def activity(cp: _cp.CertProject, *, env: dict | None = None,
             now: _dt.datetime | None = None,
             policy: ActivityPolicy | None = None) -> str:
    """The project's activity, worked out from :func:`last_used` and the policy."""
    return activity_for(last_used(cp, env), now=now,
                        policy=policy or load_activity_policy(env))


# ---------------------------------------------------------------------------
# Which project a repository belongs to
# ---------------------------------------------------------------------------


def is_lab_records_clone(path: Path) -> bool:
    """A lab records repository (``lab.md`` plus ``members/``), whatever its name."""
    return (path / "lab.md").is_file() and (path / "members").is_dir()


def local_repositories(root: Path | None = None) -> list[Path]:
    """Every git repository in this machine's repositories folder.

    Those directly in it, and those one level down inside a project folder
    (``<repositories>/<project>/<repository>``, issue #166). Hidden folders
    are left out.
    """
    from .repo import repos_root
    root = root or repos_root()
    found: list[Path] = []
    try:
        tops = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    for top in tops:
        if (top / ".git").exists():
            found.append(top)
            continue
        try:
            found += sorted(c for c in top.iterdir()
                            if c.is_dir() and not c.name.startswith(".")
                            and (c / ".git").exists())
        except OSError:
            continue
    return found


def project_for_repo(repo_path: Path, *, project_names: set[str],
                     repo_names: set[str], root: Path | None = None) -> tuple[str, str]:
    """The project a repository would belong to by its name and place, and its role.

    Returns ``(project, role)``:

    - inside a project folder ``<repositories>/<P>/``: project ``P``; the role
      is ``code`` for ``P`` itself, ``manuscript`` for ``P_manuscript`` and so
      on for each role, otherwise ``code``;
    - directly in the repositories folder and named ``<x>_<role>`` (role one of
      manuscript, seminar, data, infra), when a project ``x`` exists or a
      repository ``x`` is on this machine: project ``x`` with that role;
    - otherwise: a project of its own name, role ``code``.

    The middle rule needs ``x`` to exist so that a repository such as
    ``cell_data`` is not split off into a project called ``cell``.
    """
    from .repo import repos_root
    repo_path = Path(repo_path)
    name = repo_path.name
    # Compare with links followed, since the repositories folder is often a
    # link to a larger drive and adopt hands over a resolved path.
    root = _resolved(Path(os.path.normpath((root or repos_root()).expanduser())))
    parent = _resolved(Path(os.path.normpath(repo_path.expanduser().parent)))
    if parent != root and parent.parent == root and not (parent / ".git").exists():
        folder = parent.name
        if name == folder:
            return folder, "code"
        for role in SIBLING_ROLES:
            if name == f"{folder}_{role}":
                return folder, role
        return folder, "code"
    known_projects = {n.casefold() for n in project_names}
    known_repos = {n.casefold() for n in repo_names}
    for role in SIBLING_ROLES:
        suffix = f"_{role}"
        if name.endswith(suffix) and len(name) > len(suffix):
            base = name[: -len(suffix)]
            if base.casefold() in known_projects or base.casefold() in known_repos:
                return base, role
    return name, "code"


def owning_project(repo_name: str, projects: list[_cp.CertProject] | None = None,
                   env: dict | None = None) -> _cp.CertProject | None:
    """The project whose record lists repository ``repo_name``, or None.

    Any status counts, since an archived project still owns its repositories;
    an active one wins when two records list it. See
    :func:`core.cert_projects.owning_project`.
    """
    return _cp.owning_project(repo_name, projects=projects, env=env)


def this_machine_lab() -> str:
    """This machine's lab, from its lab settings, or "" on a bare install."""
    try:
        from .lab import load_lab_config
        return str(load_lab_config().lab or "")
    except Exception:  # noqa: BLE001 - no lab is a normal answer
        return ""


def local_handle() -> str:
    """The person using this machine, from local settings only, or "".

    ``$MURMURENT_USER``, then ``~/.murmurent/user``. Never asks GitHub, so it
    makes no network call.
    """
    try:
        from . import identity as _id
        ident = _id.from_env() or _id.from_user_file()
    except Exception:  # noqa: BLE001 - no handle is a normal answer
        return ""
    handle = (ident.handle if ident else "").strip().lstrip("@")
    return "" if handle in ("", "unknown") else handle


def marker_sensitivity(repo: Path) -> str:
    """The sensitivity a repository declares in its ``.murmurent.yaml``, or "".

    A marker that still says the former name ``clinical`` reads as ``protected``.
    """
    try:
        from .repo_ready import read_marker
        value = _sens.normalize((read_marker(Path(repo)) or {}).get("sensitivity"))
    except Exception:  # noqa: BLE001
        return ""
    return value if value in _cp.VALID_SENSITIVITY_TIERS else ""


def most_sensitive(tiers: list[str]) -> str:
    """The most sensitive of ``tiers`` (protected, then restricted, then standard)."""
    order = list(_cp.VALID_SENSITIVITY_TIERS)
    known = [_sens.normalize(t) for t in tiers if _sens.normalize(t) in order]
    return max(known, key=order.index) if known else "standard"


def ensure_repo_project(repo_path: Path, *, lab: str = "", lead: str = "",
                        host: str = "local", remote_path: str = "",
                        env: dict | None = None, today: str | None = None) -> Probe:
    """Make sure the repository at ``repo_path`` belongs to a project.

    Used by ``murmurent repo adopt``. Three outcomes, and adopting the same
    repository again changes nothing:

    - a project already lists it: nothing is written;
    - no project of the name it would belong to exists (see
      :func:`project_for_repo`): a new project is written with this repository
      as its only repository, ``lead`` as its lead and only member;
    - a project of that name exists but does not list it: nothing is written,
      because an existing project is never changed here. The message says to
      add it with ``murmurent project migrate``, which shows the change and
      asks first.

    ``host`` and ``remote_path`` say where the repository is when it is on
    another machine.
    """
    repo_path = Path(repo_path)
    name = repo_path.name
    # Writing a record into a lab records folder that is not there would create
    # it, and other commands would then treat that invented folder as the lab's
    # records (#227). Only pi-init, or cloning the real one, makes it.
    records = _repo.lab_mgmt_repo_root(env)
    if not records.is_dir():
        return Probe(name="project", status="warn",
                     detail=(f"no lab records folder on this machine ({records}), "
                             "so no project was made"))
    try:
        projects = _cp.iter_projects(env)
    except Exception as exc:  # noqa: BLE001 - the repository is ready either way
        return Probe(name="project", status="warn",
                     detail=f"could not read the project records ({exc}); no project was made")
    owner = owning_project(name, projects)
    if owner is not None:
        return Probe(name="project", status="ok",
                     detail=f"already part of project {owner.name}")
    here = {p.name for p in local_repositories()} if host == "local" else set()
    project, role = project_for_repo(repo_path, project_names={p.name for p in projects},
                                     repo_names=here)
    existing = next((p for p in projects if p.name.casefold() == project.casefold()), None)
    if existing is not None:
        return Probe(name="project", status="warn",
                     detail=(f"project {existing.name} exists and does not list {name}. "
                             "Nothing was changed. To add it, run `murmurent project migrate`, "
                             "check what it shows, and confirm."))
    is_local = (host or "local") == "local"
    ref = _cp.RepoRef(name=name, role=role, host=host or "local",
                      path=str(repo_path) if is_local else "",
                      remote_path="" if is_local else (remote_path or str(repo_path)))
    sensitivity = marker_sensitivity(repo_path) if is_local else ""
    handle = lead.strip().lstrip("@")
    try:
        _cp.upsert(project, lab=lab, lead=f"@{handle}" if handle else None,
                   member=handle or None, sensitivity=sensitivity or None,
                   repos=[ref], today=today, env=env)
    except Exception as exc:  # noqa: BLE001 - the repository is ready either way
        return Probe(name="project", status="warn",
                     detail=f"could not write project {project} ({exc})")
    return Probe(name="project", status="ok",
                 detail=f"made project {project}, with {name} as its {role} repository")


__all__ = [
    "ACTIVE", "QUIET", "DORMANT", "UNKNOWN",
    "DEFAULT_QUIET_AFTER_MONTHS", "DEFAULT_DORMANT_AFTER_MONTHS",
    "RUNS_SUBDIR", "SPACE_SUBDIR", "DATA_DATES_FILENAME",
    "DATA_DATES_SCHEMA", "SIBLING_ROLES",
    "murmurent_home", "runs_dir", "data_dates_path",
    "default_data_folders", "effective_data_folders", "ReadsFrom",
    "resolve_reads_from", "parse_iso_date", "retention_blocks_deletion",
    "UsageEvidence", "newest_commit", "repo_commit_evidence", "job_card_evidence",
    "read_data_dates", "data_change_evidence", "usage_evidence", "last_used",
    "ActivityPolicy", "load_activity_policy", "months_between", "activity_for",
    "activity", "local_repositories", "project_for_repo", "owning_project",
    "is_lab_records_clone", "this_machine_lab", "local_handle",
    "marker_sensitivity", "most_sensitive", "ensure_repo_project",
]
