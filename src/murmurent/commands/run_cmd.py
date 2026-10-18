"""
Purpose: ``murmurent run`` (start a long job the polite way) and ``murmurent
         jobs`` (what is running, how long, and how it went), in plain English.
Author:  Mike Hallett (with Claude Code)
Date:    2026-10-16
Input:   The command line; the job cards under ``~/.murmurent/runs/``.
Output:  A job started in tmux, or text describing jobs.

Issue #151, step 1. The logic lives in ``core/run_launcher.py``,
``core/run_supervisor.py`` and ``core/run_cards.py``; this file only reads
options and prints.
"""

from __future__ import annotations

import datetime as _dt
import os
import signal
from pathlib import Path

import click

from ..core import run_cards as _cards
from ..core import run_launcher as _rl
from ..core.millwright_policy import describe_policy, load_policy

RECENT_DAYS = 7
RECENT_LIMIT = 10


def _launch_or_fail(options: _rl.LaunchOptions) -> None:
    try:
        result = _rl.launch(options)
    except _rl.LaunchError as exc:
        raise click.ClickException(str(exc)) from exc
    for line in result.lines:
        click.echo(line)


@click.command(
    "run",
    context_settings={"allow_interspersed_args": False},
    help="Start a long job inside tmux, so a dropped connection does not stop it. "
    "It runs at low priority with thread limits set, on cores and GPUs chosen "
    "from the lab's rules and how busy the server is, and keeps a job card you "
    "can read with `murmurent jobs`. Put the command after --, for example: "
    "murmurent run --cores 8 --out results/ -- Rscript fit.R",
)
@click.option(
    "--name",
    default="",
    help="A short name for the job, used in Slack. "
    "Letters, digits, spaces, dots, dashes; no slashes. Default: its id.",
)
@click.option(
    "--cores",
    type=int,
    default=None,
    help="Cores the job may use. Also sets the thread limits. Default: the "
    "lab's default (usually 1).",
)
@click.option(
    "--gpus",
    type=int,
    default=0,
    show_default=True,
    help="GPUs the job needs. The least busy ones are chosen.",
)
@click.option(
    "--memory",
    default="",
    help="Memory the job expects to use, such as 64G. "
    "Checked against free memory and the lab's allowance.",
)
@click.option(
    "--out",
    default="",
    help="The folder the job writes to. Its free space "
    "is checked, and its growth gives a disk estimate.",
)
@click.option(
    "--input",
    "inputs",
    multiple=True,
    metavar="PATH",
    help="A file or folder the job reads. Repeat for more than one. Recorded so "
    "the space scan can tell later whether the job's output could be made again.",
)
@click.option(
    "--expect-disk",
    default="",
    help="How much the job expects to write, "
    "such as 500G. The job is refused if it would not fit.",
)
@click.option(
    "--log",
    default="",
    help="Where to save the job's output. " "Default: ~/.murmurent/runs/<id>.log",
)
@click.option(
    "--watch",
    default="",
    help="A file whose growth shows the job is " "progressing, if not its log.",
)
@click.option(
    "--stall-after",
    type=int,
    default=None,
    help="Minutes without new output before the job is reported as stalled. "
    "Default: the lab's setting.",
)
@click.option("--at", "at", default="", help="Start later: 22:00, or 2026-10-17 22:00.")
@click.option(
    "--when-load-below",
    type=float,
    default=None,
    help="Start once the server's load falls below this number.",
)
@click.option(
    "--wait",
    is_flag=True,
    default=False,
    help="If the server is too busy now, wait for room instead of refusing.",
)
@click.option(
    "--exception",
    default="",
    help="Why this job needs more than the lab's "
    "allowance. Ask in the server channel first. Needs --until.",
)
@click.option("--until", default="", help="When the exception ends: 23:00, or " "2026-10-17 08:00.")
@click.option(
    "--session",
    default="",
    help="Put the job in a new window of this tmux " "session instead of a session of its own.",
)
@click.option(
    "--pass-env",
    "pass_env",
    multiple=True,
    metavar="NAME",
    help="Give the job this environment variable even though its name looks like a "
    "secret (a token, password or key). Repeat for more than one.",
)
@click.option(
    "--no-notify", is_flag=True, default=False, help="Do not post to the project's Slack channel."
)
@click.option(
    "--dry-run", is_flag=True, default=False, help="Show what would be chosen, and start nothing."
)
@click.argument("command", nargs=-1, required=True, type=click.UNPROCESSED)
def run_command(
    name: str,
    cores: int | None,
    gpus: int,
    memory: str,
    out: str,
    inputs: tuple[str, ...],
    expect_disk: str,
    log: str,
    watch: str,
    stall_after: int | None,
    at: str,
    when_load_below: float | None,
    wait: bool,
    exception: str,
    until: str,
    session: str,
    pass_env: tuple[str, ...],
    no_notify: bool,
    dry_run: bool,
    command: tuple[str, ...],
) -> None:
    """Start ``command`` under the run launcher."""
    options = _rl.LaunchOptions(
        command=list(command),
        workdir=Path.cwd(),
        name=name,
        cores=cores,
        gpus=gpus,
        memory=memory,
        out=out,
        inputs=tuple(inputs),
        expect_disk=expect_disk,
        log=log,
        watch=watch,
        stall_after=stall_after,
        at=at,
        when_load_below=when_load_below,
        wait=wait,
        exception=exception,
        until=until,
        session=session,
        pass_env=tuple(pass_env),
        notify=not no_notify,
        dry_run=dry_run,
    )
    _launch_or_fail(options)


