"""
Purpose: ``murmurent init`` — the one-time, post-install session setup. Everyone
(member, PI, or mayor) runs this after installing murmurent. It mints your identity
key if needed, saves who you are, asks your role, collects the relevant info, and
prints your next steps. It does NOT grant any privileges — being a registrar
still requires a real centre; picking "mayor" here only routes you to
``centre-init``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
import yaml

ROLES = {
    "1": ("member", "Member  — you work in a lab/core that already uses murmurent"),
    "2": ("pi", "PI      — you lead a lab or core"),
    "3": ("mayor", "Mayor   — you're setting up murmurent for a whole institution"),
}


def _home() -> Path:
    return Path(os.environ.get("WIGAMIG_HOME", str(Path.home() / ".wigamig")))


def profile_path() -> Path:
    return _home() / "profile.yaml"


def run_init() -> None:
    from ..core import idkeys as _k
    from ..core import identity as _id
    from ..core import identity_bootstrap as _ib

    home = _home()
    home.mkdir(parents=True, exist_ok=True)

    if not sys.stdin.isatty():
        click.echo("`murmurent init` is interactive — run it in a terminal. "
                   "(It picks your role and sets your session info.)")
        return

    click.echo("Welcome to murmurent. Let's set up your session.\n")

    # 1. Identity key — your unique ID (idempotent; auto-minted on first run).
    fp = _ib.ensure_local_keypair() or _k.local_fingerprint()
    click.echo(f"✓ your identity key (unique ID): {fp}\n")

    # 2. Handle.
    ident = _id.resolve(allow_unknown=True)
    default_handle = ident.handle if ident.source != "unknown" else ""
    handle = click.prompt("Your handle (username)", default=default_handle).strip().lstrip("@")
    (home / "user").write_text(handle + "\n", encoding="utf-8")

    # 3. Role.
    click.echo("\nWhat is your role?")
    for k, (_v, label) in ROLES.items():
        click.echo(f"  {k}. {label}")
    choice = click.prompt("Choose", type=click.Choice(list(ROLES)), default="1")
    role = ROLES[choice][0]

    # 4. Contact info (everyone). Email + GitHub are the join keys for the lab's
    # Slack channel + GitHub repo, so they travel with your enrollment.
    name = click.prompt("Your full name", default="")
    email = click.prompt("Your email", default="")
    github = click.prompt("Your GitHub username (optional)", default="").strip().lstrip("@")
    profile = {"handle": f"@{handle}", "role": role, "name": name, "email": email,
               "github": github}

    # 5. Role-specific info.
    if role == "pi":
        profile["group"] = click.prompt(
            "Your lab or core short name (e.g. hallett_lab)", default="")

    profile_path().write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
    click.echo(f"\n✓ saved your profile to {profile_path()}")

    # 6. Next steps, per role.
    click.echo("\nNext steps:")
    if role == "member":
        click.echo("  • Ask your PI for a membership ID (a signed certificate).")
        click.echo("  • Import it:  murmurent import-card <file> --trust-root <centre-signing-key>")
    elif role == "pi":
        group = profile.get("group") or ""
        # Self-issue the PI's own PI ID now — a lab can run standalone, no mayor
        # needed. The PI becomes their group's root and can issue member IDs
        # immediately.
        if group and click.confirm(
                f"Generate your PI ID for '{group}' now, so you can issue member "
                "IDs? (No mayor needed — you'll be your lab's root.)", default=True):
            from ..core import issuance as _iss
            try:
                out = _iss.self_issue_pi_card(f"@{handle}", group)
                click.echo(f"  ✓ PI ID ready. Give members this trust root:\n"
                           f"      {out['trust_root']}")
                click.echo(f"  • Issue a member ID:  murmurent issue-member-card "
                           f"<their-request> --group {group}")
            except _iss.IssuanceError as exc:
                click.echo(f"  ! could not self-issue PI ID: {exc}")
        else:
            click.echo("  • Self-issue your PI ID any time:  murmurent pi-init <lab-name>")
        click.echo("  • Optional — to join a centre, register with its mayor "
                   "(https://github.com/hallettmiket/murmurent_public → murmurent-join.sh). "
                   "That's a SEPARATE, centre-level PI ID; your members keep working.")
    else:  # mayor
        click.echo("  • Bootstrap your centre — the dashboard has a one-time setup form:")
        click.echo("      murmurent dashboard --hifi --port 8771   → http://localhost:8771/registrar")
        click.echo("    …or headless:  murmurent centre-init --mayor @%s --name … --institution …"
                   % handle)
        click.echo("  • Full mayor setup: the README's \"Setting up a centre\" section.")

    click.echo("\nDone. Re-run `murmurent init` any time to change your role or info.")


@click.command("init", help="One-time setup: pick your role (member / PI / mayor) "
                            "and set your session info. Run this once after installing.")
def init_command() -> None:
    run_init()
