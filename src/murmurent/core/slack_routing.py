"""
Purpose: the ONE answer to "which Slack channel does a note about this
repository go to, and with which bot?" (issue #243).

Before this module, three answers coexisted: the always-loaded Slack rule named
one channel for every push, the ``/murmurent-push`` skill resolved the project
channel, and ``murmurent project push`` resolved it a third way. Sessions
following the rule sent the notes of every project into the same channel. Now
every writer asks :func:`resolve_route` and posts with :func:`post_note`.

Resolution order, first hit wins:

1. ``slack_channel`` in the repository's ``.murmurent.yaml`` marker (or the
   older ``update_me.channel``): a per-repository override a deployment records
   on purpose (for example, a development repository whose notes are kept out
   of the project's channel).
2. The project named explicitly by the caller, or the one project whose record
   lists this repository. A repository listed by two active projects is
   AMBIGUOUS and gets no channel until the records are fixed; guessing is how
   notes end up in the wrong place.
3. The project's recorded ``slack_channel_id``.
4. The lab's own channel from the registry, when the repository is
   murmurent-ready but belongs to no project with a channel.
5. Nothing. A note with no destination is not posted anywhere; the reason is
   returned so the caller can say so. There is no development-channel fallback.

Author: Mike Hallett (with Claude Code)
Input: a folder (default: the current one), the project records, the registry.
Output: a :class:`Route`; :func:`post_note` posts and reports where it went.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_CHANNEL_ID = re.compile(r"^[CG][A-Z0-9]{6,}$")


@dataclass
class Route:
    """Where a note about a repository goes, and why."""

    channel_id: str = ""
    project: str = ""
    lab: str = ""
    repo: str = ""
    source: str = ""        # marker | project | lab | ""
    reason: str = ""        # why there is no channel, when channel_id is empty
    candidates: list[str] = field(default_factory=list)   # projects, when ambiguous

    @property
    def ok(self) -> bool:
        return bool(self.channel_id)

    def describe(self) -> str:
        """One plain line for a person."""
        if self.ok:
            where = {"marker": "the channel set in .murmurent.yaml",
                     "project": f"the channel of project '{self.project}'",
                     "lab": f"the channel of lab '{self.lab}'"}.get(self.source, "its channel")
            return f"{self.channel_id}: {where}"
        return self.reason or "no Slack channel"


def _marker_for(start: Path | str | None):
    """``(repo_path, marker_dict)`` for the murmurent repository containing
    ``start``, or ``(None, {})``."""
    try:
        from .repo import find_project_repo
        from .repo_ready import read_marker
    except Exception:  # noqa: BLE001
        return None, {}
    repo = find_project_repo(start)
    if repo is None:
        return None, {}
    try:
        marker = read_marker(repo.path) or {}
    except Exception:  # noqa: BLE001
        marker = {}
    return repo.path, (marker if isinstance(marker, dict) else {})


def _lab_channel(lab: str, env: dict | None = None) -> str:
    if not lab:
        return ""
    try:
        from .centre_provision import _group_entry
        entry = _group_entry(lab, env)
        return str(getattr(entry, "slack_channel_id", "") or "")
    except Exception:  # noqa: BLE001
        return ""


def resolve_route(start: Path | str | None = None, *, project: str | None = None,
                  env: dict | None = None, honour_marker: bool | None = None) -> Route:
    """The channel for a note about the repository containing ``start`` (default:
    the current folder), or about ``project`` when it is named. The repository's
    own ``slack_channel`` override applies to notes about that repository, so by
    default it is honoured only when no project is named; a caller that passes
    the folder's own project name sets ``honour_marker=True``. Never raises."""
    if honour_marker is None:
        honour_marker = not project
    from . import cert_projects as _cp

    route = Route()
    repo_path, marker = _marker_for(start)
    if repo_path is not None:
        route.repo = repo_path.name
        route.lab = str(marker.get("lab") or "").removeprefix("lab_")
        # The repository's own override applies to notes ABOUT this repository;
        # a caller naming another project is asking about that project.
        override = str(marker.get("slack_channel") or "").strip() if honour_marker else ""
        if not override and honour_marker:
            # the older per-repository override, set for /murmurent-update-me
            block = marker.get("update_me") if isinstance(marker.get("update_me"), dict) else {}
            override = str(block.get("channel") or "").strip()
        if override:
            if _CHANNEL_ID.match(override):
                route.channel_id, route.source = override, "marker"
                return route
            route.reason = (f"slack_channel in {repo_path / '.murmurent.yaml'} is "
                            f"{override!r}, which is not a Slack channel id (C…)")
            return route

    name = (project or "").strip()
    if not name and repo_path is not None:
        owners = [p for p in _cp.owning_projects(repo_path.name, env=env)
                  if p.status == "active"] or _cp.owning_projects(repo_path.name, env=env)
        if len(owners) > 1:
            route.candidates = sorted(p.name for p in owners)
            route.reason = (f"repository '{repo_path.name}' is listed by "
                            f"{len(owners)} projects ({', '.join(route.candidates)}); "
                            "a note cannot be routed until one of them drops it "
                            "from its record or the repository's .murmurent.yaml "
                            "names a slack_channel")
            return route
        if owners:
            name = owners[0].name
        else:
            name = _cp.project_name_for_cwd(repo_path, env=env) or ""
    if name:
        rec = _cp.get(name, env)
        if rec is None:
            route.reason = (f"no Slack channel is recorded for the project '{name}' "
                            "(there is no project record of that name)")
            if repo_path is None:
                return route
        else:
            route.project = rec.name
            route.lab = route.lab or str(rec.lab or "").removeprefix("lab_")
            if rec.slack_channel_id:
                route.channel_id, route.source = rec.slack_channel_id, "project"
                return route
            route.reason = (f"no Slack channel is recorded for the project '{rec.name}' "
                            f"yet; the PI runs `murmurent project provision-slack {rec.name}`")
    elif repo_path is None:
        route.reason = ("this folder is not inside a murmurent repository "
                        "(no .murmurent.yaml), so there is no project to notify")
        return route

    if not route.lab:
        try:
            from .project_unit import this_machine_lab
            route.lab = str(this_machine_lab() or "")
        except Exception:  # noqa: BLE001
            route.lab = ""
    lab_chan = _lab_channel(route.lab, env)
    if lab_chan:
        route.channel_id, route.source = lab_chan, "lab"
        route.reason = ""
        return route
    if not route.reason:
        route.reason = (f"repository '{route.repo}' belongs to no project and lab "
                        f"'{route.lab or '?'}' has no channel in the registry")
    return route


