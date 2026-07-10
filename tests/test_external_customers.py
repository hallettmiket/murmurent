"""
Phase 6 tests: external customer registry + lab resolver + booking
validation + invoice header + registrar HTTP endpoints.

Covers:
  - create_customer validates id, refuses duplicates
  - iter_customers excludes archived by default
  - get_customer roundtrip; update_customer partial; archive flips status
  - lab_roster.resolve: local lab, centre registry lab, external,
    unknown
  - booking endpoint: unknown lab proceeds with warning; strict_lab=true
    refuses; known external lab passes (kind=external in resolution)
  - invoice render_lab_md embeds external billing header (PO, contact)
  - invoice render_summary_md splits by recipient kind when mixed
  - registrar HTTP: list/create/update/archive gated to registrar
  - GET /api/lab_roster/resolve public read
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core import external_customers as EC
from murmurent.core import invoices as INV
from murmurent.core import lab_roster as ROSTER
from murmurent.core import registrar as R
from murmurent.core import service_requests as SR
from murmurent.core import services as S
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "wigamig_home"))
    monkeypatch.setenv("MURMURENT_USER", "alice")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("the_pi\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    for h in ("alice", "the_pi", "gary"):
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active'}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    S.create_service(core="biocore", slug="itc", name="ITC")
    return tmp_path


# ---- 6a: external_customers CRUD ---------------------------------------

def test_create_customer_persists_and_validates(world):
    p = EC.create_customer(
        id="acme-bio", name="ACME Biosciences",
        billing_contact="ap@acme.example", po_number="PO-12345",
    )
    assert p.is_file()
    c = EC.get_customer("acme-bio")
    assert c.name == "ACME Biosciences"
    assert c.po_number == "PO-12345"


@pytest.mark.parametrize("bad", ["", "a", "Has Space", "_leading"])
def test_create_customer_rejects_bad_id(world, bad):
    with pytest.raises(EC.ExternalCustomerError):
        EC.create_customer(id=bad, name="X")


def test_create_customer_auto_lowercases(world):
    """UPPER -> lower is normalisation, not error (mirrors services)."""
    p = EC.create_customer(id="ACME-Bio", name="X")
    assert p.stem == "acme-bio"


def test_create_customer_refuses_duplicate(world):
    EC.create_customer(id="acme", name="ACME")
    with pytest.raises(EC.ExternalCustomerError, match="already exists"):
        EC.create_customer(id="acme", name="Other")


def test_iter_excludes_archived_by_default(world):
    EC.create_customer(id="live", name="Live")
    EC.create_customer(id="gone", name="Gone")
    EC.archive_customer(id="gone")
    ids = sorted(c.id for c in EC.iter_customers())
    assert ids == ["live"]
    ids = sorted(c.id for c in EC.iter_customers(include_archived=True))
    assert ids == ["gone", "live"]


def test_update_customer_partial(world):
    EC.create_customer(id="xx", name="X", po_number="OLD")
    EC.update_customer(id="xx", patch={"po_number": "NEW", "name": "Renamed"})
    c = EC.get_customer("xx")
    assert c.po_number == "NEW"
    assert c.name == "Renamed"


def test_archive_flips_status(world):
    EC.create_customer(id="xx", name="X")
    EC.archive_customer(id="xx")
    assert EC.get_customer("xx").status == "archived"


# ---- 6b: lab_roster.resolve --------------------------------------------

def test_resolve_local_lab(world):
    res = ROSTER.resolve("hallett")
    assert res.kind == ROSTER.KIND_LAB
    assert "@the_pi" in res.pi_or_contact


def test_resolve_unknown_lab(world):
    res = ROSTER.resolve("nonsense")
    assert res.kind == ROSTER.KIND_UNKNOWN


def test_resolve_external_customer(world):
    EC.create_customer(id="acme", name="ACME",
                        po_number="PO-9", contact_name="Jane Doe",
                        billing_contact="jane@acme.example")
    res = ROSTER.resolve("acme")
    assert res.kind == ROSTER.KIND_EXTERNAL
    assert res.display_name == "ACME"
    assert res.billing_meta["po_number"] == "PO-9"


def test_resolve_empty_returns_unknown(world):
    assert ROSTER.resolve("").kind == ROSTER.KIND_UNKNOWN


# ---- 6c: booking validates requester_lab --------------------------------

@patch("murmurent.dashboard.slack_notify._post")
def test_book_unknown_lab_returns_warning(mock_post, world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00"},
              "requester_lab": "ghost"},
    )
    assert res.status_code == 200
    j = res.json()
    assert j["lab_resolution"]["kind"] == ROSTER.KIND_UNKNOWN
    assert "not registered" in j["lab_resolution"]["warning"]


def test_book_strict_lab_refuses_unknown(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00"},
              "requester_lab": "ghost", "strict_lab": True},
    )
    assert res.status_code == 422


@patch("murmurent.dashboard.slack_notify._post")
def test_book_external_lab_resolves_clean(mock_post, world):
    EC.create_customer(id="acme", name="ACME")
    client = TestClient(create_app())
    res = client.post(
        "/api/core/biocore/services/itc/book?user=alice",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00"},
              "requester_lab": "acme"},
    )
    assert res.status_code == 200
    j = res.json()
    assert j["lab_resolution"]["kind"] == ROSTER.KIND_EXTERNAL
    assert j["lab_resolution"]["warning"] == ""


# ---- 6d: invoice header for external customers --------------------------

def test_render_lab_md_external_header(world):
    EC.create_customer(
        id="acme", name="ACME Biosciences",
        billing_contact="ap@acme.example", po_number="PO-12",
        contact_name="Jane Doe", billing_address="1 Main St\nCity",
    )
    line = INV.InvoiceLine(
        request_id="r1", service="itc", requester="@x",
        slot_start="2026-05-23T10:00-04:00", slot_end="2026-05-23T11:00-04:00",
        state="completed", tier="industry", unit="per_run",
        base=260.0, charge=260.0, is_confirmed=True,
    )
    inv = INV.LabInvoice(core="biocore", lab="acme", month="2026-05",
                          lines=[line])
    md = INV.render_lab_md(inv)
    assert "ACME Biosciences (external customer)" in md
    assert "PO-12" in md
    assert "ap@acme.example" in md
    assert "1 Main St" in md


def test_render_summary_md_splits_by_kind(world):
    EC.create_customer(id="acme", name="ACME")
    L1 = INV.LabInvoice(core="biocore", lab="hallett", month="2026-05",
                         lines=[INV.InvoiceLine(
                             request_id="a", service="itc", requester="@x",
                             slot_start="", slot_end="", state="completed",
                             tier="academic_internal", unit="per_run",
                             base=80.0, charge=80.0, is_confirmed=True)])
    L2 = INV.LabInvoice(core="biocore", lab="acme", month="2026-05",
                         lines=[INV.InvoiceLine(
                             request_id="b", service="itc", requester="@y",
                             slot_start="", slot_end="", state="completed",
                             tier="industry", unit="per_run",
                             base=260.0, charge=260.0, is_confirmed=True)])
    md = INV.render_summary_md([L1, L2], core="biocore", month="2026-05")
    assert "Breakdown by recipient kind:" in md
    assert "external:" in md
    assert "lab:" in md
    assert "| acme | external |" in md
    assert "| hallett | lab |" in md


# ---- 6e: registrar HTTP endpoints --------------------------------------

def test_http_list_requires_registrar(world):
    client = TestClient(create_app())
    res = client.get("/api/registrar/external_customers?user=alice")
    assert res.status_code == 403


def test_http_create_list_update_archive(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/external_customers?user=the_pi",
        json={"id": "acme", "name": "ACME", "po_number": "PO-1"},
    )
    assert res.status_code == 200, res.text
    res = client.get("/api/registrar/external_customers?user=the_pi")
    assert any(c["id"] == "acme" for c in res.json()["customers"])
    res = client.patch(
        "/api/registrar/external_customers/acme?user=the_pi",
        json={"po_number": "PO-2"},
    )
    assert res.status_code == 200
    assert EC.get_customer("acme").po_number == "PO-2"
    res = client.post(
        "/api/registrar/external_customers/acme/archive?user=the_pi",
    )
    assert res.status_code == 200
    assert EC.get_customer("acme").status == "archived"


def test_http_create_rejects_bad_payload(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/external_customers?user=the_pi",
        json={"id": "Has Space", "name": "X"},
    )
    assert res.status_code == 422


def test_http_patch_unknown_id_404(world):
    client = TestClient(create_app())
    res = client.patch(
        "/api/registrar/external_customers/ghost?user=the_pi",
        json={"po_number": "PO-9"},
    )
    assert res.status_code == 404


def test_lab_roster_resolve_public(world):
    EC.create_customer(id="acme", name="ACME")
    client = TestClient(create_app())
    # No registrar gate — anyone can ask.
    res = client.get("/api/lab_roster/resolve?lab=acme")
    assert res.status_code == 200
    assert res.json()["kind"] == "external"
    res = client.get("/api/lab_roster/resolve?lab=hallett")
    assert res.json()["kind"] == "lab"
    res = client.get("/api/lab_roster/resolve?lab=nothing")
    assert res.json()["kind"] == "unknown"
