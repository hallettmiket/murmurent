"""
Purpose: CLI handlers for ``murmurent repo {list, status, adopt, upgrade}``.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-14 (readiness split 2026-07-15)
Input: Arguments from the click subcommand layer.
Output: Stdout tables/ladders + (for adopt/upgrade) the same side
        effects as the dashboard's Repos-panel buttons.

Terminology: adopting a repo makes it **murmurent-ready** (readiness
marker + commons agent symlinks) — it does NOT create a project. A
project is a set of repos + members, made via the New Project flow.
``upgrade`` re-runs the bootstrap against the current murmurent release
(new commons agents, marker schema) and stamps the marker on a legacy
CHARTER.md bootstrap, preserving the CHARTER.md (issue #28).
"""

from __future__ import annotations

from pathlib import Path

import click

from ..core import adopt as _adopt
from ..core import hosts as _hosts
from ..core import repo_inventory as _inv

# Verdict → what the reader sees. The internal verdict names are unchanged
# (the dashboard and adopt.py share them); only the wording differs, because
# the words are read by researchers rather than by git users. "• clone" in
# particular said nothing about what to do next: it is git's word for "a
# folder under version control", and the thing the reader needs to know is
# that murmurent has not set it up yet.
_GLYPH = {
    "ready": "✓ ready",
    "partial": "± half set up",
    "plain clone": "• not set up yet",
    "not a git repo": "✗ not tracked by git",
    "missing": "✗ no such folder",
}


def _looks_like_path(target: str) -> bool:
    return target.startswith(("/", "~", ".")) or "/" in target


def _clone_verdict(clone: _inv.RepoOnHost) -> str:
    if clone.has_marker and clone.has_claude_dir:
        return "ready"
    if clone.has_marker or clone.has_claude_dir:
        return "partial"
    return "plain clone"


def cmd_list(host_filter: str | None) -> int:
    """Print every clone on THIS machine, with its readiness verdict.

    Issue #94: the cross-machine SSH scan is retired — this lists the local
    machine only. Remote (``ssh``-kind) hosts in a pre-existing ``hosts.yaml``
    are skipped; to see another machine's repos, open its own dashboard
    (see ``docs/remote_dashboard.md``)."""
    registry = _hosts.read()
    if host_filter:
        if host_filter not in registry:
            raise click.ClickException(
                f"unknown host {host_filter!r} — see `murmurent host list`"
            )
        if registry[host_filter].is_remote():
            raise click.ClickException(
                f"host {host_filter!r} is a remote machine — the cross-machine "
                "repo scan is retired (issue #94). Open its own dashboard "
                "instead (see docs/remote_dashboard.md)."
            )
        registry = {host_filter: registry[host_filter]}

    for name, host in registry.items():
        if host.is_remote():
            continue   # local-only inventory (issue #94)
        click.echo(f"{name}  (this machine)")
        clones, err = _inv.list_machine_repos(name)
        if err:
            click.echo(f"  ! scan failed: {err}")
            continue
        if not clones:
            dirs = ", ".join(_inv._effective_scan_dirs(host))
            click.echo(f"  (no git repos under {dirs})")
            continue
        name_w = max(len(Path(c.path).name) for c in clones) + 1
        for c in sorted(clones, key=lambda c: Path(c.path).name.lower()):
            verdict = _GLYPH[_clone_verdict(c)]
            click.echo(f"  {Path(c.path).name:<{name_w}} {verdict:<14} {c.path}")
    return 0


def _print_status(st: _adopt.AdoptionStatus) -> None:
    mark = lambda b: "✓" if b else "—"  # noqa: E731
    click.echo(f"{st.host}:{st.path}")
    click.echo(f"  verdict:          {_GLYPH.get(st.verdict, st.verdict)}")
    click.echo(f"  git working tree  {mark(st.is_git)}")
    click.echo(f"  readiness marker  {mark(st.has_marker)}"
               + ("  (legacy CHARTER.md — run `murmurent repo upgrade`)"
                  if st.legacy_charter and not st.has_marker else ""))
    click.echo(f"  .claude/agents/   {mark(st.has_claude_agents)}")
    if st.bootstrap_version:
        click.echo(f"  bootstrapped by   murmurent {st.bootstrap_version}")
    _print_follows(Path(st.path))


