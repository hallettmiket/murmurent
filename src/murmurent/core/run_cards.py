"""
Purpose: Job cards for ``murmurent run``: one small JSON file per job saying what
         was run, where, with what resources, and how it went.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-16
Input:   Cards under ``~/.murmurent/runs/<id>.json`` (``$MURMURENT_HOME`` moves
         the whole ``~/.murmurent`` folder, as everywhere in murmurent).
Output:  :class:`JobCard` objects; atomic writes back to the same files.

Issue #151, step 1. A card is written by the launcher, kept up to date by the
supervisor that runs the job inside tmux, and read by ``murmurent jobs``.

Cards hold the command line and file paths, so they stay in the person's own
home folder (folder mode 0700, files 0600) and are never posted anywhere. The
Slack notice is built from the name, state, duration and exit code only.

Not to be confused with ``core/jobs.py``, which holds core-facility service jobs.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import secrets
import socket
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CARD_SCHEMA = 1
RUNS_SUBDIR = "runs"

STATE_WAITING = "waiting"
STATE_RUNNING = "running"
STATE_STALLED = "stalled"
STATE_FINISHED = "finished"
STATE_FAILED = "failed"
STATE_STOPPED = "stopped"

ACTIVE_STATES = (STATE_WAITING, STATE_RUNNING, STATE_STALLED)
ENDED_STATES = (STATE_FINISHED, STATE_FAILED, STATE_STOPPED)

#: How many earlier runs feed a time estimate.
ESTIMATE_HISTORY = 5


def now_local() -> _dt.datetime:
    """The current time, with the machine's time zone attached."""
    return _dt.datetime.now().astimezone()


def to_iso(moment: _dt.datetime | None) -> str | None:
    """Format a time for a card, to the second."""
    return moment.isoformat(timespec="seconds") if moment else None


def from_iso(text: str | None) -> _dt.datetime | None:
    """Read a time written by :func:`to_iso`; None for a missing or bad value."""
    if not text:
        return None
    try:
        moment = _dt.datetime.fromisoformat(text)
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.astimezone()


def runs_dir(env: dict[str, str] | None = None) -> Path:
    """The folder holding this person's job cards, created private on first use.

    Parameters
    ----------
    env : dict, optional
        Environment to read ``$MURMURENT_HOME`` from.

    Returns
    -------
    Path
        ``<murmurent home>/runs``, always absolute, because the supervisor starts
        in the job's own folder.
    """
    env = os.environ if env is None else env
    home = Path(env.get("MURMURENT_HOME") or (Path.home() / ".murmurent")).expanduser()
    folder = home.resolve() / RUNS_SUBDIR
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    return folder


def new_job_id(moment: _dt.datetime | None = None) -> str:
    """A job id that sorts by time and is safe as a tmux session name.

    Examples
    --------
    >>> len(new_job_id())
    20
    """
    moment = moment or now_local()
    return f"{moment:%Y%m%d-%H%M%S}-{secrets.token_hex(2)}"