def token_for(route: Route) -> str:
    """The bot token for the workspace that hosts ``route``'s channel: the
    project's workspace when it is a project channel, else the lab's bot."""
    try:
        if route.project:
            from .cert_provision import resolve_project_slack
            _ws, tok = resolve_project_slack(route.project)
            if tok:
                return tok
        if route.lab:
            from .group_reconcile import resolve_group_slack_token
            return resolve_group_slack_token(route.lab) or ""
    except Exception:  # noqa: BLE001
        return ""
    return ""


def post_note(text: str, *, start: Path | str | None = None, project: str | None = None,
              env: dict | None = None, poster=None, token: str | None = None) -> tuple[bool, Route, str]:
    """Post ``text`` where :func:`resolve_route` says. Returns ``(posted, route,
    detail)``; ``detail`` is a plain sentence for the person either way."""
    route = resolve_route(start, project=project, env=env)
    if not route.ok:
        return False, route, f"not posted: {route.reason}"
    tok = token if token is not None else token_for(route)
    if not tok:
        who = f"project '{route.project}'" if route.project else f"lab '{route.lab}'"
        return False, route, f"not posted: no Slack bot token on this machine for {who}"
    if poster is None:
        from ..dashboard.slack_notify import _post as poster  # noqa: PLC0415
    try:
        ok = bool(poster(route.channel_id, text, token=tok))
    except Exception as exc:  # noqa: BLE001
        return False, route, f"not posted: Slack error ({exc})"
    return ok, route, (f"posted to {route.describe()}" if ok
                       else f"not posted: Slack refused the message for {route.channel_id} "
                            "(is the bot a member of that channel?)")


__all__ = ["Route", "resolve_route", "token_for", "post_note"]
