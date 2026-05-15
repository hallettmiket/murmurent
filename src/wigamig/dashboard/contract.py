"""
Purpose: Data contract for the hi-fi dashboard. Mirrors ``hifi-data.jsx``
         field-for-field; the response shape is the source of truth — every
         panel JSX in ``docs/designer_dashboard/`` reads from this.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: Pydantic models only.
Output: ``DashboardResponse`` and the nested models that compose it.

Keep names and types aligned with ``hifi-data.jsx``. Adding a new field is
fine; renaming or retyping breaks the JSX-side panel that reads it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Top-level scalars
# ---------------------------------------------------------------------------


class TodayBlock(BaseModel):
    iso: str
    pretty: str
    weekday: str
    week: int


class MemberContact(BaseModel):
    """Per-member contact links surfaced in the footer.

    Every field is optional. The dashboard's ``FooterMeta`` falls back to
    the lab default (PI's contact) for fields the member didn't override.
    """

    email: str | None = None
    orcid: str | None = None
    bluesky: str | None = None
    github: str | None = None
    osf: str | None = None
    website: str | None = None


class MemberLocation(BaseModel):
    """Per-member office / lab location."""

    office: str | None = None
    dry_lab: str | None = None
    wet_labs: str | None = None
    address: str | None = None
    city: str | None = None
    department: str | None = None


class IdentityBlock(BaseModel):
    handle: str
    name: str
    role: str
    lab: str = "hallett"
    contact: MemberContact = MemberContact()
    location: MemberLocation = MemberLocation()
    # Phase 3: only set on the ``member`` block (always False on ``pi``).
    # When True, the front-end shows the persona toggle in the command bar.
    # Auto-detected from PI handle today; ``project lead → can_pi`` is v2.
    can_pi: bool = False
    is_active: bool = True  # Phase 13: deactivated members can read but not act
    # Phase A+: True iff this handle matches ``~/.wigamig/registrar``.
    # The lab dashboard uses this to show a cross-link to /registrar.
    is_registrar: bool = False


class MemberSettings(BaseModel):
    """Editable member profile settings — cross-machine, lives in
    ``<lab-mgmt>/members/<handle>.md`` so it follows the user to any
    machine they sign in from. Strictly contact + location info: the
    Obsidian/notebook fields have been moved to :class:`MachineSettings`
    because they are per-machine, not per-member.
    """

    # Contact
    email: str | None = None
    orcid: str | None = None
    bluesky: str | None = None
    github: str | None = None
    osf: str | None = None
    website: str | None = None
    # Location
    office: str | None = None
    dry_lab: str | None = None
    wet_labs: str | None = None
    address: str | None = None
    city: str | None = None
    department: str | None = None
    # Read-only Obsidian fields, surfaced for backwards-compat callers.
    # New code should read these from ``machine_settings`` instead — the
    # Member Profile modal no longer edits them.
    obsidian_vault_path: str | None = None
    obsidian_vault_name: str | None = None
    notebook_subfolder: str = "lab-notebook"
    oracle_subfolder: str = "oracle"
    # Phase 3 (2026-05-15): per-provider usernames. Keys are
    # :attr:`LabSettings.git_providers[*].id`; values are the user's
    # username on that provider. e.g. ``{"github": "hallettmiket"}``.
    # On read, the resolver back-fills ``git_logins["github"]`` from the
    # legacy ``contact.github`` field so older member.md files keep
    # working until they get re-saved.
    git_logins: dict[str, str] = {}


class MachineSettings(BaseModel):
    """Per-machine settings, stored in ``~/.wigamig/machine.yaml``.

    These paths differ between a user's laptop and a lab server, so they
    cannot live in the git-synced ``<lab-mgmt>/members/<handle>.md``.
    The dashboard reads this file once per request and exposes it as
    :attr:`DashboardResponse.machine_settings`.

    2026-05-14 layout: ``wigamig_base`` is the per-machine root for
    wigamig data and repos. The four sibling subfolders ``raw``,
    ``refined``, ``lab_notebooks``, ``repos`` live under it. The
    Obsidian vault is intentionally *not* under ``wigamig_base`` — it
    typically lives in the user's iCloud Drive and is treated as a
    separate, user-managed location that wigamig points into.
    """

    # Per-machine wigamig umbrella. Default ``~/wigamig``; on a lab
    # server this may resolve to ``/data/lab_vm/wigamig``.
    wigamig_base: str | None = None
    # Obsidian vault — separate from wigamig_base.
    obsidian_vault_path: str | None = None      # absolute path on this machine
    obsidian_vault_name: str | None = None      # for obsidian:// URLs
    notebook_subfolder: str = "lab-notebook"    # subfolder within the vault
    oracle_subfolder: str = "oracle"            # personal oracle subfolder
    # Legacy field: the server-side lab_base value as seen from this
    # machine. Retained so the install wizard's old fallback still
    # works; new code should use ``wigamig_base``.
    lab_base: str | None = None


# ---------------------------------------------------------------------------
# Attention queue
# ---------------------------------------------------------------------------


Severity = Literal["red", "amber", "ok"]
AttentionKind = Literal["SEA", "CERT", "EXP", "INV", "PROJ", "GRP"]


class AttentionAction(BaseModel):
    """One action button on an attention row.

    Marshalled to a 2-tuple ``[label, tone]`` in JSON to match
    ``hifi-data.jsx`` (which uses tuples). ``tone`` is one of
    ``""`` (default), ``"primary"``, or ``"tiger"``.
    """

    label: str
    tone: Literal["", "primary", "tiger"] = ""

    def to_pair(self) -> list[str]:
        return [self.label, self.tone]


class AttentionItem(BaseModel):
    sev: Severity
    kind: AttentionKind
    id: str
    text: str
    project: str
    age: str
    actions: list[list[str]]  # serialised as [[label, tone], ...]


# ---------------------------------------------------------------------------
# Stats strip
# ---------------------------------------------------------------------------


class AttentionStats(BaseModel):
    red: int
    amber: int
    ok: int


class SeasStats(BaseModel):
    closed_this_week: int
    delta_pct: int
    in_: int = Field(alias="in")
    out: int

    model_config = {"populate_by_name": True}


class ComplianceStats(BaseModel):
    expired: int
    expiring: int
    missing: int


class InventoryStats(BaseModel):
    expired: int
    low: int
    expiring30: int


class NotebookStats(BaseModel):
    entries_this_week: int
    last_written: str


class StatStrip(BaseModel):
    attention: AttentionStats
    seas: SeasStats
    compliance: ComplianceStats
    inventory: InventoryStats
    notebook: NotebookStats


# ---------------------------------------------------------------------------
# Projects + peers
# ---------------------------------------------------------------------------


Sensitivity = Literal["clinical", "restricted", "standard"]
RepoDestination = Literal["github", "local"]


class ProjectRow(BaseModel):
    name: str
    sens: Sensitivity
    lead: str
    choreo: str | None
    members: int
    open_seas: int
    last_activity: str
    # Phase 9: where to find the project's artefacts.
    github_repo: str | None = None       # e.g. "hallettmiket/dcis_sc_tutorial"
    github_pushed: bool = False          # local git repo has a GitHub remote
    slack_channel: str | None = None     # derived channel name, e.g. "proj_dcis_sc_tutorial"
    slack_channel_id: str | None = None  # real Slack channel ID from CHARTER.md
    slack_url: str | None = None         # full deep-link, when known
    # Phase 16: generalised repo destination. ``github`` matches the
    # original behaviour; ``local`` means the project's ``origin`` is a
    # bare repo on the lab VM rather than on github.com. ``remote_url``
    # is whatever ``git remote get-url origin`` returns regardless of
    # kind, so the JSX can render the correct link.
    repo_kind: RepoDestination = "github"
    remote_url: str | None = None
    # Installation (per-machine): raw/refined dirs may not exist if project not yet installed.
    refined_path: str | None = None      # e.g. ~/lab_vm/data/refined/<project>
    raw_path: str | None = None          # e.g. ~/lab_vm/data/raw/<project>
    raw_exists: bool = False
    refined_exists: bool = False
    # Item 3 (R2/R3): host on which the project's working tree actually
    # lives. ``"local"`` (default) means this laptop; anything else (e.g.
    # ``"lab-server"``) means the project is a remote-pointer placeholder
    # locally and the real tree is at ``remote_path`` on ``remote_ssh_host``.
    host: str = "local"
    remote_path: str | None = None
    remote_ssh_host: str | None = None  # ssh alias for "Open in VSCode Remote"
    # 2026-05-14: lifecycle status. "active" projects appear in the main
    # Projects list; "archived" projects move to the Decommissioned section
    # and can be unarchived from there. Files on disk are never touched
    # by archive/unarchive — only the CHARTER.md frontmatter changes.
    status: str = "active"
    decommissioned_at: str | None = None
    decommissioned_by: str | None = None


class PeerRow(BaseModel):
    handle: str
    name: str
    role: str
    tcps: Literal["ok", "expiring", "missing"]
    shared: int
    # Phase 7: per-peer involvement summary.
    # PI lens populates with the peer's complete set; member lens filters
    # to projects the viewer also belongs to.
    projects: list[str] = []
    open_seas: int = 0
    experiments: int = 0
    # Phase 13: roster status. "inactive" = file exists but person is on
    # leave / departed; cannot run wigamig actions but historical refs
    # (audit, SEAs, projects) still resolve to their handle.
    status: Literal["active", "inactive"] = "active"


class AgentRow(BaseModel):
    """Phase 7: an installed agent visible to the dashboard."""

    name: str
    description: str
    freeze: Literal["frozen", "personal"]
    model: str | None = None
    required_tools: list[str] = []
    disabled: bool = False  # personal agents only; frozen are always active


class OracleEntry(BaseModel):
    """Phase 7: one curated note in the lab oracle."""

    title: str
    excerpt: str
    author: str
    date: str  # ISO date or human-readable
    project: str | None = None
    path: str  # ``oracle/<file>.md`` for click-to-open


class PersonalOracleEntry(BaseModel):
    """One entry in the member's personal Oracle memory."""

    title: str
    excerpt: str
    date: str      # ISO date or human-readable
    path: str      # e.g. "oracle/memory_entry.md" for click-to-open


class PersonalOracleBlock(BaseModel):
    """The member's personal Oracle panel data."""

    folder: str            # short display path, e.g. "obsidian-lab/oracle/"
    entry_count: int = 0
    recent: list[PersonalOracleEntry] = []


class GitProvider(BaseModel):
    """One git origin server the lab supports for project repos.

    The lab declares a list of these (Phase 2 of the 2026-05-15
    providers refactor). Each member then registers their identity per
    provider (Phase 3, ``MemberSettings.git_logins``). Each project
    picks one provider id (Phase 4, charter ``git_provider:``). Today's
    flat ``LabSettings.github_org`` is preserved as a fallback when the
    lab.md has no ``git_providers`` block yet (migration path).
    """

    id: str                           # short kebab/underscore id; referenced from members + projects
    kind: str = "github"              # "github" | "gitea" | "local-bare"
    label: str = ""                   # human label, e.g. "GitHub (hallettmiket org)"
    # github: org name; gitea: base URL like https://lab-server/gitea;
    # local-bare: absolute server-side directory like
    # /data/lab_vm/wigamig/repos.
    target: str = ""


class LabSettings(BaseModel):
    """Lab-wide configuration — editable only by the PI or a designated admin.

    Storage layout convention (2026-05-15): ``lab_base`` is a ``host:/path``
    string ending in ``/wigamig``. Four data subdirs live underneath
    (``raw``, ``refined``, ``notebooks``, ``lab_oracle``) — no ``repos/``
    subdir (working clones live in each user's ``~/repos/``; git origins
    are managed by the declared :class:`GitProvider` list).
    """

    name: str = "hallett"                      # short identifier, used in paths
    display_name: str = "Hallett Lab"          # human label shown in the UI
    pi_handle: str = ""
    website: str | None = None                 # e.g. https://mikehallett.science
    admins: list[str] = []                     # handles with PI-level settings edit rights
    # Canonical server-side wigamig umbrella. Example:
    # ``lab-server.example.edu:/data/lab_vm/wigamig``. When unset the
    # dashboard shows the four storage paths as "—".
    lab_base: str | None = None
    # Phase 2 (2026-05-15): the lab's menu of git origin servers. Empty
    # list = pre-migration; the resolver auto-derives a single GitHub
    # entry from ``github_org`` to keep older lab.md files working.
    git_providers: list[GitProvider] = []
    # Legacy: single flat GitHub org. Kept for backwards-compat with
    # lab.md files that pre-date ``git_providers``. New code should
    # iterate ``git_providers`` instead.
    github_org: str = "hallettmiket"
    # Subpath under lab_base where bare git repos live (used by the
    # ``local-bare`` provider kind, if the lab declares one).
    git_repos_subpath: str = "repos"
    # Deprecated fields kept on the model for backwards-compat with older
    # lab.md frontmatters. Not surfaced in the redesigned UI; will be
    # removed once the migration completes.
    notebook_large_files_path: str | None = None
    lab_oracle_vault: str | None = None


class TrainingCertSpec(BaseModel):
    """Phase 14: one required cert from <lab-mgmt>/compliance.md."""

    code: str
    name: str
    short: str
    cadence_years: int | None = None
    audience: Literal["all", "lab", "clinical", "optional"] = "all"


class TrainingCertCell(BaseModel):
    code: str
    status: Literal["ok", "expiring", "expired", "missing", "n/a", "one_time"]
    expires: str | None = None


class TrainingMemberRow(BaseModel):
    handle: str
    name: str
    role: str
    member_status: Literal["active", "inactive"]
    certs: list[TrainingCertCell] = []


class TrainingComplianceBlock(BaseModel):
    """The whole panel: declared specs + per-member status grid."""

    required: list[TrainingCertSpec] = []
    members: list[TrainingMemberRow] = []
    yellow_threshold_days: int = 60


class JoinRequestRow(BaseModel):
    """Phase 8 / 9: project-join or project-create request row."""

    id: int
    requester: str  # ``@handle``
    project: str
    kind: Literal["project-join", "project-create"] = "project-join"
    state: Literal["pending", "approved", "declined"]
    justification: str = ""
    created_at: str | None = None
    resolved_at: str | None = None
    resolved_by: str | None = None
    decline_reason: str | None = None
    proposed_members: list[str] | None = None
    proposed_sensitivity: str | None = None
    proposed_lead: str | None = None


class CatalogEntryRow(BaseModel):
    """Phase 10: one offered SEA in our group's catalog."""

    slug: str
    title: str
    kind: Literal["skill", "experiment", "analysis"]
    contact: str
    description: str = ""
    turnaround_days: int | None = None
    prerequisites: list[str] = []
    accepting: bool = True
    created: str | None = None
    updated: str | None = None


class InboundRequestRow(BaseModel):
    """Phase 10: receptionist's view of a cross-group inbound request."""

    id: int
    catalog_slug: str
    from_group: str
    from_handle: str
    from_pi: str | None = None
    description: str = ""
    state: Literal["pending", "accepted", "declined", "fulfilled"]
    created_at: str | None = None
    routed_to: str | None = None
    decline_reason: str | None = None


# ---------------------------------------------------------------------------
# SEAs
# ---------------------------------------------------------------------------


SeaState = Literal["requested", "claimed", "complete", "examined", "concluded", "declined"]
SeaKind = Literal["skill", "experiment", "analysis"]
SeaDir = Literal["in", "out"]


class SeaRow(BaseModel):
    id: int
    dir: SeaDir
    state: SeaState
    kind: SeaKind
    who: str
    project: str
    desc: str
    age: str


# ---------------------------------------------------------------------------
# Experiment folders
# ---------------------------------------------------------------------------


class ExperimentRow(BaseModel):
    project: str
    folder: str
    status: str
    analysis: str
    performer: str
    date: str


# ---------------------------------------------------------------------------
# Notifications feed
# ---------------------------------------------------------------------------


class Notif(BaseModel):
    time: str
    text: str


# ---------------------------------------------------------------------------
# Compliance heatmap
# ---------------------------------------------------------------------------


HeatCell = Literal["ok", "exp", "amb", "mis", "na"]


class HeatmapRow(BaseModel):
    project: str
    sens: Sensitivity
    cells: list[HeatCell]


class Heatmap(BaseModel):
    members: list[str]
    rows: list[HeatmapRow]


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------


class InventoryItem(BaseModel):
    name: str
    expiry: str
    qty: str | None = None


class InventoryStock(BaseModel):
    reagents: list[int]  # [in_stock, capacity]
    kits: list[int]


class InventoryBlock(BaseModel):
    expired: list[InventoryItem]
    low: list[InventoryItem]
    expiring: list[InventoryItem]
    stock: InventoryStock


# ---------------------------------------------------------------------------
# Notebook (daily notes)
# ---------------------------------------------------------------------------


class NotebookDay(BaseModel):
    iso: str
    weekday: str
    word_count: int
    has_entry: bool
    is_today: bool = False


# Block kinds are a discriminated union by ``kind``.
class NbHeading(BaseModel):
    kind: Literal["h4"]
    text: str


class NbParagraph(BaseModel):
    kind: Literal["p"]
    text: str


class NbTask(BaseModel):
    kind: Literal["task"]
    done: bool
    text: str


class NbList(BaseModel):
    kind: Literal["list"]
    items: list[str]


class NbBlockquote(BaseModel):
    kind: Literal["blockquote"]
    text: str


class NbCode(BaseModel):
    kind: Literal["code"]
    text: str


class NbHint(BaseModel):
    """Renders as a small ⓘ button; full text appears in a click-to-open popover.
    First line of text is treated as the file path (displayed as <code>);
    remaining lines are the human-readable explanation."""

    kind: Literal["hint"]
    text: str


NbBlock = Annotated[
    NbHeading | NbParagraph | NbTask | NbList | NbBlockquote | NbCode | NbHint,
    Field(discriminator="kind"),
]


class NotebookToday(BaseModel):
    iso: str
    title: str
    tags: list[str]
    links_seas: list[int]
    links_exp: list[str]
    content: list[NbBlock]


class NotebookYesterday(BaseModel):
    iso: str
    title: str
    excerpt: str


class NotebookBlock(BaseModel):
    folder: str
    days: list[NotebookDay]
    today: NotebookToday
    yesterday_excerpt: NotebookYesterday


class InstallationRow(BaseModel):
    """One member-project-machine triple, persisted to disk by the install wizard.

    Manifest lives at ``~/.wigamig/installations/<project>.yaml`` — per-machine
    state, not shared across machines. If a user installs the same project on
    two machines, each machine has its own manifest under its own
    ``~/.wigamig/installations/`` directory.
    """

    member: str                                # ``@handle``
    project: str
    machine_type: Literal["laptop", "lab_server"]
    hostname: str | None = None                # ``None`` for laptops
    username: str                              # local OS account on the machine
    access: Literal["direct", "ssh"] = "direct"
    has_direct_access: bool = True
    lab_base: str | None = None
    raw_path: str | None = None
    refined_path: str | None = None
    notebook_path: str | None = None
    ssh_remote: str | None = None
    mount_point: str | None = None
    components: list[str] = []                 # infra installed (git, vscode, …)
    agents: list[str] = []                     # agent set provisioned
    status: Literal["active", "issues", "pending"] = "active"
    created: str | None = None                 # ISO date
    last_checked: str | None = None
    issues: list[str] = []


# ---------------------------------------------------------------------------
# Registrar (Phase A, read-only): the administrative layer above any lab.
# ---------------------------------------------------------------------------


class RegistrarMemberRow(BaseModel):
    """One member of a lab/core as the registrar sees them.

    Intentionally narrow: handle, role, and a one-line cert summary.
    The registrar must NEVER see notebooks, oracles, SEAs, or
    inventories — those stay inside the lab's own dashboard.
    """

    handle: str                              # ``@netname``
    full_name: str = ""
    role: str = "member"
    member_status: Literal["active", "inactive"] = "active"
    cert_summary: str = ""                   # e.g. "TCPS_2: ok · TOTP: ok"


class RegistrarLabRow(BaseModel):
    """One lab as the registrar sees it.

    Source of truth is the lab's own ``lab.md``; this row is what the
    registrar dashboard renders to the UI.
    """

    name: str                                # short ID, e.g. "hallett"
    display_name: str
    pi: str                                  # ``@handle``
    status: Literal["active", "archived"] = "active"
    created: str | None = None
    lab_mgmt_path: str                       # filesystem path (audit-only)
    slack_workspace: str | None = None
    github_org: str | None = None
    oracle_vault: str | None = None
    members: list[RegistrarMemberRow] = []
    member_count: int = 0
    # Set when the registry points at a path that no longer resolves —
    # the registrar should see this without the whole dashboard breaking.
    unresolved: bool = False
    unresolved_reason: str | None = None


class RegistrarCoreRow(BaseModel):
    """One core facility. Same shape as :class:`RegistrarLabRow` but the
    lead's field is ``leader`` (cores have core-leaders, not PIs).
    Phase E ships parity; later phases will add core-specific structure
    (accountant agent, SEA cost tracking, inventory)."""

    name: str
    display_name: str
    leader: str                              # @handle of the core leader
    status: Literal["active", "archived"] = "active"
    created: str | None = None
    lab_mgmt_path: str
    slack_workspace: str | None = None
    github_org: str | None = None
    oracle_vault: str | None = None
    members: list[RegistrarMemberRow] = []
    member_count: int = 0
    unresolved: bool = False
    unresolved_reason: str | None = None


class RegistrarCollaborationRow(BaseModel):
    """One cross-group collaboration."""

    name: str
    pis: list[str] = []
    groups: list[str] = []                   # short IDs of contributing labs/cores
    member_subset: dict[str, list[str]] = {} # by group: list of @handles
    oracle_vault: str | None = None
    status: Literal["active", "archived"] = "active"
    created: str | None = None


class RegistrarStats(BaseModel):
    total_labs: int = 0
    total_cores: int = 0
    total_collaborations: int = 0
    total_members: int = 0                   # deduped across labs


class RegistrarProfile(BaseModel):
    """The registrar's own contact + location, stored centre-level.

    Lives at ``<lab_info_root>/registrar.md`` (frontmatter), so it
    follows the registrar role rather than any lab they happen to also
    belong to. A registrar who is also a lab PI has both this profile
    (centre admin contact) and their lab's ``members/<handle>.md``
    profile (lab contact) — these are intentionally separate.
    """

    handle: str = ""                         # ``@netname``, set by snapshot
    full_name: str = ""
    title: str = ""                          # e.g. "VP Research", "Centre Director"
    # Contact
    email: str | None = None
    orcid: str | None = None
    website: str | None = None
    github: str | None = None
    # Location
    office: str | None = None
    address: str | None = None
    city: str | None = None
    department: str | None = None
    institution: str | None = None


# -- Phase C+: cross-group certification visibility ---------------


class RegistrarCertCell(BaseModel):
    """One cert's status for one member in one group (lab/core)."""

    code: str
    status: Literal["ok", "expiring", "expired", "missing", "n/a", "one_time"]
    expires: str | None = None


class RegistrarMemberCertRow(BaseModel):
    """A flat row joining (group, member, certs) for the centre-wide table.

    Members who belong to multiple labs appear once per lab — that's
    the correct shape because each lab declares its own compliance
    config, and a member's "missing" cert in lab A might be "n/a"
    (wrong audience) in lab B.
    """

    group: str                               # short ID (e.g. "hallett")
    group_display: str                       # e.g. "Hallett Lab"
    group_kind: Literal["lab", "core"] = "lab"
    handle: str                              # ``@netname``
    full_name: str = ""
    role: str = "member"
    member_status: Literal["active", "inactive"] = "active"
    certs: list[RegistrarCertCell] = []
    # Convenience flags so the JSX can colour the row without re-scanning:
    has_expired: bool = False
    has_expiring: bool = False
    has_missing: bool = False


class RegistrarCertAggregate(BaseModel):
    """Centre-wide compliance summary, surfaced as stat cards."""

    members_total: int = 0                   # unique handles across active groups
    members_with_issues: int = 0             # any expired / missing / expiring
    expired_count: int = 0                   # total expired cert cells
    expiring_count: int = 0                  # total expiring cert cells (< yellow threshold)
    missing_count: int = 0                   # total missing required certs


class RegistrarCertPanel(BaseModel):
    """The whole Certifications panel — aggregate + per-member rows."""

    aggregate: RegistrarCertAggregate = RegistrarCertAggregate()
    rows: list[RegistrarMemberCertRow] = []
    # Distinct cert specs seen across every active group, in discovery
    # order (labs first, then cores). The JSX uses ``spec.short`` as
    # the column header and ``spec.name`` + ``spec.cadence_years`` in
    # the tooltip — matching exactly how the PI's lab-internal
    # ``TrainingCompliancePanel`` renders these.
    cert_specs: list[TrainingCertSpec] = []


class RegistrarResponse(BaseModel):
    """The payload for ``GET /api/registrar/dashboard``.

    Deliberately does NOT include projects, SEAs, inventory, notebooks,
    personal Oracles, or any per-lab editable content. The registrar
    sees groups as opaque units. Certifications are explicitly in scope
    (institutional compliance is a centre-level concern, not lab-private).
    """

    registrar_handle: str                    # the actor (``@the_pi`` in dev)
    today: TodayBlock
    profile: RegistrarProfile = RegistrarProfile()
    labs: list[RegistrarLabRow] = []
    cores: list[RegistrarCoreRow] = []
    collaborations: list[RegistrarCollaborationRow] = []
    # 2026-05-14: PI-proposed collaboration requests (item #9). Loose dicts
    # rather than a typed row so the schema can evolve without breaking
    # the registrar UI's existing read paths.
    collaboration_requests: list[dict] = []
    stats: RegistrarStats = RegistrarStats()
    certs: RegistrarCertPanel = RegistrarCertPanel()


# ---------------------------------------------------------------------------
# Top-level response
# ---------------------------------------------------------------------------


Persona = Literal["member", "pi"]


class DashboardResponse(BaseModel):
    """The full payload for ``GET /api/dashboard``.

    1-to-1 with ``docs/designer_dashboard/hifi-data.jsx`` so panels can
    drop the ``window.DATA = …`` literal and ``fetch('/api/dashboard')``
    instead.
    """

    today: TodayBlock
    persona: Persona = "member"
    member: IdentityBlock
    pi: IdentityBlock
    member_settings: MemberSettings = MemberSettings()
    machine_settings: MachineSettings = MachineSettings()
    lab_settings: LabSettings = LabSettings()
    agents: list[AgentRow] = []
    oracle_recent: list[OracleEntry] = []
    oracle_drafts: list[OracleEntry] = []  # PI-only; awaiting approval
    personal_oracle: PersonalOracleBlock = PersonalOracleBlock(folder="oracle/")
    lab_oracle_folder: str = ""   # short display path for the lab oracle vault root
    requests_pending: list[JoinRequestRow] = []  # PI: all pending; member: theirs only
    requests_mine: list[JoinRequestRow] = []     # the viewer's outgoing requests
    group_members: list[str] = []                # all known @handles (for forms)
    sea_catalog: list[CatalogEntryRow] = []      # SEAs we offer (entire group sees)
    inbound_requests: list[InboundRequestRow] = []  # receptionist queue (PI only)
    training_compliance: TrainingComplianceBlock = TrainingComplianceBlock()
    attention: list[AttentionItem]
    stats: StatStrip
    spark: list[int]
    spark_labels: list[str]
    projects: list[ProjectRow]
    # Archived (soft-deleted) projects — surfaced as a separate collapsed
    # section in the UI so they don't visually disappear after decommission.
    archived_projects: list[ProjectRow] = []
    peers: list[PeerRow]
    seas: list[SeaRow]
    experiments: list[ExperimentRow]
    notifs: list[Notif]
    heatmap: Heatmap
    inventory: InventoryBlock
    notebook: NotebookBlock
    installations: list[InstallationRow] = []
    # Cached status of the lab's master folders on its lab_base server.
    # Rendered as a persistent green/yellow/red pill on the dashboard so
    # the user can see at a glance whether lab-server has been
    # bootstrapped. Empty dict when never probed — the pill shows "?"
    # and prompts the PI to click "check" inside Lab Settings.
    master_folders: dict = {}
