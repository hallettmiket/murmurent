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


class PeerRow(BaseModel):
    handle: str
    name: str
    role: str
    tcps: Literal["ok", "expiring", "missing"]
    shared: int


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
