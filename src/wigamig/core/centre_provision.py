"""
Purpose: Centre-wide project provisioning + reconcile loop.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-26

Companion to ``core.project_provision`` (which handles per-lab
GitHub/Slack/origin wiring). This module adds the centre-scope
concerns the user flagged in item (0) of the post-smoke design
conversation:

  - **Per-project filesystem ACLs** on shared lab servers via a
    sudo-grantable script (``/opt/wigamig/wigamig_project_acl.sh``).
  - **Cross-lab membership tracking** so a project's member set is
    declared once, regardless of which labs the members come from.
  - **Reconcile loop** that diffs desired state (the project's
    declared members) vs actual state (Slack channel membership,
    GitHub collaborators, filesystem ACLs) and emits one Probe per
    drift item. Apply mode runs the deltas.

Storage:

  <lab_info>/projects/<project>.md (frontmatter):
    name: dcis_imaging
    primary_lab: hallett       # whose workspace owns the Slack channel
    members:
      - '@allie'
      - '@cara'                # may come from another lab
    machines:                  # lab servers that host this project's data
      - lab-server
    github:
      org: hallettmiket
      repo: dcis_imaging
    slack:
      channel_id: C0CHANNEL    # filled in after first provision
    created: '2026-05-26'

The reconcile loop is intentionally read-mostly. It never deletes
data; it only adjusts membership (Slack invites/kicks, GitHub
collaborator grants/revokes, ACL grants/revokes). Filesystem files
in raw/ + refined/ are NEVER touched — that's enforced by the
existing raw_guard + protected_paths hooks.
"""

from __future__ import annotations

import datetime as _dt
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .frontmatter import parse_file
from .preflight import Probe
from .registrar import (
    _git_commit_all, _git_init_if_needed, lab_info_root,
)


PROJECTS_SUBDIR = "projects"
ACL_SUDO_SCRIPT = "/opt/wigamig/wigamig_project_acl.sh"


class CentreProvisionError(RuntimeError):
    """Project-provisioning failed."""


@dataclass
class ProjectRecord:
    """Desired-state record for one centre project."""

    name: str
    primary_lab: str
    members: list[str] = field(default_factory=list)
    machines: list[str] = field(default_factory=list)
    github_org: str = ""
    github_repo: str = ""
    slack_channel_id: str = ""
    description: str = ""
    created: str = ""
    path: Path | None = None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def projects_dir(env: dict[str, str] | None = None) -> Path:
    """``<lab_info>/projects/``."""
    return lab_info_root(env) / PROJECTS_SUBDIR


def project_path(
    project: str, env: dict[str, str] | None = None,
) -> Path:
    return projects_dir(env) / f"{project}.md"


def project_log_path(
    project: str, env: dict[str, str] | None = None,
) -> Path:
    return projects_dir(env) / project / "provision_log.md"


# ---------------------------------------------------------------------------
# Reader / writer
# ---------------------------------------------------------------------------

def _parse_project(path: Path) -> ProjectRecord | None:
    try:
        parsed = parse_file(path)
    except Exception:
        return None
    meta = parsed.meta or {}
    name = str(meta.get("name") or path.stem)
    members = [str(h).lower() for h in (meta.get("members") or [])]
    gh = (meta.get("github") or {}) if isinstance(meta.get("github"), dict) else {}
    slack = (meta.get("slack") or {}) if isinstance(meta.get("slack"), dict) else {}
    return ProjectRecord(
        name=name,
        primary_lab=str(meta.get("primary_lab") or "").lower(),
        members=members,
        machines=[str(m) for m in (meta.get("machines") or [])],
        github_org=str(gh.get("org") or ""),
        github_repo=str(gh.get("repo") or name),
        slack_channel_id=str(slack.get("channel_id") or ""),
        description=str(meta.get("description") or "").strip(),
        created=str(meta.get("created") or ""),
        path=path,
    )