# ---------------------------------------------------------------------------
# Describing jobs
# ---------------------------------------------------------------------------


def _label(card: _cards.JobCard) -> str:
    return card.id if card.name == card.id else f"{card.name} [{card.id}]"


def _resources(card: _cards.JobCard) -> str:
    text = f"{card.cores} core{'s' if card.cores != 1 else ''}"
    if card.gpus:
        text += f" and GPU{'s' if len(card.gpus) > 1 else ''} " + ", ".join(map(str, card.gpus))
    return text


def _clock(moment: _dt.datetime | None, now: _dt.datetime) -> str:
    if moment is None:
        return "an unknown time"
    return f"{moment:%H:%M}" if moment.date() == now.date() else f"{moment:%Y-%m-%d %H:%M}"


def estimate_lines(card: _cards.JobCard, now: _dt.datetime) -> list[str]:
    """Plain-English estimate lines for a running job, each labelled as an estimate."""
    lines = []
    estimate = card.estimates.get("duration_seconds")
    elapsed = card.duration_seconds(now) or 0.0
    remaining = None
    if estimate:
        runs = card.estimates.get("duration_runs", 0)
        if elapsed < estimate:
            remaining = estimate - elapsed
            finish = now + _dt.timedelta(seconds=remaining)
            left = _cards.about(remaining)
            lines.append(
                f"{left[0].upper()}{left[1:]} left, finishing around "
                f"{_clock(finish, now)} (an estimate from {runs} earlier run(s))."
            )
        else:
            lines.append(
                f"It has run longer than its earlier runs, which took " f"{_cards.about(estimate)}."
            )
    else:
        lines.append(
            "No time estimate yet: there is no earlier finished run of this "
            "command in this folder."
        )
    rate = card.estimates.get("disk_growth_bytes_per_hour")
    hours_left = card.estimates.get("hours_until_disk_full")
    if isinstance(card.estimates.get("disk"), str):
        lines.append(card.estimates["disk"])
    elif rate is not None and rate > 0:
        line = (
            f"Writing about {_cards.format_size(rate)} an hour to its output folder "
            f"(an estimate from its first {card.estimates.get('disk_measured_minutes')} min)."
        )
        if hours_left is not None:
            line += f" At that rate the disk is full in {_cards.about(hours_left * 3600)}."
            if remaining is not None and hours_left * 3600 < remaining:
                line += " The disk may fill before the job finishes."
        lines.append(line)
    return lines


def card_line(card: _cards.JobCard, now: _dt.datetime) -> list[str]:
    """One job in a sentence or two, for ``murmurent jobs``."""
    label = _label(card)
    elapsed = _cards.format_duration(card.duration_seconds(now))
    ended = _cards.from_iso(card.ended_at)
    if card.state == _cards.STATE_WAITING:
        return [f"{label}: waiting for {card.waiting_for or 'its start'}."]
    if card.state == _cards.STATE_RUNNING:
        head = f"{label}: running for {elapsed} on {_resources(card)}."
        return [head] + [f"    {line}" for line in estimate_lines(card, now)]
    if card.state == _cards.STATE_STALLED:
        last = _cards.from_iso(card.last_output_at)
        quiet = _cards.format_duration((now - last).total_seconds()) if last else "a while"
        return [
            f"{label}: may be stuck. No new output for {quiet}; running for {elapsed}. "
            f"Look at its log: {card.log}"
        ]
    if card.state == _cards.STATE_FINISHED:
        return [
            f"{label}: finished at {_clock(ended, now)} after {elapsed} "
            f"(exit code {card.exit_code})."
        ]
    if card.state == _cards.STATE_FAILED:
        code = "unknown" if card.exit_code is None else card.exit_code
        reason = card.notes[-1]["text"] if card.notes else ""
        line = f"{label}: failed at {_clock(ended, now)} after {elapsed} (exit code {code})."
        return [line] + ([f"    {reason}"] if reason else []) + [f"    Log: {card.log}"]
    if card.state == _cards.STATE_STOPPED:
        return [f"{label}: stopped at {_clock(ended, now)} after {elapsed}."]
    return [f"{label}: {card.state}."]


