"""
Purpose: `murmurent etiquette`: the server etiquette check (issue #151, step 4).
Author: Mike Hallett (with Claude Code)
Date: 2026-10-18
Input: the server's process list and GPU use; the lab's policy file.
Output: a report in the terminal; with --notify, Slack messages.

`check` reports by default and messages nobody: run it a few times and judge
the report before adding --notify. `schedule` runs it every weekday.
"""

from __future__ import annotations

import json

import click

from ..core import etiquette as _et


@click.group("etiquette", help="Check that lab members' jobs follow the lab's rules for "
             "priority, cores and GPUs, and tell them politely how to fix it.")
def etiquette_group() -> None:
    pass


@etiquette_group.command(
    "check",
    help="Look at the server now. Reports only, unless --notify: then the person gets "
         "a direct message, a repeat the next day goes to the lab channel, and after "
         "that to the PI. Never changes anyone's jobs; never reads command lines.")
@click.option("--notify", is_flag=True, help="Send the messages.")
@click.option("--json", "as_json", is_flag=True, help="Print the report as JSON.")
def etiquette_check(notify: bool, as_json: bool) -> None:
    report = _et.check()
    if as_json:
        click.echo(json.dumps(report, indent=2))
    else:
        for line in _et.describe(report):
            click.echo(line)
    if notify:
        for line in _et.notify(report):
            click.echo(f"  {line}")


@etiquette_group.command(
    "schedule",
    help="Run the check every weekday under your account (a systemd user timer).")
@click.option("--install", is_flag=True, help="Set it up.")
@click.option("--remove", "remove_it", is_flag=True, help="Remove it.")
@click.option("--at", "at", default="11:00", show_default=True, help="Time of day.")
@click.option("--notify", is_flag=True,
              help="Let the scheduled check send messages. Without it, it only writes "
                   "its report, which is the way to start.")
def etiquette_schedule(install: bool, remove_it: bool, at: str, notify: bool) -> None:
    if install == remove_it:
        raise click.UsageError("choose --install or --remove")
    try:
        lines = _et.install(at, notify_people=notify) if install else _et.remove()
    except (ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from exc
    except FileNotFoundError as exc:
        raise click.ClickException("This computer has no systemd, so the check cannot be "
                                   "scheduled here. Set it up on the lab's server.") from exc
    for line in lines:
        click.echo(line)