def get_project(
    name: str, env: dict[str, str] | None = None,
) -> ProjectRecord | None:
    p = project_path(name, env)
    if not p.is_file():
        return None
    return _parse_project(p)


def iter_projects(
    env: dict[str, str] | None = None,
) -> list[ProjectRecord]:
    pdir = projects_dir(env)
    if not pdir.is_dir():
        return []
    out: list[ProjectRecord] = []
    for entry in sorted(pdir.iterdir()):
        if entry.is_file() and entry.suffix == ".md":
            r = _parse_project(entry)
            if r is not None:
                out.append(r)
    return out


def _render(r: ProjectRecord) -> str:
    meta = {
        "name": r.name,
        "primary_lab": r.primary_lab,
        "description": r.description,
        "members": list(r.members),
        "machines": list(r.machines),
        "github": {"org": r.github_org, "repo": r.github_repo},
        "slack": {"channel_id": r.slack_channel_id},
        "created": r.created,
    }
    yaml_text = yaml.safe_dump(meta, sort_keys=False).rstrip()
    return f"---\n{yaml_text}\n---\n\n# {r.name}\n"


def upsert_project(
    *,
    name: str,
    primary_lab: str,
    members: list[str] | None = None,
    machines: list[str] | None = None,
    github_org: str = "",
    github_repo: str = "",
    description: str = "",
    env: dict[str, str] | None = None,
) -> Path:
    """Create or overwrite a project record. Idempotent."""
    if not name.strip():
        raise CentreProvisionError("name is required")
    if not primary_lab.strip():
        raise CentreProvisionError("primary_lab is required")
    existing = get_project(name, env)
    created = (existing.created if existing else
               _dt.datetime.now(_dt.timezone.utc).date().isoformat())
    rec = ProjectRecord(
        name=name.strip(),
        primary_lab=primary_lab.strip().lower(),
        members=[m.lower().lstrip("@") for m in (members or [])],
        machines=list(machines or []),
        github_org=github_org or (existing.github_org if existing else ""),
        github_repo=github_repo or (existing.github_repo if existing else name),
        slack_channel_id=(existing.slack_channel_id if existing else ""),
        description=description or (existing.description if existing else ""),
        created=created,
    )
    p = project_path(name, env)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_render(rec), encoding="utf-8")
    root = lab_info_root(env)
    _git_init_if_needed(root)
    verb = "updated" if existing else "created"
    _git_commit_all(root,
        f"projects: {verb} {name} (primary_lab={primary_lab.lower()}, "
        f"{len(rec.members)} members)")
    return p


