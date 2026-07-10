"""
Purpose: External customer registry — non-Schulich industry/academic
         clients who book core services without a lab affiliation.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-22
Input: ``<lab_mgmt>/external_customers/<id>.md`` files (frontmatter).
Output: ``ExternalCustomer`` records + CRUD helpers used by Phase 6e
        registrar endpoints and Phase 6d invoice rendering.

Per plan §9: every Schulich-affiliated user has a member file with a
``lab:`` field that maps to a lab in the centre registry. External
customers don't fit that model — they may be one-off industry users
or recurring academic-external clients. We park them in a side-table
distinct from the lab roster so:

  - Billing knows where to send the PDF (company billing contact +
    PO number rather than a Western lab fund code).
  - The lab roster validator can recognise ``<id>`` as a legitimate
    requester_lab value rather than rejecting it as ``unknown``.
  - The registrar dashboard has a clear place to add / edit them
    without polluting the per-lab members/ dir.

ID is a kebab-case slug (e.g. ``acme-biosciences``, ``pi-jdoe``);
matches the filename stem and is what booking requests carry in their
``requester_lab`` field.
"""

from __future__ import annotations

import datetime as _dt
import re as _re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .frontmatter import parse_file
from .repo import lab_mgmt_repo_root


EXTERNAL_CUSTOMERS_SUBDIR = "external_customers"
_ID_RE = _re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")


class ExternalCustomerError(ValueError):
    """External customer mutation failed (bad id, duplicate, …)."""


@dataclass
class ExternalCustomer:
    """One non-Schulich client. Stored as frontmatter at
    ``<lab_mgmt>/external_customers/<id>.md``."""

    id: str                                # filename stem, kebab-case
    name: str                              # display ('ACME Biosciences')
    kind: str = "industry"                 # industry | academic_external | hospital
    billing_contact: str = ""              # email
    billing_address: str = ""              # multi-line
    po_number: str = ""                    # current PO (rotates)
    tax_id: str = ""                       # for non-Western billing
    status: str = "active"                 # active | archived
    contact_name: str = ""                 # human point-of-contact
    notes: str = ""
    created: str = ""
    path: Path | None = None


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def external_customers_dir(env: dict[str, str] | None = None) -> Path:
    """``<lab_mgmt>/external_customers/``."""
    return lab_mgmt_repo_root(env) / EXTERNAL_CUSTOMERS_SUBDIR


def customer_path(cust_id: str, env: dict[str, str] | None = None) -> Path:
    return external_customers_dir(env) / f"{cust_id}.md"


# ---------------------------------------------------------------------------
# Readers
# ---------------------------------------------------------------------------

def _parse_customer(path: Path) -> ExternalCustomer | None:
    try:
        parsed = parse_file(path)
    except Exception:
        return None
    meta = parsed.meta or {}
    cid = str(meta.get("id") or path.stem)
    return ExternalCustomer(
        id=cid,
        name=str(meta.get("name") or cid),
        kind=str(meta.get("kind") or "industry"),
        billing_contact=str(meta.get("billing_contact") or ""),
        billing_address=str(meta.get("billing_address") or ""),
        po_number=str(meta.get("po_number") or ""),
        tax_id=str(meta.get("tax_id") or ""),
        status=str(meta.get("status") or "active"),
        contact_name=str(meta.get("contact_name") or ""),
        notes=(parsed.body or "").strip(),
        created=str(meta.get("created") or ""),
        path=path,
    )


def iter_customers(
    *, include_archived: bool = False,
    env: dict[str, str] | None = None,
) -> list[ExternalCustomer]:
    cdir = external_customers_dir(env)
    if not cdir.is_dir():
        return []
    out: list[ExternalCustomer] = []
    for entry in sorted(cdir.iterdir()):
        if not entry.is_file() or entry.suffix != ".md":
            continue
        c = _parse_customer(entry)
        if c is None:
            continue
        if c.status == "archived" and not include_archived:
            continue
        out.append(c)
    return out


def get_customer(
    cust_id: str, env: dict[str, str] | None = None,
) -> ExternalCustomer | None:
    p = customer_path(cust_id, env)
    if not p.is_file():
        return None
    return _parse_customer(p)


# ---------------------------------------------------------------------------
# Writers
# ---------------------------------------------------------------------------

def _validate_id(cust_id: str) -> str:
    cid = (cust_id or "").strip().lower()
    if not _ID_RE.match(cid):
        raise ExternalCustomerError(
            f"id must match {_ID_RE.pattern} (got {cust_id!r}); "
            "use lowercase letters / digits / -_ ; 2-64 chars."
        )
    return cid


def _render(c: ExternalCustomer) -> str:
    meta = {
        "id": c.id,
        "name": c.name,
        "kind": c.kind,
        "billing_contact": c.billing_contact,
        "billing_address": c.billing_address,
        "po_number": c.po_number,
        "tax_id": c.tax_id,
        "contact_name": c.contact_name,
        "status": c.status,
        "created": c.created,
    }
    yaml_text = yaml.safe_dump(meta, sort_keys=False).rstrip()
    body = (c.notes or "").strip() or f"# {c.name}"
    return f"---\n{yaml_text}\n---\n\n{body}\n"


def create_customer(
    *,
    id: str,
    name: str,
    kind: str = "industry",
    billing_contact: str = "",
    billing_address: str = "",
    po_number: str = "",
    tax_id: str = "",
    contact_name: str = "",
    notes: str = "",
    env: dict[str, str] | None = None,
) -> Path:
    cid = _validate_id(id)
    if not name.strip():
        raise ExternalCustomerError("name is required")
    p = customer_path(cid, env)
    if p.is_file():
        raise ExternalCustomerError(
            f"external customer already exists: {cid}"
        )
    now = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
    c = ExternalCustomer(
        id=cid, name=name.strip(), kind=kind.strip().lower() or "industry",
        billing_contact=billing_contact.strip(),
        billing_address=billing_address.strip(),
        po_number=po_number.strip(),
        tax_id=tax_id.strip(),
        contact_name=contact_name.strip(),
        notes=notes,
        created=now,
    )
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_render(c), encoding="utf-8")
    return p


def update_customer(
    *,
    id: str,
    patch: dict[str, Any],
    env: dict[str, str] | None = None,
) -> Path:
    c = get_customer(id, env)
    if c is None:
        raise ExternalCustomerError(f"external customer not found: {id}")
    allowed = {"name", "kind", "billing_contact", "billing_address",
               "po_number", "tax_id", "contact_name", "status", "notes"}
    for k, v in (patch or {}).items():
        if k not in allowed:
            continue
        setattr(c, k, v if isinstance(v, str) else str(v or ""))
    p = customer_path(id, env)
    p.write_text(_render(c), encoding="utf-8")
    return p


def archive_customer(
    *, id: str, env: dict[str, str] | None = None,
) -> Path:
    return update_customer(id=id, patch={"status": "archived"}, env=env)


__all__ = [
    "EXTERNAL_CUSTOMERS_SUBDIR",
    "ExternalCustomerError", "ExternalCustomer",
    "external_customers_dir", "customer_path",
    "iter_customers", "get_customer",
    "create_customer", "update_customer", "archive_customer",
]