def card_detail(card: _cards.JobCard, now: _dt.datetime) -> list[str]:
    """Everything on a card, for ``murmurent jobs show``."""
    started = _cards.from_iso(card.started_at)
    requested = card.requested or {}
    lines = [f"Job {_label(card)}"]
    state = card.state
    if card.state == _cards.STATE_WAITING:
        state += f", for {card.waiting_for or 'its start'}"
    elif started:
        duration = _cards.format_duration(card.duration_seconds(now))
        ended = _cards.from_iso(card.ended_at)
        if ended:
            state += f" at {ended:%Y-%m-%d %H:%M}, after {duration} (started {started:%H:%M})"
        else:
            state += f" for {duration}, since {started:%Y-%m-%d %H:%M}"
    lines.append(f"  State: {state}")
    if card.exit_code is not None:
        lines.append(f"  Exit code: {card.exit_code}")
    lines.append(f"  Project: {card.project or 'none found'}")
    lines.append(f"  Command: {' '.join(card.command)}")
    lines.append(f"  Folder: {card.workdir}")
    lines.append(f"  Log: {card.log}")
    if card.watch != card.log:
        lines.append(f"  Watched for progress: {card.watch}")
    if card.out:
        lines.append(f"  Output folder: {card.out}")
    for path in card.inputs or ():
        lines.append(f"  Input: {path}")
    asked = requested.get("cores")
    if card.cores:
        lines.append(f"  Cores: {card.cores}" + (f" (asked for {asked})" if asked else ""))
    if card.gpus or requested.get("gpus"):
        lines.append(
            f"  GPUs: {', '.join(map(str, card.gpus)) or 'none yet'}"
            f" (asked for {requested.get('gpus')})"
        )
    if requested.get("memory_bytes"):
        lines.append(f"  Memory stated: {_cards.format_size(requested['memory_bytes'])}")
    lines.append(f"  Priority: nice {card.priority}")
    if card.env_set:
        lines.append(
            "  Set for the job: "
            + ", ".join(f"{k}={v if v else '(none)'}" for k, v in sorted(card.env_set.items()))
        )
    if card.exception:
        lines.append(
            f"  Exception: until {card.exception.get('until')}, because "
            f"{card.exception.get('reason')}"
        )
    if card.state in (_cards.STATE_RUNNING, _cards.STATE_STALLED):
        lines.extend(f"  {line}" for line in estimate_lines(card, now))
    if requested.get("expect_disk_bytes"):
        lines.append(
            f"  Expected output (stated): " f"{_cards.format_size(requested['expect_disk_bytes'])}"
        )
    lines.append("  Slack: " + _slack_text(card))
    if card.state in _cards.ACTIVE_STATES:
        lines.append(f"  Watch it live: tmux attach -t {card.tmux_session}")
    if card.restarted_from:
        lines.append(f"  Restart of: {card.restarted_from}")
    if card.notes:
        lines.append("  Notes:")
        for note in card.notes:
            when = _cards.from_iso(note.get("at"))
            stamp = f"{when:%Y-%m-%d %H:%M}" if when else ""
            lines.append(f"    {stamp}  {note.get('text', '')}")
    return lines


def _slack_text(card: _cards.JobCard) -> str:
    notify = card.notify or {}
    if not notify.get("enabled"):
        return "notices are off for this job."
    posted = [p for p in notify.get("posted", []) if p.get("ok")]
    if posted:
        return "posted when it " + ", then ".join(p.get("state", "") for p in posted) + "."
    if notify.get("skipped"):
        return f"nothing posted: {notify['skipped']}."
    if not notify.get("channel"):
        return f"nothing will be posted: {notify.get('reason') or 'no channel is known'}."
    return "one line goes to the project's channel when it finishes, fails or stalls."


# ---------------------------------------------------------------------------
# murmurent jobs
# ---------------------------------------------------------------------------


