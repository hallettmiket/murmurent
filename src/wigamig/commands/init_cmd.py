"""
Purpose: ``wigamig init`` — the one-time, post-install session setup. Everyone
(member, PI, or mayor) runs this after installing wigamig. It mints your identity
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
    "1": ("member", "Member  — you work in a lab/core that already uses wigamig"),
    "2": ("pi", "PI      — you lead a lab or core"),
    "3": ("mayor", "Mayor   — you're setting up wigamig for a whole institution"),
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
        click.echo("`wigamig init` is interactive — run it in a terminal. "
                   "(It picks your role and sets your session info.)")
        return

    click.echo("Welcome to wigamig. Let's set up your session.\n")

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

    # 4. Contact info (everyone).
    name = click.prompt("Your full name", default="")
    email = click.prompt("Your email", default="")
    profile = {"handle": f"@{handle}", "role": role, "name": name, "email": email}

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
        click.echo("  • Import it:  wigamig import-card <file> --trust-root <centre-signing-key>")
    elif role == "pi":
        click.echo("  • Register your lab with your institution's mayor: find your "
                   "institution at")
        click.echo("    https://github.com/hallettmiket/wigamig_public and run its "
                   "wigamig-join.sh.")
        click.echo("  • Once you have your PI ID, issue member IDs with:  "
                   "wigamig issue-member-card")
    else:  # mayor
        click.echo("  • Bootstrap your centre — the dashboard has a one-time setup form:")
        click.echo("      wigamig dashboard --hifi --port 8771   → http://localhost:8771/registrar")
        click.echo("    …or headless:  wigamig centre-init --mayor @%s --name … --institution …"
                   % handle)
        click.echo("  • Full mayor setup: the README's \"Setting up a centre\" section.")

    click.echo("\nDone. Re-run `wigamig init` any time to change your role or info.")


@click.command("init", help="One-time setup: pick your role (member / PI / mayor) "
                            "and set your session info. Run this once after installing.")
def init_command() -> None:
    run_init()