def _print_follows(repo: Path) -> None:
    """Name the commons this repo's agent links actually resolve to.

    Shown because it was previously discoverable only by running ``readlink``
    on a link by hand. A machine can hold more than one murmurent clone, and
    which one a repo follows decides whether an edit to an agent is visible in
    it — so the answer belongs in the status output rather than in a developer's
    memory. A repo linked to a clone other than the one now installed is
    flagged, not silently reported: that is the state that makes an edit appear
    to do nothing.
    """
    from ..core.commons import commons_root

    links = sorted((repo / ".claude" / "agents").glob("*.md")) \
        if (repo / ".claude" / "agents").is_dir() else []
    targets = set()
    for link in links:
        if not link.is_symlink():
            continue
        try:
            targets.add(link.readlink().parent.parent)
        except OSError:
            continue
    if not targets:
        if links:
            click.echo("  follows commons    — (no symlinks; local files only)")
        return
    current = commons_root().resolve()
    for tgt in sorted(targets):
        stale = "" if tgt.resolve() == current else \
            f"  ← NOT the commons you are running ({current})"
        click.echo(f"  follows commons   {tgt}{stale}")
    if any(t.resolve() != current for t in targets):
        click.echo("  fix:              murmurent repo upgrade "
                   f"{repo} --all-agents")


def cmd_status(target: str, host_name: str | None) -> int:
    """Report whether a repo is murmurent-ready.

    ``target`` is either a path (checked directly, on ``--host`` or
    local) or a bare repo name (searched across THIS machine's scan
    dirs). Exit code: 0 = every clone found is ready, 1 = found but
    not (fully) ready, 2 = not found.

    Issue #94: this searches the local machine only. Remote (``ssh``-kind)
    hosts are skipped — view another machine's repos on its own dashboard
    (see ``docs/remote_dashboard.md``).
    """
    statuses: list[_adopt.AdoptionStatus] = []

    if _looks_like_path(target):
        try:
            statuses.append(
                _adopt.adoption_status(target, host=host_name or "local")
            )
        except _adopt.AdoptError as exc:
            raise click.ClickException(str(exc)) from exc
    else:
        registry = _hosts.read()
        if host_name:
            if host_name not in registry:
                raise click.ClickException(
                    f"unknown host {host_name!r} — see `murmurent host list`"
                )
            if registry[host_name].is_remote():
                raise click.ClickException(
                    f"host {host_name!r} is a remote machine — the cross-machine "
                    "repo scan is retired (issue #94). Open its own dashboard "
                    "instead (see docs/remote_dashboard.md)."
                )
            registry = {host_name: registry[host_name]}
        for name, host in registry.items():
            if host.is_remote():
                continue   # local-only inventory (issue #94)
            clones, err = _inv.list_machine_repos(name)
            if err:
                click.echo(f"! {name}: scan failed: {err}", err=True)
                continue
            for c in clones:
                if Path(c.path).name != target:
                    continue
                statuses.append(_adopt.adoption_status(c.path, host="local"))

    found = [s for s in statuses if s.exists]
    if not found:
        click.echo(f"{target}: not found on this machine")
        return 2
    for st in found:
        _print_status(st)
    return 0 if all(s.ready for s in found) else 1


def cmd_adopt(*, path: str, lab: str | None, agents_csv: str | None,
              host_name: str, all_agents: bool = False) -> int:
    """Make an existing clone murmurent-ready (CLI twin of the Repos
    panel's ↑ adopt button). Creates NO project — attach the ready repo
    to a project via `murmurent project new` / the dashboard.

    ``all_agents`` links every agent in the commons. It exists because the
    alternative was to name them: with neither option, adopt makes the repo
    ready with an EMPTY ``.claude/agents/``, which is rarely what anyone
    wants and is invisible until an agent turns out to be missing. Telling a
    newcomer to type ``--agents oracle,blacksmith`` instead made them invent a
    choice they had no basis for making."""
    from ..core.commons import commons_root

    agents = ([a.strip() for a in agents_csv.split(",") if a.strip()]
              if agents_csv else None)
    if all_agents:
        src = commons_root() / "agents"
        found = sorted(p.stem for p in src.glob("*.md")) if src.is_dir() else []
        if not found:
            raise click.ClickException(
                f"no agents found in {src} — is murmurent installed? "
                "Run `murmurent doctor`."
            )
        agents = sorted(set((agents or []) + found))
    try:
        outcome = _adopt.adopt_clone(
            clone_path=path, lab=(lab or "").strip(),
            agents=agents, host=host_name,
        )
    except _adopt.AdoptError as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(f"{outcome.repo} is murmurent-ready on {outcome.host} "
               f"({outcome.clone_path}).")
    icon = {"ok": "✓", "warn": "!", "fail": "✗"}
    for p in outcome.probes:
        click.echo(f"  {icon.get(p.status, '?')} {p.name}: {p.detail}")
    click.echo("Next: attach it to a project when you need one — "
               "`murmurent project new … ` or the dashboard's New Project.")
    return 0