@dataclass
class JobCard:
    """Everything known about one job.

    The fields are the card's JSON keys. Times are ISO strings, so the file reads
    the same in any language. ``requested`` holds what the person asked for;
    ``cores`` and ``gpus`` hold what was given.
    """

    id: str
    name: str
    user: str
    host: str
    command: list[str]
    workdir: str
    log: str
    watch: str
    out: str = ""
    inputs: list[str] = field(default_factory=list)
    project: str = ""
    tmux_session: str = ""
    tmux_window: str = ""
    priority: int = 19
    requested: dict[str, Any] = field(default_factory=dict)
    cores: int = 0
    gpus: list[int] = field(default_factory=list)
    env_set: dict[str, str] = field(default_factory=dict)
    state: str = STATE_WAITING
    waiting_for: str = ""
    created_at: str | None = None
    started_at: str | None = None
    ended_at: str | None = None
    exit_code: int | None = None
    stall_minutes: int = 60
    last_output_at: str | None = None
    estimates: dict[str, Any] = field(default_factory=dict)
    disk_samples: list[dict[str, Any]] = field(default_factory=list)
    exception: dict[str, str] | None = None
    notify: dict[str, Any] = field(default_factory=dict)
    notes: list[dict[str, str]] = field(default_factory=list)
    supervisor_pid: int | None = None
    child_pid: int | None = None
    restarted_from: str = ""
    schema: int = CARD_SCHEMA

    def add_note(self, text: str, moment: _dt.datetime | None = None) -> None:
        """Append a dated, plain-English note to the card."""
        self.notes.append({"at": to_iso(moment or now_local()) or "", "text": text})

    def duration_seconds(self, moment: _dt.datetime | None = None) -> float | None:
        """Seconds from start to end, or to ``moment`` while still running."""
        start = from_iso(self.started_at)
        if start is None:
            return None
        end = from_iso(self.ended_at) or moment or now_local()
        return max(0.0, (end - start).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        """The card as a JSON-ready dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobCard:
        """Build a card from a dict, ignoring keys this version does not know."""
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def card_path(job_id: str, env: dict[str, str] | None = None) -> Path:
    """Where the card for ``job_id`` lives."""
    return runs_dir(env) / f"{job_id}.json"


def write_card(card: JobCard, path: Path | None = None) -> Path:
    """Write a card atomically (a half-written card is never visible).

    Parameters
    ----------
    card : JobCard
        The card to save.
    path : Path, optional
        Where to save it; defaults to :func:`card_path`.

    Returns
    -------
    Path
        The file written.
    """
    target = path or card_path(card.id)
    tmp = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(card.to_dict(), handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, target)
    return target


def read_card(path: Path) -> JobCard | None:
    """Read one card; None when the file is missing or not a card."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "id" not in data:
        return None
    try:
        return JobCard.from_dict(data)
    except TypeError:
        return None


ENV_SUFFIX = ".env.json"
SUPERVISOR_LOG_SUFFIX = ".supervisor.log"

#: How long after launch a card may still lack the supervisor's process number.
START_GRACE_SECONDS = 120


def list_cards(env: dict[str, str] | None = None) -> list[JobCard]:
    """Every readable card, newest first."""
    paths = [p for p in runs_dir(env).glob("*.json") if not p.name.endswith(ENV_SUFFIX)]
    cards = [c for c in (read_card(p) for p in paths) if c]
    return sorted(cards, key=lambda c: c.created_at or c.id, reverse=True)


def supervisor_log_path(job_id: str, env: dict[str, str] | None = None) -> Path:
    """Where the supervisor's own error messages go, if it has any."""
    return runs_dir(env) / f"{job_id}{SUPERVISOR_LOG_SUFFIX}"


def find_card(key: str, env: dict[str, str] | None = None) -> JobCard | None:
    """Find a card by id, by the start of an id, or by job name.

    An exact id wins, then a unique id prefix, then the newest job with that
    name. Returns None when nothing matches or a prefix is ambiguous.
    """
    key = key.strip()
    if not key:
        return None
    exact = read_card(card_path(key, env))
    if exact:
        return exact
    cards = list_cards(env)
    by_prefix = [c for c in cards if c.id.startswith(key)]
    if len(by_prefix) == 1:
        return by_prefix[0]
    by_name = [c for c in cards if c.name == key]
    return by_name[0] if by_name else None


def this_host() -> str:
    """The short name of this machine, as recorded on cards."""
    return socket.gethostname().split(".")[0]


def supervisor_alive(card: JobCard) -> bool | None:
    """Whether the card's supervisor is still running.

    Returns
    -------
    bool or None
        None when the card belongs to another machine (a home folder shared
        between servers), so nothing can be said from here.
    """
    if card.host and card.host != this_host():
        return None
    pid = card.supervisor_pid
    if not pid:
        created = from_iso(card.created_at)
        if created and (now_local() - created).total_seconds() < START_GRACE_SECONDS:
            return None  # tmux is still starting it
        return False
    cmdline = Path(f"/proc/{pid}/cmdline")
    if cmdline.parent.parent.is_dir() and Path("/proc/self").exists():
        try:
            return card.id in cmdline.read_bytes().decode("utf-8", "replace")
        except OSError:
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def mark_lost_cards(cards: list[JobCard]) -> list[JobCard]:
    """Record an end on active cards whose supervisor has gone.

    This happens when the server restarts or the supervisor is killed hard. The
    card is marked failed with a note, so it does not show as running for ever.
    """
    for card in cards:
        if card.state in ACTIVE_STATES and supervisor_alive(card) is False:
            card.state = STATE_FAILED
            card.ended_at = card.ended_at or to_iso(now_local())
            note = (
                "The job stopped without recording an end. The server may have "
                "restarted, or its window was closed by force."
            )
            errors = supervisor_log_path(card.id)
            if errors.is_file() and errors.stat().st_size > 0:
                note += f" Error messages, if any, are in {errors}."
            card.add_note(note)
            write_card(card)
    return cards


def resources_held(cards: list[JobCard], exclude_id: str = "") -> tuple[int, int, int]:
    """Cores, GPUs and stated memory held by this person's active jobs here.

    Parameters
    ----------
    cards : list of JobCard
        The person's cards.
    exclude_id : str
        A job to leave out, usually the one being planned.

    Returns
    -------
    tuple of (int, int, int)
        Cores, number of GPUs, and bytes of memory stated with ``--memory``.
    """
    cores = gpus = memory = 0
    for card in cards:
        if card.id == exclude_id or card.state not in (STATE_RUNNING, STATE_STALLED):
            continue
        if card.host and card.host != this_host():
            continue
        if supervisor_alive(card) is False:
            continue
        cores += int(card.cores or 0)
        gpus += len(card.gpus or [])
        memory += int((card.requested or {}).get("memory_bytes") or 0)
    return cores, gpus, memory


def estimate_duration(
    cards: list[JobCard], command: list[str], workdir: str, exclude_id: str = ""
) -> tuple[float | None, int]:
    """Estimate a job's running time from earlier successful runs.

    Parameters
    ----------
    cards : list of JobCard
        The person's cards.
    command : list of str
        The command being estimated.
    workdir : str
        The folder it runs in.
    exclude_id : str
        A job to leave out, usually the one being estimated.

    Returns
    -------
    tuple of (float or None, int)
        The median duration in seconds of the last few finished runs of the same
        command in the same folder, and how many runs it is based on. None and 0
        when there is no earlier run.
    """
    durations: list[float] = []
    for card in cards:  # newest first
        if card.id == exclude_id or card.state != STATE_FINISHED:
            continue
        if list(card.command) != list(command) or card.workdir != workdir:
            continue
        seconds = card.duration_seconds()
        if seconds is not None:
            durations.append(seconds)
        if len(durations) >= ESTIMATE_HISTORY:
            break
    if not durations:
        return None, 0
    return float(statistics.median(durations)), len(durations)


def about(seconds: float | None) -> str:
    """An estimated duration: "about 2 h", or "less than a minute".

    Examples
    --------
    >>> about(7200)
    'about 2 h'
    """
    text = format_duration(seconds)
    return text if text in ("unknown", "less than a minute") else f"about {text}"


def format_duration(seconds: float | None) -> str:
    """A duration in words a person reads at a glance.

    Examples
    --------
    >>> format_duration(3 * 3600 + 12 * 60)
    '3 h 12 min'
    >>> format_duration(40)
    'less than a minute'
    """
    if seconds is None:
        return "unknown"
    minutes = int(seconds // 60)
    if minutes < 1:
        return "less than a minute"
    days, rest = divmod(minutes, 24 * 60)
    hours, minutes = divmod(rest, 60)
    parts = []
    if days:
        parts.append(f"{days} d")
    if hours:
        parts.append(f"{hours} h")
    if minutes and not days:
        parts.append(f"{minutes} min")
    return " ".join(parts) or "less than a minute"


def format_size(size: float | None) -> str:
    """A byte count in the units people use for disks.

    Examples
    --------
    >>> format_size(1.5 * 1024 ** 3)
    '1.5 GB'
    """
    if size is None:
        return "unknown"
    value = float(size)
    for unit in ("bytes", "KB", "MB", "GB", "TB", "PB"):
        if abs(value) < 1024 or unit == "PB":
            return f"{value:.0f} {unit}" if unit == "bytes" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


__all__ = [
    "about",
    "ACTIVE_STATES",
    "CARD_SCHEMA",
    "ENDED_STATES",
    "JobCard",
    "STATE_FAILED",
    "STATE_FINISHED",
    "STATE_RUNNING",
    "STATE_STALLED",
    "STATE_STOPPED",
    "STATE_WAITING",
    "card_path",
    "estimate_duration",
    "find_card",
    "format_duration",
    "format_size",
    "from_iso",
    "list_cards",
    "mark_lost_cards",
    "new_job_id",
    "now_local",
    "read_card",
    "resources_held",
    "runs_dir",
    "supervisor_alive",
    "supervisor_log_path",
    "this_host",
    "to_iso",
    "write_card",
]
