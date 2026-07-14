"""
Purpose: provision a cert-project's shared infrastructure — starting with a
private Slack channel — with membership synced to the project's CERTIFIED
members. Cert-projects are the authoritative project model, so this is Phase C
of the Slack↔CC plan re-keyed onto them.

Everything is best-effort + injectable: the Slack seams (``creator`` / ``inviter``)
no-op without a bot token, so the test suite stays green token-free. The
handle→email map comes from the lab roster (``members/<handle>.md``), which
already carries each member's email + github.

Author: Mike Hallett (with Claude Code)
Input: the cert-project registry + the lab roster + a Slack bot token (env or
       ``~/.config/murmurent/slack-token``).
Output: a private channel per project; ``slack_channel_id`` stamped on the record.
"""

from __future__ import annotations

from . import cert_projects as _cp
from . import membership as _mem


class CertProvisionError(RuntimeError):
    """A cert-project provisioning step could not be completed."""


def slack_channel_name(project: str) -> str:
    """Slack channel name for a cert-project: the project name, lowercased and
    reduced to Slack's allowed charset (a–z, 0–9, ``-``, ``_``), capped at 80.
    ``_`` is preserved (matches murmurent's identifier convention)."""
    s = "".join(c if (c.isalnum() or c in "-_") else "-" for c in str(project).lower())
    return s.strip("-_")[:80] or "project"


def member_email_map(handles=None) -> dict[str, str]:
    """``{bare-lowercased-handle: email}`` from the lab roster, optionally limited
    to ``handles``. The roster is the source of truth for member email."""
    want = None if handles is None else {str(h).lstrip("@").lower() for h in handles}
    out: dict[str, str] = {}
    for m in _mem.iter_members():
        h = m.handle.lstrip("@").lower()
        if m.email and (want is None or h in want):
            out[h] = m.email
    return out


def member_github_map(handles=None) -> dict[str, str]:
    """``{bare-lowercased-handle: github-login}`` from the lab roster, optionally
    limited to ``handles``. The roster is the source of truth for github login."""
    want = None if handles is None else {str(h).lstrip("@").lower() for h in handles}
    out: dict[str, str] = {}
    for m in _mem.iter_members():
        h = m.handle.lstrip("@").lower()
        if m.github and (want is None or h in want):
            out[h] = m.github
    return out


def resolve_project_slack(project: str, *, env: dict | None = None) -> tuple[str, str]:
    """Which Slack workspace hosts ``project``, and the bot token for it.

    Returns ``(workspace, token)``. ``workspace`` is ``cp.slack_workspace``
    when set (an inter-group project's agreed shared workspace) else the
    owning lab. The token comes from the group-token mechanism
    (``$MURMURENT_GROUP_SLACK_TOKEN`` /
    ``~/.config/murmurent/groups/<workspace>/slack-token``) — a shared
    workspace is just a named token dir. Empty token is NOT an error here
    (callers degrade like every other Slack seam); creation-time validation
    for inter-group projects is the hard gate."""
    cp = _cp.get(project, env)
    if cp is None:
        raise CertProvisionError(f"no cert-project named {project!r}")
    workspace = cp.slack_workspace or cp.lab
    token = ""
    if workspace:
        try:
            from . import group_reconcile as _gr
            token = _gr.resolve_group_slack_token(workspace) or ""
        except Exception:  # noqa: BLE001
            token = ""
    return workspace, token


def is_inter_group(members, *, env: dict | None = None) -> bool:
    """True when the proposed ``members`` span more than one group: any handle
    absent from THIS lab's roster is (from this machine's vantage) external.
    The deployable check on a PI machine — the full cross-lab member→group map
    only exists at the registrar level. An EMPTY roster can't classify anyone
    (the lab isn't running the cert-membership model yet) → not inter-group."""
    roster = {m.handle.lstrip("@").lower() for m in _mem.iter_members()}
    if not roster:
        return False
    return any(str(h).lstrip("@").lower() not in roster for h in (members or []))


def _default_creator(name: str, *, token: str | None = None):
    from . import centre_provision as _prov
    return _prov.slack_create_channel(name, private=True, token=token)


