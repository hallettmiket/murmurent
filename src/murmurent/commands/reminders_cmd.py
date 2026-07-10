"""
Purpose: ``murmurent core-remind`` — scan all cores for booked slots
         entering the 24h or 1h reminder window and post Slack pings.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22

Designed to be invoked every ~15 minutes from a CC ``/routine``:

    /routine create wigamig-core-reminders
      prompt: |
        Run `murmurent core-remind --apply` and post the one-line summary
        line of its stdout to #claude-test if any reminders fired.
      schedule: every 15 minutes

Idempotent: each (request_id, window) pair is recorded in
``~/.wigamig/cores/<core>/reminders_sent.json`` after a successful
send, so re-running the same scanner cycle won't double-ping.
"""

from __future__ import annotations

import click

from ..core import reminders as _rem


@click.command(
    "core-remind",
    help="Scan + send service-booking reminders (24h / 1h).",
)
@click.option("--apply", is_flag=True, default=False,
              help="Send Slack pings + record. Without this flag: dry-run.")
@click.option("--core", default="", help="Limit to a single core.")
def core_remind(apply: bool, core: str) -> None:
    """Walk scheduled requests; ping anyone whose slot is 24h or 1h out."""
    from ..dashboard import slack_notify as _notify
    due = _rem.scan_due_reminders()
    if core:
        due = [d for d in due if d.core == core]
    if not due:
        click.echo("No reminders due.")
        return
    sent = 0
    for d in due:
        click.echo(
            f"[{d.window}] {d.core}/{d.request.request_id} "
            f"{d.request.requester} → {d.request.service} "
            f"in ~{d.minutes_until} min"
        )
        if apply:
            try:
                _notify.core_request_reminder(
                    core=d.core, request_id=d.request.request_id,
                    requester=d.request.requester,
                    service=d.request.service,
                    start=d.request.booked_slot.start,
                    window=d.window,
                    minutes_until=d.minutes_until,
                )
                _rem.record_sent(d.core, d.request.request_id, d.window)
                sent += 1
            except Exception as exc:  # noqa: BLE001
                click.echo(f"  ! send failed: {exc}", err=True)
    if apply:
        click.echo(f"Sent {sent} reminder(s).")
    else:
        click.echo(f"(dry-run) {len(due)} reminder(s) would have been sent. "
                   "Pass --apply to fire.")
