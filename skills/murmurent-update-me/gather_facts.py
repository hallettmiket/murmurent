#!/usr/bin/env python3
"""
Purpose: Gather read-only facts about a project's builds and computation,
         for the /murmurent-update-me skill. It reports the clock, analyses
         running on any lab account, agents started but not finished, the
         newest outputs in the data tree, the latest gate results, git state of
         the two repositories, open progress issues on GitHub, and items in the
         output tree that this account cannot open.
Author: blacksmith (Claude Code) for Mike Hallett
Date: 2026-09-30 (survival project); generalised for every project 2026-10-14 (#152)
Input: Nothing from the data tree is read except, for each phase, the verdict
       line and the assertion-count line of its newest gate result file. Every
       other fact is a file name, a modification time or an owner (from
       os.stat), the process table (ps and /proc/<pid>/cmdline),
       ~/.murmurent/agents.log, git, and the GitHub API through gh.
Output: Plain text on standard output, or JSON with --json. Writes no file.
        The only change it makes anywhere is `git fetch` in the two
        repositories, which updates their record of GitHub's copy (skip it
        with --no-fetch).

Run from inside the project's repository, under nice:
    nice -n 19 python3 ~/.claude/skills/murmurent-update-me/gather_facts.py
    nice -n 19 python3 ~/.claude/skills/murmurent-update-me/gather_facts.py --json

Project settings come from an optional `update_me:` block in the repository's
`.murmurent.yaml`; see SKILL.md. Every setting has a default, so a project with
no block still gets an update.

Governance: this script never prints file contents from the data tree, never
descends into a folder called `publication`, and prints no patient-level value
or cohort count. See SKILL.md.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import grp
import json
import logging
import os
import pwd
import re
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("update_me.gather")

# ---------------------------------------------------------------------------
# Project facts. Each is recorded in the repository's CLAUDE.md.
# ---------------------------------------------------------------------------
DATA_ROOT = Path(os.environ.get("MURMURENT_DATA_ROOT", "/data/lab_vm"))

# Project settings. These are defaults; configure() replaces them from the
# repository's `.murmurent.yaml` (an `update_me:` block, every key optional)
# before anything is gathered. Until 2026-10-14 they were fixed to the survival
# project, where this skill was built.
PROJECT = ""
CHANNEL = ""                        # this project's Slack channel ID, to find its earlier posts
OUTPUT_ROOT = DATA_ROOT / "append_only"
LAB_GROUP = ""                      # Unix group whose accounts' jobs count; "" = this account's group
GITHUB_OWNER = ""
GITHUB_REPO = ""
PROGRESS_LABEL = "progress"
OTHER_REPO_NAMES: tuple[str, ...] = ()
STATE_DOCUMENT = "state_of_the_project.md"
GUI_FOLDER = "src/gui"
PEOPLE: dict[str, str] = {}

# Gate result files: (label, folder under OUTPUT_ROOT, file-name stem, experiment folder).
GATES: tuple[tuple[str, str, str, str], ...] = ()
CODE_PATTERNS = ("*.R", "*.py")

# Folders never entered: nothing from them may appear in an update.
SKIPPED_FOLDER_NAMES = frozenset({"publication"})

# A process belongs to this project when its command line contains one of these.
PROJECT_MARKERS: tuple[str, ...] = ()

# Editor helpers and notebook kernels are not analyses.
IGNORED_MARKERS = (
    ".vscode-server/",
    "IRkernel::main",
    "ipykernel_launcher",
    "language-server",
    "/.claude/skills/update-me/",
    "/skills/murmurent-update-me/",
)

AGENT_LOG = Path.home() / ".murmurent" / "agents.log"
POST_LOG = Path.home() / ".murmurent" / "update_me_posted.log"
AGENT_WINDOW_HOURS = 24
AGENT_START_WORD = "starting"
MAX_LISTED_PATHS = 25
MAX_LISTED_COMMITS = 12
GIT_TIMEOUT_S = 60
GH_TIMEOUT_S = 60
DEFAULT_STREAMLIT_PORT = 8501
SECONDS_PER_MINUTE = 60

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
AGENT_LINE_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\] ([^:]+): (.*)$")
LAST_UPDATED_RE = re.compile(r"Last updated (\d{4}-\d{2}-\d{2}), (\d{1,2}:\d{2})")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def run_command(argv: list[str], timeout: int = GIT_TIMEOUT_S) -> tuple[int, str, str]:
    """Run a command and return (exit status, stdout, stderr).

    Parameters
    ----------
    argv : list of str
        The command and its arguments. Never passed through a shell.
    timeout : int
        Seconds before the command is abandoned.

    Returns
    -------
    tuple of (int, str, str)
        Exit status (127 if the program is missing, 124 on timeout), stdout, stderr.
    """
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return 127, "", f"{argv[0]} is not installed"
    except subprocess.TimeoutExpired:
        return 124, "", f"{' '.join(argv[:3])} took longer than {timeout} s"
    return done.returncode, done.stdout, done.stderr


def person(account: str) -> str:
    """Return 'Full Name (account)' when the account is known, else the account."""
    name = PEOPLE.get(account)
    return f"{name} ({account})" if name else account


def owner_name(uid: int) -> str:
    """Return the account name for a numeric user id, or the id itself."""
    try:
        return pwd.getpwuid(uid).pw_name
    except KeyError:
        return str(uid)


def format_time(moment: dt.datetime | None, now: dt.datetime) -> str:
    """Format a local time as 'HH:MM today', 'yesterday HH:MM' or a full date."""
    if moment is None:
        return "unknown"
    if moment.date() == now.date():
        return f"{moment:%H:%M} today"
    if moment.date() == (now - dt.timedelta(days=1)).date():
        return f"yesterday {moment:%H:%M}"
    return f"{moment:%Y-%m-%d %H:%M}"


def format_duration(seconds: float) -> str:
    """Format a duration in plain words: '14 min', '3 h 5 min', '2 days 4 h'."""
    minutes = int(seconds // SECONDS_PER_MINUTE)
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {minutes} min"
    days, hours = divmod(hours, 24)
    return f"{days} days {hours} h"


def from_utc_iso(text: str | None) -> dt.datetime | None:
    """Convert a GitHub UTC timestamp ('2026-09-30T17:38:00Z') to naive local time."""
    if not text:
        return None
    moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    return moment.astimezone().replace(tzinfo=None)


def mtime_of(path: Path) -> dt.datetime | None:
    """Return a file's modification time as naive local time, or None."""
    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return None


def find_repo_root() -> Path:
    """Return the top folder of the repository the session is open in.

    The shared skill lives in ~/.claude/skills/, so its own location says
    nothing about the project; the working directory does.
    """
    here = Path.cwd()
    status, out, _ = run_command(["git", "-C", str(here), "rev-parse", "--show-toplevel"])
    if status == 0 and out.strip():
        return Path(out.strip())
    return here


def github_from_origin(repo: Path) -> tuple[str, str]:
    """Owner and name of the GitHub repository behind `origin`, or ("", "")."""
    status, out, _ = run_command(["git", "-C", str(repo), "remote", "get-url", "origin"])
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", out.strip()) if status == 0 else None
    return (match.group(1), match.group(2)) if match else ("", "")