def _default_inviter(channel_id: str, handles: list[str], *, member_email_map: dict,
                     token: str | None = None):
    from ..dashboard import slack_notify as _sn
    return _sn.invite_members_to_channel(channel_id, handles,
                                         member_email_map=member_email_map,
                                         token=token)


def provision_slack(project: str, *, lab: str | None = None,
                    env: dict | None = None, creator=None, inviter=None) -> dict:
    """Ensure a private Slack channel for cert-project ``project`` and invite its
    certified members. Stamps ``slack_channel_id`` on the record the first time.
    Idempotent: an already-provisioned project re-syncs membership without
    re-creating the channel. Returns a structured summary; reports ``missing_token``
    (not an error) when there is no Slack token, so callers/tests degrade cleanly.

    ``creator`` / ``inviter`` are injectable seams (default to the real Slack
    engines, which themselves no-op without a token)."""
    cp = _cp.get(project, env)
    if cp is None:
        raise CertProvisionError(f"no cert-project named {project!r}")
    # Resolve the hosting workspace's token once (group or shared workspace);
    # bind it into the DEFAULT seams only, so injected test seams keep their
    # signatures. Empty token → the engines fall back to the centre token and
    # then to their token-free no-op, exactly as before.
    _ws, _tok = resolve_project_slack(project, env=env)
    creator = creator or (lambda name: _default_creator(name, token=_tok or None))
    inviter = inviter or (lambda cid, hs, *, member_email_map:
                          _default_inviter(cid, hs, member_email_map=member_email_map,
                                           token=_tok or None))

    channel_id = cp.slack_channel_id
    created = False
    if not channel_id:
        res = creator(slack_channel_name(project))
        if not getattr(res, "ok", False):
            return {"ok": False, "channel_id": None, "created": False,
                    "error": getattr(res, "error", "channel_create_failed"),
                    "detail": getattr(res, "detail", ""),
                    "invited": [], "already_in": [], "unresolved": []}
        channel_id = res.channel_id
        created = True
        _cp.upsert(project, lab=(lab or cp.lab), slack_channel_id=channel_id, env=env)

    handles = [m.lstrip("@") for m in cp.members]
    inv = inviter(channel_id, handles, member_email_map=member_email_map(handles))
    return {"ok": True, "channel_id": channel_id, "created": created,
            "invited": inv.get("invited", []), "already_in": inv.get("already_in", []),
            "unresolved": inv.get("unresolved", []), "error": inv.get("error")}


# ---------------------------------------------------------------------------
# GitHub repo provisioning — a private repo per cert-project, certified members
# as collaborators (keyed off each member's github login on the roster).
# ---------------------------------------------------------------------------

def _default_repo_creator(org: str, name: str):
    """Create a private ``org/name`` repo if missing. Returns ``(ok, detail)``."""
    from . import project_provision as _pp
    if not _pp._gh_available():
        return (False, "gh CLI not installed")
    if _pp._gh(["repo", "view", f"{org}/{name}"]).returncode == 0:
        return (True, "exists")
    res = _pp._gh(["repo", "create", f"{org}/{name}", "--private"])
    if res.returncode == 0:
        return (True, "created")
    return (False, (res.stderr or res.stdout or "").strip() or "gh repo create failed")


def _default_collaborator(org: str, name: str, login: str):
    """Grant ``login`` push access on ``org/name`` (idempotent). ``(ok, detail)``."""
    from . import project_provision as _pp
    if not _pp._gh_available():
        return (False, "gh CLI not installed")
    res = _pp._gh(["api", "-X", "PUT", f"repos/{org}/{name}/collaborators/{login}",
                   "-f", "permission=push"])
    return (res.returncode == 0, (res.stderr or res.stdout or "").strip())