def set_slack_channel_id(
    *, name: str, channel_id: str,
    env: dict[str, str] | None = None,
) -> Path:
    """Stamp the resolved Slack channel ID after provisioning."""
    r = get_project(name, env)
    if r is None:
        raise CentreProvisionError(f"project not found: {name}")
    r.slack_channel_id = channel_id.strip()
    p = project_path(name, env)
    p.write_text(_render(r), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Filesystem ACL via sudo script
# ---------------------------------------------------------------------------

def _acl_script_path(env: dict[str, str] | None = None) -> str:
    source = os.environ if env is None else env
    return source.get("WIGAMIG_PROJECT_ACL_SCRIPT", ACL_SUDO_SCRIPT)


def apply_fs_acl(
    *,
    project: str,
    members: list[str],
    machine: str | None = None,
    sudo: bool = True,
    env: dict[str, str] | None = None,
    runner=None,                           # injectable for tests
) -> Probe:
    """Apply the ACL grant for ``project``'s members on ``machine``.

    Invokes ``WIGAMIG_PROJECT_ACL_SCRIPT`` (default
    ``/opt/wigamig/wigamig_project_acl.sh``) via sudo. The script is
    expected to be present on the lab server with a NOPASSWD sudoers
    entry; the sysadmin installs it once (see
    ``scripts/wigamig_project_acl.sh`` in the wigamig repo for the
    template).

    When ``machine`` is None, runs locally. Otherwise wraps in ssh.

    ``runner`` is an injectable callable
    ``(argv: list[str]) -> subprocess.CompletedProcess`` so tests
    don't shell out for real.
    """
    script = _acl_script_path(env)
    handle_args = ",".join(sorted(set(m.lstrip("@").lower() for m in members)))
    base = [script, "--project", project, "--members", handle_args]
    if sudo:
        base = ["sudo", "-n", *base]
    if machine:
        # Wrap in ssh; we rely on the caller's SSH config to resolve.
        argv = ["ssh", "-o", "ConnectTimeout=10", machine, " ".join(base)]
    else:
        argv = base
    run = runner or _default_runner
    try:
        r = run(argv)
    except Exception as exc:  # noqa: BLE001
        return Probe(name=f"fs-acl[{machine or 'local'}]", status="block",
                     detail=f"runner error: {exc}")
    if r.returncode == 0:
        return Probe(name=f"fs-acl[{machine or 'local'}]", status="ok",
                     detail=(r.stdout or "").strip())
    return Probe(name=f"fs-acl[{machine or 'local'}]", status="warn",
                 detail=(r.stderr or r.stdout or "").strip())


def _default_runner(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        argv, capture_output=True, text=True, timeout=30, check=False,
    )


# ---------------------------------------------------------------------------
# Lab onboarding (item 2g — fires when a lab/core join request is approved)
# ---------------------------------------------------------------------------

def _has_env_slack_token() -> bool:
    """True iff a Slack bot token is set via env (WIGAMIG_SLACK_TOKEN or the
    legacy SLACK_BOT_TOKEN). Deliberately env-only — the ~/.config token file
    is NOT consulted here so the token-less test suite never triggers live
    Slack member invites even on a dev machine that has the file."""
    return bool(os.environ.get("WIGAMIG_SLACK_TOKEN", "").strip()
                or os.environ.get("SLACK_BOT_TOKEN", "").strip())


def resolve_slack_token(*, allow_file: bool = False) -> str:
    """Resolve a Slack bot token for EXPLICIT mayor commands.

    Env first (``WIGAMIG_SLACK_TOKEN`` → ``SLACK_BOT_TOKEN``); when
    ``allow_file`` is set, fall back to the mode-0600
    ``~/.config/wigamig/slack-token`` file — the same source the long-running
    dashboard uses — so a mayor doesn't have to re-export the token in every
    terminal. **Automatic** provisioning must NOT pass ``allow_file=True``:
    keeping that path env-only (see :func:`_has_env_slack_token`) is what stops
    a stale token file from firing live Slack calls unattended.
    """
    tok = (os.environ.get("WIGAMIG_SLACK_TOKEN", "").strip()
           or os.environ.get("SLACK_BOT_TOKEN", "").strip())
    if tok or not allow_file:
        return tok
    try:
        from pathlib import Path
        f = Path.home() / ".config" / "wigamig" / "slack-token"
        if f.is_file():
            return f.read_text(encoding="utf-8").strip()
    except Exception:  # noqa: BLE001
        pass
    return ""


def provision_lab_onboarding(
    lab_name: str,
    *,
    env: dict[str, str] | None = None,
    slack_creator=None,             # injectable: (channel_name, ws_id) -> str | None
    member_inviter=None,            # injectable: (channel_id, handles, member_email_map) -> dict
    github_creator=None,            # injectable: (org, repo, members) -> bool
    acl_runner=None,                # injectable: same shape as apply_fs_acl runner
) -> list[Probe]:
    """Provision Slack channel + GitHub repo + filesystem ACLs for a
    newly-approved lab.

    The three injectable hooks let tests run end-to-end without
    touching real Slack / GitHub / sudo. Production calls leave them
    None and the helpers fall back to the live integrations:

      - Slack: ``slack_notify._post`` + a thin create-channel wrapper
      - GitHub: ``project_provision._gh`` (the existing gh wrapper)
      - ACL:   ``apply_fs_acl`` defined above

    Reads the centre profile (``centre_init.read_centre``) to pull
    workspace id / github org / data server. If the centre isn't
    initialised yet, returns a single block-severity Probe so the
    UI surfaces the missing precondition cleanly.

    Returns a Probe per step (4 probes max).
    """
    from . import centre_init as _ci
    centre = _ci.read_centre(env=env)
    if centre is None:
        return [Probe(
            name="centre-profile", status="block",
            detail="centre is not initialised; run wigamig centre-init first.",
        )]

    probes: list[Probe] = []

    # 1. Slack channel — a private channel named after the group, with the
    #    group's members invited. The channel name is the group's own name
    #    (normalized to Slack rules), e.g. lab_mh -> #lab_mh.
    if slack_creator is None:
        slack_creator = _live_slack_create_channel
    if centre.slack_workspace:
        try:
            from . import registrar as _reg
            from ..dashboard import slack_notify as _sn
            channel_name = _sn.normalize_channel_name(lab_name) or lab_name
            channel_id = slack_creator(channel_name, centre.slack_workspace)
            if channel_id:
                _reg.set_group_slack_channel(lab_name, channel_id, env=env)
                # Invite members. Gated so the token-less test suite never
                # hits the wire: only when an inviter is injected OR an env
                # Slack token is present (mirrors the creator's env gating).
                invited_n = 0
                if member_inviter is not None or _has_env_slack_token():
                    inviter = member_inviter or _sn.invite_members_to_channel
                    email_map = _reg.group_email_map(lab_name, env=env)
                    inv = inviter(channel_id, list(email_map.keys()),
                                  member_email_map=email_map) or {}
                    invited_n = len(inv.get("invited", [])) + len(inv.get("already_in", []))
                probes.append(Probe(
                    name="slack-channel", status="ok",
                    detail=f"#{channel_name} in {centre.slack_workspace} → "
                           f"{channel_id} (members: {invited_n})",
                ))
            else:
                probes.append(Probe(
                    name="slack-channel", status="warn",
                    detail=f"#{channel_name} could not be created (workspace {centre.slack_workspace})",
                ))
        except Exception as exc:  # noqa: BLE001
            probes.append(Probe(
                name="slack-channel", status="warn",
                detail=f"slack error: {exc}",
            ))
    else:
        probes.append(Probe(
            name="slack-channel", status="warn",
            detail="centre.slack_workspace not configured; skipping",
        ))

    # 2. GitHub repo.
    if github_creator is None:
        github_creator = _live_github_create_repo
    if centre.github_org:
        try:
            ok = github_creator(centre.github_org, lab_name, [])
            probes.append(Probe(
                name="github-repo",
                status="ok" if ok else "warn",
                detail=(
                    f"{centre.github_org}/{lab_name}"
                    if ok else
                    f"gh create failed for {centre.github_org}/{lab_name}"
                ),
            ))
        except Exception as exc:  # noqa: BLE001
            probes.append(Probe(
                name="github-repo", status="warn",
                detail=f"gh error: {exc}",
            ))
    else:
        probes.append(Probe(
            name="github-repo", status="warn",
            detail="centre.github_org not configured; skipping",
        ))

    # 3. Filesystem ACL (one probe per machine; here just centre.data_server).
    if centre.data_server:
        probes.append(apply_fs_acl(
            project=lab_name,
            members=[],          # PI joins as roster grows; v1 grants empty.
            machine=centre.data_server,
            sudo=True,
            env=env,
            runner=acl_runner,
        ))
    else:
        probes.append(Probe(
            name="fs-acl[unspecified]", status="warn",
            detail="centre.data_server not configured; skipping",
        ))

    return probes


def provision_centre_slack(
    *,
    env: dict[str, str] | None = None,
    channel_creator=None,     # injectable: (channel_name, ws_id) -> str | None
    channel_resolver=None,    # injectable: (channel_name) -> str | None
    token: str | None = None,  # explicit token for the live path (env-only if None)
) -> list[Probe]:
    """Provision the centre's Slack fabric: the private mayor↔CC channel
    (``#wigamig-ops``, stored as ``mayor_channel_id``) and the broadcast
    audience map (``admin`` → mayor channel, ``everyone`` → ``#general``).

    Explicit entry point — run by ``wigamig centre-slack-setup``, never
    auto-fired from ``init_centre``. Best-effort + injectable; the live
    creator is env-token-gated so the token-less suite makes no live calls.
    """
    from . import centre_init as _ci
    from . import registrar as _reg
    centre = _ci.read_centre(env=env)
    if centre is None:
        return [Probe(name="centre-profile", status="block",
                      detail="centre is not initialised; run wigamig centre-init first.")]
    if not centre.slack_workspace:
        return [Probe(name="slack", status="warn",
                      detail="centre.slack_workspace not configured; skipping.")]

    probes: list[Probe] = []

    # 1. Mayor↔CC channel.
    mayor_id = ""
    if channel_creator is not None:
        # Injected seam (tests): returns a channel id or None.
        try:
            mayor_id = channel_creator("wigamig-ops", centre.slack_workspace) or ""
            probes.append(Probe(
                name="mayor-channel",
                status="ok" if mayor_id else "warn",
                detail=(f"#wigamig-ops → {mayor_id}" if mayor_id
                        else "#wigamig-ops could not be created")))
        except Exception as exc:  # noqa: BLE001
            probes.append(Probe(name="mayor-channel", status="warn",
                                detail=f"slack error: {exc}"))
    else:
        # Live path: use the structured API so we surface the actual Slack
        # error (missing_scope / invalid_auth / channel_not_found / …) instead
        # of a bare "could not be created".
        res = slack_create_channel("wigamig-ops", workspace_id=centre.slack_workspace,
                                   private=True, token=token)
        if res.ok:
            mayor_id = res.channel_id or ""
            probes.append(Probe(name="mayor-channel", status="ok",
                                detail=f"#wigamig-ops → {mayor_id}"))
        elif res.error == "name_taken":
            # Already exists → reuse it, so re-running setup is idempotent.
            try:
                from ..dashboard import slack_notify as _sn
                mayor_id = _sn._lookup_channel_id_by_name("wigamig-ops") or ""
            except Exception:  # noqa: BLE001
                mayor_id = ""
            if mayor_id:
                probes.append(Probe(name="mayor-channel", status="ok",
                                    detail=f"#wigamig-ops → {mayor_id} (existing)"))
            else:
                probes.append(Probe(name="mayor-channel", status="warn",
                                    detail="#wigamig-ops already exists but couldn't be "
                                           "resolved — add the `groups:read` scope and reinstall."))
        else:
            probes.append(Probe(name="mayor-channel", status="warn",
                                detail=f"#wigamig-ops could not be created — "
                                       f"{res.error}: {res.detail}"))
    if mayor_id:
        _ci.update_centre({"mayor_channel_id": mayor_id}, env=env)

    # 2. Broadcast audiences: admin → mayor channel, everyone → #general.
    profile = _reg.read_profile(env)
    bc = dict(profile.get("broadcast_channels") or {})

    # 1b. Invite the mayor to their own private channel. The bot CREATED
    # #wigamig-ops, so it's the only member — the human mayor can't even see it
    # until they're added. Needs the mayor's email (registrar profile → centre
    # join_email) and users:read.email + invite scopes.
    if mayor_id and (channel_creator is None):
        mayor_handle = (centre.founding_mayor or "").strip()
        mayor_email = (str(profile.get("email") or "").strip()
                       or (centre.join_email or "").strip())
        if mayor_handle and mayor_email and (token or _has_env_slack_token()):
            try:
                from ..dashboard import slack_notify as _sn
                inv = _sn.invite_members_to_channel(
                    mayor_id, [mayor_handle],
                    member_email_map={mayor_handle.lstrip("@").lower(): mayor_email})
                if mayor_handle in inv.get("invited", []):
                    probes.append(Probe(name="mayor-invite", status="ok",
                                        detail=f"added {mayor_handle} to #wigamig-ops"))
                elif mayor_handle in inv.get("already_in", []):
                    probes.append(Probe(name="mayor-invite", status="ok",
                                        detail=f"{mayor_handle} already in #wigamig-ops"))
                else:
                    why = (inv.get("unresolved") or [{}])[0].get("reason", "") \
                        or inv.get("error", "")
                    probes.append(Probe(name="mayor-invite", status="warn",
                        detail=f"couldn't add {mayor_handle} to #wigamig-ops"
                               + (f" ({why})" if why else "")
                               + " — open the channel in Slack and add yourself."))
            except Exception as exc:  # noqa: BLE001
                probes.append(Probe(name="mayor-invite", status="warn",
                                    detail=f"mayor invite error: {exc}"))
        elif mayor_handle and not mayor_email:
            probes.append(Probe(name="mayor-invite", status="warn",
                detail="no mayor email on record — set the centre join_email (or your "
                       "registrar profile email) so you can be added to #wigamig-ops."))
    if mayor_id:
        bc["admin"] = mayor_id
    if channel_resolver is not None or token or _has_env_slack_token():
        if channel_resolver is None:
            from ..dashboard import slack_notify as _sn
            channel_resolver = _sn._lookup_channel_id_by_name
        try:
            gen = channel_resolver("general")
            if gen:
                bc["everyone"] = gen
                probes.append(Probe(name="general-channel", status="ok",
                                    detail=f"#general → {gen}"))
            else:
                probes.append(Probe(name="general-channel", status="warn",
                                    detail="#general not found; create it in Slack"))
        except Exception as exc:  # noqa: BLE001
            probes.append(Probe(name="general-channel", status="warn",
                                detail=f"slack error: {exc}"))
    if bc:
        _reg.write_profile({"broadcast_channels": bc}, env=env)
    return probes


@dataclass
class SlackChannelResult:
    """Outcome of a live Slack channel-create attempt. Used both by
    the join-approve flow (which only cares about channel_id) AND by
    the ``wigamig centre-slack-smoke`` CLI (which surfaces the full
    detail so the registrar can debug a misconfigured token)."""
    ok: bool
    channel_id: str = ""                    # populated when ok=True
    channel_name: str = ""
    error: str = ""                         # Slack API error code
    detail: str = ""                        # human-readable explanation


def slack_create_channel(
    channel_name: str,
    *,
    workspace_id: str = "",
    private: bool = True,
    token: str | None = None,
) -> SlackChannelResult:
    """Live Slack ``conversations.create``. Returns a structured
    result that the smoke CLI can render in full and the join-approve
    flow can collapse to "ok / not ok".

    ``token`` defaults to ``$SLACK_BOT_TOKEN``. The token's bot needs:

      - ``channels:manage`` for public channels
      - ``groups:write``    for private channels (the join-approve
                              path uses ``private=True``)

    The Slack ``conversations.create`` payload doesn't take a
    workspace id — the token is scoped to one workspace. We accept
    ``workspace_id`` only for caller-side documentation / parity with
    the centre profile field.
    """
    import os
    import httpx
    # Unified token: prefer WIGAMIG_SLACK_TOKEN, fall back to the legacy
    # SLACK_BOT_TOKEN (both are workspace-scoped bot tokens). The posting /
    # invite path (dashboard/slack_notify) additionally honours the
    # ~/.config/wigamig/slack-token file.
    tok = token if token is not None else (
        os.environ.get("WIGAMIG_SLACK_TOKEN", "").strip()
        or os.environ.get("SLACK_BOT_TOKEN", "").strip()
    )
    if not tok:
        return SlackChannelResult(
            ok=False, channel_name=channel_name,
            error="missing_token",
            detail="no Slack token: set $WIGAMIG_SLACK_TOKEN (or the legacy "
                    "$SLACK_BOT_TOKEN), or pass token=.",
        )
    payload: dict = {"name": channel_name, "is_private": bool(private)}
    try:
        r = httpx.post(
            "https://slack.com/api/conversations.create",
            headers={"Authorization": f"Bearer {tok}"},
            json=payload,
            timeout=10,
        )
    except Exception as exc:  # noqa: BLE001
        return SlackChannelResult(
            ok=False, channel_name=channel_name,
            error="transport",
            detail=f"network error: {exc}",
        )
    try:
        data = r.json()
    except Exception as exc:  # noqa: BLE001
        return SlackChannelResult(
            ok=False, channel_name=channel_name,
            error="bad_response",
            detail=f"non-JSON response from Slack (HTTP {r.status_code}): {exc}",
        )
    if data.get("ok"):
        return SlackChannelResult(
            ok=True, channel_name=channel_name,
            channel_id=str(data.get("channel", {}).get("id") or ""),
            detail=f"created (HTTP {r.status_code})",
        )
    # Slack's documented error codes — make them actionable.
    err = str(data.get("error") or "unknown")
    hints = {
        "missing_scope": "your bot token lacks the required OAuth scope; "
                         "add 'groups:write' (private) or 'channels:manage' "
                         "(public) in the app's OAuth settings and reinstall.",
        "not_authed": "no token or expired token.",
        "invalid_auth": "the token is wrong or has been revoked.",
        "name_taken": "a channel with that name already exists. Slack "
                       "doesn't allow re-creating it; rename or reuse.",
        "invalid_name_specials": "channel name has special chars; only "
                                  "lowercase letters / digits / hyphens / "
                                  "underscores allowed.",
        "invalid_name_maxlength": "channel name longer than 80 chars.",
        "ratelimited": "Slack rate-limited the call; retry after a minute.",
        "restricted_action": "your workspace plan / admin policy forbids "
                              "bot-created channels.",
    }
    return SlackChannelResult(
        ok=False, channel_name=channel_name,
        error=err,
        detail=hints.get(err, f"Slack returned error={err!r} (raw: {data})"),
    )


def _live_slack_create_channel(
    channel_name: str, workspace_id: str,
) -> str | None:
    """Compat shim used by provision_lab_onboarding's default hook.

    Returns the channel_id on success, None on failure (so the
    join-approve probe collapses to ok/warn). For a structured
    result use :func:`slack_create_channel` directly.
    """
    res = slack_create_channel(channel_name, workspace_id=workspace_id,
                                 private=True)
    return res.channel_id if res.ok else None


def _live_github_create_repo(
    org: str, repo: str, collaborators: list[str],
) -> bool:
    """Live GitHub repo creation via gh CLI. Returns True on success.

    Reuses the existing _gh helper from project_provision for
    consistency with the per-lab provisioning path.
    """
    try:
        from . import project_provision as _pp
        r = _pp._gh(["repo", "create", f"{org}/{repo}", "--private",
                      "--confirm"])
        return r.returncode == 0
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Reconcile loop (diff desired vs actual)
# ---------------------------------------------------------------------------

@dataclass
class Delta:
    """One drift item the reconcile loop found."""

    kind: str                  # 'slack' | 'github' | 'fs_acl'
    severity: str              # 'ok' | 'warn' | 'block'
    summary: str
    apply_hint: str = ""       # what `--apply` would do


def reconcile_project(
    *,
    project: str,
    slack_actual_members: list[str] | None = None,
    github_actual_collaborators: list[str] | None = None,
    fs_actual_acl: dict[str, list[str]] | None = None,   # machine → handles
    env: dict[str, str] | None = None,
) -> list[Delta]:
    """Diff a project's declared state vs the passed-in actual state.

    The caller (CLI / endpoint) is responsible for fetching the actual
    state — this function is pure (no I/O) so it's trivially testable.

    Returns a Delta per drift item. Empty list means everything's in sync.
    """
    r = get_project(project, env)
    if r is None:
        raise CentreProvisionError(f"project not found: {project}")
    desired = set(m.lower().lstrip("@") for m in r.members)
    deltas: list[Delta] = []

    # Slack
    if slack_actual_members is not None:
        actual = set(m.lower().lstrip("@") for m in slack_actual_members)
        for missing in sorted(desired - actual):
            deltas.append(Delta(
                kind="slack", severity="warn",
                summary=f"@{missing} in project but not in Slack channel",
                apply_hint=f"invite @{missing} to {r.slack_channel_id or '#'+project}",
            ))
        for extra in sorted(actual - desired):
            deltas.append(Delta(
                kind="slack", severity="warn",
                summary=f"@{extra} in Slack channel but not in project",
                apply_hint=f"kick @{extra} from {r.slack_channel_id or '#'+project}",
            ))

    # GitHub
    if github_actual_collaborators is not None:
        actual = set(m.lower().lstrip("@") for m in github_actual_collaborators)
        for missing in sorted(desired - actual):
            deltas.append(Delta(
                kind="github", severity="warn",
                summary=f"@{missing} in project but not a GitHub collaborator",
                apply_hint=f"gh api -X PUT repos/{r.github_org}/{r.github_repo}/collaborators/{missing}",
            ))
        for extra in sorted(actual - desired):
            deltas.append(Delta(
                kind="github", severity="warn",
                summary=f"@{extra} is a GitHub collaborator but not in project",
                apply_hint=f"gh api -X DELETE repos/{r.github_org}/{r.github_repo}/collaborators/{extra}",
            ))

    # Filesystem ACL (per machine)
    if fs_actual_acl is not None:
        for machine, granted in fs_actual_acl.items():
            actual = set(m.lower().lstrip("@") for m in granted)
            for missing in sorted(desired - actual):
                deltas.append(Delta(
                    kind="fs_acl", severity="warn",
                    summary=f"@{missing} missing FS ACL on {machine}",
                    apply_hint=f"sudo {_acl_script_path(env)} --project {project} --members {','.join(sorted(desired))}",
                ))
            for extra in sorted(actual - desired):
                deltas.append(Delta(
                    kind="fs_acl", severity="warn",
                    summary=f"@{extra} has FS ACL on {machine} but not in project",
                    apply_hint=f"sudo {_acl_script_path(env)} --project {project} --members {','.join(sorted(desired))}",
                ))
    return deltas


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def append_log(
    *,
    project: str,
    actor: str,
    action: str,
    detail: str = "",
    env: dict[str, str] | None = None,
) -> Path:
    p = project_log_path(project, env)
    p.parent.mkdir(parents=True, exist_ok=True)
    now = _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")
    line = (
        f"- {now} · @{actor.lstrip('@')} · {action}"
        + (f" — {detail}" if detail else "")
        + "\n"
    )
    header = f"# Provision log — {project}\n\n"
    if not p.is_file():
        p.write_text(header + line, encoding="utf-8")
    else:
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line)
    root = lab_info_root(env)
    _git_init_if_needed(root)
    _git_commit_all(root,
        f"projects/{project}: log @{actor.lstrip('@')} {action}")
    return p


__all__ = [
    "PROJECTS_SUBDIR", "ACL_SUDO_SCRIPT",
    "CentreProvisionError",
    "ProjectRecord", "Delta",
    "projects_dir", "project_path", "project_log_path",
    "get_project", "iter_projects",
    "upsert_project", "set_slack_channel_id",
    "apply_fs_acl",
    "reconcile_project",
    "append_log",
    "provision_lab_onboarding",
    "SlackChannelResult", "slack_create_channel",
]
