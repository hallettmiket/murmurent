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
       ``~/.config/wigamig/slack-token``).
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
    ``_`` is preserved (matches wigamig's identifier convention)."""
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


def _default_creator(name: str):
    from . import centre_provision as _prov
    return _prov.slack_create_channel(name, private=True)


def _default_inviter(channel_id: str, handles: list[str], *, member_email_map: dict):
    from ..dashboard import slack_notify as _sn
    return _sn.invite_members_to_channel(channel_id, handles,
                                         member_email_map=member_email_map)


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
    creator = creator or _default_creator
    inviter = inviter or _default_inviter

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

def _default_channel_archiver(channel_id: str):
    """Slack ``conversations.archive``. Returns ``(ok, detail)``."""
    from ..dashboard import slack_notify as _sn
    tok = _sn._token()
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
    archiver = channel_archiver or _default_channel_archiver
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


__all__ = ["CertProvisionError", "slack_channel_name", "member_email_map",
           "member_github_map", "provision_slack", "provision_github", "teardown"]
