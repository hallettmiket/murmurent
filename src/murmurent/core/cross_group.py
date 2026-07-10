"""
Purpose: Storage + lifecycle for cross-group SEA requests.

           ``<lab-mgmt>/inbound/<id>.md``    requests other groups sent us
           ``<lab-mgmt>/outbound/<id>.md``   requests our members made

Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: Markdown files with frontmatter, one per request.
Output: ``InboundRequest`` / ``OutboundRequest`` dataclasses + helpers.

Lifecycle (inbound):

  pending     ← receptionist sees the request
  accepted    ← our PI says yes; routed to ``contact`` for actual work
  declined    ← our PI says no, with a reason
  fulfilled   ← actual work done (state transitions out of receptionist's view)

Lifecycle (outbound, our member made a cross-group request):

  draft       ← member proposed it, our PI hasn't OK'd outbound yet
  outbound-approved   ← our PI approved leaving the lab
  inbound-approved    ← target group's PI also said yes; their member is on it
  declined            ← either side said no
  fulfilled           ← done
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .frontmatter import dump_document, parse_file
from .repo import lab_mgmt_repo_root

INBOUND_SUBDIR = "inbound"
OUTBOUND_SUBDIR = "outbound"
ID_RE = re.compile(r"^(?P<id>\d+)\.md$")

InboundState = Literal["pending", "accepted", "declined", "fulfilled"]
OutboundState = Literal[
    "draft",
    "outbound-approved",
    "inbound-approved",
    "declined",
    "fulfilled",
]


class CrossGroupError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------


@dataclass
class InboundRequest:
    """A request another group sent us."""

    id: int
    catalog_slug: str  # which of our offered SEAs they want
    from_group: str  # ``imaging-lab``
    from_handle: str  # ``@diego``
    from_pi: str  # ``@imaging_pi``
    description: str = ""
    state: str = "pending"
    created_at: str | None = None
    routed_to: str | None = None  # our member who'll do the work
    decline_reason: str | None = None
    body: str = ""
    path: Path | None = None

    def to_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "id": self.id,
            "catalog_slug": self.catalog_slug,
            "from_group": self.from_group,
            "from_handle": self.from_handle,
            "from_pi": self.from_pi,
            "description": self.description,
            "state": self.state,
        }
        for key, value in (
            ("created_at", self.created_at),
            ("routed_to", self.routed_to),
            ("decline_reason", self.decline_reason),
        ):
            if value is not None:
                meta[key] = value
        return meta


def inbound_dir() -> Path:
    return lab_mgmt_repo_root() / INBOUND_SUBDIR


def inbound_path(req_id: int) -> Path:
    return inbound_dir() / f"{req_id}.md"


def parse_inbound(path: Path) -> InboundRequest:
    parsed = parse_file(path)
    meta = parsed.meta
    return InboundRequest(
        id=int(meta["id"]),
        catalog_slug=str(meta["catalog_slug"]),
        from_group=str(meta["from_group"]),
        from_handle=str(meta["from_handle"]),
        from_pi=str(meta.get("from_pi", "")),
        description=str(meta.get("description", "")),
        state=str(meta.get("state", "pending")),
        created_at=_opt_str(meta.get("created_at")),
        routed_to=_opt_str(meta.get("routed_to")),
        decline_reason=_opt_str(meta.get("decline_reason")),
        body=parsed.body,
        path=path,
    )


def iter_inbound() -> list[InboundRequest]:
    out: list[InboundRequest] = []
    d = inbound_dir()
    if not d.is_dir():
        return out
    for child in d.iterdir():
        m = ID_RE.match(child.name)
        if not m:
            continue
        try:
            out.append(parse_inbound(child))
        except Exception:
            continue
    out.sort(key=lambda r: r.id, reverse=True)
    return out


def next_inbound_id() -> int:
    used = [r.id for r in iter_inbound()]
    return (max(used) + 1) if used else 1


def write_inbound(req: InboundRequest) -> Path:
    d = inbound_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = inbound_path(req.id)
    body = req.body or _default_inbound_body(req)
    path.write_text(dump_document(req.to_meta(), body), encoding="utf-8")
    req.path = path
    return path


def file_inbound(
    *,
    catalog_slug: str,
    from_group: str,
    from_handle: str,
    from_pi: str = "",
    description: str = "",
    today: _dt.date | None = None,
) -> InboundRequest:
    today = today or _dt.date.today()
    req = InboundRequest(
        id=next_inbound_id(),
        catalog_slug=catalog_slug,
        from_group=from_group,
        from_handle=from_handle if from_handle.startswith("@") else f"@{from_handle}",
        from_pi=from_pi if (from_pi.startswith("@") or not from_pi) else f"@{from_pi}",
        description=description,
        state="pending",
        created_at=today.isoformat(),
    )
    write_inbound(req)
    return req


def accept_inbound(
    req: InboundRequest, *, routed_to: str, today: _dt.date | None = None
) -> InboundRequest:
    if req.state != "pending":
        raise CrossGroupError(
            f"inbound #{req.id} is already {req.state}; cannot accept."
        )
    req.state = "accepted"
    req.routed_to = routed_to if routed_to.startswith("@") else f"@{routed_to}"
    return req


def decline_inbound(
    req: InboundRequest, *, reason: str, today: _dt.date | None = None
) -> InboundRequest:
    if req.state != "pending":
        raise CrossGroupError(
            f"inbound #{req.id} is already {req.state}; cannot decline."
        )
    if not reason:
        raise CrossGroupError("decline requires a reason")
    req.state = "declined"
    req.decline_reason = reason
    return req


def _default_inbound_body(req: InboundRequest) -> str:
    return (
        f"# Inbound SEA request #{req.id}\n\n"
        f"From **{req.from_handle}** ({req.from_group}) — for our `"
        f"{req.catalog_slug}` offering.\n\n"
        f"## Description\n\n{req.description or '_(none provided)_'}\n"
    )


def _opt_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str) and not v.strip():
        return None
    return str(v)