def cmd_upgrade(*, path: str | None, all_repos: bool,
                add_agents_csv: str | None, all_agents: bool,
                quiet: bool = False, marker_only: bool = False) -> int:
    """Re-run the readiness bootstrap against the current murmurent
    release: stamps the marker on a legacy CHARTER.md bootstrap (the
    CHARTER.md is preserved — issue #28), migrates the marker schema,
    re-links commons agents (content updates never need this — symlinks
    track the commons clone), and re-stamps bootstrap_version.

    ``quiet`` collapses the per-probe report to one summary line, and says
    nothing at all when there is nothing to upgrade. It exists for the tail of
    ``murmurent install``, which runs this over every ready repo: an install
    that ends by printing fifteen probes for each of seventeen repos buries
    its own result.

    ``marker_only`` restricts ``--all`` to repos that already carry a
    ``.murmurent.yaml``, skipping the ones whose only bootstrap is a legacy
    ``CHARTER.md``. Typed by hand, ``--all`` is meant to migrate those: it
    stamps a marker and brings them across. Run automatically from ``install``
    it must NOT, because stamping a marker on a repo nobody adopted turns an
    upgrade into an adoption and leaves untracked files in a repo whose owner
    asked for nothing. Caught the first time this ran on a real machine: a
    years-old repo with a CHARTER.md came out of a routine `install` carrying a
    new marker and a new .vscode/ directory."""
    from ..core import repo_ready as _rr

    add_agents = ([a.strip() for a in add_agents_csv.split(",") if a.strip()]
                  if add_agents_csv else None)
    targets: list[Path] = []
    if all_repos:
        repos_root = Path.home() / "repos"
        for child in sorted(repos_root.iterdir()) if repos_root.is_dir() else []:
            if not child.is_dir():
                continue
            r = _rr.readiness(child)
            if r.marker is not None or (r.legacy_charter and not marker_only):
                targets.append(child)
        if not targets:
            if not quiet:
                click.echo("no murmurent-ready repos found under ~/repos")
            return 0
    elif path:
        targets = [Path(path).expanduser()]
    else:
        raise click.ClickException("pass a repo path or --all")

    icon = {"ok": "✓", "warn": "!", "fail": "✗"}
    rc = 0
    failed: list[str] = []
    for t in targets:
        if not quiet:
            click.echo(f"{t.name}:")
        for p in _rr.upgrade(t, add_agents=add_agents, all_agents=all_agents):
            if not quiet:
                click.echo(f"  {icon.get(p.status, '?')} {p.name}: {p.detail}")
            if p.status == "fail":
                rc = 1
                if t.name not in failed:
                    failed.append(t.name)
    if quiet:
        n = len(targets)
        msg = f"  ✓ repos: {n} murmurent-ready repo{'s' if n != 1 else ''} re-linked"
        if failed:
            msg = (f"  ✗ repos: {n - len(failed)} of {n} re-linked; failed: "
                   + ", ".join(failed)
                   + " — run `murmurent repo upgrade --all` to see why")
        click.echo(msg)
    return rc


# ---------------------------------------------------------------------------
# private — keep a repo out of the inventory entirely
# ---------------------------------------------------------------------------


def cmd_private_list() -> int:
    """Print this machine's private-repo patterns."""
    patterns = _inv.load_exclusions()
    if not patterns:
        click.echo("No private repos. Every git clone under the scan dirs is "
                   "inventoried.")
        click.echo(f"Add one with: murmurent repo private add <name-or-glob>")
        return 0
    click.echo(f"Private repos ({_inv.EXCLUDE_FILE}) — never inventoried, "
               "never published:")
    for pat in patterns:
        click.echo(f"  {pat}")
    return 0


def cmd_private_add(pattern: str) -> int:
    """Mark PATTERN private and drop it from the cached report.

    Rewrites the cached inventory in place as well as adding the pattern,
    so the repo disappears immediately rather than at the next weekly
    scan — a privacy setting that takes a week to apply is not one.
    """
    try:
        patterns = _inv.add_exclusion(pattern)
    except ValueError as exc:
        click.echo(f"✗ {exc}", err=True)
        return 2
    dropped = _inv.purge_excluded_from_cache()
    click.echo(f"✓ {pattern} is private — excluded from the repo inventory.")
    if dropped:
        click.echo(f"  Removed {dropped} cached row(s); the clone itself is untouched.")
    click.echo(f"  {len(patterns)} pattern(s) in {_inv.EXCLUDE_FILE}")
    return 0


def cmd_private_remove(pattern: str) -> int:
    """Un-mark PATTERN, so the repo is inventoried again."""
    before = _inv.load_exclusions()
    if pattern.strip() not in before:
        click.echo(f"✗ {pattern!r} is not in the private list.", err=True)
        return 2
    patterns = _inv.remove_exclusion(pattern)
    click.echo(f"✓ {pattern} is no longer private — it returns on the next scan "
               "(or hit Refresh in the dashboard).")
    click.echo(f"  {len(patterns)} pattern(s) remain.")
    return 0
