"""
Purpose: The small program ``murmurent run`` starts inside tmux. It waits when
         asked to, runs the job at low priority, follows its log, and keeps the
         job card up to date until the job ends.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-16
Input:   The path of one job card (``python -m murmurent.core.run_supervisor
         <card>``), and the private environment copy the launcher wrote beside it.
Output:  Updates to that card: start and end times, exit code, state, stall and
         disk notes, estimates. One Slack line when the job finishes, fails or
         stalls.

Issue #151, step 1. What it records, in the card's ``state``:

- ``waiting``: not started yet (a start time, a load threshold, or no room).
- ``running``: the command is running.
- ``stalled``: running, but its log has not grown for the policy's stall time.
  Nothing is stopped; a person decides.
- ``finished``: ended with exit code 0. ``failed``: any other ending.
- ``stopped``: someone stopped it (``murmurent jobs stop``, or closing its tmux
  window).

Every piece of housekeeping (stall check, disk sample, card write) is wrapped so
that a problem in it is noted on the card and never stops the job.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from . import run_cards as _cards
from . import run_launcher as _rl
from .millwright_policy import Policy, load_policy

POLL_SECONDS = 2
CHECK_SECONDS = 60
WAIT_CHECK_SECONDS = 60
STOP_GRACE_SECONDS = 30
DISK_SAMPLE_MINUTES = (1, 2, 5, 10)
FOLDER_WALK_MAX_ENTRIES = 200_000
FOLDER_WALK_MAX_SECONDS = 20.0
ECHO_MAX_BYTES = 64 * 1024
SIGNAL_HINTS = {
    signal.SIGKILL: "This often means the server ran out of memory, or someone stopped it by force.",
    signal.SIGSEGV: "The program crashed (a memory access error).",
}


def folder_size(
    path: Path,
    *,
    max_entries: int = FOLDER_WALK_MAX_ENTRIES,
    max_seconds: float = FOLDER_WALK_MAX_SECONDS,
) -> int | None:
    """Total size of the files under ``path``, or None when too big to count quickly.

    Reads sizes only, never contents, and does not follow links.
    """
    start = time.monotonic()
    total = 0
    seen = 0
    stack = [Path(path)]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            seen += 1
            if seen > max_entries or time.monotonic() - start > max_seconds:
                return None
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
    return total


class Supervisor:
    """Run one job from its card.

    Parameters
    ----------
    card_file : Path
        The job card.
    base_env : dict
        The environment the job runs in, before the launcher's limits are added.
    probes : SystemProbes, optional
        The machine; tests pass a fake.
    policy : Policy, optional
        The lab's rules; read fresh when omitted.
    popen : callable, optional
        Replacement for ``subprocess.Popen``.
    sleep, monotonic : callable, optional
        Replacements for the clock, so tests run in moments.
    poster, token_resolver : callable, optional
        Replacements for the Slack post and token lookup.
    out : file, optional
        Where the log is echoed for someone watching the tmux window.
    """

    def __init__(
        self,
        card_file: Path,
        base_env: dict[str, str],
        *,
        probes: _rl.SystemProbes | None = None,
        policy: Policy | None = None,
        popen: Callable[..., Any] = subprocess.Popen,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        poster: Callable[..., bool] | None = None,
        token_resolver: Callable[[str, str], str] | None = None,
        out: TextIO | None = None,
    ) -> None:
        card = _cards.read_card(card_file)
        if card is None:
            raise FileNotFoundError(f"no job card at {card_file}")
        self.card_file = card_file
        self.card = card
        self.base_env = dict(base_env)
        self.probes = probes or _rl.SystemProbes()
        self.policy = policy
        self.popen = popen
        self.sleep = sleep
        self.monotonic = monotonic
        self.poster = poster
        self.token_resolver = token_resolver
        self.out = out if out is not None else sys.stdout
        self.stop_requested = False
        self.child: Any = None
        self._watch_seen: tuple[int, float] | None = None
        self._echo_offset = 0
        self._disk_start: tuple[float, int] | None = None
        self._disk_samples_due = list(DISK_SAMPLE_MINUTES)

    # -- small helpers ------------------------------------------------------

    def save(self) -> None:
        """Write the card; a failure is printed, never raised."""
        try:
            _cards.write_card(self.card, self.card_file)
        except OSError as exc:
            self._say(f"[murmurent] could not update the job card: {exc}")

    def _say(self, text: str) -> None:
        try:
            print(text, file=self.out, flush=True)
        except (OSError, ValueError):
            pass

    def _nap(self, seconds: float) -> None:
        """Sleep in short steps, so a stop request is answered within a second."""
        end = self.monotonic() + seconds
        while not self.stop_requested:
            left = end - self.monotonic()
            if left <= 0:
                return
            self.sleep(min(1.0, left))

    def request_stop(self, *_args: Any) -> None:
        """Ask the supervisor to stop the job (called from a signal handler)."""
        self.stop_requested = True

    def _policy(self) -> Policy:
        if self.policy is None:
            self.policy = load_policy(self.base_env)
        return self.policy

    def notify(self) -> None:
        """Post the card's one-line notice and record the outcome on the card."""
        try:
            _rl.post_notice(self.card, poster=self.poster, token_resolver=self.token_resolver)
        except Exception as exc:  # noqa: BLE001 - a Slack problem never fails a job
            self.card.notify["skipped"] = f"posting failed: {exc.__class__.__name__}"

    # -- waiting --------------------------------------------------------------

    def wait_until_ready(self) -> bool:
        """Wait for the start time, the load threshold and room on the server.

        Returns
        -------
        bool
            True when the job may start; False when it ended before starting
            (stopped, or refused under the rules at its start time).
        """
        card = self.card
        requested = card.requested or {}
        start_at = _cards.from_iso(requested.get("at"))
        below = requested.get("when_load_below")
        while True:
            if self.stop_requested:
                self._end_before_start(_cards.STATE_STOPPED, "Stopped before it started.")
                return False
            now = self.probes.now()
            if start_at and now < start_at:
                self._waiting(f"the start time {start_at:%Y-%m-%d %H:%M}")
                self._nap(min(WAIT_CHECK_SECONDS, (start_at - now).total_seconds()))
                continue
            if below:
                load = self.probes.load_1min()
                if load is not None and load >= float(below):
                    self._waiting(
                        f"the server's load to fall below {float(below):g} " f"(it is {load:.0f})"
                    )
                    self._nap(WAIT_CHECK_SECONDS)
                    continue
            if card.cores > 0:
                return True  # the launcher already chose cores and GPUs
            plan = self._plan()
            if plan.ok:
                card.cores = plan.cores
                card.gpus = plan.gpus
                card.env_set = _rl.thread_environment(
                    plan.cores, plan.gpus, int(requested.get("gpus") or 0) > 0
                )
                for note in plan.notes:
                    card.add_note(note)
                return True
            if plan.can_wait:
                self._waiting("room on the server: " + plan.refusals[0])
                self._nap(WAIT_CHECK_SECONDS)
                continue
            self._end_before_start(
                _cards.STATE_FAILED, "Could not start: " + " ".join(plan.refusals)
            )
            self.notify()
            self.save()
            return False

    def _plan(self) -> _rl.ResourcePlan:
        card = self.card
        requested = card.requested or {}
        request = _rl.ResourceRequest(
            cores=requested.get("cores"),
            gpus=int(requested.get("gpus") or 0),
            memory_bytes=requested.get("memory_bytes"),
            expect_disk_bytes=requested.get("expect_disk_bytes"),
            disk_path=Path(card.out or card.workdir),
            exception=card.exception,
        )
        held = _cards.resources_held(_cards.list_cards(), exclude_id=card.id)
        return _rl.plan_resources(request, self._policy(), self.probes, held)

    def _waiting(self, what: str) -> None:
        if self.card.waiting_for != what or self.card.state != _cards.STATE_WAITING:
            self.card.state = _cards.STATE_WAITING
            self.card.waiting_for = what
            self.save()

    def _end_before_start(self, state: str, note: str) -> None:
        self.card.state = state
        self.card.ended_at = _cards.to_iso(self.probes.now())
        self.card.add_note(note)
        self.save()

    # -- running --------------------------------------------------------------

    def start_child(self) -> bool:
        """Start the command with its log, limits and low priority inherited."""
        card = self.card
        log_path = Path(card.log)
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log = open(log_path, "ab")  # noqa: SIM115 - kept open for the child
        except OSError as exc:
            self._end_before_start(_cards.STATE_FAILED, f"Could not open the log: {exc}")
            self.notify()
            self.save()
            return False
        now = self.probes.now()
        header = f"=== murmurent run {card.id} started {_cards.to_iso(now)} ===\n"
        log.write(header.encode("utf-8"))
        log.flush()
        echo_from = log.tell()  # the job's own output starts here
        env = dict(self.base_env)
        env.update(card.env_set)
        try:
            self.child = self.popen(
                card.command,
                cwd=card.workdir,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
            )
        except OSError as exc:
            log.close()
            card.exit_code = 127
            self._end_before_start(
                _cards.STATE_FAILED, f"The command could not be started: {exc.strerror or exc}."
            )
            self.notify()
            self.save()
            return False
        finally:
            if self.child is not None:
                log.close()  # the child holds its own copy
        card.state = _cards.STATE_RUNNING
        card.waiting_for = ""
        card.started_at = _cards.to_iso(now)
        card.last_output_at = card.started_at
        card.child_pid = getattr(self.child, "pid", None)
        self._echo_offset = echo_from
        self.save()
        self._say(
            f"[murmurent] job {card.name} started on {card.cores} core(s)"
            + (f" and GPU(s) {', '.join(map(str, card.gpus))}" if card.gpus else "")
            + f". Its output follows; it is also saved in {card.log}"
        )
        return True

    def follow(self) -> int | None:
        """Watch the running job until it ends; return its exit code."""
        last_check = self.monotonic()
        while True:
            code = self.child.poll()
            if code is not None:
                self.echo_log()
                return code
            if self.stop_requested:
                return self.stop_child()
            self.echo_log()
            if self.monotonic() - last_check >= CHECK_SECONDS:
                last_check = self.monotonic()
                self.housekeeping()
            self.sleep(POLL_SECONDS)

    def housekeeping(self) -> None:
        """The once-a-minute checks: stall, disk, exception expiry."""
        now = self.probes.now()
        for step in (self.check_stall, self.sample_disk, self.check_exception):
            try:
                step(now)
            except Exception as exc:  # noqa: BLE001 - housekeeping never stops a job
                self.card.add_note(f"A routine check failed ({step.__name__}): {exc}")
        self.save()

    def echo_log(self) -> None:
        """Copy new log output to the tmux window, for someone watching."""
        try:
            with open(self.card.log, "rb") as handle:
                handle.seek(self._echo_offset)
                chunk = handle.read(ECHO_MAX_BYTES)
        except OSError:
            return
        if chunk:
            self._echo_offset += len(chunk)
            try:
                self.out.write(chunk.decode("utf-8", "replace"))
                self.out.flush()
            except (OSError, ValueError):
                pass

    def check_stall(self, now: _dt.datetime) -> None:
        """Mark the job stalled when its watched file has not grown for a while."""
        card = self.card
        try:
            stat = Path(card.watch).stat()
            seen = (stat.st_size, stat.st_mtime)
        except OSError:
            seen = None
        if seen is not None and seen != self._watch_seen:
            first_look = self._watch_seen is None
            self._watch_seen = seen
            if not first_look:
                card.last_output_at = _cards.to_iso(now)
            if card.state == _cards.STATE_STALLED:
                card.state = _cards.STATE_RUNNING
                card.add_note("New output appeared; the job is no longer stalled.", now)
            if not first_look:
                return
        last = _cards.from_iso(card.last_output_at) or _cards.from_iso(card.started_at)
        if last is None or card.state != _cards.STATE_RUNNING:
            return
        quiet_seconds = (now - last).total_seconds()
        if quiet_seconds >= card.stall_minutes * 60:
            card.state = _cards.STATE_STALLED
            card.add_note(
                f"No new output for {_cards.format_duration(quiet_seconds)}. The "
                "job was not stopped; check whether it is stuck.",
                now,
            )
            self.notify()

    def sample_disk(self, now: _dt.datetime) -> None:
        """Measure the output folder in the first minutes and estimate its growth."""
        card = self.card
        if not card.out or not self._disk_samples_due:
            return
        started = _cards.from_iso(card.started_at)
        if started is None:
            return
        minutes = (now - started).total_seconds() / 60
        if self._disk_start is not None and minutes < self._disk_samples_due[0]:
            return
        size = folder_size(Path(card.out))
        disk = self.probes.disk(Path(card.out))
        if size is None:
            card.estimates["disk"] = "The output folder has too many files to measure quickly."
            self._disk_samples_due = []
            return
        free = disk[2] if disk else None
        card.disk_samples.append({"at": _cards.to_iso(now), "bytes": size, "free": free})
        if self._disk_start is None:
            self._disk_start = (minutes, size)
            return
        self._disk_samples_due.pop(0)
        start_minutes, start_size = self._disk_start
        hours = max((minutes - start_minutes) / 60, 1e-6)
        rate = (size - start_size) / hours
        card.estimates["disk_growth_bytes_per_hour"] = rate
        card.estimates["disk_free_bytes"] = free
        card.estimates["disk_measured_minutes"] = round(minutes, 1)
        if rate > 0 and free is not None:
            card.estimates["hours_until_disk_full"] = free / rate
        else:
            card.estimates.pop("hours_until_disk_full", None)

    def check_exception(self, now: _dt.datetime) -> None:
        """Note once when an approved exception ends while the job still runs."""
        exception = self.card.exception
        if not exception or exception.get("ended_noted"):
            return
        if not _rl.exception_active(exception, now):
            exception["ended_noted"] = "yes"
            self.card.add_note(
                f"The exception ended at {exception.get('until')}. The job is still running "
                f"with {self.card.cores} cores and {len(self.card.gpus)} GPUs.",
                now,
            )

    def stop_child(self) -> int | None:
        """Stop the job: ask politely, then by force after a grace period."""
        pid = getattr(self.child, "pid", None)
        for sig, grace in ((signal.SIGTERM, STOP_GRACE_SECONDS), (signal.SIGKILL, 5)):
            try:
                if pid:
                    os.killpg(pid, sig)  # the job and anything it started
                else:
                    self.child.send_signal(sig)
            except OSError:
                pass
            try:
                return self.child.wait(timeout=grace)
            except subprocess.TimeoutExpired:
                continue
        return self.child.poll()

    def record_end(self, code: int | None) -> None:
        """Record how the job ended and post the notice."""
        card = self.card
        card.ended_at = _cards.to_iso(self.probes.now())
        card.exit_code = code
        if self.stop_requested:
            card.state = _cards.STATE_STOPPED
            card.add_note("Stopped by hand, or its tmux window was closed.")
        elif code == 0:
            card.state = _cards.STATE_FINISHED
        else:
            card.state = _cards.STATE_FAILED
            if code is not None and code < 0:
                number = -code
                try:
                    name = signal.Signals(number).name
                except ValueError:
                    name = f"signal {number}"
                hint = SIGNAL_HINTS.get(number, "")
                card.add_note(f"The job was ended by {name}. {hint}".strip())
        self.save()
        if card.state in (_cards.STATE_FINISHED, _cards.STATE_FAILED):
            self.notify()
            self.save()
        self._say(
            f"[murmurent] job {card.name} {card.state} after "
            f"{_cards.format_duration(card.duration_seconds())}"
            + (f", exit code {code}." if code is not None else ".")
        )

    def run(self) -> int:
        """Wait, run, follow and record. Returns the job's exit code (or 1)."""
        self.card.supervisor_pid = os.getpid()
        self.save()
        if not self.wait_until_ready():
            return 1
        if not self.start_child():
            return 1
        try:
            self.housekeeping()  # first stall and disk look, at the start
            code = self.follow()
        except Exception as exc:  # noqa: BLE001 - record rather than vanish
            self.card.add_note(f"The supervisor met an error while following the job: {exc}")
            code = self.child.wait() if self.child is not None else None
        self.record_end(code)
        return code if isinstance(code, int) and code >= 0 else 1


def load_environment(card_file: Path) -> dict[str, str]:
    """Read and delete the environment copy the launcher wrote for this job.

    Falls back to the supervisor's own environment when there is none, for
    example when a card is replayed by hand.
    """
    snapshot = card_file.with_name(card_file.stem + ".env.json")
    try:
        data = json.loads(snapshot.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return dict(os.environ)
    finally:
        snapshot.unlink(missing_ok=True)
    if not isinstance(data, dict):
        return dict(os.environ)
    return {str(k): str(v) for k, v in data.items()}


def main(argv: list[str] | None = None) -> int:
    """Entry point used inside tmux: ``python -m murmurent.core.run_supervisor <card>``."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m murmurent.core.run_supervisor <job card>", file=sys.stderr)
        return 2
    card_file = Path(args[0])
    base_env = load_environment(card_file)
    # Behave as if started from the person's own shell, so the lab's policy file,
    # the management repository and the Slack token resolve as they did at launch.
    os.environ.clear()
    os.environ.update(base_env)
    supervisor = Supervisor(card_file, base_env)
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, supervisor.request_stop)
    return supervisor.run()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
