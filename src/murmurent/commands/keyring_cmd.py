"""
Purpose: `murmurent keyring …` — Phase 1 CLI over :mod:`murmurent.core.keyring`.
Distributes shared centre secrets across a principal's machines via per-machine
age identities and multi-recipient age boxes committed to the lab_info repo.

Author: Mike Hallett (with Claude Code)
Date: 2026-07-28

Subcommands: init · authorize · set-secret · rotate-secret · revoke · sync ·
status · check. The reconcile-loop auto-sync is a later phase.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import click

from ..core import keyring as _kr
from ..core.registrar import lab_info_root


def _git_pull(warn_on_fail: bool = False) -> bool:
    """Best-effort `git pull --ff-only` of lab_info. Returns True when the tree is
    up to date afterwards (nothing to pull, no remote, or a clean fast-forward),
    False when it could not fast-forward. With ``warn_on_fail`` (the mutating
    commands), a False result prints a clear warning so the operator knows they
    may be editing stale state rather than silently proceeding."""
    root = lab_info_root()
    if not (root / ".git").exists():
        return True
    remotes = subprocess.run(["git", "-C", str(root), "remote"],
                             capture_output=True, text=True).stdout.strip()
    if not remotes:
        return True
    try:
        r = subprocess.run(["git", "-C", str(root), "pull", "--ff-only"],
                           capture_output=True, text=True, check=False)
    except OSError:
        if warn_on_fail:
            click.echo("  ! could not run git pull — you may be editing stale state.")
        return False
    out = (r.stdout + r.stderr).strip()
    if r.returncode == 0:
        if out and "Already up to date" not in out:
            click.echo(f"  (pulled lab_info: {out.splitlines()[-1]})")
        return True
    if warn_on_fail:
        click.echo("  ! could not fast-forward lab_info (it has diverged from the "
                   "remote). You may be editing STALE state — do a manual pull/rebase "
                   "before pushing.")
    return False


def _git_commit_push(message: str) -> None:
    """Stage .keyring, commit if anything changed, then push (if a remote exists).

    Commits only when there are staged .keyring changes — but ALWAYS attempts the
    push, so a commit that a previous run made but failed to push still goes out.
    Best-effort with clear messages; the target of the --push convenience flag."""
    root = lab_info_root()
    if not (root / ".git").exists():
        click.echo("  (lab_info has no git repo — commit skipped)")
        return
    subprocess.run(["git", "-C", str(root), "add", ".keyring"], check=False)
    # anything staged? (exit 1 from --quiet means "yes, there is a diff")
    has_staged = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--quiet"]).returncode != 0
    if has_staged:
        c = subprocess.run(["git", "-C", str(root), "commit", "-m", message],
                           capture_output=True, text=True)
        if c.returncode != 0:
            tail = (c.stderr or c.stdout).strip().splitlines()
            click.echo(f"  ! commit failed: {tail[-1] if tail else 'see git output'}")
            return
        click.echo("  ✓ committed")
    else:
        click.echo("  (no .keyring changes to commit)")
    remotes = subprocess.run(["git", "-C", str(root), "remote"],
                             capture_output=True, text=True).stdout.strip()
    if not remotes:
        return
    p = subprocess.run(["git", "-C", str(root), "push"], capture_output=True, text=True)
    if p.returncode == 0:
        click.echo("  ✓ pushed")
    else:
        tail = (p.stderr or "").strip().splitlines()
        click.echo(f"  ! push failed: {tail[-1] if tail else 'see git output'}")


def _report_checks(checks, healthy_word: str) -> None:
    """Print a list of core.keyring.Check and exit non-zero on any failure."""
    marks = {"ok": "✓", "warn": "!", "fail": "✗"}
    n_fail = sum(1 for c in checks if c.status == "fail")
    n_warn = sum(1 for c in checks if c.status == "warn")
    for c in checks:
        click.echo(f"  {marks[c.status]} {c.name}" + (f": {c.detail}" if c.detail else ""))
    verdict = "FAIL" if n_fail else ("OK with warnings" if n_warn else healthy_word)
    click.echo(f"\n  {len(checks)} checks · {n_fail} failed · {n_warn} warning(s)  →  {verdict}")
    if n_fail:
        raise click.exceptions.Exit(1)


@click.group(name="keyring",
             help="Share centre secrets across your machines (Phase 1 MVP): "
                  "per-machine age identities + encrypted boxes in lab_info.")
def keyring_group() -> None:
    ...


@keyring_group.command("init")
def init_cmd() -> None:
    """Create THIS machine's keyring identity and print its public recipient."""
    try:
        recipient = _kr.ensure_identity()
    except _kr.KeyringError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✓ keyring identity ready: {_kr.identity_path()}  (mode 0600, never leaves this machine)")
    click.echo("\npublic recipient — share this to be authorised (safe to send in the clear):")
    click.echo(f"    {recipient}")
    click.echo("\nThen, on a machine that is ALREADY authorised, run:")
    click.echo(f"    murmurent keyring authorize {recipient} --label <this-machine> --role mayor")


