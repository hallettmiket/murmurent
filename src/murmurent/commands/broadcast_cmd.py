"""
Purpose: ``murmurent broadcast`` — send a tier-tailored Slack message
         to the centre.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-26

Examples:

    # Dry-run (no send, no ledger write) — sanity-check the routing.
    murmurent broadcast --to leaders --message "Quarterly cores review Friday 2pm"

    # Actually send.
    murmurent broadcast --to leaders --message "Quarterly cores review Friday 2pm" --apply

    # List recent broadcasts (any month).
    murmurent broadcast recent --limit 5
"""

from __future__ import annotations

import click

from ..core import broadcasts as _bc


@click.group(name="broadcast",
              help="Centre-wide broadcasts to {everyone, pis, leaders, admin}.")
def broadcast() -> None:
    pass


@broadcast.command("send",
                    help="Send (or dry-run) a broadcast. Default is dry-run.")
@click.option("--to", "audience", required=True,
              type=click.Choice(list(_bc.VALID_AUDIENCES)),
              help="Audience: everyone | pis | leaders | admin.")
@click.option("--message", required=True,
              help="Message body. Wrap in single quotes if it has shell chars.")
@click.option("--sender", default="",
              help="@handle of the sender. Defaults to $WIGAMIG_USER.")
@click.option("--apply", is_flag=True, default=False,
              help="Actually send + log. Without this flag: dry-run only.")
@click.option("--tag", "tags", multiple=True,
              help="Repeatable; one tag per flag.")
def cmd_send(audience: str, message: str, sender: str,
              apply: bool, tags: tuple[str, ...]) -> None:
    import os
    if not sender:
        sender = os.environ.get("WIGAMIG_USER", "")
    if not sender:
        raise click.ClickException(
            "--sender not provided and $WIGAMIG_USER is unset.")
    try:
        cid = _bc.channel_id_for(audience)
    except _bc.BroadcastError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"audience: {audience}")
    click.echo(f"channel:  {cid}")
    click.echo(f"sender:   @{sender.lstrip('@')}")
    click.echo(f"message:")
    for line in message.splitlines() or [""]:
        click.echo(f"  | {line}")
    if not apply:
        click.echo("\n(dry-run) Pass --apply to actually send + log.")
        return
    try:
        b = _bc.send_broadcast(
            audience=audience, message=message, sender=sender,
            tags=list(tags),
        )
    except _bc.BroadcastError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"\nSent ✓")
    if b.message_link:
        click.echo(f"link: {b.message_link}")


@broadcast.command("recent",
                    help="List the most recent broadcasts (audit view).")
@click.option("--limit", default=20, type=int)
def cmd_recent(limit: int) -> None:
    rows = _bc.iter_recent(limit=limit)
    if not rows:
        click.echo("(no broadcasts yet)")
        return
    for b in rows:
        head = f"{b.iso_ts} · {b.audience} · @{b.sender}"
        click.echo(head)
        for line in b.message.splitlines():
            click.echo(f"  | {line}")
        if b.message_link:
            click.echo(f"  link: {b.message_link}")
        click.echo("")