def provision_github(project: str, *, org: str | None = None, lab: str | None = None,
                     env: dict | None = None, repo_creator=None,
                     collaborator=None) -> dict:
    """Ensure a private GitHub repo for cert-project ``project`` and add its
    certified members as collaborators (by their github login on the roster).
    Stamps ``github_repo`` on the record. ``org`` defaults to ``lab.md``'s
    github_org. Injectable ``repo_creator`` / ``collaborator`` seams default to
    the real ``gh`` calls and degrade gracefully when gh is missing."""
    cp = _cp.get(project, env)
    if cp is None:
        raise CertProvisionError(f"no cert-project named {project!r}")
    if not org:
        try:
            from .lab import load_lab_config
            org = load_lab_config().github_org
        except Exception:  # noqa: BLE001
            org = ""
    if not org:
        return {"ok": False, "error": "no_github_org",
                "detail": "no github org (set github_org in lab.md or pass --org)",
                "repo": None, "collaborators": []}
    repo_creator = repo_creator or _default_repo_creator
    collaborator = collaborator or _default_collaborator

    ok, detail = repo_creator(org, project)
    if not ok:
        return {"ok": False, "error": "repo_create_failed", "detail": detail,
                "repo": None, "collaborators": []}
    repo = f"{org}/{project}"
    _cp.upsert(project, lab=(lab or cp.lab), github_repo=repo, env=env)

    gh_map = member_github_map([m.lstrip("@") for m in cp.members])
    results: list[dict] = []
    for m in cp.members:
        h = m.lstrip("@").lower()
        login = gh_map.get(h)
        if not login:
            results.append({"handle": h, "status": "no_github",
                            "detail": "no github login on roster"})
            continue
        cok, cdetail = collaborator(org, project, login)
        results.append({"handle": h, "login": login,
                        "status": "ok" if cok else "fail", "detail": cdetail})
    return {"ok": True, "repo": repo, "collaborators": results}


# ---------------------------------------------------------------------------
# Teardown — archive the Slack channel + drop GitHub collaborators. Best-effort;
# called from issuance.delete_project after the certs are revoked (the revocation
# is the security-critical enforcement; infra teardown is cleanup).
# ---------------------------------------------------------------------------

def _default_channel_archiver(channel_id: str, *, token: str | None = None):
    """Slack ``conversations.archive``. Returns ``(ok, detail)``."""
    from ..dashboard import slack_notify as _sn
    tok = token or _sn._token()
    if not tok:
        return (False, "no slack token configured")
    try:
        import httpx
        r = httpx.post("https://slack.com/api/conversations.archive",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"channel": channel_id}, timeout=10)
        j = r.json()
        return (bool(j.get("ok")), "archived" if j.get("ok")
                else j.get("error", "archive_failed"))
    except Exception as exc:  # noqa: BLE001
        return (False, str(exc))


def _default_collab_remover(org: str, name: str, login: str):
    """Remove ``login`` as a collaborator on ``org/name``. Returns ``(ok, detail)``."""
    from . import project_provision as _pp
    if not _pp._gh_available():
        return (False, "gh CLI not installed")
    res = _pp._gh(["api", "-X", "DELETE",
                   f"repos/{org}/{name}/collaborators/{login}"])
    return (res.returncode == 0, (res.stderr or res.stdout or "").strip() or "removed")


def teardown(project: str, *, env: dict | None = None,
             channel_archiver=None, collab_remover=None) -> dict:
    """Tear down a cert-project's provisioned infra: archive its Slack channel and
    remove its GitHub collaborators. Best-effort + injectable; a project with no
    provisioned channel/repo is a clean no-op. Does NOT revoke certs or archive
    the registry record — that is ``issuance.delete_project``'s job."""
    cp = _cp.get(project, env)
    if cp is None:
        raise CertProvisionError(f"no cert-project named {project!r}")
    _ws, _tok = resolve_project_slack(project, env=env)
    archiver = channel_archiver or (
        lambda cid: _default_channel_archiver(cid, token=_tok or None))
    remover = collab_remover or _default_collab_remover
    out: dict = {"channel_archived": None, "collaborators_removed": []}
    if cp.slack_channel_id:
        ok, detail = archiver(cp.slack_channel_id)
        out["channel_archived"] = {"channel_id": cp.slack_channel_id,
                                   "ok": ok, "detail": detail}
    if cp.github_repo and "/" in cp.github_repo:
        org, name = cp.github_repo.split("/", 1)
        gh_map = member_github_map([m.lstrip("@") for m in cp.members])
        for m in cp.members:
            login = gh_map.get(m.lstrip("@").lower())
            if not login:
                continue
            ok, detail = remover(org, name, login)
            out["collaborators_removed"].append(
                {"handle": m.lstrip("@"), "login": login, "ok": ok, "detail": detail})
    return out