@click.group(
    "jobs",
    invoke_without_command=True,
    help="Your jobs started with `murmurent run`: what is running, for how "
    "long, when it should finish, and how earlier jobs ended.",
)
@click.option(
    "--all",
    "show_all",
    is_flag=True,
    default=False,
    help="List every job, not only active and recent ones.",
)
@click.pass_context
def jobs_group(ctx: click.Context, show_all: bool) -> None:
    """List this person's jobs when no subcommand is given."""
    if ctx.invoked_subcommand is not None:
        return
    now = _cards.now_local()
    cards = _cards.mark_lost_cards(_cards.list_cards())
    active = [c for c in cards if c.state in _cards.ACTIVE_STATES]
    ended = [c for c in cards if c.state not in _cards.ACTIVE_STATES]
    if not show_all:
        cutoff = now - _dt.timedelta(days=RECENT_DAYS)
        ended = [
            c for c in ended if (_cards.from_iso(c.ended_at or c.created_at) or now) >= cutoff
        ][:RECENT_LIMIT]
    if not active and not ended:
        click.echo(
            "You have no jobs started with `murmurent run`"
            + ("." if show_all else f" in the last {RECENT_DAYS} days.")
        )
        return
    if active:
        click.echo("Now:")
        for card in sorted(active, key=lambda c: c.created_at or c.id):
            for line in card_line(card, now):
                click.echo(f"  {line}")
    if ended:
        click.echo("Ended:" if show_all else f"Ended in the last {RECENT_DAYS} days:")
        for card in ended:
            for line in card_line(card, now):
                click.echo(f"  {line}")
    click.echo("Details of one job: murmurent jobs show <id or name>")


def _find_or_fail(key: str) -> _cards.JobCard:
    card = _cards.find_card(key)
    if card is None:
        raise click.ClickException(f"No job matches '{key}'. `murmurent jobs --all` lists them.")
    _cards.mark_lost_cards([card])
    return card


@jobs_group.command("show", help="Everything recorded about one job.")
@click.argument("job")
def jobs_show(job: str) -> None:
    """Print one card in full."""
    card = _find_or_fail(job)
    for line in card_detail(card, _cards.now_local()):
        click.echo(line)


@jobs_group.command(
    "restart",
    help="Run a job again from its card, with the same "
    "command, folder and requests. Cores and GPUs are chosen afresh.",
)
@click.argument("job")
@click.option(
    "--wait",
    is_flag=True,
    default=False,
    help="If the server is too busy now, wait for room instead of refusing.",
)
def jobs_restart(job: str, wait: bool) -> None:
    """Relaunch a job from its card."""
    card = _find_or_fail(job)
    if card.state in _cards.ACTIVE_STATES:
        raise click.ClickException(
            f"Job {_label(card)} is still {card.state}. Stop it first: "
            f"murmurent jobs stop {card.id}"
        )
    if not Path(card.workdir).is_dir():
        raise click.ClickException(f"The job's folder no longer exists: {card.workdir}")
    _launch_or_fail(_rl.restart_options(card, wait=wait))


@jobs_group.command(
    "stop",
    help="Stop a running or waiting job. It is asked to end "
    "cleanly first, and stopped by force 30 seconds later.",
)
@click.argument("job")
def jobs_stop(job: str) -> None:
    """Ask a job's supervisor to stop it."""
    card = _find_or_fail(job)
    if card.state not in _cards.ACTIVE_STATES:
        click.echo(f"Job {_label(card)} is not running; it {card.state}.")
        return
    alive = _cards.supervisor_alive(card)
    if alive is None and card.host != _cards.this_host():
        raise click.ClickException(
            f"Job {_label(card)} runs on {card.host}. " "Stop it from there."
        )
    if not card.supervisor_pid:
        raise click.ClickException("The job is still starting. Try again in a moment.")
    try:
        os.kill(card.supervisor_pid, signal.SIGTERM)
    except ProcessLookupError:
        _cards.mark_lost_cards([card])
        click.echo(f"Job {_label(card)} had already stopped.")
        return
    click.echo(
        f"Asked job {_label(card)} to stop. `murmurent jobs show {card.id}` " "shows when it has."
    )


@jobs_group.command(
    "policy", help="The lab's rules the launcher follows, and the " "files they come from."
)
@click.option("--init", "init", is_flag=True,
              help="Create the lab's policy file from the commented template, if the lab "
                   "has none (never overwrites one).")
def jobs_policy(init: bool) -> None:
    """Print the policy in force; with --init, create the lab's file first."""
    if init:
        from ..core.millwright_policy import write_default_policy
        path, created = write_default_policy()
        if path is None:
            raise click.ClickException("the lab records repository was not found on this machine.")
        click.echo(f"Created {path} from the template. Edit the numbers to suit your lab, "
                   "then commit and push the lab records repository." if created
                   else f"The lab already has a policy file: {path}")
    for line in describe_policy(load_policy()):
        click.echo(line)


__all__ = ["card_detail", "card_line", "estimate_lines", "jobs_group", "run_command"]