@keyring_group.command("authorize")
@click.argument("recipient")
@click.option("--label", required=True, help="A short name for the machine being authorised.")
@click.option("--role", type=click.Choice(_kr.VALID_ROLES), required=True,
              help="What the machine may open. 'mayor' gets everything; 'server' "
                   "gets only secrets whose consumers include 'server'.")
@click.option("--push", is_flag=True, help="Also commit + push lab_info.")
def authorize_cmd(recipient: str, label: str, role: str, push: bool) -> None:
    """Add a machine's public RECIPIENT to the roster and re-lock its boxes."""
    _git_pull(warn_on_fail=True)   # edit the latest roster; warn if we can't refresh
    try:
        res = _kr.authorize(recipient, label, role)
    except _kr.KeyringError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✓ authorised {label} ({role})")
    if res["relocked"]:
        click.echo("  re-locked so it can open: " + ", ".join(res["relocked"]))
    if res["skipped"]:
        click.echo("  ! skipped (this machine can't open them to re-lock): "
                   + ", ".join(res["skipped"]))
    if push:
        _git_commit_push(f"keyring: authorise {label} ({role})")
    else:
        click.echo("\n  Now commit + push lab_info so the machine can pull (or use --push):")
        click.echo(f"    git -C {lab_info_root()} add .keyring && git -C {lab_info_root()} commit -m 'keyring: authorise {label}' && git -C {lab_info_root()} push")


@keyring_group.command("set-secret")
@click.argument("name")
@click.option("--target", required=True, help="Where the secret unpacks on a machine, e.g. ~/.config/murmurent/slack-token")
@click.option("--mode", default="0600", show_default=True, help="File mode for the unpacked secret.")
@click.option("--consumers", required=True, help="Comma-separated roles that may open it, e.g. mayor,server")
@click.option("--file", "file_", type=click.Path(exists=True, dir_okay=False),
              default=None, help="Read the secret value from this file.")
@click.option("--value", default=None, help="The secret value inline (prefer --file or the prompt for real secrets).")
@click.option("--push", is_flag=True, help="Also commit + push lab_info.")
def set_secret_cmd(name: str, target: str, mode: str, consumers: str,
                   file_: str | None, value: str | None, push: bool) -> None:
    """Add/update a secret and lock it into a box for the given roles."""
    _git_pull(warn_on_fail=True)
    if file_:
        plaintext = Path(file_).read_text(encoding="utf-8")
    elif value is not None:
        plaintext = value
    else:
        plaintext = click.prompt("secret value", hide_input=True)
    roles = [r.strip() for r in consumers.split(",") if r.strip()]
    try:
        box = _kr.set_secret(name, plaintext, target=target, mode=mode, consumers=roles)
    except _kr.KeyringError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✓ secret '{name}' locked → {box}")
    click.echo(f"  opens for roles: {', '.join(roles)}  ·  unpacks to: {target}")
    if push:
        _git_commit_push(f"keyring: set secret {name}")
    else:
        click.echo("  remember to commit + push lab_info to share it (or use --push).")


@keyring_group.command("rotate-secret")
@click.argument("name")
@click.option("--file", "file_", type=click.Path(exists=True, dir_okay=False),
              default=None, help="Read the NEW value from this file.")
@click.option("--value", default=None, help="The new value inline (prefer --file / the prompt).")
@click.option("--push", is_flag=True, help="Also commit + push lab_info.")
def rotate_secret_cmd(name: str, file_: str | None, value: str | None, push: bool) -> None:
    """Replace an EXISTING secret's value and re-lock its box.

    Use after regenerating the real secret (e.g. a new Slack token) — this stores
    the new value you supply; it does not invent one."""
    _git_pull(warn_on_fail=True)
    if file_:
        plaintext = Path(file_).read_text(encoding="utf-8")
    elif value is not None:
        plaintext = value
    else:
        plaintext = click.prompt("new secret value", hide_input=True)
    try:
        box = _kr.rotate_secret(name, plaintext)
    except _kr.KeyringError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✓ rotated '{name}' — re-locked {box}")
    if push:
        _git_commit_push(f"keyring: rotate {name}")
    else:
        click.echo("  commit + push lab_info so machines pick up the new value (or use --push).")


