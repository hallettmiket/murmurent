"""
Purpose: Run the lab-wide space scan on a timer (issue #151, step 3), with a
         systemd user timer, and record what runs in the lab records repository.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-17
Input:   The day and time to run; this machine's systemd user manager.
Output:  ``~/.config/systemd/user/murmurent-space-scan.{service,timer}``, the
         timer switched on, and ``policy/scheduled_jobs.md`` in the lab
         records repository describing it.

Why systemd and not cron: on the lab's server, ordinary accounts may not use
``crontab``. A systemd user timer needs no administrator, but it runs only
while the account has a session, unless the administrator has turned on
"lingering" for the account (``loginctl enable-linger <user>``). The timer is
set to catch up: a run missed while nobody was logged in happens at the next
login. :func:`status` says which case applies.

Moving the job to a lab service account later is the same command run under
that account; nothing here names a person.
"""

from __future__ import annotations

import getpass
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

UNIT = "murmurent-space-scan"
DAYS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri",
        "sat": "Sat", "sun": "Sun"}

#: Settings the scan needs that a timer would not otherwise see.
CARRIED_ENV = ("MURMURENT_HOME", "MURMURENT_DATA_ROOT", "MURMURENT_LAB_MGMT_REPO",
               "MURMURENT_USER", "MURMURENT_MILLWRIGHT_POLICY", "MURMURENT_REPOS_ROOT")

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)


def unit_dir() -> Path:
    """Where systemd looks for this account's own units."""
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def _program() -> str:
    from .launcher import murmurent_program
    return str(murmurent_program())


def calendar(day: str, at: str) -> str:
    """A systemd calendar line, such as ``Sun *-*-* 02:00:00``."""
    key = day.strip().lower()[:3]
    if key not in DAYS:
        raise ValueError(f"'{day}' is not a day; use mon, tue, wed, thu, fri, sat or sun")
    parts = at.strip().split(":")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        raise ValueError(f"'{at}' is not a time; write it like 02:00")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError(f"'{at}' is not a time; write it like 02:00")
    return f"{DAYS[key]} *-*-* {hour:02d}:{minute:02d}:00"


def service_text(env: dict[str, str] | None = None) -> str:
    """The service unit: one lab scan at the lowest priority, then a message to the PI."""
    env = dict(os.environ) if env is None else env
    lines = ["[Unit]", "Description=murmurent: weekly lab space scan (report only, #151)", "",
             "[Service]", "Type=oneshot", "Nice=19", "IOSchedulingClass=idle"]
    for key in CARRIED_ENV:
        if env.get(key):
            lines.append(f"Environment={key}={shlex.quote(env[key])}")
    log = "%h/.murmurent/space/lab_scan.log"
    lines.append(f"ExecStart=/bin/bash -lc {shlex.quote(f'{_program()} space scan-lab --notify')}")
    lines += [f"StandardOutput=append:{log}", f"StandardError=append:{log}", ""]
    return "\n".join(lines)


def timer_text(when: str) -> str:
    """The timer unit. ``Persistent`` makes a missed run happen at the next chance."""
    return "\n".join(["[Unit]", "Description=murmurent: weekly lab space scan", "",
                      "[Timer]", f"OnCalendar={when}", "Persistent=true", "",
                      "[Install]", "WantedBy=timers.target", ""])


@dataclass
class ScheduleStatus:
    installed: bool
    active: bool
    when: str
    next_run: str
    lingering: bool | None
    record: str = ""

    def lines(self) -> list[str]:
        if not self.installed:
            return ["The weekly lab scan is not scheduled. Set it up with: "
                    "murmurent space schedule --install"]
        out = [f"The lab scan runs {self.when or 'on its timer'}"
               + (f"; next run {self.next_run}." if self.next_run else ".")]
        if not self.active:
            out.append("  The timer is installed but switched off.")
        if self.lingering is False:
            out.append("  It runs only while you are logged in to this machine: the account "
                       "is not set to linger. A missed run happens at your next login. To run "
                       "it while you are logged out, ask the administrator to run: "
                       f"loginctl enable-linger {getpass.getuser()}")
        elif self.lingering:
            out.append("  It runs whether or not you are logged in.")
        if self.record:
            out.append(f"  Recorded in {self.record}")
        return out


def lingering(run: Runner = _run) -> bool | None:
    """Whether this account's timers run while it is logged out; None if unknown."""
    try:
        out = run(["loginctl", "show-user", getpass.getuser(), "-p", "Linger"])
    except (OSError, subprocess.SubprocessError):
        return None
    value = (out.stdout or "").strip().split("=", 1)[-1].lower()
    return {"yes": True, "no": False}.get(value)