def read_settings(repo: Path) -> dict[str, Any]:
    """The `update_me:` block of the repository's .murmurent.yaml, or {}.

    Also returns the marker's `sensitivity` under the key `_sensitivity`, which
    decides how strict the posting checks are.
    """
    marker = repo / ".murmurent.yaml"
    if not marker.is_file():
        return {}
    try:
        import yaml  # murmurent's own dependency; absent only outside an install
    except ImportError:
        # Say so: silently falling back to defaults would lose the project's settings.
        return {"_note": "NOTE: this Python cannot read .murmurent.yaml (no PyYAML), so the project's "
                         "update_me settings were ignored. Run the script with murmurent's own Python."}
    try:
        data = yaml.safe_load(marker.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        return {"_note": f"NOTE: .murmurent.yaml could not be read ({exc}); using defaults."}
    block = data.get("update_me") if isinstance(data, dict) else None
    settings = dict(block) if isinstance(block, dict) else {}
    settings["_sensitivity"] = str(data.get("sensitivity") or "") if isinstance(data, dict) else ""
    settings["_name"] = str(data.get("name") or "") if isinstance(data, dict) else ""
    data_block = data.get("data") if isinstance(data, dict) else None
    settings["_root_subdir"] = str(data_block.get("root_subdir") or "") if isinstance(data_block, dict) else ""
    settings["_lab"] = str(data.get("lab") or "") if isinstance(data, dict) else ""
    return settings


def configure(repo: Path, settings: dict[str, Any]) -> None:
    """Set the project settings from the `update_me:` block, with defaults.

    Every default is chosen so a project that never wrote a block still gets a
    useful update: the outputs folder named for the project under the data
    root, the GitHub repository behind `origin`, a `<project>_manuscript` clone
    if one sits beside this one, and the state document if it exists.
    """
    global PROJECT, CHANNEL, OUTPUT_ROOT, LAB_GROUP, GITHUB_OWNER, GITHUB_REPO, PROGRESS_LABEL
    global OTHER_REPO_NAMES, STATE_DOCUMENT, GUI_FOLDER, PEOPLE, GATES, PROJECT_MARKERS
    PROJECT = str(settings.get("project") or settings.get("_name") or repo.name)
    CHANNEL = str(settings.get("channel") or "")
    subdir = settings.get("_root_subdir") or PROJECT          # a choreography names its own data folder
    OUTPUT_ROOT = Path(str(settings.get("outputs") or DATA_ROOT / "append_only" / subdir)).expanduser()
    LAB_GROUP = str(settings.get("lab_group") or grp.getgrgid(os.getgid()).gr_name)
    if settings.get("github"):
        owner, _, name = str(settings["github"]).partition("/")
        GITHUB_OWNER, GITHUB_REPO = owner, name
    else:
        GITHUB_OWNER, GITHUB_REPO = github_from_origin(repo)
    PROGRESS_LABEL = str(settings.get("progress_label") or "progress")
    others = settings.get("other_repos")
    if others is None:
        guess = f"{PROJECT}_manuscript"
        others = [guess] if (repo.parent / guess).is_dir() else []
    OTHER_REPO_NAMES = tuple(str(o) for o in others)
    STATE_DOCUMENT = str(settings.get("state_document") or "state_of_the_project.md")
    GUI_FOLDER = str(settings.get("gui_folder") or "src/gui")
    PEOPLE = {str(k): str(v) for k, v in (settings.get("people") or {}).items()}
    GATES = tuple(
        (str(g.get("label", "")), str(g.get("folder", "")), str(g.get("prefix", "")), str(g.get("experiment", "")))
        for g in (settings.get("gates") or []) if isinstance(g, dict)
    )
    markers = [f"/repos/{PROJECT}/", f"/append_only/{PROJECT}"]
    markers += [f"/repos/{name}" for name in OTHER_REPO_NAMES]
    markers += [str(m) for m in (settings.get("process_markers") or [])]
    PROJECT_MARKERS = tuple(dict.fromkeys(markers))


# ---------------------------------------------------------------------------
# The window "since the last update"
# ---------------------------------------------------------------------------
def last_post_time() -> dt.datetime | None:
    """Return the time of this account's last real update post FOR THIS PROJECT.

    The post log holds every project's posts. A line counts when its fourth
    column names this project, or, for lines written before 2026-10-14 (three
    columns, no project), when its channel is this project's channel.
    """
    try:
        lines = [line for line in POST_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    mine = []
    for line in lines:
        cols = line.split("\t")
        if (len(cols) >= 4 and cols[3] == PROJECT) or (len(cols) < 4 and CHANNEL and len(cols) > 1 and cols[1] == CHANNEL):
            mine.append(cols[0])
    if not mine:
        return None
    try:
        return dt.datetime.fromisoformat(mine[-1])
    except ValueError:
        return None


def choose_since(requested: str | None, now: dt.datetime) -> tuple[dt.datetime, str]:
    """Decide where 'since the last update' starts, and say why.

    Parameters
    ----------
    requested : str or None
        A time given on the command line as 'YYYY-MM-DD HH:MM', if any.
    now : datetime
        The current local time.

    Returns
    -------
    tuple of (datetime, str)
        The start of the window and a sentence explaining the choice.
    """
    if requested:
        return dt.datetime.fromisoformat(requested), "given on the command line"
    posted = last_post_time()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if posted is not None:
        return posted, f"the last /update-me post from this account ({POST_LOG})"
    return midnight, "midnight today: no earlier /update-me post is recorded on this account"


# ---------------------------------------------------------------------------
# Processes
# ---------------------------------------------------------------------------
@dataclass
class Process:
    """One row of the process table."""

    user: str
    pid: int
    ppid: int
    elapsed_s: int
    started: dt.datetime
    argv: list[str]

    @property
    def joined(self) -> str:
        """The command line as one string."""
        return " ".join(self.argv)


@dataclass
class Job:
    """One analysis, app or test run, with its forked workers folded in."""

    user: str
    kind: str
    script: str
    location: str
    pid: int
    started: str
    running_for: str
    workers: int
    via_conda_run: bool
    port: int | None = None
    note: str = ""


def read_cmdline(pid: int, fallback: str) -> list[str]:
    """Return a process's arguments from /proc, which keeps spaces inside arguments."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return fallback.split()
    parts = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    return parts or fallback.split()


def list_processes() -> list[Process]:
    """Return every process on this server, with start time and full arguments."""
    status, out, err = run_command(
        ["ps", "-eww", "-o", "user:32=,pid=,ppid=,etimes=,lstart=,args="], timeout=30
    )
    if status != 0:
        raise RuntimeError(f"ps failed: {err.strip()}")
    processes = []
    for line in out.splitlines():
        tokens = line.split(None, 9)
        if len(tokens) < 10:
            continue
        user, pid, ppid, elapsed = tokens[0], int(tokens[1]), int(tokens[2]), int(tokens[3])
        try:
            started = dt.datetime.strptime(" ".join(tokens[4:9]), "%a %b %d %H:%M:%S %Y")
        except ValueError:
            continue
        processes.append(Process(user, pid, ppid, elapsed, started, read_cmdline(pid, tokens[9])))
    return processes


def lab_accounts() -> set[str]:
    """Return the lab group's accounts, plus the caller's."""
    accounts = {pwd.getpwuid(os.getuid()).pw_name}
    group = LAB_GROUP or grp.getgrgid(os.getgid()).gr_name   # default: this account's main group
    try:
        accounts.update(grp.getgrnam(group).gr_mem)
    except KeyError:
        LOGGER.warning("group %s not found; showing this account only", group)
    return accounts


def streamlit_port(argv: list[str]) -> int:
    """Return the port a Streamlit command line serves on."""
    for index, arg in enumerate(argv):
        if arg.startswith("--server.port="):
            return int(arg.split("=", 1)[1])
        if arg == "--server.port" and index + 1 < len(argv):
            return int(argv[index + 1])
    return DEFAULT_STREAMLIT_PORT


def describe_command(argv: list[str]) -> tuple[str, str] | None:
    """Say what kind of analysis a command line is, and which script it runs.

    R launched through `conda run` appears as
    `exec/R --no-echo --no-restore --file=<script>.R`, not as `Rscript`
    (how_this_project_breaks.md, 2026-09-30), so both forms are recognised.

    Returns
    -------
    tuple of (str, str) or None
        (kind, script), or None when the command is not an analysis.
    """
    if not argv:
        return None
    joined = " ".join(argv)
    if any(marker in joined for marker in IGNORED_MARKERS):
        return None
    exe = Path(argv[0]).name
    if "run" in argv and any(Path(arg).name == "streamlit" for arg in argv[: argv.index("run")]):
        after = argv.index("run") + 1
        return ("Streamlit app", argv[after] if after < len(argv) else "?")
    if exe in ("R", "Rscript"):
        for arg in argv[1:]:
            if arg.startswith("--file="):
                script = arg.split("=", 1)[1]
                return ("R script", "(read from standard input)" if script == "-" else script)
        if exe == "Rscript":
            scripts = [arg for arg in argv[1:] if not arg.startswith("-")]
            if scripts:
                return ("R script", scripts[0])
        return None
    if exe.startswith("python"):
        if "-m" in argv:
            module_at = argv.index("-m") + 1
            if module_at < len(argv):
                return ("Python module", argv[module_at])
        scripts = [arg for arg in argv[1:] if arg.endswith(".py")]
        if scripts:
            return ("Python script", scripts[0])
    return None


def conda_run_target(argv: list[str]) -> str | None:
    """Return the script a `conda run` launcher starts, or None if it is not one."""
    if len(argv) < 3 or not any(Path(arg).name == "conda" for arg in argv[:2]) or "run" not in argv:
        return None
    scripts = [arg for arg in argv if arg.endswith((".R", ".py", ".r"))]
    return Path(scripts[-1]).name if scripts else None


def locate_script(script: str, repo_root: Path) -> str:
    """Find a script's place in this clone, so 02_gate_d2.R reads as exp/03_.../02_gate_d2.R."""
    name = Path(script).name
    if not name.endswith((".R", ".py", ".r")):
        return script
    matches = [
        path
        for folder in ("exp", "src")
        for path in (repo_root / folder).rglob(name)
        if "__pycache__" not in path.parts
    ]
    if len(matches) == 1:
        return str(matches[0].relative_to(repo_root))
    return script


def root_of(process: Process, same: dict[int, Process]) -> int:
    """Follow parents while they run the same command; the top one is the main process."""
    current = process
    seen = set()
    while current.ppid in same and current.ppid not in seen:
        seen.add(current.pid)
        current = same[current.ppid]
    return current.pid


def gather_processes(repo_root: Path, gui_changed: dt.datetime | None, now: dt.datetime) -> dict[str, Any]:
    """Collect this project's running analyses and apps on every lab account.

    Forked workers (children running the same command as their parent) are
    folded into one job. Two separate main processes running the same script
    at once are reported as a warning: that is how the duplicate real run of
    2026-09-30 looked.
    """
    accounts = lab_accounts()
    everyone = list_processes()
    me = pwd.getpwuid(os.getuid()).pw_name
    own_pid = os.getpid()

    launchers: set[tuple[str, str]] = set()
    candidates: list[tuple[Process, str, str, bool]] = []
    other_projects = 0
    for proc in everyone:
        if proc.user not in accounts or proc.pid == own_pid:
            continue
        target = conda_run_target(proc.argv)
        if target is not None:
            launchers.add((proc.user, target))
            continue
        described = describe_command(proc.argv)
        if described is None:
            continue
        is_project = any(marker in proc.joined for marker in PROJECT_MARKERS)
        candidates.append((proc, described[0], described[1], is_project))

    groups: dict[tuple[str, str], dict[int, Process]] = {}
    for proc, _, _, _ in candidates:
        groups.setdefault((proc.user, proc.joined), {})[proc.pid] = proc

    jobs: list[Job] = []
    seen_roots: set[int] = set()
    for proc, kind, script, is_project in candidates:
        same = groups[(proc.user, proc.joined)]
        root_pid = root_of(proc, same)
        if root_pid in seen_roots:
            continue
        seen_roots.add(root_pid)
        if not is_project:
            other_projects += 1
            continue
        root = same[root_pid]
        workers = sum(1 for other in same.values() if other.pid != root_pid and root_of(other, same) == root_pid)
        job = Job(
            user=root.user,
            kind=kind,
            script=script,
            location=locate_script(script, repo_root),
            pid=root.pid,
            started=format_time(root.started, now),
            running_for=format_duration(root.elapsed_s),
            workers=workers,
            via_conda_run=(root.user, Path(script).name) in launchers,
        )
        if kind == "Streamlit app":
            job.port = streamlit_port(root.argv)
            if gui_changed is not None and gui_changed > root.started:
                job.note = (
                    f"the app code on GitHub changed at {format_time(gui_changed, now)}, after this app "
                    "started; it shows the new version only after a restart"
                )
        jobs.append(job)

    warnings = []
    by_script: dict[str, list[Job]] = {}
    for job in jobs:
        if job.kind != "Streamlit app":
            by_script.setdefault(Path(job.script).name, []).append(job)
    for name, same_jobs in by_script.items():
        if len(same_jobs) > 1:
            who = ", ".join(sorted({job.user for job in same_jobs}))
            warnings.append(f"{len(same_jobs)} separate runs of {name} at the same time (accounts: {who})")

    sessions = sorted(p.started for p in everyone if p.user == me and Path(p.argv[0]).name == "claude")
    active_accounts = sorted({job.user for job in jobs} - {me})
    return {
        "host": socket.gethostname(),
        "accounts_checked": sorted(accounts),
        "jobs": [dataclasses.asdict(job) for job in jobs],
        "warnings": warnings,
        "other_projects_count": other_projects,
        "caller_claude_sessions": len(sessions),
        "caller_oldest_session": sessions[0].isoformat(timespec="seconds") if sessions else None,
        "other_active_accounts": active_accounts,
    }


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------
@dataclass
class AgentLine:
    """One line of ~/.murmurent/agents.log."""

    time: dt.datetime
    agent: str
    is_start: bool
    text: str


def read_agent_log(path: Path) -> list[AgentLine]:
    """Parse the agent log, dropping its colour codes."""
    lines = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = AGENT_LINE_RE.match(ANSI_RE.sub("", raw).strip())
        if not match:
            continue
        stamp, agent, text = match.groups()
        is_start = text.startswith(AGENT_START_WORD)
        if is_start:
            text = text[len(AGENT_START_WORD) :].lstrip(" —-:")
        lines.append(AgentLine(dt.datetime.strptime(stamp, "%Y-%m-%d %H:%M"), agent.strip(), is_start, text))
    return lines


# Words that name no particular task: the verbs every brief starts with, the
# phrases every finish line uses, and the agents' verdict words. They are
# ignored when deciding which task a finish line belongs to.
TASK_STOPWORDS = frozenset(
    """
    a an and the of to for on in into onto with from by at as is it its be are was were has have had
    this that these those then than but or not no all any each every one new now out up me my you
    your ive we our via per so do done
    build built builds building rebuild rebuilt write wrote written writes rewrite rewritten draft
    drafted review reviewed reviews check checked checks run ran runs rerun make made fix fixed fixes
    add added test tested tests finish finished send sent
    report reports caller session main coordinator agent summary verdict full back gone delivered
    dispatched questions pass reject partial failed found clear explained gap
    """.split()
)
MIN_PREFIX_MATCH = 4  # 'part' matches 'part11' and 'result' matches 'results'; shorter words must be equal
WORD_RE = re.compile(r"[a-z0-9]+")


def words_of(text: str) -> set[str]:
    """Lower-case words and numbers in a text."""
    return set(WORD_RE.findall(text.lower()))


def task_words(task: str) -> set[str]:
    """The words of a task description that could name it: no stopwords, no bare numbers."""
    return {word for word in words_of(task) if len(word) >= 2 and not word.isdigit() and word not in TASK_STOPWORDS}


def is_word_in(word: str, message_words: set[str]) -> bool:
    """True when a task word appears in the message, allowing a shared stem of four letters or more."""
    for other in message_words:
        if word == other:
            return True
        if min(len(word), len(other)) >= MIN_PREFIX_MATCH and (other.startswith(word) or word.startswith(other)):
            return True
    return False


def shared_words(candidate_words: set[str], message: str) -> list[str]:
    """The candidate's words that the finish message also uses."""
    message_words = words_of(message)
    return sorted(word for word in candidate_words if is_word_in(word, message_words))


def distinguishing_words(tasks: list[str]) -> list[set[str]]:
    """Each task's words minus the words every task shares, which cannot tell them apart."""
    word_sets = [task_words(task) for task in tasks]
    if len(word_sets) < 2:
        return word_sets
    common = set.intersection(*word_sets)
    return [words - common for words in word_sets]


@dataclass
class OpenStart:
    """A start line with no finish matched to it yet."""

    line: AgentLine
    unmatched_finishes: list[dt.datetime] = field(default_factory=list)


def classify_finish(
    line: AgentLine, candidates: list[OpenStart], closed: list[tuple[AgentLine, dt.datetime]]
) -> dict[str, Any]:
    """Decide which start a finish line belongs to, only when that is certain.

    The log carries no task identifier: a start line has the agent type and
    the task description, a finish line the agent type and the first 200
    characters of the agent's reply. So a finish is matched only when its text
    uses words of exactly one open task of that type, counting only the words
    that tell the open tasks apart. Several agents of one type often run at
    once (four blacksmiths at 14:25 on 2026-09-30), so the most recent start
    is not evidence.

    Returns
    -------
    dict
        'match' is one of:
        'matched'         one open task is named; 'chosen' is it;
        'resumed'         no open task is named, but one task that already
                          finished is: an agent resumed by a message;
        'not matched'     the text names no open task, or more than one;
                          'candidates' lists them, and none is closed;
        'no start logged' nothing of this type is open or named.
    """
    named: list[tuple[OpenStart, list[str]]] = []
    if candidates:
        word_sets = distinguishing_words([start.line.text for start in candidates])
        scored = [(start, shared_words(words, line.text)) for start, words in zip(candidates, word_sets)]
        named = [(start, shared) for start, shared in scored if shared]
    if len(named) == 1:
        return {"match": "matched", "chosen": named[0][0], "shared": named[0][1]}
    if len(named) > 1:
        return {
            "match": "not matched",
            "candidates": [start for start, _ in named],
            "reason": "its text names more than one open task",
        }
    open_words = set().union(*(task_words(start.line.text) for start in candidates))
    earlier = [
        (start, finished_at, shared_words(task_words(start.text) - open_words, line.text))
        for start, finished_at in closed
    ]
    earlier = [item for item in earlier if item[2]]
    if len(earlier) == 1:
        start, finished_at, shared = earlier[0]
        return {"match": "resumed", "chosen_line": start, "finished_before": finished_at, "shared": shared}
    if candidates:
        reason = "its text names none of the open tasks"
        if len(earlier) > 1:
            reason += ", and more than one task that already finished, so it may be a resumed agent"
        return {"match": "not matched", "candidates": list(candidates), "reason": reason}
    return {"match": "no start logged"}


def match_agent_lines(
    lines: list[AgentLine], since: dt.datetime, now: dt.datetime, oldest_session: dt.datetime | None
) -> dict[str, list[dict[str, Any]]]:
    """Pair start and finish lines, and say which agents have no certain finish.

    A second start of the same agent with the same task, while the first is
    open, is a restart: the first attempt stopped and never finishes (the
    teacher at 10:00 and again at 12:35 on 2026-09-30). A background agent
    stops, without notice, when the session that started it closes, so an
    open start older than every Claude Code session now open on this account
    certainly stopped.

    Returns
    -------
    dict
        'finished': finish lines since `since`, each with how it was matched;
        'open': starts in the last AGENT_WINDOW_HOURS with no certain finish.
    """
    open_starts: dict[str, list[OpenStart]] = {}
    closed: dict[str, list[tuple[AgentLine, dt.datetime]]] = {}
    restarted: list[tuple[AgentLine, AgentLine]] = []
    finished: list[dict[str, Any]] = []
    for line in lines:
        if line.is_start:
            stack = open_starts.setdefault(line.agent, [])
            for earlier in [start for start in stack if start.line.text == line.text]:
                stack.remove(earlier)
                restarted.append((earlier.line, line))
            stack.append(OpenStart(line))
            continue
        # A start more than AGENT_WINDOW_HOURS before a finish is not a candidate for it: no agent here runs
        # that long, and without this bound a start whose finish line named nothing stays a candidate forever.
        earliest = line.time - dt.timedelta(hours=AGENT_WINDOW_HOURS)
        candidates = [
            start for start in open_starts.get(line.agent, []) if earliest <= start.line.time <= line.time
        ]
        recent_closed = [(start, finished_at) for start, finished_at in closed.get(line.agent, []) if start.time >= earliest]
        verdict = classify_finish(line, candidates, recent_closed)
        entry: dict[str, Any] = {
            "agent": line.agent,
            "finished": format_time(line.time, now),
            "message": line.text,
            "match": verdict["match"],
            "task": "",
            "started": "",
            "evidence": "",
            "candidates": [],
        }
        if verdict["match"] == "matched":
            chosen: OpenStart = verdict["chosen"]
            open_starts[line.agent].remove(chosen)
            closed.setdefault(line.agent, []).append((chosen.line, line.time))
            entry.update(
                task=chosen.line.text,
                started=format_time(chosen.line.time, now),
                evidence="its text uses the task's words: " + ", ".join(verdict["shared"]),
            )
        elif verdict["match"] == "resumed":
            start = verdict["chosen_line"]
            entry.update(
                task=start.text,
                started=format_time(start.time, now),
                evidence=(
                    f"no open task is named, but this one is ({', '.join(verdict['shared'])}), and its finish was "
                    f"already logged at {format_time(verdict['finished_before'], now)}: an agent resumed by a message"
                ),
            )
        elif verdict["match"] == "not matched":
            for start in verdict["candidates"]:
                start.unmatched_finishes.append(line.time)
            entry["candidates"] = [
                {"task": start.line.text, "started": format_time(start.line.time, now)} for start in verdict["candidates"]
            ]
            entry["evidence"] = verdict["reason"]
        else:
            entry["evidence"] = "no start of this agent type is open: probably an agent resumed by a message"
        if line.time >= since:
            finished.append(entry)

    window_start = now - dt.timedelta(hours=AGENT_WINDOW_HOURS)
    unfinished: list[tuple[dt.datetime, dict[str, str]]] = []
    for earlier, later in restarted:
        if earlier.time >= window_start:
            status = f"stopped: restarted with the same task at {format_time(later.time, now)}"
            unfinished.append((earlier.time, {"agent": earlier.agent, "started": format_time(earlier.time, now), "task": earlier.text, "status": status}))
    for agent, stack in open_starts.items():
        for start in stack:
            if start.line.time < window_start:
                continue
            # The log is to the minute; the start could be up to 59 s after its stamp.
            is_certainly_stopped = oldest_session is None or start.line.time + dt.timedelta(minutes=1) <= oldest_session
            status = (
                "stopped: the session that started it has closed (no Claude Code session on this account is that old)"
                if is_certainly_stopped
                else "may still be running: a Claude Code session open at that time is still open; "
                "its report file in the output tree is the proof it finished"
            )
            if start.unmatched_finishes:
                times = ", ".join(format_time(moment, now) for moment in start.unmatched_finishes)
                status += f". It may have finished: a finish line of this agent type at {times} could be its (not matched)"
            unfinished.append((start.line.time, {"agent": agent, "started": format_time(start.line.time, now), "task": start.line.text, "status": status}))
    return {"finished": finished, "open": [item for _, item in sorted(unfinished, key=lambda pair: pair[0])]}


def gather_agents(since: dt.datetime, now: dt.datetime, processes: dict[str, Any]) -> dict[str, Any]:
    """Read this account's agent log and match its lines (see match_agent_lines)."""
    result: dict[str, Any] = {"log": str(AGENT_LOG), "open": [], "finished": [], "error": None}
    try:
        lines = read_agent_log(AGENT_LOG)
    except OSError as exc:
        result["error"] = f"cannot read {AGENT_LOG}: {exc.strerror}"
        return result
    oldest = processes.get("caller_oldest_session")
    result.update(match_agent_lines(lines, since, now, dt.datetime.fromisoformat(oldest) if oldest else None))

    unreadable = []
    for account in processes.get("other_active_accounts", []):
        try:
            other_log = Path(pwd.getpwnam(account).pw_dir) / ".murmurent" / "agents.log"
            other_log.open("rb").close()
        except (KeyError, OSError):
            unreadable.append(account)
    result["other_logs_unreadable"] = unreadable
    return result


# ---------------------------------------------------------------------------
# The output tree
# ---------------------------------------------------------------------------
def can_open(path: str) -> bool:
    """Open and close a file without reading a byte. On the Isilon share the
    mode can say readable while the open is refused, so the mode is not enough."""
    try:
        handle = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except PermissionError:
        return False
    except OSError:
        return True  # a link or a special file: not a permission problem
    os.close(handle)
    return True


def scan_folder(top: Path, since: dt.datetime) -> tuple[dict[str, Any], list[str]]:
    """Walk one top-level folder: its newest file, how many changed, what cannot be opened.

    Returns
    -------
    tuple of (dict, list of str)
        The folder summary and the paths (relative to OUTPUT_ROOT) that could not be opened.
    """
    newest: tuple[float, str, int] | None = None
    changed = 0
    files = 0
    skipped = 0
    unreadable: list[str] = []
    since_ts = since.timestamp()
    stack = [top]
    while stack:
        folder = stack.pop()
        try:
            entries = list(os.scandir(folder))
        except PermissionError:
            try:
                owner = owner_name(os.stat(folder).st_uid)
            except OSError:
                owner = "unknown"
            unreadable.append(f"{Path(folder).relative_to(OUTPUT_ROOT)}/ (folder, owner {owner})")
            continue
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in SKIPPED_FOLDER_NAMES:
                        skipped += 1
                    else:
                        stack.append(Path(entry.path))
                    continue
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            files += 1
            if info.st_mtime >= since_ts:
                changed += 1
            if newest is None or info.st_mtime > newest[0]:
                newest = (info.st_mtime, entry.path, info.st_uid)
            if not can_open(entry.path):
                unreadable.append(f"{Path(entry.path).relative_to(OUTPUT_ROOT)} (owner {owner_name(info.st_uid)})")
    summary = {
        "folder": top.name,
        "files": files,
        "changed_since": changed,
        "publication_folders_skipped": skipped,
        "newest_path": str(Path(newest[1]).relative_to(OUTPUT_ROOT)) if newest else None,
        "newest_time": dt.datetime.fromtimestamp(newest[0]).isoformat(timespec="seconds") if newest else None,
        "newest_owner": owner_name(newest[2]) if newest else None,
    }
    return summary, unreadable


def gather_outputs(since: dt.datetime) -> dict[str, Any]:
    """Summarise every top-level folder of the output tree, newest first."""
    result: dict[str, Any] = {"root": str(OUTPUT_ROOT), "folders": [], "unreadable": [], "error": None}
    try:
        tops = sorted(entry for entry in OUTPUT_ROOT.iterdir() if entry.is_dir() and not entry.is_symlink())
    except OSError as exc:
        result["error"] = (f"NOTE: no outputs folder at {OUTPUT_ROOT}; if this project keeps its outputs elsewhere, "
                           "set update_me.outputs in .murmurent.yaml" if not OUTPUT_ROOT.exists()
                           else f"cannot list {OUTPUT_ROOT}: {exc.strerror}")
        return result
    for top in tops:
        if top.name in SKIPPED_FOLDER_NAMES:
            continue
        summary, unreadable = scan_folder(top, since)
        result["folders"].append(summary)
        result["unreadable"].extend(unreadable)
    result["folders"].sort(key=lambda item: item["newest_time"] or "", reverse=True)
    return result


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------
def code_commits_since(repo: Path, experiment: str, since: dt.datetime) -> list[str]:
    """List commits on GitHub's copy that changed an experiment's R or Python code after `since`."""
    status, upstream, _ = git(repo, "rev-parse", "--abbrev-ref", "@{u}")
    ref = upstream.strip() if status == 0 and upstream.strip() else "HEAD"
    paths = [f"{experiment}/{pattern}" for pattern in CODE_PATTERNS]
    out = git(
        repo, "log", f"--since={since:%Y-%m-%d %H:%M:%S}", "--date=format-local:%Y-%m-%d %H:%M",
        "--format=%h %ad %an: %s", ref, "--", *paths,
    )[1]
    return out.splitlines()


def gather_gates(repo: Path) -> list[dict[str, Any]]:
    """Read the verdict and assertion-count lines of each phase's newest gate result,
    and list commits that changed that phase's code after the result was written."""
    gates = []
    for label, folder, stem, experiment in GATES:
        gate_dir = OUTPUT_ROOT / folder
        entry: dict[str, Any] = {"gate": label, "folder": folder}
        pattern = re.compile(rf"^{re.escape(stem)}(\d+)\.txt$")
        try:
            names = [path.name for path in gate_dir.iterdir()]
        except OSError as exc:
            entry["error"] = f"cannot list {folder}: {exc.strerror}"
            gates.append(entry)
            continue
        versions = sorted(int(m.group(1)) for m in map(pattern.match, names) if m)
        if not versions:
            entry["error"] = "no result file"
            gates.append(entry)
            continue
        latest = versions[-1]
        result_file = gate_dir / f"{stem}{latest}.txt"
        try:
            lines = result_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            entry["error"] = f"cannot open {result_file.name}: {exc.strerror}"
            gates.append(entry)
            continue
        entry["result_file"] = result_file.name
        entry["verdict"] = lines[0].strip() if lines else "(empty file)"
        entry["assertions"] = next((line.strip() for line in lines if "assertion" in line and ":" not in line), "")
        entry["written"] = mtime_of(result_file).isoformat(timespec="seconds") if mtime_of(result_file) else None
        claimed = re.compile(r"assertions_(\d+)\.")
        later = sorted(name for name in names if (m := claimed.search(name)) and int(m.group(1)) > latest)
        entry["claimed_without_result"] = later
        written = mtime_of(result_file)
        entry["code_commits_since"] = code_commits_since(repo, experiment, written) if written else []
        entry["experiment"] = experiment
        gates.append(entry)
    return gates


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------
def git(repo: Path, *args: str) -> tuple[int, str, str]:
    """Run one git command in a repository."""
    return run_command(["git", "-C", str(repo), *args])


def gather_git(repo: Path, fetch: bool, midnight: dt.datetime) -> dict[str, Any]:
    """Report branch, remote, ahead/behind, uncommitted files and today's commits."""
    result: dict[str, Any] = {"repo": repo.name, "path": str(repo)}
    if not (repo / ".git").exists():
        result["error"] = f"no git repository at {repo}"
        return result
    if fetch:
        status, _, err = git(repo, "fetch", "--quiet")
        result["fetch"] = "ok" if status == 0 else f"failed: {err.strip()[:200]}"
    else:
        result["fetch"] = "skipped (--no-fetch)"
    result["branch"] = git(repo, "rev-parse", "--abbrev-ref", "HEAD")[1].strip()
    result["origin"] = git(repo, "remote", "get-url", "origin")[1].strip()
    status, upstream, _ = git(repo, "rev-parse", "--abbrev-ref", "@{u}")
    upstream = upstream.strip() if status == 0 else ""
    result["upstream"] = upstream or None
    if upstream:
        counts = git(repo, "rev-list", "--left-right", "--count", f"HEAD...{upstream}")[1].split()
        if len(counts) == 2:
            result["ahead"], result["behind"] = int(counts[0]), int(counts[1])
    porcelain = git(repo, "status", "--porcelain=v1")[1].splitlines()
    result["uncommitted_count"] = len(porcelain)
    result["uncommitted"] = porcelain[:MAX_LISTED_PATHS]
    refs = ["HEAD"] + ([upstream] if upstream else [])
    log = git(
        repo, "log", f"--since={midnight:%Y-%m-%d %H:%M}", "--date=format-local:%H:%M",
        "--format=%h%x09%an%x09%ad%x09%s", *refs,
    )[1].splitlines()
    result["commits_today_count"] = len(log)
    result["commits_today"] = [dict(zip(("hash", "author", "time", "subject"), row.split("\t", 3))) for row in log[:MAX_LISTED_COMMITS]]
    latest_by_author: dict[str, str] = {}
    history = git(repo, "log", "-300", "--date=format-local:%Y-%m-%d %H:%M", "--format=%an%x09%ad%x09%h", upstream or "HEAD")[1]
    for row in history.splitlines():
        author, when, short = row.split("\t", 2)
        latest_by_author.setdefault(author, f"{when} ({short})")
    result["latest_commit_by_author"] = latest_by_author
    return result


def gui_last_changed(repo: Path) -> dt.datetime | None:
    """When the app's code last changed on GitHub's copy (origin), for the restart check."""
    status, upstream, _ = git(repo, "rev-parse", "--abbrev-ref", "@{u}")
    ref = upstream.strip() if status == 0 and upstream.strip() else "HEAD"
    status, out, _ = git(repo, "log", "-1", "--format=%ct", ref, "--", GUI_FOLDER)
    if status != 0 or not out.strip():
        return None
    return dt.datetime.fromtimestamp(int(out.strip()))


# ---------------------------------------------------------------------------
# GitHub issues
# ---------------------------------------------------------------------------
ISSUE_QUERY = """
query($owner: String!, $name: String!, $label: String!) {
  repository(owner: $owner, name: $name) {
    open: issues(first: 100, states: OPEN, labels: [$label],
                 orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title updatedAt
              comments(last: 1) { totalCount nodes { author { login } createdAt } } }
    }
    closed: issues(first: 20, states: CLOSED, labels: [$label],
                   orderBy: {field: UPDATED_AT, direction: DESC}) {
      nodes { number title closedAt }
    }
  }
}
"""


def gather_issues(since: dt.datetime, now: dt.datetime) -> dict[str, Any]:
    """List open progress issues with their last comment, and those closed since `since`."""
    result: dict[str, Any] = {"repo": f"{GITHUB_OWNER}/{GITHUB_REPO}", "open": [], "closed_since": [], "error": None}
    if not (GITHUB_OWNER and GITHUB_REPO):
        result["repo"] = "(none)"
        result["error"] = "NOTE: no GitHub repository: origin is not on GitHub and update_me.github is not set"
        return result
    status, out, err = run_command(
        [
            "gh", "api", "graphql", "-f", f"query={ISSUE_QUERY}",
            "-f", f"owner={GITHUB_OWNER}", "-f", f"name={GITHUB_REPO}", "-f", f"label={PROGRESS_LABEL}",
        ],
        timeout=GH_TIMEOUT_S,
    )
    if status != 0:
        result["error"] = f"gh failed: {(err or out).strip()[:300]}"
        return result
    data = json.loads(out)["data"]["repository"]
    for node in data["open"]["nodes"]:
        comments = node["comments"]
        last = comments["nodes"][0] if comments["nodes"] else None
        login = (last or {}).get("author") or {}
        result["open"].append(
            {
                "number": node["number"],
                "title": node["title"],
                "comments": comments["totalCount"],
                "last_comment": format_time(from_utc_iso(last["createdAt"]), now) if last else "none",
                "last_comment_by": person(login.get("login", "")) if last else "",
                "updated": format_time(from_utc_iso(node["updatedAt"]), now),
            }
        )
    for node in data["closed"]["nodes"]:
        closed = from_utc_iso(node["closedAt"])
        if closed and closed >= since:
            result["closed_since"].append({"number": node["number"], "title": node["title"], "closed": format_time(closed, now)})
    return result


# ---------------------------------------------------------------------------
# The state document
# ---------------------------------------------------------------------------
def gather_state_document(repo: Path, repo_git: dict[str, Any]) -> dict[str, Any]:
    """Find the state document's 'Last updated' line and where sections 0 and 5 are.

    When this clone is behind GitHub and has no local edit to the document,
    the copy on GitHub is newer, so that copy is the one read and described.
    """
    path = repo / STATE_DOCUMENT
    result: dict[str, Any] = {"path": str(path)}
    if not path.exists():
        # Optional: many projects have none. Say so rather than report an error.
        result["absent"] = True
        result["error"] = f"NOTE: this project has no {STATE_DOCUMENT} (optional; set update_me.state_document)"
        return result
    upstream = repo_git.get("upstream")
    locally_edited = any(line.endswith(STATE_DOCUMENT) for line in repo_git.get("uncommitted", []))
    if upstream and repo_git.get("behind", 0) > 0 and not locally_edited:
        status, text, err = git(repo, "show", f"{upstream}:{STATE_DOCUMENT}")
        if status != 0:
            result["error"] = f"cannot read {STATE_DOCUMENT} from {upstream}: {err.strip()}"
            return result
        lines = text.splitlines()
        result["source"] = f"the copy on {upstream} (this clone is {repo_git['behind']} commits behind GitHub)"
        result["read_with"] = f"git -C {repo} show {upstream}:{STATE_DOCUMENT} | sed -n '<first>,<last>p'"
    else:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            result["error"] = f"cannot read {path}: {exc.strerror}"
            return result
        result["source"] = "this clone" + (" (it has uncommitted edits)" if locally_edited else "")
        result["read_with"] = f"the Read tool on {path}, with those line numbers"
    for line in lines[:20]:
        match = LAST_UPDATED_RE.search(line)
        if match:
            result["last_updated"] = f"{match.group(1)} {match.group(2)}"
            break
    headings = [(index + 1, line) for index, line in enumerate(lines) if line.startswith("## ")]
    for number in ("0", "5"):
        for position, (line_no, text) in enumerate(headings):
            if text.startswith(f"## {number}."):
                end = headings[position + 1][0] - 1 if position + 1 < len(headings) else len(lines)
                result[f"section_{number}"] = {"heading": text[3:], "lines": f"{line_no}-{end}"}
                break
    return result


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------
def render_text(facts: dict[str, Any], now: dt.datetime) -> str:
    """Turn the facts into plain text for the session to read."""
    out: list[str] = []
    add = out.append
    add(f"UPDATE-ME FACTS for {facts.get('project', '?')} (read-only; paths, times and owners only)")
    if facts.get("settings_note"):
        add(facts["settings_note"])
    add(f"Clock: {facts['clock']} (from `date`)")
    add(f"Account: {person(facts['account'])} on {facts['processes'].get('host', '?')}")
    add(f"'Since the last update' means since {facts['since']} ({facts['since_reason']})")

    procs = facts["processes"]
    add("")
    add(f"== Running now: this project's analyses and apps on this server (lab group {LAB_GROUP}) ==")
    if procs.get("error"):
        add(f"  {procs['error'] if procs['error'].startswith('NOTE:') else 'ERROR: ' + procs['error']}")
    elif not procs["jobs"]:
        add("  Nothing from this project is running on any lab account.")
    for job in procs.get("jobs", []):
        text = f"  - {person(job['user'])}: {job['kind']} {job['location']}"
        if job["port"]:
            text += f" on port {job['port']}"
        text += f", pid {job['pid']}, started {job['started']}, running {job['running_for']}"
        if job["workers"]:
            text += f", {job['workers']} worker processes"
        if job["via_conda_run"]:
            text += ", launched through conda run"
        add(text)
        if job["note"]:
            add(f"      note: {job['note']}")
    for warning in procs.get("warnings", []):
        add(f"  WARNING: {warning}")
    if "other_projects_count" in procs:
        add(f"  Analysis processes by lab members for other projects (not listed): {procs['other_projects_count']}")
    add("  Only this server is checked; a job on another machine does not appear.")

    agents = facts["agents"]
    add("")
    add(f"== Agents (from {agents['log']}) ==")
    if agents.get("error"):
        add(f"  {agents['error'] if agents['error'].startswith('NOTE:') else 'ERROR: ' + agents['error']}")
    else:
        oldest = procs.get("caller_oldest_session")
        oldest_text = format_time(dt.datetime.fromisoformat(oldest), now) if oldest else "none"
        add(f"  Claude Code sessions open on this account: {procs.get('caller_claude_sessions', 0)}, oldest started {oldest_text}")
        maybe_running = [item for item in agents["open"] if not item["status"].startswith("stopped")]
        stopped = [item for item in agents["open"] if item["status"].startswith("stopped")]
        add(f"  Started with no certain finish line, and may still be running (last {AGENT_WINDOW_HOURS} h):")
        if not maybe_running:
            add("    none")
        for item in maybe_running:
            add(f"    - {item['agent']}, started {item['started']}: \"{item['task']}\". {item['status']}")
        add(f"  Started with no certain finish line, and certainly stopped (last {AGENT_WINDOW_HOURS} h): {len(stopped)}")
        for item in stopped:
            add(f"    - {item['agent']}, started {item['started']}: \"{item['task']}\". {item['status']}")
        add(f"  Finished since {facts['since']}:")
        if not agents["finished"]:
            add("    none")
        for item in agents["finished"]:
            if item["match"] == "matched":
                head = (
                    f"{item['agent']} \"{item['task']}\", started {item['started']}, finished {item['finished']} "
                    f"(matched: {item['evidence']})"
                )
            elif item["match"] == "resumed":
                head = (
                    f"{item['agent']}, finished {item['finished']}: resumed \"{item['task']}\" "
                    f"(started {item['started']}; {item['evidence']})"
                )
            elif item["match"] == "not matched":
                listed = "; ".join(f"\"{c['task']}\" (started {c['started']})" for c in item["candidates"])
                head = (
                    f"{item['agent']}, finished {item['finished']}: finish line not matched "
                    f"({item['evidence']}). Candidates: {listed}"
                )
            else:
                head = f"{item['agent']}, finished {item['finished']}: no start logged ({item['evidence']})"
            add(f"    - {head}")
            add(f"        its finish line says: {item['message']}")
        add("  A background agent stops, without notice, when the session that started it closes.")
        for account in agents.get("other_logs_unreadable", []):
            add(f"  Not visible: agents started from {person(account)}'s account (that log cannot be read from here).")

    outputs = facts["outputs"]
    add("")
    add(f"== Newest outputs in {outputs['root']} (by folder; 'publication' folders are never entered) ==")
    if outputs.get("error"):
        add(f"  {outputs['error'] if outputs['error'].startswith('NOTE:') else 'ERROR: ' + outputs['error']}")
    for folder in outputs.get("folders", []):
        newest = dt.datetime.fromisoformat(folder["newest_time"]) if folder["newest_time"] else None
        add(
            f"  - {folder['folder']}/: newest {folder['newest_path']}, {format_time(newest, now)}, "
            f"owner {folder['newest_owner']}; {folder['changed_since']} of {folder['files']} files changed since {facts['since']}"
        )

    add("")
    add("== Latest gate results ==")
    for gate in facts["gates"]:
        if gate.get("error"):
            add(f"  - {gate['gate']}: {gate['error']}")
            continue
        written = dt.datetime.fromisoformat(gate["written"]) if gate["written"] else None
        add(f"  - {gate['gate']}: {gate['verdict']}; {gate['assertions']}; {gate['result_file']}, written {format_time(written, now)}")
        if gate["claimed_without_result"]:
            add(f"      a later run has an assertions file but no result yet: {', '.join(gate['claimed_without_result'])}")
        commits = gate["code_commits_since"]
        add(
            f"      commits on GitHub changing {gate['experiment']} code (R, Python) since this result: {len(commits)}"
            " (committed code only; a member's uncommitted edits are not visible)"
        )
        for commit in commits[:MAX_LISTED_COMMITS]:
            add(f"        {commit}")

    add("")
    add("== Git ==")
    for repo in facts["git"]:
        if repo.get("error"):
            add(f"  - {repo['repo']}: {repo['error']}")
            continue
        add(f"  - {repo['repo']} ({repo['path']}), branch {repo['branch']}, origin {repo['origin']}, fetch {repo['fetch']}")
        if "ahead" in repo:
            add(f"      ahead of {repo['upstream']} by {repo['ahead']}, behind by {repo['behind']}")
        add(f"      uncommitted paths: {repo['uncommitted_count']}")
        for line in repo["uncommitted"]:
            add(f"        {line}")
        add(f"      commits today: {repo['commits_today_count']}")
        for commit in repo["commits_today"]:
            add(f"        {commit['hash']} {commit['time']} {commit['author']}: {commit['subject']}")
        for author, when in repo["latest_commit_by_author"].items():
            add(f"      latest commit by {author} on {repo['upstream'] or 'HEAD'}: {when}")
    for repo in facts["git"][1:]:
        if GITHUB_REPO and repo.get("origin", "").endswith(f"/{GITHUB_REPO}.git"):
            add(f"  WARNING: {repo['repo']}'s origin points at {GITHUB_REPO}, the project's main repository.")

    issues = facts["issues"]
    add("")
    add(f"== Open GitHub issues labelled '{PROGRESS_LABEL}' on {issues['repo']} ==")
    if issues.get("error"):
        add(f"  {issues['error'] if issues['error'].startswith('NOTE:') else 'ERROR: ' + issues['error']}")
    for issue in issues.get("open", []):
        add(
            f"  - #{issue['number']} {issue['title']}: last comment {issue['last_comment']}"
            f"{' by ' + issue['last_comment_by'] if issue['last_comment_by'] else ''}; {issue['comments']} comments"
        )
    if issues.get("closed_since"):
        add(f"  Closed since {facts['since']}:")
        for issue in issues["closed_since"]:
            add(f"    - #{issue['number']} {issue['title']}, closed {issue['closed']}")

    unreadable = outputs.get("unreadable", [])
    add("")
    add(f"== Items in the output tree this account cannot open: {len(unreadable)} ==")
    for path in unreadable[:MAX_LISTED_PATHS]:
        add(f"  - {path}")
    if len(unreadable) > MAX_LISTED_PATHS:
        add(f"  ... and {len(unreadable) - MAX_LISTED_PATHS} more (use --json for all)")

    state = facts["state_document"]
    add("")
    add(f"== {STATE_DOCUMENT} ==")
    if state.get("error"):
        add(f"  {state['error'] if state['error'].startswith('NOTE:') else 'ERROR: ' + state['error']}")
    else:
        add(f"  Read from {state['source']}")
        add(f"  'Last updated' line says: {state.get('last_updated', 'not found')}")
        for number in ("0", "5"):
            section = state.get(f"section_{number}")
            if section:
                add(f"  Section {number} ('{section['heading']}') is lines {section['lines']}")
        add(f"  Read those lines with: {state['read_with']}")
    add("")
    add("GUI test suite: not reported. The pytest cache is not a reliable record of the last run, and the full suite takes minutes.")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def gather_all(args: argparse.Namespace) -> tuple[dict[str, Any], dt.datetime]:
    """Collect every section; one failing section does not stop the others."""
    clock = run_command(["date", "+%a %Y-%m-%d %H:%M:%S %Z"])[1].strip()
    now = dt.datetime.now()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    repo_root = find_repo_root()
    settings = read_settings(repo_root)
    configure(repo_root, settings)          # first: "since the last update" depends on the project
    since, reason = choose_since(args.since, now)
    others = [Path(p) for p in args.other_repo] if args.other_repo else [repo_root.parent / n for n in OTHER_REPO_NAMES]

    facts: dict[str, Any] = {
        "settings_note": settings.get("_note", ""),
        "project": PROJECT,
        "sensitivity": settings.get("_sensitivity", ""),
        "clock": clock,
        "account": pwd.getpwuid(os.getuid()).pw_name,
        "since": format_time(since, now),
        "since_iso": since.isoformat(timespec="minutes"),
        "since_reason": reason,
    }
    facts["git"] = [gather_git(repo, not args.no_fetch, midnight) for repo in [repo_root, *others]]
    try:
        facts["processes"] = gather_processes(repo_root, gui_last_changed(repo_root), now)
    except (RuntimeError, OSError) as exc:
        facts["processes"] = {"error": str(exc), "jobs": [], "warnings": []}
    facts["agents"] = gather_agents(since, now, facts["processes"])
    facts["outputs"] = gather_outputs(since)
    facts["gates"] = gather_gates(repo_root)
    try:
        facts["issues"] = gather_issues(since, now)
    except (KeyError, ValueError, TypeError) as exc:
        facts["issues"] = {"repo": f"{GITHUB_OWNER}/{GITHUB_REPO}", "error": f"unexpected reply from GitHub: {exc}"}
    facts["state_document"] = gather_state_document(repo_root, facts["git"][0])
    return facts, now


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Read the command line."""
    parser = argparse.ArgumentParser(description="Gather read-only facts for /murmurent-update-me.")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    parser.add_argument("--no-fetch", action="store_true", help="do not run git fetch first")
    parser.add_argument("--since", help="start of 'since the last update', as 'YYYY-MM-DD HH:MM'")
    parser.add_argument("--other-repo", action="append",
                        help="path to another of the project's repositories (repeatable); "
                             "default: update_me.other_repos, or <project>_manuscript beside this one")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Gather the facts and print them."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
    args = parse_args(argv)
    facts, now = gather_all(args)
    if args.json:
        json.dump(facts, sys.stdout, indent=2, default=str)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(render_text(facts, now) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
