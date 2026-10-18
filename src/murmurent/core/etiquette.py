"""
Purpose: The server etiquette check (issue #151, step 4): who in the lab is
         running jobs outside the lab's rules for priority, cores and GPUs, and
         a polite, escalating message that says how to fix it.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-18
Input: the server's process list (`ps`) and GPU use (`nvidia-smi`); the lab's
       limits in policy/millwright.yaml; the lab roster.
Output: a report (``~/.murmurent/etiquette/latest.json``); with ``notify``,
        Slack messages through the lab's own bot.

What it reads. For each process: the account, its priority (nice value), its
average CPU share and how long it has run; and which GPUs each process holds.
Never the command line: command lines often hold file names, and file names
can identify patients or reveal unpublished work. Nothing here needs
administrator rights, and nothing changes anyone's jobs: it reports.

Who hears about it (Mike's decisions on #151):

- only members of this lab are named. Other accounts appear in the PI's
  report as a count per kind of issue, without names;
- a person is compared with their own allowance, never with other people;
- the first day an issue is seen, a direct message to the person; if it is
  still there on the next check, a line in the lab's Slack channel; after
  that, a message to the PI. A day without the issue starts again from the
  beginning;
- every message says what was seen, why it matters to other people on the
  server, and the exact command that fixes it. A "how to" link is sent once,
  not with every message.

The CPU share `ps` reports is the average over a process's life, so only
processes that have run for at least ``MIN_AGE_SECONDS`` are counted; a short
burst is not a breach.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import json
import os
import pwd
import shlex
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

Runner = Callable[[list[str]], subprocess.CompletedProcess]

#: Processes younger than this are not counted (see the module docstring).
MIN_AGE_SECONDS = 10 * 60
#: A process using less CPU than this is idle enough to ignore for priority.
BUSY_CPU_PERCENT = 5.0
#: A priority message needs at least this much work above nice 19, so an
#: editor or a shell that once used a little CPU is not reported.
MIN_NOT_NICE_CORES = 1.0
#: Accounts below this user id are the system's own.
FIRST_PERSON_UID = 1000

HOW_TO = "https://mikehallett.science/murmurent/run_launcher/"

PRIORITY = "priority"
CORES = "cores"
GPUS = "gpus"
KINDS = (PRIORITY, CORES, GPUS)

UNIT = "murmurent-etiquette"


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=60, check=False)


# ---------------------------------------------------------------------------
# Reading the server
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Proc:
    user: str
    pid: int
    nice: int
    cpu_percent: float
    seconds: int


def read_processes(run: Runner = _run) -> list[Proc]:
    """Every process's account, priority, CPU share and age. No command lines."""
    out = run(["ps", "-eo", "user:64,pid,ni,pcpu,etimes", "--no-headers"])
    procs: list[Proc] = []
    for line in (out.stdout or "").splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        user, pid, ni, pcpu, et = parts
        try:
            procs.append(Proc(user, int(pid), int(ni) if ni.lstrip("-").isdigit() else 0,
                              float(pcpu), int(et)))
        except ValueError:
            continue
    return procs


