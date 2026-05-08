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
    closedThisWeek: int
    deltaPct: int
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
    entriesThisWeek: int
    lastWritten: str


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


class ProjectRow(BaseModel):
    name: str
    sens: Sensitivity
    lead: str
    choreo: str | None
    members: int
    openSeas: int
    lastActivity: str
    # Phase 9: where to find the project's artefacts.
    github_repo: str | None = None    # e.g. "hallettmiket/dcis_sc_tutorial"
    slack_channel: str | None = None  # e.g. "proj_dcis_sc_tutorial"
    slack_url: str | None = None      # full deep-link, when known
    refined_path: str | None = None   # /data/lab_vm/refined/<project>
    raw_path: str | None = None       # /data/lab_vm/raw/<project>


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
    """Phase 7: one curated note in the group oracle."""

    title: str
    excerpt: str
    author: str
    date: str  # ISO date or human-readable
    project: str | None = None
    path: str  # ``oracle/<file>.md`` for click-to-open


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


NbBlock = Annotated[
    NbHeading | NbParagraph | NbTask | NbList | NbBlockquote | NbCode,
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
    agents: list[AgentRow] = []
    oracle_recent: list[OracleEntry] = []
    oracle_drafts: list[OracleEntry] = []  # PI-only; awaiting approval
    requests_pending: list[JoinRequestRow] = []  # PI: all pending; member: theirs only
    requests_mine: list[JoinRequestRow] = []     # the viewer's outgoing requests
    group_members: list[str] = []                # all known @handles (for forms)
    sea_catalog: list[CatalogEntryRow] = []      # SEAs we offer (entire group sees)
    inbound_requests: list[InboundRequestRow] = []  # receptionist queue (PI only)
    attention: list[AttentionItem]
    stats: StatStrip
    spark: list[int]
    sparkLabels: list[str]
    projects: list[ProjectRow]
    peers: list[PeerRow]
    seas: list[SeaRow]
    experiments: list[ExperimentRow]
    notifs: list[Notif]
    heatmap: Heatmap
    inventory: InventoryBlock
    notebook: NotebookBlock