# ---------------------------------------------------------------------------
# Reconcile — bring a cert-project's Slack channel + GitHub repo membership back
# in line with its CERTIFIED members (someone added/removed by hand, or a member
# whose cert was revoked but who lingers). Injectable fetch/apply seams so it's
# testable without live Slack/gh; ``apply=False`` returns the drift without
# changing anything.
# ---------------------------------------------------------------------------

def _diff(desired, actual) -> tuple[list, list]:
    """Return ``(to_add, to_remove)`` as sorted lists, compared case-insensitively
    on the values themselves (values are ids/logins, already the compare key)."""
    d, a = {str(x) for x in desired}, {str(x) for x in actual}
    return sorted(d - a), sorted(a - d)


def _default_channel_ids_fetcher(channel_id: str, *, token: str | None = None) -> set:
    from ..dashboard import slack_notify as _sn
    return _sn._channel_member_ids(channel_id, token=token)


def _default_uid_resolver(handles, email_map, *, token: str | None = None):
    from ..dashboard import slack_notify as _sn
    out = {}
    for h in handles:
        email = email_map.get(h)
        out[h] = _sn._lookup_user_id_by_email(email, token=token) if email else None
    return out


def _default_kicker(channel_id: str, uid: str, *, token: str | None = None):
    from ..dashboard import slack_notify as _sn
    tok = token or _sn._token()
    if not tok:
        return (False, "no slack token configured")
    try:
        import httpx
        r = httpx.post("https://slack.com/api/conversations.kick",
                       headers={"Authorization": f"Bearer {tok}"},
                       json={"channel": channel_id, "user": uid}, timeout=10)
        j = r.json()
        return (bool(j.get("ok")), "kicked" if j.get("ok") else j.get("error", "kick_failed"))
    except Exception as exc:  # noqa: BLE001
        return (False, str(exc))


def _default_collaborators_fetcher(org: str, name: str) -> set:
    from . import project_provision as _pp
    if not _pp._gh_available():
        return set()
    res = _pp._gh(["api", f"repos/{org}/{name}/collaborators", "--jq", ".[].login"])
    if res.returncode != 0:
        return set()
    return {ln.strip() for ln in (res.stdout or "").splitlines() if ln.strip()}


def reconcile_slack(project: str, *, env: dict | None = None, apply: bool = True,
                    remove_extras: bool = True, ids_fetcher=None,
                    uid_resolver=None, inviter=None, kicker=None,
                    bot_uid: str | None = None) -> dict:
    """Sync a cert-project's Slack channel membership to its certified members:
    invite missing, kick extras (never ``bot_uid``). ``apply=False`` reports the
    drift without changing anything. Injectable seams; reports ``not_provisioned``
    if the project has no channel yet."""
    cp = _cp.get(project, env)
    if cp is None:
        raise CertProvisionError(f"no cert-project named {project!r}")
    if not cp.slack_channel_id:
        return {"ok": False, "error": "not_provisioned", "invited": [],
                "kicked": [], "unresolved": []}
    _ws, _tok = resolve_project_slack(project, env=env)
    ids_fetcher = ids_fetcher or (
        lambda cid: _default_channel_ids_fetcher(cid, token=_tok or None))
    uid_resolver = uid_resolver or (
        lambda hs, em: _default_uid_resolver(hs, em, token=_tok or None))
    inviter = inviter or (lambda cid, hs, *, member_email_map:
                          _default_inviter(cid, hs, member_email_map=member_email_map,
                                           token=_tok or None))
    kicker = kicker or (lambda cid, uid: _default_kicker(cid, uid, token=_tok or None))

    handles = [m.lstrip("@").lower() for m in cp.members]
    resolved = uid_resolver(handles, member_email_map(handles))
    desired_uids = {u for u in resolved.values() if u}
    unresolved = [h for h, u in resolved.items() if not u]
    actual = set(ids_fetcher(cp.slack_channel_id))

    to_invite = [h for h, u in resolved.items() if u and u not in actual]
    keep = desired_uids | ({bot_uid} if bot_uid else set())
    to_kick = sorted(actual - keep) if remove_extras else []

    invited, kicked = [], []
    if apply:
        if to_invite:
            inviter(cp.slack_channel_id, to_invite, member_email_map=member_email_map(to_invite))
            invited = to_invite
        for uid in to_kick:
            ok, _d = kicker(cp.slack_channel_id, uid)
            if ok:
                kicked.append(uid)
    return {"ok": True, "channel_id": cp.slack_channel_id,
            "invited": invited if apply else [], "to_invite": to_invite,
            "kicked": kicked if apply else [], "to_kick": to_kick,
            "unresolved": unresolved,
            "in_sync": not to_invite and not to_kick}


