"""
Purpose: The lab's rules for running jobs and keeping space tidy, read from one
         policy file so the written procedure and what murmurent does agree.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-16
Input:   Built-in defaults; then ``<lab-mgmt>/policy/millwright.yaml`` in the
         lab's management repository, when it exists; then the file named by
         ``$MURMURENT_MILLWRIGHT_POLICY``, when set (used by tests, and by anyone
         who wants to try a rule before the PI adopts it).
Output:  A :class:`Policy`, with the list of files it was built from and any
         problems found in them.

Issue #151, step 1. The launcher (``murmurent run``) reads the job settings;
step 0 reads ``project_quiet_months`` and ``project_dormant_months``; step 2,
the space scan (``murmurent space scan``), reads the space settings; later
steps read the home-folder sizes.

The built-in defaults are generic on purpose. They are fractions of the machine
or modest numbers, never one server's figures, because the same code runs on a
laptop and on a 200-core server. A lab sets its own numbers in its policy file;
``templates/millwright_policy.yaml`` is a commented example.

A bad value in a policy file never stops a job. It is reported in
``Policy.problems`` and the earlier value (usually the built-in default) is
kept, so a typo in the lab's file cannot silently remove a limit.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass, field, fields, replace
from pathlib import Path
from typing import Any

import yaml

POLICY_ENV = "MURMURENT_MILLWRIGHT_POLICY"
POLICY_RELATIVE_PATH = Path("policy") / "millwright.yaml"

#: The word a GPU allowance may take instead of a number: every GPU that is
#: idle when the job starts.
ALL_IDLE_GPUS = "all"

WEEKDAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class WorkingHours:
    """When the daytime GPU allowance applies.

    Attributes
    ----------
    days : tuple of str
        Three-letter lower-case day names, for example ``("mon", "tue")``.
    start, end : str
        Clock times ``HH:MM``. A moment counts as working hours when it falls on
        one of ``days`` at or after ``start`` and before ``end``.
    """

    days: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri")
    start: str = "08:00"
    end: str = "18:00"

    def contains(self, moment: _dt.datetime) -> bool:
        """Return True when ``moment`` falls inside working hours.

        Examples
        --------
        >>> WorkingHours().contains(_dt.datetime(2026, 10, 16, 9, 0))  # a Friday
        True
        """
        if WEEKDAY_NAMES[moment.weekday()] not in self.days:
            return False
        clock = moment.strftime("%H:%M")
        return self.start <= clock < self.end


@dataclass(frozen=True)
class Policy:
    """The rules in force, with where they came from.

    Attributes
    ----------
    priority : int
        The ``nice`` value every job runs at. 19 is the lowest priority, so other
        people's interactive work always goes first.
    max_cores_per_person : int
        The most cores one person's jobs may use at once, across all of them.
    default_cores : int
        Cores given to a job that does not ask for a number.
    hold_new_work_at_load_fraction : float
        New work is held once the server's load (the number of processes
        running or waiting for a core, averaged over one minute) passes this
        share of its cores.
    min_free_memory_fraction : float
        A job does not start if it would leave less than this share of memory
        free.
    memory_per_person_fraction : float
        The share of total memory one person may claim with ``--memory`` without
        an exception.
    working_hours : WorkingHours
        When ``gpus_per_person_working_hours`` applies.
    gpus_per_person_working_hours : int or "all"
        GPUs one person may hold in working hours.
    gpus_per_person_outside_hours : int or "all"
        GPUs one person may hold outside working hours. ``"all"`` means every GPU
        that is idle when the job starts, and never fewer than the daytime
        allowance.
    gpu_idle_below_percent : int
        A GPU counts as idle when both its use and its memory in use are below
        this percentage.
    disk_fill_limit_fraction : float
        A job that states its expected output is refused if writing it would
        fill the disk past this share.
    stall_minutes : int
        A running job whose log has not grown for this long is reported as
        stalled.
    home_folder_heads_up_gb, home_folder_firm_gb : int
        Home-folder sizes for a friendly note and a firm reminder (later steps).
    project_quiet_months, project_dormant_months : int
        Months without use after which a project is quiet, then dormant (step 0).
    temporary_min_age_days : int
        A temporary file (``nohup.out``, a notebook checkpoint, a partial
        download) is suggested for deletion only once it is this many days old,
        so a running job's scratch files are left alone (step 2).
    large_file_in_repo_mb : int
        A file at least this big inside a repository folder is out of place:
        data belongs in the project's data folders (step 2).
    compress_min_mb : int
        Uncompressed text formats (FASTQ, SAM, VCF, CSV) at least this big are
        suggested for lossless compression (step 2).
    duplicate_min_mb : int
        Files at least this big are compared for duplicates. Smaller files are
        not worth reading to fingerprint (step 2).
    duplicate_max_read_gb : int
        The most a scan reads in full to confirm duplicates. Past it, files with
        the same size and the same first and last megabyte are listed as
        probable duplicates, not confirmed (step 2).
    scan_threads : int
        Folders the space scan lists at once (step 3). Each waits on the
        drive more than it uses a core.
    remake_cheap_below_cpu_hours : int
        An intermediate file that took less than this many CPU hours to make,
        from committed code and inputs that still exist, is suggested for
        deletion. Anything costlier is ``ask the owner`` (step 2).
    disk_emergency_fill_fraction : float
        A disk fuller than this share is an emergency (step 2).
    emergency_item_share_of_free : float
        One suggestion bigger than this share of a disk's free space is an
        emergency (step 2).
    sources : tuple of str
        The files read, in order, after the built-in defaults.
    problems : tuple of str
        One plain sentence per value that was ignored, and why.
    """

    priority: int = 19
    max_cores_per_person: int = 16
    default_cores: int = 1
    hold_new_work_at_load_fraction: float = 0.8
    min_free_memory_fraction: float = 0.20
    memory_per_person_fraction: float = 0.25
    working_hours: WorkingHours = field(default_factory=WorkingHours)
    gpus_per_person_working_hours: int | str = 1
    gpus_per_person_outside_hours: int | str = 2
    gpu_idle_below_percent: int = 10
    disk_fill_limit_fraction: float = 0.95
    stall_minutes: int = 60
    home_folder_heads_up_gb: int = 50
    home_folder_firm_gb: int = 100
    project_quiet_months: int = 12
    project_dormant_months: int = 24
    temporary_min_age_days: int = 7
    large_file_in_repo_mb: int = 100
    compress_min_mb: int = 100
    duplicate_min_mb: int = 10
    duplicate_max_read_gb: int = 100
    scan_threads: int = 8
    remake_cheap_below_cpu_hours: int = 10
    disk_emergency_fill_fraction: float = 0.90
    emergency_item_share_of_free: float = 0.25
    sources: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()

    def gpu_allowance(self, moment: _dt.datetime, idle_gpu_count: int) -> int:
        """How many GPUs one person may hold at ``moment``.

        Parameters
        ----------
        moment : datetime
            When the job would start.
        idle_gpu_count : int
            GPUs idle right now; used only when the allowance is ``"all"``.

        Returns
        -------
        int
            The allowance as a count.
        """
        daytime = _as_count(self.gpus_per_person_working_hours, idle_gpu_count)
        if self.working_hours.contains(moment):
            return daytime
        outside = _as_count(self.gpus_per_person_outside_hours, idle_gpu_count)
        return max(outside, daytime)


def _as_count(value: int | str, idle_gpu_count: int) -> int:
    if value == ALL_IDLE_GPUS:
        return idle_gpu_count
    return int(value)


# ---------------------------------------------------------------------------
# Validation: one checker per kind of value
# ---------------------------------------------------------------------------


def _check_int(low: int, high: int | None = None):
    def check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("must be a whole number")
        if value < low or (high is not None and value > high):
            span = f"from {low} to {high}" if high is not None else f"at least {low}"
            raise ValueError(f"must be {span}")
        return value

    return check


def _check_fraction(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("must be a number between 0 and 1, such as 0.8")
    if not 0 < float(value) <= 1:
        raise ValueError("must be more than 0 and at most 1, such as 0.8")
    return float(value)


def _check_gpus(value: Any) -> int | str:
    if isinstance(value, str) and value.strip().lower() == ALL_IDLE_GPUS:
        return ALL_IDLE_GPUS
    return _check_int(0)(value)


def _check_clock(value: Any) -> str:
    text = str(value).strip()
    match = _CLOCK.match(text)
    if not match:
        raise ValueError("must be a clock time such as 08:00")
    return f"{int(match.group(1)):02d}:{match.group(2)}"


def _check_working_hours(value: Any, current: WorkingHours) -> WorkingHours:
    if not isinstance(value, dict):
        raise ValueError("must list days, start and end")
    days = current.days
    if "days" in value:
        raw = value["days"]
        if not isinstance(raw, list) or not raw:
            raise ValueError("days must be a list such as [mon, tue, wed, thu, fri]")
        cleaned = tuple(str(d).strip().lower()[:3] for d in raw)
        unknown = [d for d in cleaned if d not in WEEKDAY_NAMES]
        if unknown:
            raise ValueError(f"days has names it does not know: {unknown}")
        days = cleaned
    start = _check_clock(value["start"]) if "start" in value else current.start
    end = _check_clock(value["end"]) if "end" in value else current.end
    if end <= start:
        raise ValueError("end must be later than start")
    return WorkingHours(days=days, start=start, end=end)


_CHECKERS = {
    "priority": _check_int(0, 19),
    "max_cores_per_person": _check_int(1),
    "default_cores": _check_int(1),
    "hold_new_work_at_load_fraction": _check_fraction,
    "min_free_memory_fraction": _check_fraction,
    "memory_per_person_fraction": _check_fraction,
    "gpus_per_person_working_hours": _check_gpus,
    "gpus_per_person_outside_hours": _check_gpus,
    "gpu_idle_below_percent": _check_int(0, 100),
    "disk_fill_limit_fraction": _check_fraction,
    "stall_minutes": _check_int(1),
    "home_folder_heads_up_gb": _check_int(1),
    "home_folder_firm_gb": _check_int(1),
    "project_quiet_months": _check_int(1),
    "project_dormant_months": _check_int(1),
    "temporary_min_age_days": _check_int(0),
    "large_file_in_repo_mb": _check_int(1),
    "compress_min_mb": _check_int(1),
    "duplicate_min_mb": _check_int(1),
    "duplicate_max_read_gb": _check_int(0),
    "scan_threads": _check_int(1, 32),
    "remake_cheap_below_cpu_hours": _check_int(0),
    "disk_emergency_fill_fraction": _check_fraction,
    "emergency_item_share_of_free": _check_fraction,
}

_INTERNAL_FIELDS = {"sources", "problems"}


def _apply(policy: Policy, data: dict, source: str) -> Policy:
    """Return ``policy`` with every valid value from ``data`` applied."""
    changes: dict[str, Any] = {}
    problems = list(policy.problems)
    known = {f.name for f in fields(Policy)} - _INTERNAL_FIELDS
    for key, value in data.items():
        if key not in known:
            problems.append(f"{source}: '{key}' is not a setting murmurent knows; ignored.")
            continue
        try:
            if key == "working_hours":
                changes[key] = _check_working_hours(value, policy.working_hours)
            else:
                changes[key] = _CHECKERS[key](value)
        except ValueError as exc:
            problems.append(f"{source}: '{key}' {exc}; kept {getattr(policy, key)!r}.")
    updated = replace(
        policy, **changes, sources=policy.sources + (source,), problems=tuple(problems)
    )
    if updated.project_dormant_months < updated.project_quiet_months:
        problems.append(
            f"{source}: 'project_dormant_months' is shorter than "
            f"'project_quiet_months'; both kept as they were."
        )
        updated = replace(
            updated,
            project_quiet_months=policy.project_quiet_months,
            project_dormant_months=policy.project_dormant_months,
            problems=tuple(problems),
        )
    return updated


def _read_yaml(path: Path) -> tuple[dict | None, str | None]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, f"{path}: could not be read ({exc.strerror or exc}); ignored."
    except yaml.YAMLError:
        return None, f"{path}: is not valid YAML; ignored."
    if data is None:
        return {}, None
    if not isinstance(data, dict):
        return None, f"{path}: should be a list of 'setting: value' lines; ignored."
    return data, None


def lab_policy_path(env: dict[str, str] | None = None) -> Path | None:
    """The lab's policy file inside its management repository, or None.

    Parameters
    ----------
    env : dict, optional
        Environment to resolve the management repository from.

    Returns
    -------
    Path or None
        ``<lab-mgmt>/policy/millwright.yaml`` when the repository can be found;
        the file itself may not exist.
    """
    try:
        from .repo import lab_mgmt_repo_root

        return lab_mgmt_repo_root(env) / POLICY_RELATIVE_PATH
    except Exception:  # noqa: BLE001 - no lab repository means built-in defaults
        return None


def load_policy(env: dict[str, str] | None = None) -> Policy:
    """Build the policy in force: defaults, then the lab's file, then the override.

    Parameters
    ----------
    env : dict, optional
        Environment to read ``$MURMURENT_MILLWRIGHT_POLICY`` and the lab
        repository location from. Defaults to ``os.environ``.

    Returns
    -------
    Policy
        Never raises for a missing or broken file; problems are listed on it.

    Examples
    --------
    >>> load_policy({}).priority
    19
    """
    env = dict(os.environ) if env is None else env
    policy = Policy()
    candidates: list[Path] = []
    lab_file = lab_policy_path(env)
    if lab_file is not None and lab_file.is_file():
        candidates.append(lab_file)
    override = env.get(POLICY_ENV, "").strip()
    if override:
        override_path = Path(override).expanduser()
        if override_path.is_file():
            candidates.append(override_path)
        else:
            policy = replace(
                policy,
                problems=policy.problems
                + (f"{POLICY_ENV} names {override_path}, which does not exist; ignored.",),
            )
    for path in candidates:
        data, problem = _read_yaml(path)
        if problem:
            policy = replace(policy, problems=policy.problems + (problem,))
            continue
        policy = _apply(policy, data or {}, str(path))
    return policy


def describe_policy(policy: Policy) -> list[str]:
    """Plain-English lines saying what the rules are and where they came from.

    Parameters
    ----------
    policy : Policy
        The policy to describe.

    Returns
    -------
    list of str
        Lines for the terminal.
    """
    hours = policy.working_hours
    days = ", ".join(hours.days)

    def gpus(value: int | str) -> str:
        return "every idle GPU" if value == ALL_IDLE_GPUS else str(value)

    lines = [
        "Rules from: " + ", ".join(("built-in defaults",) + policy.sources),
        f"  Every job runs at priority nice {policy.priority}.",
        f"  Cores per person, across all their jobs: {policy.max_cores_per_person}"
        f" (a job that does not ask gets {policy.default_cores}).",
        f"  New work is held when the server's load passes "
        f"{policy.hold_new_work_at_load_fraction:.0%} of its cores.",
        f"  A job may not leave less than {policy.min_free_memory_fraction:.0%} of memory free.",
        f"  Memory one person may claim without asking: "
        f"{policy.memory_per_person_fraction:.0%} of the total.",
        f"  GPUs per person, {days} {hours.start} to {hours.end}: "
        f"{gpus(policy.gpus_per_person_working_hours)}; at other times: "
        f"{gpus(policy.gpus_per_person_outside_hours)}.",
        f"  A job is reported as stalled after {policy.stall_minutes} minutes with no new output.",
        f"  A stated output size is refused if it would fill the disk past "
        f"{policy.disk_fill_limit_fraction:.0%}.",
    ]
    lines += [
        "  Space (murmurent space scan):",
        f"    temporary files are suggested for deletion after {policy.temporary_min_age_days} days;",
        f"    a file of {policy.large_file_in_repo_mb} MB or more inside a repository is out of place;",
        f"    text data of {policy.compress_min_mb} MB or more is suggested for compression;",
        f"    files of {policy.duplicate_min_mb} MB or more are compared for duplicates, reading "
        f"at most {policy.duplicate_max_read_gb} GB in full to confirm them;",
        f"    an intermediate file that cost under {policy.remake_cheap_below_cpu_hours} CPU hours "
        "to make may be suggested for deletion;",
        f"    a disk more than {policy.disk_emergency_fill_fraction:.0%} full, or one item larger "
        f"than {policy.emergency_item_share_of_free:.0%} of a disk's free space, is an emergency.",
    ]
    for problem in policy.problems:
        lines.append(f"  Problem: {problem}")
    return lines


__all__ = [
    "ALL_IDLE_GPUS",
    "POLICY_ENV",
    "POLICY_RELATIVE_PATH",
    "Policy",
    "WorkingHours",
    "describe_policy",
    "lab_policy_path",
    "load_policy",
]
