"""
Purpose: ``murmurent run``: start a long job the polite way, inside tmux, with a
         job card that says what it was given and how it went.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-16
Input:   A command; what the person asks for (cores, GPUs, memory, output
         folder, start time); the lab's policy (core/millwright_policy.py); and
         what the machine reports right now (load, memory, GPUs, disk).
Output:  A job card under ``~/.murmurent/runs/`` and a detached tmux session (or
         window) running ``core/run_supervisor.py``, which runs the command.

Issue #151, step 1. tmux is a program that keeps a command running after you
disconnect, so a dropped connection or a closed laptop does not stop the job.

How the pieces fit:

1. :func:`plan_resources` decides cores and GPUs from the request, the policy and
   :class:`SystemProbes`. It is a pure function of those three, so tests pass
   fakes for the machine.
2. :func:`launch` writes the card and a private copy of the person's environment,
   then asks tmux to start the supervisor. The environment is copied because a
   tmux server started earlier keeps its own, older environment; without the
   copy a job could find a different ``R`` or ``python`` than the person expects.
3. The supervisor (``core/run_supervisor.py``) waits when asked to, plans again
   at the real start time, runs the command at low priority, follows the log,
   and updates the card.

Slack notices never include the command line or any file path, because file
names can identify patients. See :func:`notice_text`.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import json
import math
import os
import re
import shlex
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import run_cards as _cards
from .millwright_policy import Policy, load_policy

#: Variables numerical libraries read to decide how many threads to start.
#: Without them, one R or numpy process can start a thread per core on the
#: whole server.
THREAD_VARIABLES = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

NVIDIA_QUERY = [
    "nvidia-smi",
    "--query-gpu=index,utilization.gpu,memory.used,memory.total",
    "--format=csv,noheader,nounits",
]

TMUX_PREFIX = "run-"
JOB_NAME_MAX = 60
_NAME_OK = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
_SIZE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgtp]?)(i?b?)\s*$", re.IGNORECASE)
_SIZE_POWERS = {"": 0, "k": 1, "m": 2, "g": 3, "t": 4, "p": 5}
_CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
COMMAND_TIMEOUT_SECONDS = 10


class LaunchError(Exception):
    """A plain-English reason the job cannot be started as asked."""


# ---------------------------------------------------------------------------
# What the machine reports
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GpuState:
    """One GPU as ``nvidia-smi`` reports it (the same figures ``nvtop`` shows).

    Attributes
    ----------
    index : int
        The GPU's number, as ``nvidia-smi`` counts them.
    utilisation : float or None
        Percent of the last sampling period the GPU was busy.
    memory_used, memory_total : float or None
        Memory in MiB.
    """

    index: int
    utilisation: float | None
    memory_used: float | None
    memory_total: float | None

    @property
    def load_percent(self) -> float:
        """The larger of its use and its share of memory in use; 100 if unknown."""
        util = 100.0 if self.utilisation is None else self.utilisation
        if self.memory_used is None or not self.memory_total:
            return util
        return max(util, 100.0 * self.memory_used / self.memory_total)


def parse_nvidia_smi(text: str) -> list[GpuState]:
    """Read the CSV printed by :data:`NVIDIA_QUERY`.

    Examples
    --------
    >>> parse_nvidia_smi("0, 35, 1024, 81920")[0].index
    0
    """

    def number(raw: str) -> float | None:
        try:
            return float(raw.strip())
        except ValueError:
            return None  # "[N/A]" and similar

    gpus = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4 or not parts[0].isdigit():
            continue
        gpus.append(GpuState(int(parts[0]), number(parts[1]), number(parts[2]), number(parts[3])))
    return gpus


class SystemProbes:
    """What the machine reports right now. Tests replace this with a fake.

    Every method returns None (or an empty value) rather than raising when the
    machine cannot say, so a laptop without GPUs or ``/proc`` still works.
    """

    def now(self) -> _dt.datetime:
        """The current local time."""
        return _cards.now_local()

    def cpu_count(self) -> int:
        """Cores on this machine."""
        return os.cpu_count() or 1

    def load_1min(self) -> float | None:
        """Processes running or waiting for a core, averaged over one minute."""
        try:
            return os.getloadavg()[0]
        except (AttributeError, OSError):
            return None

    def memory(self) -> tuple[int, int] | None:
        """Total and available memory in bytes, from ``/proc/meminfo``."""
        try:
            text = Path("/proc/meminfo").read_text(encoding="utf-8")
        except OSError:
            return None
        values: dict[str, int] = {}
        for line in text.splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts and parts[0].isdigit():
                values[key] = int(parts[0]) * 1024
        if "MemTotal" not in values or "MemAvailable" not in values:
            return None
        return values["MemTotal"], values["MemAvailable"]

    def gpus(self) -> list[GpuState] | None:
        """Every GPU, or None when ``nvidia-smi`` is missing or fails."""
        if shutil.which(NVIDIA_QUERY[0]) is None:
            return None
        try:
            result = subprocess.run(
                NVIDIA_QUERY,
                capture_output=True,
                text=True,
                timeout=COMMAND_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        return parse_nvidia_smi(result.stdout)

    def disk(self, path: Path) -> tuple[int, int, int] | None:
        """Total, used and free bytes on the disk holding ``path``."""
        target = existing_ancestor(path)
        try:
            usage = shutil.disk_usage(target)
        except OSError:
            return None
        return usage.total, usage.used, usage.free

    def has_tmux(self) -> bool:
        """Whether tmux is installed."""
        return shutil.which("tmux") is not None


def existing_ancestor(path: Path) -> Path:
    """The nearest folder at or above ``path`` that exists."""
    current = Path(path).expanduser()
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


# ---------------------------------------------------------------------------
# Reading what people type
# ---------------------------------------------------------------------------


def parse_size(text: str) -> int:
    """Read a size such as ``500G``, ``1.5TB`` or ``64GiB`` as bytes.

    Units are powers of 1024, which is how ``df`` and ``du -h`` count.

    Examples
    --------
    >>> parse_size("2G")
    2147483648
    """
    match = _SIZE.match(str(text))
    if not match:
        raise LaunchError(f"'{text}' is not a size. Write it like 500G, 2T or 64GB.")
    number, prefix, _ = match.groups()
    return int(float(number) * 1024 ** _SIZE_POWERS[prefix.lower()])


def parse_time(text: str, now: _dt.datetime) -> _dt.datetime:
    """Read ``HH:MM`` (the next time the clock shows it) or ``YYYY-MM-DD HH:MM``.

    Raises
    ------
    LaunchError
        For text that is neither, or a date and time already past.
    """
    raw = str(text).strip()
    clock = _CLOCK.match(raw)
    if clock:
        moment = now.replace(
            hour=int(clock.group(1)), minute=int(clock.group(2)), second=0, microsecond=0
        )
        return moment if moment > now else moment + _dt.timedelta(days=1)
    try:
        moment = _dt.datetime.fromisoformat(raw.replace(" ", "T", 1))
    except ValueError:
        raise LaunchError(f"'{text}' is not a time. Write 22:00, or 2026-10-17 22:00.") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=now.tzinfo)
    if moment <= now:
        raise LaunchError(f"{raw} has already passed.")
    return moment


def check_job_name(name: str) -> str:
    """Return a job name that is safe to post, or raise.

    A name is posted to Slack, so it may not look like a path: no slashes, and
    no more than 60 letters, digits, spaces, dots, dashes or underscores.
    """
    name = name.strip()
    if len(name) > JOB_NAME_MAX or not _NAME_OK.match(name):
        raise LaunchError(
            "A job name may use letters, digits, spaces, dots, dashes and underscores, "
            f"up to {JOB_NAME_MAX} characters, and no slashes. It is posted to Slack, "
            "so it should not be a file name."
        )
    return name


# ---------------------------------------------------------------------------
# Deciding the resources
# ---------------------------------------------------------------------------


@dataclass
class ResourceRequest:
    """What the person asked for.

    Attributes
    ----------
    cores : int or None
        ``--cores``; None means the policy's default.
    gpus : int
        ``--gpus``; 0 means none.
    memory_bytes : int or None
        ``--memory``: what the job expects to use.
    expect_disk_bytes : int or None
        ``--expect-disk``: what the job expects to write.
    disk_path : Path
        The folder whose disk is checked: ``--out``, else the working folder.
    exception : dict or None
        ``{"reason": ..., "until": ISO time}`` from ``--exception``/``--until``.
    """

    cores: int | None
    gpus: int
    memory_bytes: int | None
    expect_disk_bytes: int | None
    disk_path: Path
    exception: dict[str, str] | None = None


@dataclass
class ResourcePlan:
    """The outcome of :func:`plan_resources`.

    Attributes
    ----------
    ok : bool
        True when the job may start now.
    cores : int
        Cores given (also the thread limit).
    gpus : list of int
        GPU numbers given.
    refusals : list of str
        Why it may not start, one sentence each.
    can_wait : bool
        True when every refusal is about how busy the machine is right now, so
        waiting may help. False when the request breaks a rule.
    notes : list of str
        What was changed from the request and why, and other warnings.
    """

    ok: bool = True
    cores: int = 0
    gpus: list[int] = field(default_factory=list)
    refusals: list[str] = field(default_factory=list)
    can_wait: bool = True
    notes: list[str] = field(default_factory=list)

    def refuse(self, reason: str, *, can_wait: bool) -> None:
        """Record a reason the job may not start."""
        self.ok = False
        self.refusals.append(reason)
        self.can_wait = self.can_wait and can_wait


def exception_active(exception: dict[str, str] | None, moment: _dt.datetime) -> bool:
    """Whether an approved exception still applies at ``moment``."""
    if not exception:
        return False
    until = _cards.from_iso(exception.get("until"))
    return until is not None and moment < until


def plan_resources(
    request: ResourceRequest,
    policy: Policy,
    probes: SystemProbes,
    held: tuple[int, int, int] = (0, 0, 0),
) -> ResourcePlan:
    """Decide how many cores and which GPUs a job gets, or why it cannot start.

    Two kinds of limit apply. **Allowances** are per person (cores, GPUs, and
    memory claimed with ``--memory``); an approved exception lifts them.
    **Server protections** keep the machine usable for everyone (the load at
    which new work is held, the memory kept free, the disk); no exception lifts
    them.

    Parameters
    ----------
    request : ResourceRequest
        What the person asked for.
    policy : Policy
        The lab's rules.
    probes : SystemProbes
        What the machine reports.
    held : tuple of (int, int, int)
        Cores, GPUs and memory the person's other running jobs already hold.

    Returns
    -------
    ResourcePlan
        Never raises for a busy machine; the refusals say why.
    """
    plan = ResourcePlan()
    moment = probes.now()
    has_exception = exception_active(request.exception, moment)
    held_cores, held_gpus, held_memory = held

    _plan_cores(plan, request, policy, probes, held_cores, has_exception)
    _check_memory(plan, request, policy, probes, held_memory, has_exception)
    _plan_gpus(plan, request, policy, probes, held_gpus, has_exception, moment)
    _check_disk(plan, request, policy, probes)
    return plan


def _plan_cores(
    plan: ResourcePlan,
    request: ResourceRequest,
    policy: Policy,
    probes: SystemProbes,
    held_cores: int,
    has_exception: bool,
) -> None:
    asked = request.cores or policy.default_cores
    allowance = policy.max_cores_per_person - held_cores
    if not has_exception and asked > allowance:
        if allowance < 1:
            plan.refuse(
                f"Your running jobs already use {held_cores} cores, the most one person "
                f"may use at once ({policy.max_cores_per_person}). Wait for one to finish, "
                "or ask for an exception.",
                can_wait=True,
            )
            return
        plan.notes.append(
            f"You asked for {asked} cores; one person may use {policy.max_cores_per_person} "
            f"at once and your other jobs hold {held_cores}, so this job gets {allowance}. "
            "Ask for an exception to go above that."
        )
        asked = allowance
    cpu_count = probes.cpu_count()
    load = probes.load_1min()
    if load is None:
        plan.cores = min(asked, cpu_count)
        plan.notes.append("This machine does not report its load, so it was not checked.")
        return
    ceiling = cpu_count * policy.hold_new_work_at_load_fraction
    headroom = math.floor(ceiling - load)
    if headroom < 1:
        plan.refuse(
            f"The server is busy: its load is {load:.0f} on {cpu_count} cores, and new "
            f"work is held above {ceiling:.0f} so that others can still work.",
            can_wait=True,
        )
        return
    if asked > headroom:
        plan.notes.append(
            f"You asked for {asked} cores; the server is busy (load {load:.0f} on "
            f"{cpu_count} cores), so this job gets {headroom}."
        )
        asked = headroom
    plan.cores = asked


def _check_memory(
    plan: ResourcePlan,
    request: ResourceRequest,
    policy: Policy,
    probes: SystemProbes,
    held_memory: int,
    has_exception: bool,
) -> None:
    memory = probes.memory()
    if memory is None:
        plan.notes.append("This machine does not report its memory, so it was not checked.")
        return
    total, available = memory
    keep_free = total * policy.min_free_memory_fraction
    wanted = request.memory_bytes or 0
    if available < keep_free:
        plan.refuse(
            f"Memory is low: {_cards.format_size(available)} of "
            f"{_cards.format_size(total)} is free, and the lab keeps at least "
            f"{policy.min_free_memory_fraction:.0%} free.",
            can_wait=True,
        )
        return
    if wanted and available - wanted < keep_free:
        plan.refuse(
            f"Your job expects {_cards.format_size(wanted)} of memory. Only "
            f"{_cards.format_size(available)} is free, and starting it would leave less "
            f"than {policy.min_free_memory_fraction:.0%} free.",
            can_wait=True,
        )
    allowance = total * policy.memory_per_person_fraction
    if wanted and not has_exception and wanted + held_memory > allowance:
        plan.refuse(
            f"Your jobs would claim {_cards.format_size(wanted + held_memory)} of memory; "
            f"one person may claim {policy.memory_per_person_fraction:.0%} of the total "
            f"({_cards.format_size(allowance)}) without asking. Ask in the server channel, "
            'then add --exception "<reason>" --until <time>.',
            can_wait=False,
        )


def _plan_gpus(
    plan: ResourcePlan,
    request: ResourceRequest,
    policy: Policy,
    probes: SystemProbes,
    held_gpus: int,
    has_exception: bool,
    moment: _dt.datetime,
) -> None:
    if request.gpus <= 0:
        return
    gpus = probes.gpus()
    if not gpus:
        plan.refuse(
            "You asked for GPUs, but this machine reports none "
            "(nvidia-smi is missing or failed).",
            can_wait=False,
        )
        return
    if request.gpus > len(gpus):
        plan.refuse(
            f"You asked for {request.gpus} GPUs; this machine has {len(gpus)}.", can_wait=False
        )
        return
    idle = [g for g in gpus if g.load_percent < policy.gpu_idle_below_percent]
    allowance = policy.gpu_allowance(moment, len(idle)) - held_gpus
    if not has_exception and request.gpus > allowance:
        when = (
            "in working hours" if policy.working_hours.contains(moment) else "outside working hours"
        )
        # An allowance of "every idle GPU" grows as other jobs finish, so a
        # request that would fit if all GPUs were idle is worth waiting for.
        if_all_idle = policy.gpu_allowance(moment, len(gpus)) - held_gpus
        if request.gpus <= if_all_idle:
            plan.refuse(
                f"You asked for {request.gpus} GPUs; {when} you may use every idle GPU, "
                f"and {len(idle)} are idle now.",
                can_wait=True,
            )
            return
        plan.refuse(
            f"You asked for {request.gpus} GPUs; {when} one person may hold "
            f"{max(allowance + held_gpus, 0)}, and your other jobs hold {held_gpus}. "
            "Ask in the server channel first, then add "
            '--exception "<reason>" --until <time>.',
            can_wait=False,
        )
        return
    ranked = sorted(gpus, key=lambda g: (g.load_percent, g.index))
    chosen = ranked[: request.gpus]
    plan.gpus = sorted(g.index for g in chosen)
    busy = [g for g in chosen if g.load_percent >= policy.gpu_idle_below_percent]
    if busy:
        listed = ", ".join(f"GPU {g.index} ({g.load_percent:.0f}% in use)" for g in busy)
        plan.notes.append(
            f"The least-busy GPUs are already in use: {listed}. " "Your job will share them."
        )


def _check_disk(
    plan: ResourcePlan, request: ResourceRequest, policy: Policy, probes: SystemProbes
) -> None:
    disk = probes.disk(request.disk_path)
    if disk is None:
        plan.notes.append("The free space of the output folder could not be read.")
        return
    total, used, free = disk
    limit = policy.disk_fill_limit_fraction
    expected = request.expect_disk_bytes
    if expected:
        if expected > free:
            plan.refuse(
                f"Your job expects to write {_cards.format_size(expected)}, but its "
                f"output folder's disk has {_cards.format_size(free)} free.",
                can_wait=False,
            )
        elif total and (used + expected) / total > limit:
            plan.refuse(
                f"Your job expects to write {_cards.format_size(expected)}. That would "
                f"fill its output folder's disk past {limit:.0%} "
                f"({_cards.format_size(free)} free of {_cards.format_size(total)}).",
                can_wait=False,
            )
    elif total and used / total > limit:
        plan.notes.append(
            f"The output folder's disk is {used / total:.0%} full "
            f"({_cards.format_size(free)} free). Use --expect-disk to check your job fits."
        )


def thread_environment(cores: int, gpus: list[int], wants_gpus: bool) -> dict[str, str]:
    """The variables set for the job: thread limits and the GPUs it may see.

    A job that did not ask for GPUs sees none, so it cannot take one by
    accident. ``CUDA_DEVICE_ORDER`` makes CUDA number the GPUs as
    ``nvidia-smi`` does; without it the numbers can differ.
    """
    env = {name: str(cores) for name in THREAD_VARIABLES}
    env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"
    env["CUDA_VISIBLE_DEVICES"] = ",".join(str(g) for g in gpus) if wants_gpus else ""
    env["PYTHONUNBUFFERED"] = "1"  # so Python output reaches the log as it happens
    return env


# ---------------------------------------------------------------------------
# Which project, which Slack channel
# ---------------------------------------------------------------------------


@dataclass
class NotifyTarget:
    """Where a job's Slack notice goes, worked out when the job is launched.

    Attributes
    ----------
    project : str
        The project the job belongs to, or "".
    channel : str
        A Slack channel ID, or "".
    slack_group : str
        The lab whose bot posts, used when the project has no record.
    reason : str
        Why no notice can be posted, when ``channel`` is empty.
    """

    project: str = ""
    channel: str = ""
    slack_group: str = ""
    reason: str = ""


def project_for_folder(folder: Path) -> tuple[str, dict]:
    """The project a folder belongs to, and its repository's marker settings.

    The name comes from ``update_me.project`` in the nearest ``.murmurent.yaml``,
    else its ``name``, else the project record's rule (``CHARTER.md`` or the
    folder name). Returns ``("", {})`` outside any murmurent repository.
    """
    try:
        from . import cert_projects as _cp
        from .repo import find_project_repo
        from .repo_ready import read_marker
    except Exception:  # noqa: BLE001
        return "", {}
    repo = find_project_repo(folder)
    if repo is None:
        return "", {}
    marker = read_marker(repo.path) or {}
    block = marker.get("update_me") if isinstance(marker.get("update_me"), dict) else {}
    name = str(block.get("project") or marker.get("name") or "")
    if not name:
        name = _cp.project_name_for_cwd(folder) or ""
    return name, marker


def resolve_notify_target(folder: Path) -> NotifyTarget:
    """Find the Slack channel and the lab bot for jobs started in ``folder``.

    The channel is the one ``/murmurent-update-me`` uses: ``update_me.channel``
    in the repository's ``.murmurent.yaml``, else the project's own channel in
    its record.
    """
    project, marker = project_for_folder(folder)
    target = NotifyTarget(project=project)
    if not project:
        target.reason = "this folder is not part of a murmurent project"
        return target
    block = marker.get("update_me") if isinstance(marker.get("update_me"), dict) else {}
    target.slack_group = str(block.get("lab") or marker.get("lab") or "").removeprefix("lab_")
    # One resolver for every note about a repository (issue #243): the marker's
    # own channel, else the project's, else the lab's, else nowhere.
    try:
        from .slack_routing import resolve_route

        route = resolve_route(folder, project=project or None, honour_marker=True)
    except Exception:  # noqa: BLE001
        route = None
    if route is not None:
        target.channel = route.channel_id
        target.slack_group = target.slack_group or route.lab
        if not target.channel:
            target.reason = route.reason
    if not target.channel and not target.reason:
        target.reason = f"no Slack channel is recorded for the project '{project}'"
    return target


def resolve_notify_token(project: str, slack_group: str) -> str:
    """The lab bot's token for a project's channel, or "" when there is none.

    Uses the same route as ``murmurent project push``: the project record's
    workspace when the project is registered, else the lab named in the
    repository's marker. The token is never written to the card.
    """
    try:
        from . import cert_projects as _cp

        if project and _cp.get(project) is not None:
            from .cert_provision import resolve_project_slack

            return resolve_project_slack(project)[1] or ""
    except Exception:  # noqa: BLE001, S110 - fall through to the lab's own token
        pass
    if not slack_group:
        return ""
    try:
        from .group_reconcile import resolve_group_slack_token

        return resolve_group_slack_token(slack_group) or ""
    except Exception:  # noqa: BLE001
        return ""


def disk_warning_text(card: _cards.JobCard, hours: float, free_bytes: float) -> str:
    """The one line sent when a job would fill its disk soon (#151). No paths."""
    return (f"Job {card.name} ({card.user}) is filling its disk: at the rate of its first "
            f"minutes, the disk is full in about {hours:.0f} h ({_cards.format_size(free_bytes)} "
            "free). Check that its output is going where it should, or make room.")


def notice_text(card: _cards.JobCard) -> str:
    """The one line posted to Slack: name, owner, state, duration, exit code.

    Never the command line or a file path: those can contain file names that
    identify patients.
    """
    duration = _cards.format_duration(card.duration_seconds())
    who = f"{card.name} ({card.user})"
    if card.state == _cards.STATE_FINISHED:
        return f"Job {who} finished after {duration}. Exit code {card.exit_code}."
    if card.state == _cards.STATE_FAILED:
        if card.started_at is None:
            return f"Job {who} could not start."
        code = "unknown" if card.exit_code is None else card.exit_code
        return f"Job {who} failed after {duration}. Exit code {code}."
    if card.state == _cards.STATE_STALLED:
        return (
            f"Job {who} has written no new output for {card.stall_minutes} min and "
            f"may be stuck. It has been running for {duration}."
        )
    return f"Job {who} is {card.state}."


Poster = Callable[..., bool]


def post_notice(
    card: _cards.JobCard,
    *,
    poster: Poster | None = None,
    token_resolver: Callable[[str, str], str] | None = None,
    text: str | None = None,
) -> bool:
    """Post the card's one-line notice, and record on the card what happened.

    Skips quietly (with a note on the card) when notices are off, or when no
    channel or token can be found. Never raises.
    """
    notify = card.notify
    if not notify.get("enabled", False):
        return False
    channel = str(notify.get("channel") or "")
    if not channel:
        notify["skipped"] = notify.get("reason") or "no Slack channel is known"
        return False
    resolver = token_resolver or resolve_notify_token
    try:
        token = resolver(card.project, str(notify.get("slack_group") or ""))
    except Exception:  # noqa: BLE001
        token = ""
    if not token:
        notify["skipped"] = "no Slack token for the lab's bot on this account"
        return False
    if poster is None:
        from ..dashboard import slack_notify as _sn

        poster = _sn._post
    try:
        posted = bool(poster(channel, text or notice_text(card), token=token))
    except Exception:  # noqa: BLE001 - a Slack problem never fails a job
        posted = False
    notify.setdefault("posted", []).append(
        {"at": _cards.to_iso(_cards.now_local()), "state": card.state, "ok": posted}
    )
    if not posted:
        notify["skipped"] = "Slack did not accept the message"
    return posted


# ---------------------------------------------------------------------------
# Starting the job
# ---------------------------------------------------------------------------


@dataclass
class LaunchOptions:
    """Everything ``murmurent run`` (or ``murmurent jobs restart``) was given."""

    command: list[str]
    workdir: Path
    name: str = ""
    cores: int | None = None
    gpus: int = 0
    memory: str = ""
    out: str = ""
    inputs: tuple[str, ...] = ()
    expect_disk: str = ""
    log: str = ""
    watch: str = ""
    stall_after: int | None = None
    at: str = ""
    when_load_below: float | None = None
    wait: bool = False
    exception: str = ""
    until: str = ""
    session: str = ""
    notify: bool = True
    dry_run: bool = False
    restarted_from: str = ""
    pass_env: tuple[str, ...] = ()


@dataclass
class LaunchResult:
    """What :func:`launch` did, for the command to report."""

    card: _cards.JobCard
    plan: ResourcePlan | None
    started_now: bool
    lines: list[str] = field(default_factory=list)


class TmuxRunner:
    """Start the supervisor inside tmux. Tests replace this with a fake."""

    def session_exists(self, session: str) -> bool:
        """Whether a tmux session with this name is running."""
        result = subprocess.run(
            ["tmux", "has-session", "-t", f"={session}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        return result.returncode == 0

    def start(self, session: str, window: str, workdir: Path, command: str) -> None:
        """Run ``command`` in a new detached session, or a new window of ``session``."""
        if self.session_exists(session):
            args = [
                "tmux",
                "new-window",
                "-d",
                "-t",
                f"={session}:",
                "-n",
                window,
                "-c",
                str(workdir),
                command,
            ]
        else:
            args = [
                "tmux",
                "new-session",
                "-d",
                "-s",
                session,
                "-n",
                window,
                "-c",
                str(workdir),
                command,
            ]
        result = subprocess.run(
            args, capture_output=True, text=True, check=False, timeout=COMMAND_TIMEOUT_SECONDS
        )
        if result.returncode != 0:
            raise LaunchError(f"tmux could not start the job: {result.stderr.strip()}")


def environment_snapshot_path(job_id: str) -> Path:
    """The private file holding the person's environment until the job starts."""
    return _cards.runs_dir() / f"{job_id}{_cards.ENV_SUFFIX}"


# Names that look like they hold a secret: tokens, passwords, keys. The job does
# not get these unless the person names them with ``--pass-env``, because the
# copy of the environment waits on disk until the job starts (for a delayed job,
# hours), and a job rarely needs them.
SECRET_NAME_PATTERN = re.compile(
    r"TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|CREDENTIAL|PRIVATE|API_?KEY|ACCESS_?KEY"
    r"|_KEY$|^KEY$|AUTH",
    re.IGNORECASE,
)


def filter_environment(
    environ: dict[str, str], pass_env: tuple[str, ...] | list[str] = ()
) -> tuple[dict[str, str], list[str]]:
    """Split the environment into what the job gets and the secret-looking names left out.

    Parameters
    ----------
    environ : dict
        The person's environment.
    pass_env : sequence of str
        Names to keep even though they look like secrets.

    Returns
    -------
    tuple
        The environment to give the job, and the sorted names left out (names
        only; their values are never recorded).

    Examples
    --------
    >>> filter_environment({"PATH": "/bin", "GH_TOKEN": "x"})
    ({'PATH': '/bin'}, ['GH_TOKEN'])
    """
    allowed = {name for name in pass_env}
    kept: dict[str, str] = {}
    left_out: list[str] = []
    for name, value in environ.items():
        if SECRET_NAME_PATTERN.search(name) and name not in allowed:
            left_out.append(name)
        else:
            kept[name] = value
    return kept, sorted(left_out)


def write_environment_snapshot(job_id: str, environ: dict[str, str]) -> Path:
    """Save the environment for the supervisor, readable by the owner only.

    The supervisor deletes it as soon as it has read it. It can hold tokens, so
    it never goes on the card and never leaves the home folder.
    """
    path = environment_snapshot_path(job_id)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(dict(environ), handle)
    return path


def supervisor_command(card_file: Path, priority: int) -> str:
    """The shell line tmux runs: the supervisor, at low priority.

    ``-P`` stops Python looking for modules in the job's own folder first, so a
    file there that happens to be called ``json.py`` cannot replace the real one.
    The supervisor's own error messages go to a file beside the card, so they
    survive the tmux window closing.
    """
    errors = _cards.supervisor_log_path(card_file.stem)
    return (
        shlex.join(
            [
                "nice",
                "-n",
                str(priority),
                sys.executable,
                "-P",
                "-m",
                "murmurent.core.run_supervisor",
                str(card_file),
            ]
        )
        + f" 2>> {shlex.quote(str(errors))}"
    )


class _ProbesAt:
    """The machine's probes, but with the clock set to a planned start time."""

    def __init__(self, inner: SystemProbes, moment: _dt.datetime) -> None:
        self._inner = inner
        self._moment = moment

    def now(self) -> _dt.datetime:
        return self._moment

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def _resolve_path(text: str, workdir: Path) -> Path:
    path = Path(text).expanduser()
    return path if path.is_absolute() else (workdir / path)


def _build_exception(options: LaunchOptions, now: _dt.datetime) -> dict[str, str] | None:
    if not options.exception and not options.until:
        return None
    if not options.exception or not options.until:
        raise LaunchError(
            "An exception needs both a reason and an end time: "
            '--exception "<reason>" --until 23:00.'
        )
    until = parse_time(options.until, now)
    return {
        "reason": options.exception.strip(),
        "until": _cards.to_iso(until) or "",
        "recorded_at": _cards.to_iso(now) or "",
    }


def launch(
    options: LaunchOptions,
    *,
    probes: SystemProbes | None = None,
    policy: Policy | None = None,
    tmux: TmuxRunner | None = None,
    environ: dict[str, str] | None = None,
) -> LaunchResult:
    """Check the request, write the job card, and start the supervisor in tmux.

    Parameters
    ----------
    options : LaunchOptions
        What the person asked for.
    probes, policy, tmux, environ : optional
        Replacements for the real machine, lab policy, tmux and environment;
        tests pass fakes.

    Returns
    -------
    LaunchResult
        The card, the resource plan, and lines to print.

    Raises
    ------
    LaunchError
        When tmux is missing, the request breaks a rule, or the machine is too
        busy and the person did not ask to wait.
    """
    probes = probes or SystemProbes()
    policy = policy or load_policy()
    tmux = tmux or TmuxRunner()
    environ = dict(os.environ) if environ is None else environ
    if not options.command:
        raise LaunchError(
            "Give the command to run after --, for example: "
            "murmurent run --cores 8 -- Rscript fit.R"
        )
    if not probes.has_tmux():
        raise LaunchError(
            "tmux is not installed on this machine, so the job could not be protected "
            "against a dropped connection. Ask the server's administrator to install "
            "tmux, or start the job some other way."
        )

    now = probes.now()
    workdir = Path(options.workdir).expanduser().resolve()
    job_id = _cards.new_job_id(now)
    name = check_job_name(options.name) if options.name else job_id
    exception = _build_exception(options, now)
    start_at = parse_time(options.at, now) if options.at else None
    memory_bytes = parse_size(options.memory) if options.memory else None
    expect_disk = parse_size(options.expect_disk) if options.expect_disk else None
    if options.cores is not None and options.cores < 1:
        raise LaunchError("--cores must be at least 1.")
    if options.gpus < 0:
        raise LaunchError("--gpus cannot be negative.")
    if options.stall_after is not None and options.stall_after < 1:
        raise LaunchError("--stall-after must be at least 1 minute.")
    if options.when_load_below is not None and options.when_load_below <= 0:
        raise LaunchError("--when-load-below must be more than 0.")
    exception_end = _cards.from_iso(exception["until"]) if exception else None
    if exception_end and start_at and exception_end <= start_at:
        raise LaunchError(
            f"The exception ends at {options.until}, before the job starts at "
            f"{options.at}. Give an end time after the start."
        )
    out = _resolve_path(options.out, workdir) if options.out else None
    log = (
        _resolve_path(options.log, workdir) if options.log else _cards.runs_dir() / f"{job_id}.log"
    )
    watch = _resolve_path(options.watch, workdir) if options.watch else log
    # Recorded so the space scan can tell later whether this job's output could
    # be made again: it can only if the inputs still exist (#151, step 2).
    inputs = [str(_resolve_path(i, workdir)) for i in options.inputs if str(i).strip()]
    stall_minutes = options.stall_after or policy.stall_minutes

    request = ResourceRequest(
        cores=options.cores,
        gpus=options.gpus,
        memory_bytes=memory_bytes,
        expect_disk_bytes=expect_disk,
        disk_path=out or workdir,
        exception=exception,
    )
    cards = _cards.mark_lost_cards(_cards.list_cards())
    delayed = bool(start_at or options.when_load_below)
    # A job that starts later is checked against the rules in force at its start
    # time (the GPU allowance differs at night). How busy the machine is now does
    # not matter for it; the supervisor checks that again when the time comes.
    plan_probes = _ProbesAt(probes, start_at) if start_at else probes
    plan = plan_resources(request, policy, plan_probes, _cards.resources_held(cards))  # type: ignore[arg-type]
    if not plan.ok and not (plan.can_wait and (options.wait or delayed)):
        hint = ""
        if plan.can_wait:
            hint = (
                " Add --wait to start it as soon as there is room, or --at 22:00 to "
                "start it tonight."
            )
        raise LaunchError(" ".join(plan.refusals) + hint)

    target = resolve_notify_target(workdir)
    card = _cards.JobCard(
        id=job_id,
        name=name,
        user=getpass.getuser(),
        host=_cards.this_host(),
        command=list(options.command),
        workdir=str(workdir),
        log=str(log),
        watch=str(watch),
        out=str(out) if out else "",
        inputs=inputs,
        project=target.project,
        tmux_session=options.session or f"{TMUX_PREFIX}{job_id}",
        tmux_window=name.replace(" ", "_")[:30],
        priority=policy.priority,
        stall_minutes=stall_minutes,
        requested={
            "cores": options.cores,
            "gpus": options.gpus,
            "memory_bytes": memory_bytes,
            "expect_disk_bytes": expect_disk,
            "at": _cards.to_iso(start_at),
            "when_load_below": options.when_load_below,
            "wait": options.wait,
            "session": options.session,
            "log_given": bool(options.log),
            "pass_env": list(options.pass_env),
        },
        exception=exception,
        created_at=_cards.to_iso(now),
        restarted_from=options.restarted_from,
        notify={
            "enabled": options.notify,
            "channel": target.channel,
            "slack_group": target.slack_group,
            "reason": target.reason,
        },
    )
    seconds, runs = _cards.estimate_duration(cards, card.command, card.workdir)
    if seconds is not None:
        card.estimates.update({"duration_seconds": seconds, "duration_runs": runs})
    if expect_disk:
        card.estimates["expect_disk_bytes"] = expect_disk

    started_now = plan.ok and not delayed
    if started_now:
        card.cores = plan.cores
        card.gpus = plan.gpus
        card.env_set = thread_environment(plan.cores, plan.gpus, options.gpus > 0)
        card.waiting_for = "its start, in a moment"
    else:
        card.waiting_for = waiting_description(card)

    result = LaunchResult(card=card, plan=plan, started_now=started_now)
    result.lines = describe_launch(
        card, None if delayed else plan, started_now, policy, dry_run=options.dry_run
    )
    if options.dry_run:
        result.lines.insert(0, "Dry run: nothing was started and no card was written.")
        return result

    job_environ, left_out = filter_environment(environ, options.pass_env)
    if left_out:
        card.add_note(
            "Left out of the job's environment because the names look like secrets: "
            + ", ".join(left_out)
            + ". Pass one with --pass-env NAME if the job needs it."
        )
    card_file = _cards.write_card(card)
    write_environment_snapshot(job_id, job_environ)
    try:
        tmux.start(
            card.tmux_session,
            card.tmux_window,
            workdir,
            supervisor_command(card_file, policy.priority),
        )
    except (LaunchError, OSError, subprocess.SubprocessError) as exc:
        environment_snapshot_path(job_id).unlink(missing_ok=True)
        card.state = _cards.STATE_FAILED
        card.add_note(f"tmux could not start the job: {exc}")
        _cards.write_card(card)
        raise LaunchError(str(exc)) from exc
    return result


def waiting_description(card: _cards.JobCard) -> str:
    """Say in words what a waiting job is waiting for."""
    parts = []
    at = _cards.from_iso(card.requested.get("at"))
    if at:
        parts.append(f"the start time {at:%Y-%m-%d %H:%M}")
    below = card.requested.get("when_load_below")
    if below:
        parts.append(f"the server's load to fall below {below:g}")
    if not parts:
        parts.append("room on the server")
    return " and ".join(parts)


def describe_launch(
    card: _cards.JobCard,
    plan: ResourcePlan | None,
    started_now: bool,
    policy: Policy,
    *,
    dry_run: bool = False,
) -> list[str]:
    """Plain-English lines saying what was started and with what."""
    lines = []
    if started_now:
        gpu_text = (
            (
                f" and GPU{'s' if len(card.gpus) > 1 else ''} "
                f"{', '.join(str(g) for g in card.gpus)}"
            )
            if card.gpus
            else ""
        )
        verb = "Would start" if dry_run else "Started"
        lines.append(
            f"{verb} job {card.name} on {card.cores} "
            f"core{'s' if card.cores != 1 else ''}{gpu_text}, at priority "
            f"nice {card.priority}."
        )
        if not card.gpus:
            lines.append("  It cannot see any GPU. Use --gpus to ask for one.")
    else:
        lines.append(
            f"Job {card.name} is waiting for {card.waiting_for}. Cores and GPUs "
            "are chosen when it starts."
        )
    if plan:
        for note in plan.notes:
            lines.append(f"  {note}")
        if not plan.ok:
            for refusal in plan.refusals:
                lines.append(f"  Not yet: {refusal}")
    if card.exception:
        lines.append(
            f"  Exception recorded until {card.exception['until']}: " f"{card.exception['reason']}"
        )
    estimate = card.estimates.get("duration_seconds")
    if estimate:
        lines.append(
            f"  Estimate: {_cards.about(estimate)}, from "
            f"{card.estimates.get('duration_runs')} earlier run(s) (an estimate)."
        )
    lines.append(f"  Output goes to the log: {card.log}")
    lines.append(f"  Watch it live: tmux attach -t {card.tmux_session}")
    lines.append(f"  Check on it: murmurent jobs show {card.id}")
    if not card.notify.get("enabled"):
        lines.append("  Slack: notices are off for this job.")
    elif card.notify.get("channel"):
        lines.append(
            "  Slack: one line goes to the project's channel when it finishes, " "fails or stalls."
        )
    else:
        lines.append(
            f"  Slack: no notice will be posted, because "
            f"{card.notify.get('reason') or 'no channel is known'}."
        )
    for problem in policy.problems:
        lines.append(f"  Policy problem: {problem}")
    return lines


def restart_options(card: _cards.JobCard, *, wait: bool = False) -> LaunchOptions:
    """Launch options that run the same job again, starting as soon as possible.

    The new job keeps the old one's name, command, folders and requests. An
    exception is kept only while it still applies.
    """
    requested = card.requested or {}
    exception = card.exception or {}
    still_valid = exception_active(card.exception, _cards.now_local())
    memory = requested.get("memory_bytes")
    expect = requested.get("expect_disk_bytes")
    return LaunchOptions(
        command=list(card.command),
        workdir=Path(card.workdir),
        name=card.name if card.name != card.id else "",
        cores=requested.get("cores"),
        gpus=int(requested.get("gpus") or 0),
        memory=str(memory) if memory else "",
        out=card.out,
        inputs=tuple(card.inputs or ()),
        expect_disk=str(expect) if expect else "",
        log=card.log if requested.get("log_given") else "",
        watch=card.watch if card.watch != card.log else "",
        stall_after=card.stall_minutes,
        wait=wait,
        exception=exception.get("reason", "") if still_valid else "",
        until=exception.get("until", "") if still_valid else "",
        session=str(requested.get("session") or ""),
        notify=bool(card.notify.get("enabled")),
        restarted_from=card.id,
        pass_env=tuple(requested.get("pass_env") or ()),
    )


__all__ = [
    "GpuState",
    "LaunchError",
    "LaunchOptions",
    "LaunchResult",
    "NotifyTarget",
    "ResourcePlan",
    "ResourceRequest",
    "SystemProbes",
    "THREAD_VARIABLES",
    "TmuxRunner",
    "check_job_name",
    "describe_launch",
    "exception_active",
    "launch",
    "notice_text",
    "parse_nvidia_smi",
    "parse_size",
    "parse_time",
    "plan_resources",
    "post_notice",
    "project_for_folder",
    "resolve_notify_target",
    "resolve_notify_token",
    "restart_options",
    "supervisor_command",
    "thread_environment",
    "filter_environment",
    "waiting_description",
    "write_environment_snapshot",
]