def reconcile_github(project: str, *, env: dict | None = None, apply: bool = True,
                     remove_extras: bool = True, collaborators_fetcher=None,
                     adder=None, remover=None, owner_logins=None) -> dict:
    """Sync a cert-project's GitHub repo collaborators to its certified members:
    add missing, remove extras (never ``owner_logins`` — the repo owner can't be a
    collaborator). ``apply=False`` reports drift only. Reports ``not_provisioned``
    if the project has no repo yet."""
    cp = _cp.get(project, env)
    if cp is None:
        raise CertProvisionError(f"no cert-project named {project!r}")
    if not (cp.github_repo and "/" in cp.github_repo):
        return {"ok": False, "error": "not_provisioned", "added": [], "removed": []}
    org, name = cp.github_repo.split("/", 1)
    collaborators_fetcher = collaborators_fetcher or _default_collaborators_fetcher
    adder = adder or _default_collaborator
    remover = remover or _default_collab_remover

    handles = [m.lstrip("@").lower() for m in cp.members]
    desired = set(member_github_map(handles).values())
    actual = set(collaborators_fetcher(org, name))
    protect = {str(l) for l in (owner_logins or [])}

    to_add = sorted(desired - actual)
    to_remove = sorted(actual - desired - protect) if remove_extras else []

    added, removed = [], []
    if apply:
        for login in to_add:
            ok, _d = adder(org, name, login)
            if ok:
                added.append(login)
        for login in to_remove:
            ok, _d = remover(org, name, login)
            if ok:
                removed.append(login)
    return {"ok": True, "repo": cp.github_repo,
            "added": added if apply else [], "to_add": to_add,
            "removed": removed if apply else [], "to_remove": to_remove,
            "in_sync": not to_add and not to_remove}


# ---------------------------------------------------------------------------
# Onboarding — is each certified member actually in the Slack workspace? On
# Free/Pro Slack there's no invite API, so we report status + let the PI hand out
# the workspace invite link; a paid admin token could auto-invite (not required).
# ---------------------------------------------------------------------------

def workspace_check(project: str, *, env: dict | None = None,
                    slack_resolver=None) -> dict:
    """For each certified member of ``project``, report whether they're in the
    Slack workspace (email resolves to a Slack uid). Reuses the unified
    ``lab_identity`` resolver. Returns ``{project, in_workspace: [...],
    missing: [...], no_email: [...]}`` — ``missing`` are members to hand the
    workspace invite link. No token/resolver ⇒ everyone with an email lands in
    ``missing`` (can't confirm), which is the safe onboarding default."""
    cp = _cp.get(project, env)
    if cp is None:
        raise CertProvisionError(f"no cert-project named {project!r}")
    from . import lab_identity as _li
    in_ws: list[dict] = []
    missing: list[dict] = []
    no_email: list[str] = []
    for m in cp.members:
        ident = _li.member_identity(m, slack_resolver=slack_resolver)
        h = m.lstrip("@")
        if ident is None or not ident.get("email"):
            no_email.append(h)
            continue
        row = {"handle": h, "email": ident["email"], "slack_uid": ident.get("slack_uid")}
        (in_ws if ident.get("in_workspace") else missing).append(row)
    return {"project": project, "in_workspace": in_ws, "missing": missing,
            "no_email": no_email}


__all__ = ["CertProvisionError", "slack_channel_name", "member_email_map",
           "member_github_map", "provision_slack", "provision_github", "teardown",
           "reconcile_slack", "reconcile_github", "workspace_check",
           "resolve_project_slack", "is_inter_group"]