@keyring_group.command("revoke")
@click.argument("label")
@click.option("--push", is_flag=True, help="Also commit + push lab_info.")
def revoke_cmd(label: str, push: bool) -> None:
    """Remove a machine from the roster and re-lock its boxes without it."""
    _git_pull(warn_on_fail=True)
    try:
        res = _kr.revoke(label)
    except _kr.KeyringError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(f"✓ revoked {res['label']} ({res['role']})")
    if res["relocked"]:
        click.echo("  re-locked without it: " + ", ".join(res["relocked"]))
    if res["skipped"]:
        click.echo("  ! could not re-lock here (rotation is what neutralises it): "
                   + ", ".join(res["skipped"]))
    if res["must_rotate"]:
        click.echo("\n  ⚠ git history is permanent — the removed machine can still read the OLD")
        click.echo("    values from history. ROTATE each of these now, with fresh values:")
        for n in res["must_rotate"]:
            click.echo(f"      murmurent keyring rotate-secret {n} --file <new-value> --push")
    if push:
        _git_commit_push(f"keyring: revoke {label}")
    else:
        click.echo("\n  commit + push lab_info to apply the revocation (or use --push).")


@keyring_group.command("sync")
@click.option("--apply", is_flag=True, help="Actually write the secrets (default: dry-run preview).")
@click.option("--no-pull", is_flag=True, help="Skip the git pull first.")
def sync_cmd(apply: bool, no_pull: bool) -> None:
    """Pull, then unpack every secret this machine is entitled to."""
    if not no_pull:
        _git_pull()
    try:
        items = _kr.sync(apply=apply)
    except _kr.KeyringError as exc:
        raise click.ClickException(str(exc)) from exc
    marks = {"write": "✓", "would-write": "~", "unchanged": "·",
             "mode-fixed": "✓", "would-fix-mode": "~",
             "skip-not-entitled": "–", "error": "✗"}
    if not items:
        click.echo("  (no secrets in the manifest yet)")
    for it in items:
        line = f"  {marks.get(it.action, '?')} {it.name}: {it.action}"
        if it.action in ("write", "would-write"):
            line += f" → {it.target}"
        if it.detail:
            line += f"  ({it.detail})"
        click.echo(line)
    if not apply and any(i.action.startswith("would-") for i in items):
        click.echo("\n(dry-run — re-run with --apply to write these)")


@keyring_group.command("status")
@click.option("--no-pull", is_flag=True, help="Skip the git pull; show the local roster as-is.")
def status_cmd(no_pull: bool) -> None:
    """Show this machine's identity, entitlements, and roster size.

    Pulls lab_info first (best-effort) so the roster reflects any authorisation a
    peer just pushed — otherwise a freshly-authorised machine would report itself
    as 'not authorised' until its next sync. ``--no-pull`` shows the local view."""
    if not no_pull:
        _git_pull()
    st = _kr.status()
    if not st["has_identity"]:
        click.echo("no keyring identity on this machine — run `murmurent keyring init`.")
        return
    click.echo(f"recipient:   {st['recipient']}")
    if st["authorized"]:
        click.echo(f"authorised:  yes  (label={st['label']}, role={st['role']})")
        click.echo(f"can open:    {', '.join(st['entitled']) or '(none)'}")
    else:
        click.echo("authorised:  NO — share the recipient above and have an existing machine authorise it.")
    click.echo(f"roster:      {st['machines']} machine(s), {st['total_secrets']} secret(s)")


@keyring_group.command("check")
@click.option("--no-pull", is_flag=True, help="Skip the git pull; check the local state only.")
def check_cmd(no_pull: bool) -> None:
    """Health-check this machine's keyring setup end to end.

    Verifies age, the machine identity, the roster/manifest, that every entitled
    secret opens and is unpacked, and — critically — that every NON-entitled box
    is refused. Exits non-zero if any check fails, so it works in CI / cron."""
    if not no_pull:
        _git_pull()
    _report_checks(_kr.health_check(), healthy_word="HEALTHY")


@keyring_group.command("verify")
@click.option("--no-pull", is_flag=True, help="Skip the git pull; verify the local .keyring only.")
def verify_cmd(no_pull: bool) -> None:
    """Verify the .keyring store's structural integrity — needs NO private key, so
    it runs in CI or on any machine (unlike `check`, which decrypts here).

    Confirms the roster and manifest are well-formed, every declared secret has a
    non-empty age box, and every box has at least one machine that can open it.
    Exits non-zero on any failure."""
    if not no_pull:
        _git_pull()
    _report_checks(_kr.verify_repo(), healthy_word="VALID")


__all__ = ["keyring_group"]