def status(run: Runner = _run) -> ScheduleStatus:
    timer = unit_dir() / f"{UNIT}.timer"
    when = ""
    if timer.is_file():
        for line in timer.read_text(encoding="utf-8").splitlines():
            if line.startswith("OnCalendar="):
                when = "every " + line.split("=", 1)[1].replace(" *-*-* ", " at ")
    active = next_run = ""
    try:
        active = (run(["systemctl", "--user", "is-active", f"{UNIT}.timer"]).stdout or "").strip()
        shown = run(["systemctl", "--user", "show", f"{UNIT}.timer", "-p",
                     "NextElapseUSecRealtime", "--value"]).stdout or ""
        next_run = shown.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return ScheduleStatus(installed=timer.is_file(), active=active == "active", when=when,
                          next_run=next_run, lingering=lingering(run))


def install(day: str = "sun", at: str = "02:00", *, env: dict[str, str] | None = None,
            run: Runner = _run) -> ScheduleStatus:
    """Write the units, switch the timer on, and record it in the lab records repository."""
    when = calendar(day, at)
    folder = unit_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{UNIT}.service").write_text(service_text(env), encoding="utf-8")
    (folder / f"{UNIT}.timer").write_text(timer_text(when), encoding="utf-8")
    (Path.home() / ".murmurent" / "space").mkdir(parents=True, exist_ok=True, mode=0o700)
    for argv in (["systemctl", "--user", "daemon-reload"],
                 ["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"]):
        out = run(argv)
        if out.returncode != 0:
            raise RuntimeError(f"{' '.join(argv)} failed: {(out.stderr or out.stdout).strip()}")
    result = status(run)
    result.record = str(record(when, env=env) or "")
    return result


def remove(*, run: Runner = _run) -> ScheduleStatus:
    """Switch the timer off and delete the units."""
    run(["systemctl", "--user", "disable", "--now", f"{UNIT}.timer"])
    for suffix in ("timer", "service"):
        (unit_dir() / f"{UNIT}.{suffix}").unlink(missing_ok=True)
    run(["systemctl", "--user", "daemon-reload"])
    result = status(run)
    result.record = str(record("", env=None) or "")
    return result


_BEGIN = "<!-- murmurent-space-scan: begin -->"
_END = "<!-- murmurent-space-scan: end -->"


def record(when: str, *, env: dict[str, str] | None = None) -> Path | None:
    """Write what runs, under whose account, in ``policy/scheduled_jobs.md``.

    One of the conditions agreed on #151: anyone in the lab can see exactly
    what runs under the PI's name. The file is written, not committed; it goes
    up with the lab records repository's next push. An empty ``when`` records
    that the job was removed.
    """
    from .millwright_policy import lab_policy_path
    policy_file = lab_policy_path(env)
    if policy_file is None:
        return None
    path = policy_file.parent / "scheduled_jobs.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        text = ("# Scheduled jobs\n\nJobs that murmurent runs on a timer, under whose "
                "account, and what they may do. Kept here so that anyone in the lab can "
                "see what runs in a person's name.\n")
    if when:
        block = (f"{_BEGIN}\n## Weekly lab space scan\n\n"
                 f"- **When:** {when.replace(' *-*-* ', ' at ')} (systemd user timer "
                 f"`{UNIT}.timer`; a missed run happens at the next chance)\n"
                 f"- **Account:** `{getpass.getuser()}`\n"
                 f"- **Runs:** `murmurent space scan-lab --notify`, at the lowest priority\n"
                 "- **May:** read sizes, dates, owners and names under the lab's data "
                 "folder; read large same-sized files to fingerprint them; write its "
                 "table and report in the account's own `~/.murmurent/space/`; send the "
                 "PI one Slack message with the lab's bot.\n"
                 "- **May not:** change, move or delete any file; use administrator "
                 "rights; write to GitHub.\n"
                 f"- **Remove with:** `murmurent space schedule --remove`\n{_END}\n")
    else:
        block = ""
    if _BEGIN in text and _END in text:
        head, rest = text.split(_BEGIN, 1)
        text = head + block + rest.split(_END, 1)[1].lstrip("\n")
    elif block:
        text = text.rstrip("\n") + "\n\n" + block
    path.write_text(text, encoding="utf-8")
    return path


__all__ = ["UNIT", "calendar", "service_text", "timer_text", "ScheduleStatus", "lingering",
           "status", "install", "remove", "record", "unit_dir"]
