"""
Purpose: Build the hi-fi ``DashboardResponse`` from real murmurent data.
         Reuses the existing ``murmurent.core.dashboard`` snapshot for member /
         peers / SEAs / projects, then adds the new fields the redesign
         requires (today, attention, stats, spark, heatmap, notifs, notebook).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: ``handle`` (Western username) and the local lab-mgmt + project repos.
Output: ``DashboardResponse`` matching ``hifi-data.jsx`` field-for-field.

Where real data isn't wired yet, we return shape-correct placeholders marked
with a TODO comment so a later phase can swap them out without touching the
contract or the JSX panels.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from ..core import dashboard as core_dashboard
from ..core import inventory as inventory_core
from ..core.dashboard import DashboardSnapshot, _load_member_meta, _parse_certifications
from ..core.frontmatter import parse_file
from ..core.projects import (
    ProjectSummary,
    iter_local_projects,
    load_summary,
    read_remote_pointer,
)
from ..core.agents import load_registry as load_agent_registry
from ..core import compliance as compliance_core
from ..core import cross_group as xgroup
from ..core import membership as membership_core
from ..core.repo import lab_mgmt_repo_root, murmurent_repo_root
from ..core import requests as req_core
from ..core import lab_vm as _lab_vm
from ..core import sea_catalog as catalog_core
from ..core.sea import Sea, iter_seas
from . import audit_log
from . import contract as C
from . import machine_settings as _machine_settings_mod

def _pi_handle() -> str:
    """Resolve the PI handle from lab.md (fresh per call for tests)."""
    from ..core.lab import pi_handle as _resolved
    return _resolved()
NOTEBOOK_DIR_NAME = "lab-notebook"
PERSONAL_ORACLE_DIR = Path.home() / ".claude" / "agent-memory" / "oracle"
# Per-machine installation manifests, written by the install wizard.
# One YAML per project; see ``murmurent.dashboard.contract.InstallationRow``.
INSTALLATIONS_DIR = Path.home() / ".murmurent" / "installations"


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_response(
    handle: str,
    *,
    persona: str = "member",
    today: _dt.date | None = None,
) -> C.DashboardResponse:
    """Assemble the full ``DashboardResponse`` for ``handle``.

    ``persona`` controls how attention queue and compliance heatmap are
    scoped:

    * ``"member"`` (default): attention = my own outstanding work + cert
      gaps; heatmap = projects I'm in.
    * ``"pi"``: attention = lab-wide blockers (peer cert lapses, project
      backlogs); heatmap = every project on disk. Silently coerced to
      ``"member"`` if the handle isn't authorised to view the PI lens
      (handoff: "non-PI users never see the toggle").
    """
    today_d = today or _dt.date.today()
    norm = handle.lstrip("@").lower()
    is_pi = norm == _pi_handle().lower()
    # Persona is now derived from lab.md, not chosen by the user. The PI
    # always sees the PI lens; members always see the member lens. The
    # ``persona`` argument is retained for back-compat with tests + CLI
    # but is overridden whenever it disagrees with the user's actual role.
    effective_persona: str = "pi" if is_pi else "member"
    can_pi = is_pi

    snap = core_dashboard.build_snapshot(handle, today=today_d)

    # Scope projects to the viewer's lab so a laptop hosting multiple labs'
    # ``~/repos/<project>`` clones doesn't leak across groups (e.g. @mhallet
    # must not see @vdumeaux's vp1/vp2). A project belongs to the viewer if
    # CHARTER.md's ``lab:`` matches the viewer's lab, OR the viewer is a
    # named member of the project. Projects without a ``lab:`` field
    # (legacy charters from before this scoping) only appear when the
    # viewer is explicitly a member — that way a stale @mhallet-led project
    # without a ``lab:`` doesn't surface in @vdumeaux's dashboard.
    member_profile_for_lab = _load_member_profile(norm)
    viewer_lab = str(member_profile_for_lab.get("lab") or "")
    all_project_summaries = [load_summary(repo) for repo in iter_local_projects()]
    charter_names = {p.name for p in all_project_summaries}
    # Cert-projects are the authoritative project model; merge them into the one
    # project list, keyed by name. A cert-project with a matching CHARTER repo
    # enriches that row (its name is flagged is_cert below); one without a repo
    # appears on its own (a code repo is optional). With zero cert-projects this
    # loop is a no-op, so the list is identical to the CHARTER-only behaviour.
    from ..core import cert_projects as _cp
    cert_projects_all = _cp.iter_projects()
    cert_names = {cp.name for cp in cert_projects_all}
    cert_members_by_name = {cp.name: list(cp.members) for cp in cert_projects_all}
    cert_repos_by_name = {
        cp.name: [{"name": r.name, "role": r.role, "host": r.host,
                   "path": r.path, "overleaf": r.overleaf} for r in cp.repos]
        for cp in cert_projects_all}
    for cp in cert_projects_all:
        if cp.name in charter_names:
            continue
        all_project_summaries.append(ProjectSummary(
            name=cp.name,
            path=(Path(cp.code_repo).expanduser() if cp.code_repo
                  else Path(f"~/repos/{cp.name}").expanduser()),
            sensitivity=cp.sensitivity or "standard",
            lead=cp.lead or _pi_handle(),
            members=tuple(cp.members),
            choreography=cp.choreography,
            lab=cp.lab or None,
            status=cp.status,
        ))
    def _is_member(p) -> bool:
        return any(m.lstrip("@").lower() == norm for m in p.members)
    def _visible_to_viewer(p) -> bool:
        if p.lab and viewer_lab and p.lab.lower() == viewer_lab.lower():
            return True
        return _is_member(p)
    project_summaries_all_visible = [p for p in all_project_summaries if _visible_to_viewer(p)]
    project_summaries = [p for p in project_summaries_all_visible if p.status != "archived"]
    archived_summaries = [p for p in project_summaries_all_visible if p.status == "archived"]
    all_seas = list(_iter_all_seas())

    # Cross-link gate: True when this handle is the centre's registrar.
    from ..core import registrar as _registrar_mod
    is_registrar_handle = _registrar_mod.is_registrar(norm)

    member_block = _identity(snap.member, snap.full_name, snap.role)
    # ``lab_sudo`` comes from the member frontmatter — controls /security
    # route visibility. The PI is always implicit lab_sudo (otherwise no
    # one could ever be the first grantee in a fresh lab).
    member_profile_for_sudo = _load_member_profile(norm)
    lab_sudo = bool(member_profile_for_sudo.get("lab_sudo", False)) or is_pi
    member_block = member_block.model_copy(update={
        "can_pi": can_pi,
        "is_registrar": is_registrar_handle,
        "lab_sudo": lab_sudo,
    })

    member_profile = _load_member_profile(norm)
    lab_name = str(member_profile.get("lab") or "")

    return C.DashboardResponse(
        today=_today_block(today_d),
        persona=effective_persona,  # type: ignore[arg-type]
        member=member_block,
        pi=_pi_identity(),
        member_settings=_member_settings(member_profile),
        machine_settings=_machine_settings_mod.load(
            legacy_obsidian=member_profile.get("obsidian") if isinstance(member_profile, dict) else None,
        ),
        lab_settings=_lab_settings(lab_name),
        agents=_agents(),
        oracle_recent=_oracle_recent(limit=8),
        oracle_drafts=_oracle_drafts(effective_persona, limit=20),
        personal_oracle=_personal_oracle(limit=5),
        lab_oracle_folder=_lab_oracle_folder(lab_name),
        vault_health=_vault_health(),
        agents_activity=_agents_activity(limit=16),
        requests_pending=_requests_pending(effective_persona, norm),
        requests_mine=_requests_mine(norm),
        group_members=_group_members(),
        sea_catalog=_sea_catalog_rows(),
        inbound_requests=_inbound_rows(effective_persona),
        training_compliance=_training_compliance(today_d),
        attention=_attention(snap, effective_persona, project_summaries, today_d),
        stats=_stats(
            snap, all_seas, today_d,
            persona=effective_persona, projects=project_summaries,
        ),
        spark=_spark(all_seas, today_d),
        spark_labels=_spark_labels(today_d),
        projects=_projects(project_summaries, all_seas, today_d,
                           cert_names=cert_names, cert_members=cert_members_by_name,
                           cert_repos=cert_repos_by_name),
        archived_projects=_projects(archived_summaries, all_seas, today_d,
                                    cert_names=cert_names, cert_members=cert_members_by_name,
                                    cert_repos=cert_repos_by_name),
        peers=_peers(
            snap,
            project_summaries,
            all_seas,
            persona=effective_persona,
            viewer=norm,
        ),
        seas=_seas(snap, all_seas, today_d),
        experiments=_experiments(snap),
        notifs=_notifs(all_seas, today_d),
        heatmap=_heatmap(project_summaries, today_d, persona=effective_persona, member_handle=norm),
        inventory=_inventory(snap),
        notebook=_notebook(handle, today_d),
        installations=_installations(norm, effective_persona),
        master_folders=_master_folders_summary(),
    )


def _iter_all_seas():
    """Yield ``(project_name, Sea)`` for every *active* SEA in every local project.

    Archived SEAs (``archived: true`` in frontmatter) are skipped — they're
    soft-deleted via /api/sea/<project>/<id>/archive but the file is
    preserved, so they're still parseable.
    """
    for repo in iter_local_projects():
        try:
            summary = load_summary(repo)
        except Exception:
            continue
        for s in iter_seas(repo):
            if getattr(s, "archived", False):
                continue
            yield summary.name, s


# ---------------------------------------------------------------------------
# today + identity
# ---------------------------------------------------------------------------


def _today_block(today_d: _dt.date) -> C.TodayBlock:
    return C.TodayBlock(
        iso=today_d.isoformat(),
        pretty=today_d.strftime("%A, %B %-d, %Y"),
        weekday=today_d.strftime("%a"),
        week=int(today_d.strftime("%V")),
    )


# Lab-default contact + location: a fallback for any field a member hasn't set
# on their own profile. Deliberately EMPTY — the footer must not invent contact
# details a member never entered (it used to hardcode one specific PI's real
# ORCID / address / handles, which then leaked onto every install and every
# member). Blank here means the footer shows only what the member fills in via
# their Profile, so the footer and the Profile modal agree. A lab that wants
# shared defaults (e.g. a common building address) should declare them on its
# own record and have this read from there — not from source.
_LAB_DEFAULT_CONTACT = C.MemberContact()
_LAB_DEFAULT_LOCATION = C.MemberLocation()


def _identity(handle: str, full_name: str | None, role: str) -> C.IdentityBlock:
    """Build the current-member ``IdentityBlock`` with frontmatter overrides."""
    profile = _load_member_profile(handle)
    is_active = str(profile.get("status", "active")) == "active" if profile else True
    return C.IdentityBlock(
        handle=handle,
        name=full_name or profile.get("full_name") or handle,
        role=role,
        lab=str(profile.get("lab") or ""),
        contact=_merge_contact(profile.get("contact"),
                               fallback_email=str(profile.get("email") or "")),
        location=_merge_location(profile.get("location")),
        is_active=is_active,
    )


def _pi_identity() -> C.IdentityBlock:
    profile = _load_member_profile(_pi_handle())
    full_name = profile.get("full_name")
    return C.IdentityBlock(
        handle=_pi_handle(),
        name=str(full_name) if full_name else _pi_handle(),
        role="Principal Investigator",
        lab=str(profile.get("lab") or ""),
        contact=_merge_contact(profile.get("contact"),
                               fallback_email=str(profile.get("email") or "")),
        location=_merge_location(profile.get("location")),
    )


def _load_member_profile(handle: str) -> dict:
    """Return the full frontmatter dict for ``members/<handle>.md``."""
    from ..core.repo import lab_mgmt_repo_root as _root

    member_path = _root() / "members" / f"{handle}.md"
    if not member_path.is_file():
        return {}
    try:
        return dict(parse_file(member_path).meta or {})
    except Exception:
        return {}


def _merge_contact(meta: dict | None, *, fallback_email: str = "") -> C.MemberContact:
    """Merge a member's ``contact:`` frontmatter on top of the lab defaults.

    ``fallback_email`` surfaces the member's top-level ``email:`` (captured at
    join time) when they haven't set ``contact.email`` themselves — so a new
    member's known email shows in the footer + Profile instead of blank.
    """
    base = _LAB_DEFAULT_CONTACT.model_dump()
    if isinstance(meta, dict):
        for key in C.MemberContact.model_fields:
            if meta.get(key):
                base[key] = str(meta[key])
    if not base.get("email") and fallback_email:
        base["email"] = str(fallback_email)
    return C.MemberContact(**base)


def _merge_location(meta: dict | None) -> C.MemberLocation:
    """Merge a member's ``location:`` frontmatter on top of the lab defaults.

    Note: location merging is *per-field*, so a postdoc in a different
    building can override `office` while still inheriting the lab address.
    """
    base = _LAB_DEFAULT_LOCATION.model_dump()
    if isinstance(meta, dict):
        for key in C.MemberLocation.model_fields:
            if meta.get(key):
                base[key] = str(meta[key])
    return C.MemberLocation(**base)


# ---------------------------------------------------------------------------
# Member settings (profile modal)
# ---------------------------------------------------------------------------


def _member_settings(profile: dict) -> C.MemberSettings:
    """Build the ``MemberSettings`` block for the profile modal.

    Sources values from the member's frontmatter dict (already loaded
    via :func:`_load_member_profile`), with sensible defaults for
    notebook / oracle subfolder names that match how the rest of the
    dashboard resolves them.
    """
    contact = profile.get("contact") if isinstance(profile, dict) else None
    location = profile.get("location") if isinstance(profile, dict) else None
    obsidian = profile.get("obsidian") if isinstance(profile, dict) else None

    contact_d = contact if isinstance(contact, dict) else {}
    location_d = location if isinstance(location, dict) else {}
    obsidian_d = obsidian if isinstance(obsidian, dict) else {}

    vault_path = obsidian_d.get("vault_path") or profile.get("obsidian_vault_path")
    vault_name = obsidian_d.get("vault_name") or profile.get("obsidian_vault_name")
    notebook_subfolder = (
        obsidian_d.get("notebook_subfolder")
        or profile.get("notebook_subfolder")
        or "lab-notebook"
    )
    oracle_subfolder = (
        obsidian_d.get("oracle_subfolder")
        or profile.get("oracle_subfolder")
        or "oracle"
    )

    def _s(value) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s or None

    from ..core import git_providers as _gp
    return C.MemberSettings(
        obsidian_vault_path=_s(vault_path),
        obsidian_vault_name=_s(vault_name),
        notebook_subfolder=str(notebook_subfolder),
        oracle_subfolder=str(oracle_subfolder),
        email=_s(contact_d.get("email") or profile.get("email")),
        orcid=_s(contact_d.get("orcid")),
        bluesky=_s(contact_d.get("bluesky")),
        github=_s(contact_d.get("github")),
        osf=_s(contact_d.get("osf")),
        website=_s(contact_d.get("website")),
        office=_s(location_d.get("office")),
        dry_lab=_s(location_d.get("dry_lab")),
        wet_labs=_s(location_d.get("wet_labs")),
        address=_s(location_d.get("address")),
        city=_s(location_d.get("city")),
        department=_s(location_d.get("department")),
        git_logins=_gp.parse_logins(profile if isinstance(profile, dict) else {}),
    )


# ---------------------------------------------------------------------------
# Personal oracle (member's own knowledge base)
# ---------------------------------------------------------------------------


def _personal_oracle(*, limit: int = 5) -> C.PersonalOracleBlock:
    """Read the personal Oracle memory at ``~/.claude/agent-memory/oracle/``.

    Returns a shape-correct empty block when the directory is absent so
    the JSX panel can render a friendly empty state.
    """
    folder = PERSONAL_ORACLE_DIR
    # Short display: ``<vault>/oracle/`` style. Use the parent's name to
    # keep it human-readable without leaking the absolute path.
    display_folder = f"{folder.parent.name}/{folder.name}/"
    if not folder.is_dir():
        return C.PersonalOracleBlock(folder=display_folder, entry_count=0, recent=[])

    md_files = [p for p in folder.glob("*.md") if p.is_file()]
    md_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    entry_count = len(md_files)

    recent: list[C.PersonalOracleEntry] = []
    for path in md_files[:limit]:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        excerpt = _personal_oracle_excerpt(text)
        try:
            mtime = _dt.datetime.fromtimestamp(path.stat().st_mtime)
            date_str = mtime.date().isoformat()
        except OSError:
            date_str = ""
        recent.append(
            C.PersonalOracleEntry(
                title=path.stem,
                excerpt=excerpt,
                date=date_str,
                path=f"oracle/{path.name}",
            )
        )

    return C.PersonalOracleBlock(
        folder=display_folder,
        entry_count=entry_count,
        recent=recent,
    )


def _personal_oracle_excerpt(text: str, *, max_len: int = 120) -> str:
    """Return the first 120 chars of useful (non-heading) content."""
    parts: list[str] = []
    in_frontmatter = False
    for idx, line in enumerate(text.splitlines()):
        stripped = line.strip()
        # Skip YAML frontmatter (---\n...\n---) at the top of the file.
        if idx == 0 and stripped == "---":
            in_frontmatter = True
            continue
        if in_frontmatter:
            if stripped == "---":
                in_frontmatter = False
            continue
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        parts.append(stripped)
    out = " ".join(parts).strip()
    if len(out) > max_len:
        out = out[: max_len - 1] + "…"
    return out


def _lab_oracle_folder(lab_name: str) -> str:
    """Short display path for the lab oracle vault root.

    Always ``lab_oracle/`` under the new 2026-05-14 umbrella layout —
    individual users get subfolders inside it. The ``lab_name`` argument
    is retained for callers but no longer parameterizes the folder name.
    """
    return "lab_oracle/"


def _vault_health() -> C.VaultHealth:
    """Whether murmurent can actually READ the personal Oracle vault dir on this
    machine. Surfaces the macOS Full-Disk-Access failure that otherwise makes the
    Oracle personal + notebook tiers silently return empty. Best-effort."""
    try:
        from ..core import oracle_publish as _op
        p = _op.probe_personal_oracle()
        return C.VaultHealth(status=p.status, detail=p.detail, path=p.path)
    except Exception:  # noqa: BLE001
        return C.VaultHealth(status="unregistered", detail="")


_AGENT_LINE_RE = __import__("re").compile(r"^\[(\d\d:\d\d)\]\s+(\S+?):\s+(.*)$")
_ANSI_RE = __import__("re").compile(r"\x1b\[[0-9;]*m")


def _agents_activity(*, limit: int = 16) -> list[C.AgentActivity]:
    """Parse the tail of ``~/.murmurent/agents.log`` (the SubagentStop /
    PreToolUse(Agent) hook feed) into structured, newest-first entries so the
    dashboard can show a live agents panel. Best-effort — a missing log is just an
    empty feed."""
    import os
    log = Path(os.environ.get("MURMURENT_AGENT_LOG",
                              str(Path.home() / ".murmurent" / "agents.log")))
    if not log.is_file():
        return []
    try:
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out: list[C.AgentActivity] = []
    for raw in reversed(lines):                       # newest first
        line = _ANSI_RE.sub("", raw).strip()
        if not line:
            continue
        m = _AGENT_LINE_RE.match(line)
        if not m:
            continue
        time_s, agent, text = m.group(1), m.group(2), m.group(3)
        started = text.startswith("starting")
        if started:
            text = text.split("—", 1)[1].strip() if "—" in text else text
        out.append(C.AgentActivity(time=time_s, agent=agent, text=text[:200],
                                   started=started))
        if len(out) >= limit:
            break
    return out


def _master_folders_summary() -> dict:
    """Return the cached master-folders status for the current lab.

    The dashboard pill reads this on every refresh; live SSH probes
    only happen when the user clicks "check" or "init" in Lab Settings.
    Returns an empty dict when nothing has been cached yet so the JSX
    can render "?" + a prompt.
    """
    try:
        from ..core import master_folders as _mf
        lab_name = ""  # resolved from the viewer's lab.md via the request override
        summary = _mf.cached_summary(lab_name)
        return summary or {}
    except Exception:
        return {}


def _lab_settings(lab_name: str) -> C.LabSettings:
    """Read lab-wide settings from ``<lab-mgmt>/lab.md`` frontmatter."""
    from ..core import git_providers as _gp
    try:
        root = lab_mgmt_repo_root()
        lab_file = root / "lab.md"
        if lab_file.is_file():
            meta = parse_file(lab_file).meta or {}
            providers = [
                C.GitProvider(**p.to_dict())
                for p in _gp.resolve_providers(meta)
            ]
            kind = str(meta.get("kind") or "lab").lower()
            if kind not in ("lab", "core"):
                kind = "lab"
            return C.LabSettings(
                name=str(meta.get("name") or lab_name),
                display_name=str(meta.get("display_name") or f"{lab_name.capitalize()} Lab"),
                pi_handle=str(meta.get("pi") or _pi_handle()),
                kind=kind,
                website=meta.get("website") or None,
                admins=list(meta.get("admins") or []),
                lab_base=meta.get("lab_base") or None,
                git_providers=providers,
                github_org=str(meta.get("github_org") or ""),
                git_repos_subpath=str(meta.get("git_repos_subpath") or "repos"),
                notebook_host=str(meta.get("notebook_host") or ""),
                notebook_path=str(meta.get("notebook_path") or ""),
                obsidian_host=str(meta.get("obsidian_host") or ""),
                obsidian_path=str(meta.get("obsidian_path") or ""),
                lab_mgmt_path=str(root),
                notebook_large_files_path=meta.get("notebook_large_files_path") or None,
                lab_oracle_vault=meta.get("lab_oracle_vault") or _lab_oracle_folder(lab_name),
            )
    except Exception:
        pass
    try:
        _fallback_root = str(lab_mgmt_repo_root())
    except Exception:
        _fallback_root = ""
    return C.LabSettings(
        name=lab_name,
        pi_handle=_pi_handle(),
        lab_mgmt_path=_fallback_root,
        lab_oracle_vault=_lab_oracle_folder(lab_name),
    )


def _current_lab_settings() -> C.LabSettings:
    """Resolve :func:`_lab_settings` for the *current* lab.

    Reads the lab slug from ``lab.md`` via ``load_lab_config().lab``
    instead of hardcoding a lab name. Use this at call sites that
    previously passed the literal ``"hallett"``.
    """
    from ..core.lab import load_lab_config
    return _lab_settings(load_lab_config().lab)


# ---------------------------------------------------------------------------
# Attention queue
# ---------------------------------------------------------------------------


def _attention(
    snap: DashboardSnapshot,
    persona: str,
    projects: list[ProjectSummary],
    today_d: _dt.date,
) -> list[C.AttentionItem]:
    """Derive attention items.

    ``persona == "member"`` (default): user's own outstanding analysis,
    cert gaps on projects they're a member of, lab inventory.

    ``persona == "pi"``: lab-wide compliance lapses (every member's certs
    on every project), project backlog warnings, lab inventory. The PI
    typically does not need their *own* outstanding items in this view —
    those are tracked from the project leads' member-views.
    """
    if persona == "pi":
        return _attention_pi(projects, today_d)
    return _attention_member(snap)


def _attention_member(snap: DashboardSnapshot) -> list[C.AttentionItem]:
    items: list[C.AttentionItem] = []

    for item in snap.outstanding:
        if item.severity == "ok":
            continue
        items.append(
            C.AttentionItem(
                sev=item.severity,
                kind="EXP" if item.scope == "experiment" else "SEA",
                id=str(item.target),
                text=f"{item.scope.title()} {item.target} — {item.state}",
                project=item.project,
                age=f"{item.age_days}d" if item.age_days is not None else "—",
                actions=[["open", ""]],
            )
        )

    for row in snap.compliance:
        for cert in row.member_certs:
            if cert.name != "TCPS_2":
                continue
            if cert.status == "expired":
                items.append(
                    C.AttentionItem(
                        sev="red",
                        kind="CERT",
                        id="TCPS_2",
                        text="TCPS_2 expired — clinical access blocked",
                        project=row.project,
                        age=f"expired {cert.expires}" if cert.expires else "—",
                        actions=[["renew now", "primary"], ["guide", ""]],
                    )
                )
            elif cert.status == "missing" and row.sensitivity == "clinical":
                items.append(
                    C.AttentionItem(
                        sev="red",
                        kind="CERT",
                        id="TCPS_2",
                        text="TCPS_2 missing — clinical access blocked",
                        project=row.project,
                        age="—",
                        actions=[["enrol", "primary"]],
                    )
                )
            elif cert.status == "expiring":
                items.append(
                    C.AttentionItem(
                        sev="amber",
                        kind="CERT",
                        id="TCPS_2",
                        text=f"TCPS_2 expires {cert.expires}",
                        project=row.project,
                        age=cert.expires or "—",
                        actions=[["renew", "primary"]],
                    )
                )

    inv = snap.inventory_summary
    for row in inv.get("expired", []):
        items.append(
            C.AttentionItem(
                sev="red",
                kind="INV",
                id=row["name"],
                text=f"{row['name']} expired",
                project="—",
                age=str(row.get("expiry") or "—"),
                actions=[["order", "primary"]],
            )
        )
    for row in inv.get("low", []):
        items.append(
            C.AttentionItem(
                sev="amber",
                kind="INV",
                id=row["name"],
                text=f"{row['name']} {row.get('status', 'low')}",
                project="—",
                age="—",
                actions=[["order", "primary"]],
            )
        )

    return items


def _attention_pi(
    projects: list[ProjectSummary], today_d: _dt.date
) -> list[C.AttentionItem]:
    """PI lens: lab-wide cert lapses + project backlogs + inventory."""
    items: list[C.AttentionItem] = []

    # Per-project cert lapses across every member, on every clinical project.
    seen: set[tuple[str, str, str]] = set()  # de-dup (project, peer, cert_status)
    for project in projects:
        if project.sensitivity != "clinical":
            continue
        for raw in project.members:
            peer = raw.lstrip("@").lower()
            _name, _status, raw_certs = _load_member_meta(peer)
            certs = _parse_certifications(raw_certs, today_d)
            tcps = next((c for c in certs if c.name == "TCPS_2"), None)
            if tcps is None:
                continue
            key = (project.name, peer, tcps.status)
            if key in seen:
                continue
            seen.add(key)
            if tcps.status == "expired":
                items.append(
                    C.AttentionItem(
                        sev="red",
                        kind="CERT",
                        id=f"@{peer}",
                        text=(
                            f"@{peer} TCPS_2 expired — clinical access blocked "
                            f"on {project.name}"
                        ),
                        project=project.name,
                        age=f"expired {tcps.expires}" if tcps.expires else "—",
                        actions=[["nudge", "primary"], ["open profile", ""]],
                    )
                )
            elif tcps.status == "missing":
                items.append(
                    C.AttentionItem(
                        sev="red",
                        kind="CERT",
                        id=f"@{peer}",
                        text=(
                            f"@{peer} missing TCPS_2 — clinical access blocked "
                            f"on {project.name}"
                        ),
                        project=project.name,
                        age="—",
                        actions=[["nudge", "primary"]],
                    )
                )
            elif tcps.status == "expiring":
                items.append(
                    C.AttentionItem(
                        sev="amber",
                        kind="CERT",
                        id=f"@{peer}",
                        text=f"@{peer} TCPS_2 expires {tcps.expires}",
                        project=project.name,
                        age=tcps.expires or "—",
                        actions=[["nudge", "primary"]],
                    )
                )

    # Project backlog warnings: many open SEAs.
    BACKLOG_AMBER = 5
    BACKLOG_RED = 10
    for project in projects:
        from ..core.repo import CHARTER_FILENAME, ProjectRepo

        repo = ProjectRepo(
            path=project.path,
            charter_path=project.path / CHARTER_FILENAME,
            members_path=None,
        )
        open_count = sum(
            1 for s in iter_seas(repo) if s.state not in {"concluded", "declined"}
        )
        if open_count >= BACKLOG_RED:
            items.append(
                C.AttentionItem(
                    sev="red",
                    kind="PROJ",
                    id=project.name,
                    text=f"{open_count} open SEAs · backlog growing",
                    project=project.name,
                    age="—",
                    actions=[["review", "primary"]],
                )
            )
        elif open_count >= BACKLOG_AMBER:
            items.append(
                C.AttentionItem(
                    sev="amber",
                    kind="PROJ",
                    id=project.name,
                    text=f"{open_count} open SEAs · backlog growing",
                    project=project.name,
                    age="—",
                    actions=[["review", "primary"]],
                )
            )

    # Inventory: same on both lenses (lab-scoped).
    inv_summary = inventory_core
    for item in inv_summary.filter_expired(inv_summary.iter_items()):
        items.append(
            C.AttentionItem(
                sev="red",
                kind="INV",
                id=item.name,
                text=f"{item.name} expired",
                project="—",
                age=str(item.expiry or "—"),
                actions=[["order", "primary"]],
            )
        )
    for item in inv_summary.filter_low(inv_summary.iter_items()):
        items.append(
            C.AttentionItem(
                sev="amber",
                kind="INV",
                id=item.name,
                text=f"{item.name} {item.status}",
                project="—",
                age="—",
                actions=[["order", "primary"]],
            )
        )

    return items


# ---------------------------------------------------------------------------
# Stat strip
# ---------------------------------------------------------------------------


def _stats(
    snap: DashboardSnapshot,
    all_seas: list[tuple[str, Sea]],
    today_d: _dt.date,
    *,
    persona: str = "member",
    projects: list[ProjectSummary] | None = None,
) -> C.StatStrip:
    attn = _attention(snap, persona, projects or [], today_d)
    red = sum(1 for a in attn if a.sev == "red")
    amber = sum(1 for a in attn if a.sev == "amber")
    ok = sum(1 for a in attn if a.sev == "ok")

    closed_this_week, delta_pct = _seas_closed_this_week(all_seas, today_d)

    cert_expired = 0
    cert_expiring = 0
    cert_missing = 0
    seen: set[tuple[str, str]] = set()
    for row in snap.compliance:
        for cert in row.member_certs:
            key = (row.project, cert.name)
            if key in seen:
                continue
            seen.add(key)
            if cert.status == "expired":
                cert_expired += 1
            elif cert.status == "expiring":
                cert_expiring += 1
            elif cert.status == "missing":
                cert_missing += 1

    inv = snap.inventory_summary
    inv_expired = len(inv.get("expired", []))
    inv_low = len(inv.get("low", []))
    inv_exp30 = len(inv.get("expiring", []))

    nb = _notebook_stats(snap.member, today_d)

    return C.StatStrip(
        attention=C.AttentionStats(red=red, amber=amber, ok=ok),
        seas=C.SeasStats(
            **{
                "closed_this_week": closed_this_week,
                "delta_pct": delta_pct,
                "in": len(snap.seas_incoming),
                "out": len(snap.seas_outgoing),
            }
        ),
        compliance=C.ComplianceStats(
            expired=cert_expired, expiring=cert_expiring, missing=cert_missing
        ),
        inventory=C.InventoryStats(expired=inv_expired, low=inv_low, expiring30=inv_exp30),
        notebook=nb,
    )


def _seas_closed_this_week(
    all_seas: list[tuple[str, Sea]], today_d: _dt.date
) -> tuple[int, int]:
    """Return (closed_this_week, delta_pct_vs_4week_avg)."""
    week_start = today_d - _dt.timedelta(days=today_d.weekday())
    prior_start = week_start - _dt.timedelta(weeks=4)

    this_week = 0
    prior_4_weeks = 0
    for _name, s in all_seas:
        if s.state != "concluded":
            continue
        when = _date_or_none(s.concluded_at)
        if when is None:
            continue
        if week_start <= when <= today_d:
            this_week += 1
        elif prior_start <= when < week_start:
            prior_4_weeks += 1

    avg_prior = prior_4_weeks / 4 if prior_4_weeks else 0
    if avg_prior == 0:
        delta_pct = 0 if this_week == 0 else 100
    else:
        delta_pct = round((this_week - avg_prior) / avg_prior * 100)
    return this_week, delta_pct


def _date_or_none(value) -> _dt.date | None:
    if not value:
        return None
    try:
        return _dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def _datetime_or_none(value) -> _dt.datetime | None:
    """Parse an ISO datetime; assume UTC if naive. Returns None on garbage.

    Used by _notifs_from_sea_timestamps so the fallback notif builder can
    pass a real datetime (not just a date) into audit_log.humanize and
    keep the time-string format consistent with the audit-backed path.
    """
    if not value:
        return None
    s = str(value)
    try:
        # `fromisoformat` handles "...+00:00" and "...Z" (3.11+) when present.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = _dt.datetime.fromisoformat(s)
    except ValueError:
        # Fall back: maybe it's just a date string. Anchor to UTC midnight.
        d = _date_or_none(value)
        if d is None:
            return None
        return _dt.datetime.combine(d, _dt.time(0, 0), _dt.timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt


def _notebook_stats(handle: str, today_d: _dt.date) -> C.NotebookStats:
    folder = _notebook_folder(handle)
    if not folder.is_dir():
        return C.NotebookStats(entries_this_week=0, last_written="never")
    week_start = today_d - _dt.timedelta(days=today_d.weekday())
    files = sorted(folder.glob("*.md"))
    entries_this_week = 0
    last_written: _dt.date | None = None
    for f in files:
        try:
            d = _dt.date.fromisoformat(f.stem)
        except ValueError:
            continue
        if d >= week_start and d <= today_d:
            entries_this_week += 1
        if last_written is None or d > last_written:
            last_written = d
    if last_written is None:
        last = "never"
    elif last_written == today_d:
        last = "today"
    elif last_written == today_d - _dt.timedelta(days=1):
        last = "yesterday"
    else:
        last = last_written.isoformat()
    return C.NotebookStats(entries_this_week=entries_this_week, last_written=last)


# ---------------------------------------------------------------------------
# Sparkline (12 weekly counts of concluded SEAs)
# ---------------------------------------------------------------------------


def _spark(all_seas: list[tuple[str, Sea]], today_d: _dt.date) -> list[int]:
    counts = [0] * 12
    week_start = today_d - _dt.timedelta(days=today_d.weekday())
    for _name, s in all_seas:
        if s.state != "concluded":
            continue
        when = _date_or_none(s.concluded_at)
        if when is None:
            continue
        delta_weeks = (week_start - (when - _dt.timedelta(days=when.weekday()))).days // 7
        if 0 <= delta_weeks < 12:
            idx = 11 - delta_weeks
            counts[idx] += 1
    return counts


def _spark_labels(today_d: _dt.date) -> list[str]:
    week = int(today_d.strftime("%V"))
    return [f"w{((week - i - 1) % 53) + 1}" for i in range(11, -1, -1)]


# ---------------------------------------------------------------------------
# Projects + peers + SEAs + experiments
# ---------------------------------------------------------------------------


def _projects(
    projects: list[ProjectSummary],
    all_seas: list[tuple[str, Sea]],
    today_d: _dt.date,
    *,
    cert_names: set[str] | None = None,
    cert_members: dict[str, list[str]] | None = None,
    cert_repos: dict[str, list[dict]] | None = None,
) -> list[C.ProjectRow]:
    cert_names = cert_names or set()
    cert_members = cert_members or {}
    cert_repos = cert_repos or {}
    rows: list[C.ProjectRow] = []
    for p in projects:
        open_seas = 0
        last_activity: _dt.date | None = None
        for name, s in all_seas:
            if name != p.name:
                continue
            if s.state not in {"concluded", "declined"}:
                open_seas += 1
            for ts in (s.concluded_at, s.examined_at, s.completed_at, s.claimed_at):
                d = _date_or_none(ts)
                if d and (last_activity is None or d > last_activity):
                    last_activity = d
        # Slack channel: name derived; real ID from CHARTER.md slack_channel_id field.
        from ..core.lab import load_lab_config as _load_lab
        import re as _re
        import subprocess as _sp
        slack_channel = f"proj_{p.name}"
        _lab_cfg = _load_lab()
        ws = _lab_cfg.slack_workspace
        slack_url = (
            f"https://{ws}/channels/{slack_channel}"
            if ws and ws != "<set-on-first-publish>"
            else None
        )
        # Read Slack ID, repo_kind, and remote_url from CHARTER.md if present.
        charter_path = Path(f"~/repos/{p.name}/CHARTER.md").expanduser()
        slack_channel_id: str | None = None
        repo_kind: str = "github"
        charter_remote_url: str | None = None
        if charter_path.is_file():
            try:
                charter_text = charter_path.read_text(encoding="utf-8")
                m = _re.search(r"^slack_channel_id:\s*(\S+)", charter_text, _re.MULTILINE)
                if m:
                    slack_channel_id = m.group(1)
                m = _re.search(r"^repo_kind:\s*(\S+)", charter_text, _re.MULTILINE)
                if m:
                    repo_kind = m.group(1).strip().strip("'\"") or "github"
                m = _re.search(r"^remote_url:\s*['\"]?([^'\"]+?)['\"]?\s*$", charter_text, _re.MULTILINE)
                if m:
                    charter_remote_url = m.group(1)
            except OSError:
                pass
        # Remote presence: ``git remote get-url origin`` works for both
        # github- and local-kind projects; the URL form just differs.
        local_repo = Path(f"~/repos/{p.name}").expanduser()
        github_pushed = False
        remote_url: str | None = None
        if (local_repo / ".git").is_dir():
            try:
                out = _sp.check_output(
                    ["git", "-C", str(local_repo), "remote", "get-url", "origin"],
                    stderr=_sp.DEVNULL,
                )
                remote_url = out.decode(errors="replace").strip() or None
                github_pushed = bool(remote_url)
            except (_sp.CalledProcessError, FileNotFoundError):
                pass
        # If git didn't find a remote (e.g. .git not present on this machine)
        # but the charter recorded one, prefer the charter value.
        if remote_url is None:
            remote_url = charter_remote_url
        # Installation: check whether raw/refined dirs exist on this machine.
        raw_path = _lab_vm.project_raw_dir(p.name)
        refined_path = _lab_vm.project_refined_dir(p.name)
        # Item 3 (R2/R3): if this project is a remote-pointer dir, surface
        # the host so the dashboard can render a 🌐 chip + a vscode-remote://
        # link instead of a local file:// path.
        host = "local"
        remote_path: str | None = None
        remote_ssh_host: str | None = None
        pointer = read_remote_pointer(p.path)
        if pointer is not None:
            host, remote_path = pointer
            try:
                from ..core import hosts as _hosts
                resolved = _hosts.resolve(host)
                remote_ssh_host = resolved.ssh_host or host
            except Exception:
                remote_ssh_host = host  # best-effort fallback
        rows.append(
            C.ProjectRow(
                name=p.name,
                sens=p.sensitivity,  # type: ignore[arg-type]
                lead=p.lead,
                choreo=p.choreography,
                members=len(p.members),
                open_seas=open_seas,
                last_activity=_humanize(last_activity, today_d),
                github_repo=(
                    f"{_lab_cfg.github_org}/{p.name}" if _lab_cfg.github_org else None
                ),
                github_pushed=github_pushed,
                slack_channel=slack_channel,
                slack_channel_id=slack_channel_id,
                slack_url=slack_url,
                repo_kind=repo_kind,  # type: ignore[arg-type]
                remote_url=remote_url,
                raw_path=str(raw_path),
                refined_path=str(refined_path),
                raw_exists=raw_path.is_dir(),
                refined_exists=refined_path.is_dir(),
                host=host,
                remote_path=remote_path,
                remote_ssh_host=remote_ssh_host,
                status=p.status,
                decommissioned_at=p.decommissioned_at,
                decommissioned_by=p.decommissioned_by,
                is_cert=p.name in cert_names,
                cert_members=cert_members.get(p.name, []),
                repos=cert_repos.get(p.name, []),
            )
        )
    return rows


def _humanize(when: _dt.date | None, today_d: _dt.date) -> str:
    if when is None:
        return "—"
    delta = (today_d - when).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "yesterday"
    if delta < 7:
        return f"{delta}d ago"
    if delta < 30:
        return f"{delta // 7}w ago"
    return when.isoformat()


def _peers(
    snap: DashboardSnapshot,
    project_summaries: list[ProjectSummary],
    all_seas: list[tuple[str, Sea]],
    *,
    persona: str,
    viewer: str,
) -> list[C.PeerRow]:
    """Build the Group panel rows.

    Member lens (default): rows = peers in the viewer's projects;
    each peer's per-peer involvement is restricted to **shared**
    projects only (so a member never sees what a peer is doing on a
    project the viewer isn't on).

    PI lens: rows = every member of every project on disk;
    per-peer involvement is unrestricted across the whole lab.
    """
    norm_viewer = viewer.lstrip("@").lower()

    # Build the (peer -> set of projects) map under the viewer's lens.
    viewer_projects = {
        p.name for p in project_summaries
        if any(m.lstrip("@").lower() == norm_viewer for m in p.members)
    }

    if persona == "pi":
        # Whole lab. Start from the canonical roster
        # (<lab-mgmt>/members/*.md) so the PI sees newly-added or
        # inactive members even before they're on any project.
        from ..core import membership as _m

        peer_handles: dict[str, list[str]] = {}
        for rec in _m.iter_members():
            if rec.handle == norm_viewer:
                continue
            peer_handles.setdefault(rec.handle, [])
        # Then layer project-membership info on top.
        for p in project_summaries:
            for raw in p.members:
                peer = raw.lstrip("@").lower()
                if peer == norm_viewer:
                    continue
                peer_handles.setdefault(peer, []).append(p.name)
    else:
        # Member: only peers from shared projects, scoped to those projects.
        peer_handles = {}
        for p in project_summaries:
            if p.name not in viewer_projects:
                continue
            for raw in p.members:
                peer = raw.lstrip("@").lower()
                if peer == norm_viewer:
                    continue
                peer_handles.setdefault(peer, []).append(p.name)

    # Index SEAs and experiments by (project, handle) once.
    open_seas_index: dict[tuple[str, str], int] = {}
    for proj, sea in all_seas:
        if sea.state in {"concluded", "declined"}:
            continue
        for h in (sea.from_handle, sea.to_handle):
            key = (proj, h.lstrip("@").lower())
            open_seas_index[key] = open_seas_index.get(key, 0) + 1

    exp_index: dict[tuple[str, str], int] = {}
    for project in project_summaries:
        exp_root = project.path / "exp"
        if not exp_root.is_dir():
            continue
        for exp_dir in exp_root.glob("*_*"):
            notebook = exp_dir / "notebook.md"
            if not notebook.is_file():
                continue
            try:
                parsed = parse_file(notebook)
            except Exception:
                continue
            for performer in parsed.meta.get("performer") or []:
                key = (project.name, str(performer).lstrip("@").lower())
                exp_index[key] = exp_index.get(key, 0) + 1

    today_d = _dt.date.today()
    rows: list[C.PeerRow] = []
    for peer, projects in sorted(peer_handles.items()):
        unique_projects = sorted(set(projects))
        full_name, member_status, raw_certs = _load_member_meta(peer)
        certs = _parse_certifications(raw_certs, today_d)
        tcps = next((c for c in certs if c.name == "TCPS_2"), None)
        role = _peer_role(peer)
        open_seas = sum(open_seas_index.get((p, peer), 0) for p in unique_projects)
        experiments = sum(exp_index.get((p, peer), 0) for p in unique_projects)
        # Pull lab_sudo from member frontmatter so the PI's
        # SecurityAccessPanel can render grantee/candidate lists without
        # a separate round-trip. Cheap (one frontmatter parse per peer
        # which already happened above for full_name / certs).
        peer_profile = _load_member_profile(peer)
        rows.append(
            C.PeerRow(
                handle=peer,
                name=full_name or peer,
                role=role,
                tcps=tcps.status
                if tcps and tcps.status in {"ok", "expiring", "missing"}
                else "missing",
                shared=len(unique_projects) if persona != "pi" else
                len(set(unique_projects) & viewer_projects),
                projects=unique_projects,
                open_seas=open_seas,
                experiments=experiments,
                status="inactive" if member_status == "inactive" else "active",  # type: ignore[arg-type]
                lab_sudo=bool(peer_profile.get("lab_sudo", False)),
            )
        )
    return rows


def _peer_role(handle: str) -> str:
    """Re-export of the helper from core.dashboard, with safe fallback."""
    from ..core.dashboard import _peer_role as _core_peer_role  # type: ignore[attr-defined]

    try:
        return _core_peer_role(handle)
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Agents (Phase 7)
# ---------------------------------------------------------------------------


def _agents() -> list[C.AgentRow]:
    """Load the murmurent agent registry as a list of dashboard rows."""
    try:
        registry = load_agent_registry(murmurent_repo_root() / "agents")
    except Exception:
        return []
    rows: list[C.AgentRow] = []
    for record in registry:
        # The AgentRecord doesn't expose model + disabled directly, so
        # re-parse the source file for the extra fields.
        model, disabled = _agent_extras(record.path)
        rows.append(
            C.AgentRow(
                name=record.name,
                description=record.description,
                freeze=record.freeze,  # type: ignore[arg-type]
                model=model,
                required_tools=list(record.required_tools),
                disabled=disabled,
            )
        )
    return rows


def _agent_extras(path) -> tuple[str | None, bool]:
    if path is None:
        return None, False
    try:
        meta = parse_file(path).meta
    except Exception:
        return None, False
    model = meta.get("model")
    return (str(model) if model else None, bool(meta.get("disabled", False)))


# ---------------------------------------------------------------------------
# Group oracle (Phase 7)
# ---------------------------------------------------------------------------


def _oracle_recent(
    *, limit: int = 8, include_drafts: bool = False
) -> list[C.OracleEntry]:
    """Return the N most-recent group-oracle entries.

    By default, **excludes drafts** — the PI sees those in the drafts
    queue (rendered separately on the dashboard). Pass
    ``include_drafts=True`` to include them (e.g. for the PI's
    queue endpoint).
    """
    oracle_dir = lab_mgmt_repo_root() / "oracle"
    if not oracle_dir.is_dir():
        return []
    files = sorted(oracle_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    rows: list[C.OracleEntry] = []
    for path in files:
        try:
            doc = parse_file(path)
        except Exception:
            continue
        meta = doc.meta or {}
        status = str(meta.get("status", "")).lower()
        # Skip drafts (and declined) for member-visible feed.
        if not include_drafts and status in {"draft", "declined"}:
            continue
        title = str(meta.get("title") or path.stem)
        author = str(meta.get("author") or "")
        date = str(meta.get("date") or "")
        project = meta.get("project")
        excerpt = _first_paragraph(doc.body)
        rows.append(
            C.OracleEntry(
                title=title,
                excerpt=excerpt,
                author=author,
                date=date,
                project=str(project) if project else None,
                path=f"oracle/{path.name}",
            )
        )
        if len(rows) >= limit:
            break
    return rows


def _oracle_drafts(persona: str, *, limit: int = 20) -> list[C.OracleEntry]:
    """PI-only: oracle entries with ``status: draft`` awaiting approval."""
    if persona != "pi":
        return []
    oracle_dir = lab_mgmt_repo_root() / "oracle"
    if not oracle_dir.is_dir():
        return []
    rows: list[C.OracleEntry] = []
    files = sorted(oracle_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in files:
        try:
            doc = parse_file(path)
        except Exception:
            continue
        meta = doc.meta or {}
        if str(meta.get("status", "")).lower() != "draft":
            continue
        rows.append(
            C.OracleEntry(
                title=str(meta.get("title") or path.stem),
                excerpt=_first_paragraph(doc.body),
                author=str(meta.get("author") or ""),
                date=str(meta.get("date") or ""),
                project=str(meta.get("project")) if meta.get("project") else None,
                path=f"oracle/{path.name}",
            )
        )
        if len(rows) >= limit:
            break
    return rows


# ---------------------------------------------------------------------------
# Project-join requests (Phase 8)
# ---------------------------------------------------------------------------


def _to_request_row(r) -> C.JoinRequestRow:
    return C.JoinRequestRow(
        id=r.id,
        requester=r.requester,
        project=r.project,
        kind=r.kind,  # type: ignore[arg-type]
        state=r.state,  # type: ignore[arg-type]
        justification=r.justification,
        created_at=r.created_at,
        resolved_at=r.resolved_at,
        resolved_by=r.resolved_by,
        decline_reason=r.decline_reason,
        proposed_members=r.proposed_members,
        proposed_sensitivity=r.proposed_sensitivity,
        proposed_lead=r.proposed_lead,
    )


def _requests_pending(persona: str, viewer: str) -> list[C.JoinRequestRow]:
    """Pending requests visible to the viewer.

    PI lens: every pending request lab-wide (the approval queue).
    Member lens: only the viewer's own pending requests (status tracking).
    """
    norm = viewer.lstrip("@").lower()
    all_reqs = req_core.iter_requests()
    pending = [r for r in all_reqs if r.state == "pending"]
    if persona == "pi":
        return [_to_request_row(r) for r in pending]
    return [
        _to_request_row(r)
        for r in pending
        if r.requester.lstrip("@").lower() == norm
    ]


def _requests_mine(viewer: str) -> list[C.JoinRequestRow]:
    """The viewer's outgoing requests, regardless of state, newest first."""
    norm = viewer.lstrip("@").lower()
    mine = [
        r
        for r in req_core.iter_requests()
        if r.requester.lstrip("@").lower() == norm
    ]
    mine.sort(key=lambda r: r.id, reverse=True)
    return [_to_request_row(r) for r in mine[:10]]


def _group_members() -> list[str]:
    """All ``@handle``s declared in <lab-mgmt>/members/*.md (alphabetised).

    Used by FE forms (project-create member picker) so users can pick
    from a known list without typing handles by hand.
    """
    members_dir = lab_mgmt_repo_root() / "members"
    if not members_dir.is_dir():
        return []
    handles: set[str] = set()
    for path in members_dir.glob("*.md"):
        try:
            meta = parse_file(path).meta or {}
        except Exception:
            continue
        handle = meta.get("handle") or path.stem
        h = str(handle).strip()
        if not h:
            continue
        handles.add(h if h.startswith("@") else f"@{h}")
    return sorted(handles)


def _training_compliance(today_d: _dt.date) -> C.TrainingComplianceBlock:
    """Read compliance.md + each member's certs; build the panel data."""
    cfg = compliance_core.load_config()
    spec_rows = [
        C.TrainingCertSpec(
            code=s.code, name=s.name, short=s.short,
            cadence_years=s.cadence_years, audience=s.audience,  # type: ignore[arg-type]
        )
        for s in cfg.required
    ]
    member_rows: list[C.TrainingMemberRow] = []
    for rec in membership_core.iter_members():
        statuses = compliance_core.compute_member_status(
            handle=rec.handle,
            member_certs=rec.certifications,
            config=cfg,
            today=today_d,
        )
        cells = [
            C.TrainingCertCell(code=cs.code, status=cs.status, expires=cs.expires)  # type: ignore[arg-type]
            for cs in statuses
        ]
        member_rows.append(
            C.TrainingMemberRow(
                handle=rec.handle,
                name=rec.full_name,
                role=rec.role,
                member_status=rec.status,  # type: ignore[arg-type]
                certs=cells,
            )
        )
    return C.TrainingComplianceBlock(
        required=spec_rows,
        members=member_rows,
        yellow_threshold_days=cfg.yellow_threshold_days,
    )


def _sea_catalog_rows() -> list[C.CatalogEntryRow]:
    """All SEAs we offer. Visible to every member (transparency)."""
    rows: list[C.CatalogEntryRow] = []
    for entry in catalog_core.iter_catalog():
        rows.append(
            C.CatalogEntryRow(
                slug=entry.slug,
                title=entry.title,
                kind=entry.kind,  # type: ignore[arg-type]
                contact=entry.contact,
                description=entry.description,
                turnaround_days=entry.turnaround_days,
                prerequisites=list(entry.prerequisites),
                accepting=entry.accepting,
                created=entry.created,
                updated=entry.updated,
            )
        )
    return rows


def _inbound_rows(persona: str) -> list[C.InboundRequestRow]:
    """Receptionist queue. PI sees pending; members see only their own
    routed-to entries."""
    rows: list[C.InboundRequestRow] = []
    for req in xgroup.iter_inbound():
        # PI sees everything; member sees only requests routed to them.
        # For now, we don't filter at member level since members don't
        # currently have inbound visibility - PI handles all routing.
        rows.append(
            C.InboundRequestRow(
                id=req.id,
                catalog_slug=req.catalog_slug,
                from_group=req.from_group,
                from_handle=req.from_handle,
                from_pi=req.from_pi or None,
                description=req.description,
                state=req.state,  # type: ignore[arg-type]
                created_at=req.created_at,
                routed_to=req.routed_to,
                decline_reason=req.decline_reason,
            )
        )
    if persona != "pi":
        return []  # only the PI sees the receptionist box for v1
    return rows


def _first_paragraph(body: str, *, max_len: int = 240) -> str:
    """Pull the first non-blank, non-heading paragraph from markdown body."""
    buf: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if buf:
                break
            continue
        if stripped.startswith("#"):
            continue
        buf.append(stripped)
    out = " ".join(buf).strip()
    if len(out) > max_len:
        out = out[: max_len - 1] + "…"
    return out


def _seas(
    snap: DashboardSnapshot,
    all_seas: list[tuple[str, Sea]],
    today_d: _dt.date,
) -> list[C.SeaRow]:
    norm = snap.member.lower()
    # Index timestamps by (project_name, sea_id) so we don't re-walk per row.
    ts_index: dict[tuple[str, int], str] = {}
    for name, s in all_seas:
        for ts in (s.completed_at, s.claimed_at, s.examined_at, s.concluded_at):
            d = _date_or_none(ts)
            if d:
                ts_index[(name, s.id)] = f"{(today_d - d).days}d"
                break

    rows: list[C.SeaRow] = []
    for row in snap.all_seas:
        if row.state == "declined":
            continue
        from_ = row.from_handle.lstrip("@").lower()
        to_ = row.to_handle.lstrip("@").lower()
        if norm == to_:
            direction: C.SeaDir = "in"
            who = row.from_handle
        elif norm == from_:
            direction = "out"
            who = row.to_handle
        else:
            continue
        rows.append(
            C.SeaRow(
                id=row.id,
                dir=direction,
                state=row.state,  # type: ignore[arg-type]
                kind=row.kind,  # type: ignore[arg-type]
                who=who,
                project=row.project,
                desc=row.description,
                age=ts_index.get((row.project, row.id), "—"),
            )
        )
    return rows


def _experiments(snap: DashboardSnapshot) -> list[C.ExperimentRow]:
    rows: list[C.ExperimentRow] = []
    for e in snap.all_experiments:
        rows.append(
            C.ExperimentRow(
                project=e.project,
                folder=e.slug,
                status=e.status,
                analysis=e.analysis_status,
                performer=e.performer[0] if e.performer else "—",
                date=str(e.date) if e.date else "—",
            )
        )
    return rows


# ---------------------------------------------------------------------------
# Notifications (TODO: pull from audit log; for now, derive from recent SEAs)
# ---------------------------------------------------------------------------


def _notifs(all_seas: list[tuple[str, Sea]], today_d: _dt.date) -> list[C.Notif]:
    """Build the notifications feed.

    Prefers the lab-mgmt audit chain when it has any rows (Phase 5+).
    Falls back to deriving notifs from SEA state-change timestamps so a
    fresh setup with no audit history still surfaces something useful.
    """
    if audit_log.has_any_events(today=today_d):
        return _notifs_from_audit(today_d)
    return _notifs_from_sea_timestamps(all_seas, today_d)


def _notifs_from_audit(today_d: _dt.date) -> list[C.Notif]:
    """Read the most recent rows from ``<lab-mgmt>/audit/`` and format them."""
    now = _dt.datetime.combine(today_d, _dt.time(23, 59, 59), _dt.timezone.utc)
    events = audit_log.read_recent(days=14, limit=10, today=today_d)
    return [
        C.Notif(time=audit_log.humanize(e.ts, now=now), text=e.summary)
        for e in events
    ]


def _notifs_from_sea_timestamps(
    all_seas: list[tuple[str, Sea]], today_d: _dt.date
) -> list[C.Notif]:
    """Pre-Phase-5 fallback: derive notifs from SEA file timestamps.

    Uses ``audit_log.humanize`` so the time strings stay TZ-aware and
    match the audit-backed path's output ("just now" / "Nm ago" /
    "HH:MM" / "yesterday" / "Nd ago"). Earlier this used a naïve
    ``d == today_d`` string compare that broke during the UTC/local
    boundary hours (local says 2026-05-14, SEA timestamp is
    2026-05-15T00:08Z, mismatch → fallback to ISO date).
    """
    events: list[tuple[_dt.datetime, str, str]] = []
    for name, s in all_seas:
        for state, ts in (
            ("claimed", s.claimed_at),
            ("complete", s.completed_at),
            ("examined", s.examined_at),
            ("concluded", s.concluded_at),
        ):
            when = _datetime_or_none(ts)
            if when is None:
                continue
            events.append(
                (
                    when,
                    f"{s.to_handle if state in {'claimed', 'complete'} else s.from_handle} "
                    f"{state} SEA #{s.id} ({name})",
                    when,
                )
            )
    events.sort(key=lambda r: r[0], reverse=True)
    # Anchor "now" to the snapshot's today_d so test runs with a pinned
    # today stay deterministic; otherwise drift to current wall-clock UTC.
    now = _dt.datetime.combine(today_d, _dt.time(23, 59, 59), _dt.timezone.utc)
    return [
        C.Notif(time=audit_log.humanize(when, now=now), text=text)
        for when, text, _orig in events[:5]
    ]


# ---------------------------------------------------------------------------
# Compliance heatmap
# ---------------------------------------------------------------------------


def _heatmap(
    projects: list[ProjectSummary],
    today_d: _dt.date,
    *,
    persona: str = "member",
    member_handle: str = "",
) -> C.Heatmap:
    """Per-project × per-member compliance grid.

    ``persona == "member"``: rows restricted to projects the user is on;
    member axis is the union of those projects' members.

    ``persona == "pi"``: every project + every member across the lab.
    """
    if persona == "member" and member_handle:
        norm = member_handle.lstrip("@").lower()
        scoped = [
            p for p in projects
            if any(m.lstrip("@").lower() == norm for m in p.members)
        ]
        if scoped:
            projects = scoped
    member_set: list[str] = []
    for p in projects:
        for m in p.members:
            if m not in member_set:
                member_set.append(m)
    rows: list[C.HeatmapRow] = []
    for p in projects:
        cells: list[C.HeatCell] = []
        project_members = set(p.members)
        for m in member_set:
            if m not in project_members:
                cells.append("na")
                continue
            handle = m.lstrip("@").lower()
            _name, _status, raw_certs = _load_member_meta(handle)
            certs = _parse_certifications(raw_certs, today_d)
            tcps = next((c for c in certs if c.name == "TCPS_2"), None)
            if tcps is None or tcps.status == "missing":
                cells.append("mis")
            elif tcps.status == "expired":
                cells.append("exp")
            elif tcps.status == "expiring":
                cells.append("amb")
            else:
                cells.append("ok")
        rows.append(C.HeatmapRow(project=p.name, sens=p.sensitivity, cells=cells))  # type: ignore[arg-type]
    return C.Heatmap(members=member_set, rows=rows)


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


def _inventory(snap: DashboardSnapshot) -> C.InventoryBlock:
    inv = snap.inventory_summary

    def _row(r: dict) -> C.InventoryItem:
        qty = r.get("qty")
        unit = r.get("unit")
        qty_str = f"{qty} {unit}" if qty is not None and unit else (str(qty) if qty is not None else None)
        return C.InventoryItem(
            name=r["name"],
            expiry=str(r.get("expiry") or "—"),
            qty=qty_str,
        )

    items = list(inventory_core.iter_items())
    in_stock_reagents = sum(1 for i in items if i.status == "in_stock")
    total_reagents = len(items)
    # Kits are a subset; without a tagged "kit" type, default to half/half
    # proxy. TODO: add a `kind:` field to inventory items.
    kits_in_stock = sum(1 for i in items if i.unit == "rxn" or "kit" in i.name)
    kits_total = max(kits_in_stock, sum(1 for i in items if "kit" in i.name) or 1)

    return C.InventoryBlock(
        expired=[_row(r) for r in inv.get("expired", [])],
        low=[_row(r) for r in inv.get("low", [])],
        expiring=[_row(r) for r in inv.get("expiring", [])],
        stock=C.InventoryStock(
            reagents=[in_stock_reagents, max(total_reagents, in_stock_reagents)],
            kits=[kits_in_stock, kits_total],
        ),
    )


# ---------------------------------------------------------------------------
# Notebook (Obsidian-style daily notes)
# ---------------------------------------------------------------------------


def _notebook_folder(handle: str) -> Path:
    """Resolve the daily-notes folder for ``handle``.

    Resolution order:
      1. Member profile ``obsidian.vault_path`` + ``notebook_subfolder``
         — lets per-user vault config drive the path without a global env var.
      2. :func:`notebook_actions.notebook_folder` (env var / system vault).
      In both cases, if a ``<handle>/`` subdirectory exists inside the
      resolved folder it is used, enabling multi-user demo layouts.
    """
    from . import notebook_actions

    # Try member profile first
    profile = _load_member_profile(handle)
    obsidian = profile.get("obsidian") if isinstance(profile, dict) else None
    obsidian_d = obsidian if isinstance(obsidian, dict) else {}
    vault_path_str = obsidian_d.get("vault_path") or profile.get("obsidian_vault_path")
    notebook_sub = (
        obsidian_d.get("notebook_subfolder")
        or profile.get("notebook_subfolder")
        or "lab-notebook"
    )
    if vault_path_str:
        vault_path = Path(str(vault_path_str)).expanduser()
        if vault_path.is_dir():
            base = vault_path / notebook_sub
            per_user = base / handle
            if per_user.is_dir():
                return per_user
            if base.is_dir():
                return base

    # Fallback to env-var / system vault
    base = notebook_actions.notebook_folder()
    per_user = base / handle
    if per_user.is_dir():
        return per_user
    return base


def _notebook(handle: str, today_d: _dt.date) -> C.NotebookBlock:
    folder = _notebook_folder(handle)
    days = _notebook_days(folder, today_d)
    today_entry = _notebook_today(folder, today_d)
    yesterday = _notebook_yesterday(folder, today_d)
    # Two-level display: vault/notebook/ or vault/notebook/handle/
    parts = [folder.parent.name, folder.name]
    display_folder = "/".join(parts) + "/"
    return C.NotebookBlock(
        folder=display_folder,
        days=days,
        today=today_entry,
        yesterday_excerpt=yesterday,
    )


def _notebook_days(folder: Path, today_d: _dt.date) -> list[C.NotebookDay]:
    if not folder.is_dir():
        return _empty_week(today_d)
    rows: list[C.NotebookDay] = []
    for offset in range(7):
        d = today_d - _dt.timedelta(days=offset)
        path = folder / f"{d.isoformat()}.md"
        word_count = 0
        has_entry = path.is_file()
        if has_entry:
            try:
                word_count = len(path.read_text(encoding="utf-8").split())
            except OSError:
                word_count = 0
        rows.append(
            C.NotebookDay(
                iso=d.isoformat(),
                weekday=d.strftime("%a"),
                word_count=word_count,
                has_entry=has_entry,
                is_today=(d == today_d),
            )
        )
    return rows


def _empty_week(today_d: _dt.date) -> list[C.NotebookDay]:
    return [
        C.NotebookDay(
            iso=(today_d - _dt.timedelta(days=offset)).isoformat(),
            weekday=(today_d - _dt.timedelta(days=offset)).strftime("%a"),
            word_count=0,
            has_entry=False,
            is_today=(offset == 0),
        )
        for offset in range(7)
    ]


def _notebook_today(folder: Path, today_d: _dt.date) -> C.NotebookToday:
    """Parse ``folder/<today>.md`` into the discriminated content tree.

    TODO: swap this for a real markdown→block-tree parser. For now, return
    an empty content list with the right shape so the JSX panel can render
    a friendly empty state.
    """
    path = folder / f"{today_d.isoformat()}.md"
    title = today_d.strftime("%-d %B %Y")
    if not path.is_file():
        # Show the user the path their click-edit will actually create,
        # not a hard-coded ~/lab-notebook reference. Prefer ~ when the
        # path is under the user's home; otherwise show the full path.
        try:
            display = "~/" + str(path.relative_to(Path.home()))
        except ValueError:
            display = str(path)
        return C.NotebookToday(
            iso=today_d.isoformat(),
            title=title,
            tags=[],
            links_seas=[],
            links_exp=[],
            content=[
                C.NbHeading(kind="h4", text="No entry yet"),
                C.NbHint(
                    kind="hint",
                    text=(
                        f"{display}\n"
                        "Opens in Obsidian when the folder is inside your "
                        "registered vault; otherwise falls back to $EDITOR."
                    ),
                ),
            ],
        )

    try:
        parsed = parse_file(path)
    except Exception:
        return C.NotebookToday(
            iso=today_d.isoformat(),
            title=title,
            tags=[],
            links_seas=[],
            links_exp=[],
            content=[C.NbParagraph(kind="p", text="(could not parse front-matter)")],
        )

    tags = [str(t) for t in parsed.meta.get("tags", []) or []]
    links_seas = [int(x) for x in parsed.meta.get("links_seas", []) or [] if str(x).isdigit()]
    links_exp = [str(x) for x in parsed.meta.get("links_exp", []) or []]
    blocks = _parse_markdown_blocks(parsed.body)
    return C.NotebookToday(
        iso=today_d.isoformat(),
        title=title,
        tags=tags,
        links_seas=links_seas,
        links_exp=links_exp,
        content=blocks,
    )


def _notebook_yesterday(folder: Path, today_d: _dt.date) -> C.NotebookYesterday:
    yest = today_d - _dt.timedelta(days=1)
    path = folder / f"{yest.isoformat()}.md"
    title = yest.strftime("%-d %B %Y")
    if not path.is_file():
        return C.NotebookYesterday(
            iso=yest.isoformat(),
            title=title,
            excerpt="(no entry yesterday)",
        )
    try:
        body = path.read_text(encoding="utf-8")
    except OSError:
        body = ""
    excerpt_lines = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")]
    excerpt = " ".join(excerpt_lines)[:280]
    return C.NotebookYesterday(iso=yest.isoformat(), title=title, excerpt=excerpt or "—")


def _parse_markdown_blocks(body: str):
    """Minimal markdown → block-tree.

    Supports H4, paragraph (with [[wikilinks]]), task ``- [ ] / - [x]``,
    bullet list, blockquote, fenced code. Anything else collapses to a
    paragraph. This is a pragmatic parser — the redesign explicitly
    constrains the notebook to these block kinds (see HANDOFF.md).
    """
    blocks: list = []
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        if stripped.startswith("```"):
            buf: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            blocks.append(C.NbCode(kind="code", text="\n".join(buf)))
            continue
        if stripped.startswith("#"):
            # Any ATX heading (#, ##, ###, #### …). The block model only
            # carries an h4 kind, so every level collapses to it — but we
            # must still consume the line here. Routing non-h4 headings to
            # the paragraph branch below would leave ``i`` unadvanced (that
            # branch refuses to consume ``#``-led lines), spinning forever.
            blocks.append(C.NbHeading(kind="h4", text=stripped.lstrip("#").strip()))
            i += 1
            continue
        if stripped.startswith(("- [ ]", "- [x]", "- [X]")):
            done = stripped[3].lower() == "x"
            text = stripped[6:].strip()
            blocks.append(C.NbTask(kind="task", done=done, text=text))
            i += 1
            continue
        if stripped.startswith("- "):
            items: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("- "):
                items.append(lines[i].strip()[2:].strip())
                i += 1
            blocks.append(C.NbList(kind="list", items=items))
            continue
        if stripped.startswith("> "):
            buf2: list[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                buf2.append(lines[i].strip().lstrip(">").strip())
                i += 1
            blocks.append(C.NbBlockquote(kind="blockquote", text=" ".join(buf2)))
            continue
        # Default: paragraph (consume contiguous non-blank, non-special lines).
        buf3: list[str] = []
        while (
            i < len(lines)
            and lines[i].strip()
            and not lines[i].strip().startswith(("#", "- ", "> ", "```"))
        ):
            buf3.append(lines[i].strip())
            i += 1
        blocks.append(C.NbParagraph(kind="p", text=" ".join(buf3)))
    return blocks


def _installations(viewer_handle: str, persona: str) -> list[C.InstallationRow]:
    """Load per-machine installation manifests from ``~/.murmurent/installations/``.

    Each YAML file (one per installed project on this machine) is parsed
    into an :class:`InstallationRow`. Member personas see only their own
    rows; the PI sees every row written on **this** machine. Cross-machine
    aggregation is intentionally out of scope here — a future "publish"
    step could push selected manifests into lab-mgmt for the PI to see
    every member's installs from any vantage point.
    """
    if not INSTALLATIONS_DIR.is_dir():
        return []

    import yaml

    expected_member = f"@{viewer_handle.lstrip('@')}".lower()
    rows: list[C.InstallationRow] = []
    for path in sorted(INSTALLATIONS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        try:
            row = C.InstallationRow(**data)
        except Exception:
            # Don't crash the whole dashboard for one bad manifest.
            continue
        if persona != "pi" and row.member.lower() != expected_member:
            continue
        rows.append(row)
    return rows