def read_gpu_holders(run: Runner = _run) -> tuple[dict[int, set[int]], dict[int, float]]:
    """``({pid: {gpu index}}, {gpu index: utilisation %})``; empty without GPUs."""
    try:
        gpus = run(["nvidia-smi", "--query-gpu=index,uuid,utilization.gpu",
                    "--format=csv,noheader,nounits"])
        apps = run(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid",
                    "--format=csv,noheader,nounits"])
    except (OSError, subprocess.SubprocessError):
        return {}, {}
    index_of: dict[str, int] = {}
    util: dict[int, float] = {}
    for line in (gpus.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3 and parts[0].isdigit():
            index_of[parts[1]] = int(parts[0])
            try:
                util[int(parts[0])] = float(parts[2])
            except ValueError:
                util[int(parts[0])] = 0.0
    held: dict[int, set[int]] = {}
    for line in (apps.stdout or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[1].isdigit() and parts[0] in index_of:
            held.setdefault(int(parts[1]), set()).add(index_of[parts[0]])
    return held, util


def _is_person(user: str) -> bool:
    try:
        return pwd.getpwnam(user).pw_uid >= FIRST_PERSON_UID
    except KeyError:
        return user.isdigit() and int(user) >= FIRST_PERSON_UID


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    kind: str
    seen: str     # what was seen, in plain words
    why: str      # why it matters to other people
    fix: str      # the exact command or step

    def text(self) -> str:
        return f"{self.seen} {self.why} To fix it: {self.fix}"


@dataclass
class Usage:
    login: str
    cores: float = 0.0
    not_nice_cores: float = 0.0
    not_nice_count: int = 0
    gpus: set[int] = field(default_factory=set)


def tally(procs: list[Proc], gpu_held: dict[int, set[int]], priority: int) -> dict[str, Usage]:
    """Per account: cores in use, cores running above the lab's priority, GPUs held."""
    users: dict[str, Usage] = {}
    for p in procs:
        if not _is_person(p.user):
            continue
        u = users.setdefault(p.user, Usage(p.user))
        if p.pid in gpu_held:
            u.gpus |= gpu_held[p.pid]
        if p.seconds < MIN_AGE_SECONDS:
            continue
        u.cores += p.cpu_percent / 100.0
        if p.nice < priority and p.cpu_percent >= BUSY_CPU_PERCENT:
            u.not_nice_cores += p.cpu_percent / 100.0
            u.not_nice_count += 1
    return users


def findings_for(u: Usage, policy, moment: _dt.datetime, idle_gpus: int) -> list[Finding]:
    """The person's issues against their own allowance, each with its fix."""
    out: list[Finding] = []
    prio = policy.priority
    if u.not_nice_count and u.not_nice_cores >= MIN_NOT_NICE_CORES:
        out.append(Finding(
            PRIORITY,
            f"{u.not_nice_count} of your processes (about {u.not_nice_cores:.1f} cores) "
            f"run above the lab's priority, nice {prio}.",
            "At normal priority they slow everyone else's work on the server; at nice "
            f"{prio} they still get every core nobody else needs.",
            f"`renice -n {prio} -u {u.login}` lowers all of your running processes now, "
            f"and `murmurent run ...` starts new jobs at nice {prio} for you."))
    limit = policy.max_cores_per_person
    if u.cores > limit:
        out.append(Finding(
            CORES,
            f"Your jobs use about {u.cores:.0f} cores; the lab's limit is {limit} per person.",
            "Above it, other people's jobs queue behind yours.",
            f"start jobs with `murmurent run --cores {limit} ...`, or set "
            f"`OMP_NUM_THREADS={limit}` before a Python or R job. If you need more for a "
            "while, ask in the lab channel with a reason and an end time."))
    allowed = policy.gpu_allowance(moment, idle_gpus)
    if len(u.gpus) > allowed:
        held = ", ".join(str(g) for g in sorted(u.gpus))
        when = "during working hours" if policy.working_hours.contains(moment) else "now"
        out.append(Finding(
            GPUS,
            f"You hold {len(u.gpus)} GPUs ({held}); {when} the lab's limit is {allowed}.",
            "Other people cannot start GPU work while they are held.",
            f"stop the jobs you do not need, or start them with `murmurent run --gpus "
            f"{allowed} ...`, which picks free GPUs. For more, ask in the lab channel first."))
    return out


def lab_logins() -> dict[str, object]:
    """``{server login: member record}`` for this lab's active members."""
    from . import membership as _members
    from .project_access import resolve_member_os_user
    out: dict[str, object] = {}
    for rec in _members.iter_members(include_inactive=False):
        handle = rec.handle.lstrip("@")
        login = resolve_member_os_user(handle) or handle
        out[login] = rec
    return out


def check(*, policy=None, run: Runner = _run, now: _dt.datetime | None = None,
          logins: dict[str, object] | None = None) -> dict:
    """Run the check once. Returns the report (also written to latest.json)."""
    from .millwright_policy import load_policy
    policy = policy or load_policy()
    now = now or _dt.datetime.now().astimezone()
    procs = read_processes(run)
    held, util = read_gpu_holders(run)
    idle = sum(1 for v in util.values() if v < policy.gpu_idle_below_percent)
    usage = tally(procs, held, policy.priority)
    members = lab_logins() if logins is None else logins
    named, others = [], {k: 0 for k in KINDS}
    for login, u in sorted(usage.items()):
        found = findings_for(u, policy, now, idle)
        if not found:
            continue
        if login in members:
            rec = members[login]
            named.append({"handle": getattr(rec, "handle", login).lstrip("@"), "login": login,
                          "findings": [asdict(f) for f in found]})
        else:
            for f in found:
                others[f.kind] += 1
    report = {"schema": 1, "taken_at": now.isoformat(timespec="seconds"),
              "limits": {"priority": policy.priority, "cores": policy.max_cores_per_person,
                         "gpus_now": policy.gpu_allowance(now, idle)},
              "members": named, "others": others}
    _write_json(report_dir() / "latest.json", report)
    return report


# ---------------------------------------------------------------------------
# Messages, with escalation
# ---------------------------------------------------------------------------

def report_dir() -> Path:
    from .project_unit import murmurent_home
    return murmurent_home() / "etiquette"


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def plan_messages(report: dict, state: dict, today: str) -> tuple[list[dict], dict]:
    """Decide who hears what today, and the new escalation state.

    Each (person, kind) has a count of consecutive check days on which it was
    seen: 1 means a direct message, 2 a line in the lab channel, 3 or more the
    PI. A day when it is not seen removes it. Running twice in one day does
    not escalate. Returns ``(messages, new_state)``; each message is
    ``{"to": "person"|"channel"|"pi", "handle", "login", "text"}``.
    """
    new_state: dict = {}
    messages: list[dict] = []
    for person in report.get("members", []):
        login = person["login"]
        prev = state.get(login, {})
        mine: dict = {}
        for f in person["findings"]:
            kind = f["kind"]
            entry = dict(prev.get(kind, {}))
            if entry.get("last_seen") != today:
                entry["days"] = int(entry.get("days", 0)) + 1
                entry["last_seen"] = today
                fresh = True
            else:
                fresh = False
            mine[kind] = entry
            if not fresh:
                continue
            body = f"{f['seen']} {f['why']} To fix it: {f['fix']}"
            days = entry["days"]
            if days == 1:
                how = "" if prev.get("_howto_sent") else f" More on running long jobs: {HOW_TO}"
                messages.append({"to": "person", "handle": person["handle"], "login": login,
                                 "text": f"Hello from the lab's millwright. {body}{how}"})
            elif days == 2:
                messages.append({"to": "channel", "handle": person["handle"], "login": login,
                                 "text": f"@{person['handle']}: {body}"})
            else:
                messages.append({"to": "pi", "handle": person["handle"], "login": login,
                                 "text": f"@{person['handle']}, day {days}: {body}"})
        if mine:
            mine["_howto_sent"] = True
            new_state[login] = mine
    return messages, new_state


def notify(report: dict, *, send_dm=None, post=None, today: str | None = None,
           lab: str = "") -> list[str]:
    """Send today's messages and the PI's summary; returns what was done, in words.

    Uses the lab's own Slack bot. Never raises: a Slack problem is reported in
    the returned lines, and the escalation state is saved either way.
    """
    from . import membership as _members
    from . import project_unit as _pu
    from .group_reconcile import resolve_group_slack_token, send_group_dm
    from .lab import pi_handle
    lab = lab or _pu.this_machine_lab()
    today = today or _dt.date.today().isoformat()
    state_path = report_dir() / "state.json"
    messages, new_state = plan_messages(report, _read_json(state_path), today)
    send_dm = send_dm or send_group_dm
    done: list[str] = []

    def dm(handle: str, text: str) -> None:
        try:
            rec = _members.get(handle)
            ok, detail = send_dm(lab, text=text, slack=rec.slack, email=rec.email)
        except Exception as exc:  # noqa: BLE001
            ok, detail = False, str(exc)
        done.append(f"message to @{handle}: " + ("sent" if ok else f"not sent ({detail})"))

    channel = _lab_channel(lab)
    for m in messages:
        if m["to"] == "person":
            dm(m["handle"], m["text"])
        elif m["to"] == "channel" and channel:
            try:
                from ..dashboard.slack_notify import _post
                (post or _post)(channel, m["text"], token=resolve_group_slack_token(lab))
                done.append(f"lab channel: line about @{m['handle']}")
            except Exception as exc:  # noqa: BLE001
                done.append(f"lab channel: not posted ({exc})")
        else:
            # No lab channel on record: the PI hears instead.
            dm(pi_handle().lstrip("@"), m["text"])
    summary = summary_text(report)
    if summary:
        dm(pi_handle().lstrip("@"), summary)
    _write_json(state_path, new_state)
    return done


def _lab_channel(lab: str) -> str:
    try:
        from .centre_provision import _group_entry
        entry = _group_entry(lab)
        return getattr(entry, "slack_channel_id", "") or ""
    except Exception:  # noqa: BLE001
        return ""


def summary_text(report: dict) -> str:
    """The PI's daily line: lab members by name, everyone else as counts. Empty
    when there is nothing to report."""
    names = [f"@{p['handle']} ({', '.join(f['kind'] for f in p['findings'])})"
             for p in report.get("members", [])]
    others = {k: v for k, v in (report.get("others") or {}).items() if v}
    if not names and not others:
        return ""
    parts = ["Server etiquette check."]
    if names:
        parts.append("In the lab: " + "; ".join(names) + ".")
    if others:
        parts.append("Other accounts on the server, not named: "
                     + ", ".join(f"{v} over the {k} rule" for k, v in others.items())
                     + ". Raise these with the administrator if they persist.")
    return " ".join(parts)


def describe(report: dict) -> list[str]:
    """The report in plain lines for a terminal."""
    lim = report.get("limits", {})
    lines = [f"Server etiquette, {report.get('taken_at', '')[:16].replace('T', ' ')}. "
             f"Limits: nice {lim.get('priority')}, {lim.get('cores')} cores per person, "
             f"{lim.get('gpus_now')} GPUs per person now."]
    if not report.get("members"):
        lines.append("Everyone in the lab is within the rules.")
    for p in report.get("members", []):
        lines.append(f"@{p['handle']} (login {p['login']}):")
        for f in p["findings"]:
            lines.append(f"  - {f['seen']} To fix it: {f['fix']}")
    others = {k: v for k, v in (report.get("others") or {}).items() if v}
    if others:
        lines.append("Other accounts, not named: "
                     + ", ".join(f"{v} over the {k} rule" for k, v in others.items()) + ".")
    return lines


# ---------------------------------------------------------------------------
# Running it every working day
# ---------------------------------------------------------------------------

def _program() -> str:
    from .launcher import murmurent_program
    return str(murmurent_program())


def calendar(at: str) -> str:
    """Weekdays at ``at`` (HH:MM), when the working-hours GPU limit applies."""
    parts = at.strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts) \
            or not (0 <= int(parts[0]) < 24 and 0 <= int(parts[1]) < 60):
        raise ValueError(f"'{at}' is not a time; write it like 11:00")
    return f"Mon..Fri *-*-* {int(parts[0]):02d}:{int(parts[1]):02d}:00"


def unit_texts(when: str, notify_people: bool, env: dict[str, str] | None = None) -> tuple[str, str]:
    from .space_schedule import CARRIED_ENV
    env = dict(os.environ) if env is None else env
    cmd = f"{_program()} etiquette check" + (" --notify" if notify_people else "")
    svc = ["[Unit]", "Description=murmurent: server etiquette check (#151 step 4)", "",
           "[Service]", "Type=oneshot", "Nice=19"]
    for key in CARRIED_ENV:
        if env.get(key):
            svc.append(f"Environment={key}={shlex.quote(env[key])}")
    log = "%h/.murmurent/etiquette/check.log"
    svc += [f"ExecStart=/bin/bash -lc {shlex.quote(cmd)}",
            f"StandardOutput=append:{log}", f"StandardError=append:{log}", ""]
    timer = ["[Unit]", "Description=murmurent: server etiquette check", "",
             "[Timer]", f"OnCalendar={when}", "Persistent=true", "",
             "[Install]", "WantedBy=timers.target", ""]
    return "\n".join(svc), "\n".join(timer)


def install(at: str = "11:00", *, notify_people: bool = False,
            env: dict[str, str] | None = None, run: Runner = _run) -> list[str]:
    """Write and switch on the weekday timer; record it in the lab records."""
    from .space_schedule import unit_dir
    when = calendar(at)
    folder = unit_dir()
    folder.mkdir(parents=True, exist_ok=True)
    svc, timer = unit_texts(when, notify_people, env)
    (folder / f"{UNIT}.service").write_text(svc, encoding="utf-8")
    (folder / f"{UNIT}.timer").write_text(timer, encoding="utf-8")
    report_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    for argv in (["systemctl", "--user", "daemon-reload"],
                 ["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"]):
        out = run(argv)
        if out.returncode != 0:
            raise RuntimeError(f"{' '.join(argv)} failed: {(out.stderr or out.stdout).strip()}")
    path = record(when, notify_people, env=env)
    lines = [f"The etiquette check runs {when.replace(' *-*-* ', ' at ')}."]
    lines.append("  It messages people." if notify_people else
                 "  It only writes its report (no messages). Add --notify once the report "
                 "looks right.")
    if path:
        lines.append(f"  Recorded in {path}; commit and push the lab records repository.")
    return lines


def remove(*, run: Runner = _run) -> list[str]:
    from .space_schedule import unit_dir
    run(["systemctl", "--user", "disable", "--now", f"{UNIT}.timer"])
    for suffix in ("timer", "service"):
        (unit_dir() / f"{UNIT}.{suffix}").unlink(missing_ok=True)
    run(["systemctl", "--user", "daemon-reload"])
    record("", False)
    return ["The etiquette check is no longer scheduled."]


_BEGIN = "<!-- murmurent-etiquette: begin -->"
_END = "<!-- murmurent-etiquette: end -->"


def record(when: str, notify_people: bool, *, env: dict[str, str] | None = None) -> Path | None:
    """Write what runs, under whose account, in ``policy/scheduled_jobs.md``
    (a condition agreed on #151), beside the space scan's entry."""
    from .millwright_policy import lab_policy_path
    policy_file = lab_policy_path(env)
    if policy_file is None:
        return None
    path = policy_file.parent / "scheduled_jobs.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = "# Scheduled jobs\n"
    block = ""
    if when:
        block = (f"{_BEGIN}\n## Server etiquette check\n\n"
                 f"- **When:** {when.replace(' *-*-* ', ' at ')} (systemd user timer "
                 f"`{UNIT}.timer`)\n"
                 f"- **Account:** `{getpass.getuser()}`\n"
                 f"- **Runs:** `murmurent etiquette check{' --notify' if notify_people else ''}`\n"
                 "- **May:** read every process's account, priority, CPU share and age, "
                 "and which GPUs it holds (never command lines); message lab members, "
                 "the lab channel and the PI with the lab's bot.\n"
                 "- **May not:** change, slow or stop anyone's jobs; use administrator "
                 "rights; name people outside the lab.\n"
                 f"- **Remove with:** `murmurent etiquette schedule --remove`\n{_END}\n")
    if _BEGIN in text and _END in text:
        head, rest = text.split(_BEGIN, 1)
        text = head + block + rest.split(_END, 1)[1].lstrip("\n")
    elif block:
        text = text.rstrip("\n") + "\n\n" + block
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
