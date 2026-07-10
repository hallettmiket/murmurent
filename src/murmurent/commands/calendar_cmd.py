"""
Purpose: ``murmurent core-calendar-auth`` — one-time Google Calendar OAuth
         flow for a core leader. Opens browser, persists refresh token.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22

Run by the core leader once per machine that hosts the dashboard:

  $ murmurent core-calendar-auth --core biocore

Prereq: drop the OAuth client_secret.json (type=Desktop) at
  ~/.wigamig/cores/<core>/google_oauth_client.json
The command prints the file location of the persisted refresh token on
success, or a CalendarError-derived message on failure.
"""

from __future__ import annotations

import click

from ..core.calendar_google import (
    CalendarError,
    creds_path,
    is_connected,
    oauth_client_path,
    run_oauth_flow,
)


@click.command(
    "core-calendar-auth",
    help="One-time Google Calendar OAuth for a core leader's calendar.",
)
@click.option("--core", required=True, help="Core name (e.g. biocore).")
@click.option(
    "--force", is_flag=True, default=False,
    help="Re-run OAuth even when a refresh token already exists.",
)
def core_calendar_auth(core: str, force: bool) -> None:
    """Walk Gary (or whichever core leader) through the InstalledAppFlow
    and persist a refresh token. Idempotent; pass --force to overwrite
    an existing token."""
    cp = oauth_client_path(core)
    if not cp.is_file():
        click.echo(
            f"ERROR: missing OAuth client secret at {cp}\n"
            "  1. Open Google Cloud Console -> APIs & Services -> Credentials\n"
            "  2. Create an OAuth 2.0 Client ID (Application type: Desktop)\n"
            "  3. Download the JSON, save it to the path above\n"
            "  4. Re-run this command.",
            err=True,
        )
        raise click.exceptions.Exit(2)
    if is_connected(core) and not force:
        click.echo(
            f"Already connected: {creds_path(core)}\n"
            "(Pass --force to re-run the OAuth flow.)"
        )
        return
    try:
        out = run_oauth_flow(core)
    except CalendarError as exc:
        click.echo(f"ERROR: {exc}", err=True)
        raise click.exceptions.Exit(1)
    click.echo(f"Calendar connected for core={core!r}: {out}")
