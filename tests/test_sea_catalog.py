"""Tests for SEA catalog + cross-group inbound (Phase 10).

Covers:
  - core.sea_catalog: upsert, set_accepting, delete, get, iter
  - core.cross_group: file/accept/decline inbound, lifecycle guards
  - dashboard contract: sea_catalog + inbound_requests in response
  - HTTP endpoints: catalog CRUD (PI-only writes), inbound action
  - MCP tools: list / get / request
"""

from __future__ import annotations

import datetime as _dt

import pytest

from murmurent.commands import project_cmd
from murmurent.core import cross_group as xg
from murmurent.core import sea_catalog as catalog
from murmurent.dashboard import snapshot
from murmurent.mcp import sea_catalog_server as mcp_srv


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n---\n",
        encoding="utf-8",
    )
    project_cmd.cmd_new(
        "p_cat", charter_path=None, members_csv="@the_pi,@allie",
        description="x", sensitivity="standard", lead="@the_pi",
        skip_github=True,
    )
    return tmp_path


# ---------------------------------------------------------------------------
# core.sea_catalog
# ---------------------------------------------------------------------------


def test_upsert_creates_entry(world):
    e = catalog.upsert(
        slug="bulk_rnaseq", title="Bulk RNA-seq align", kind="experiment",
        contact="@allie", description="Align fastqs.", turnaround_days=7,
        prerequisites=["GRCh38", "fastq files"],
    )
    assert e.slug == "bulk_rnaseq"
    assert e.contact == "@allie"
    assert e.accepting is True
    assert e.path.is_file()


def test_upsert_validates_slug(world):
    with pytest.raises(catalog.CatalogError):
        catalog.upsert(slug="Bad-Slug", title="x", kind="skill", contact="@a")


def test_upsert_validates_kind(world):
    with pytest.raises(catalog.CatalogError):
        catalog.upsert(slug="ok", title="x", kind="bogus", contact="@a")


def test_upsert_requires_contact(world):
    with pytest.raises(catalog.CatalogError):
        catalog.upsert(slug="ok", title="x", kind="skill", contact="")


def test_upsert_preserves_body_on_re_upsert(world):
    e = catalog.upsert(slug="ok", title="x", kind="skill", contact="@a")
    e.body = "MY BODY"
    catalog.write_entry(e)
    e2 = catalog.upsert(slug="ok", title="y", kind="skill", contact="@a")
    assert "MY BODY" in e2.body  # body not blown away by re-upsert


def test_set_accepting_toggles(world):
    catalog.upsert(slug="a", title="A", kind="skill", contact="@a")
    catalog.set_accepting("a", accepting=False)
    e = catalog.get("a")
    assert e.accepting is False


def test_set_accepting_unknown_404s(world):
    with pytest.raises(catalog.CatalogNotFound):
        catalog.set_accepting("nope", accepting=False)


def test_delete(world):
    catalog.upsert(slug="d", title="D", kind="skill", contact="@a")
    catalog.delete("d")
    with pytest.raises(catalog.CatalogNotFound):
        catalog.get("d")


def test_iter_catalog_filter_accepting_only(world):
    catalog.upsert(slug="x", title="X", kind="skill", contact="@a", accepting=True)
    catalog.upsert(slug="y", title="Y", kind="skill", contact="@a", accepting=False)
    slugs_all = {e.slug for e in catalog.iter_catalog()}
    slugs_open = {e.slug for e in catalog.iter_catalog(accepting_only=True)}
    assert slugs_all == {"x", "y"}
    assert slugs_open == {"x"}


# ---------------------------------------------------------------------------
# core.cross_group
# ---------------------------------------------------------------------------


def test_file_inbound_assigns_id(world):
    req = xg.file_inbound(
        catalog_slug="bulk_rnaseq", from_group="imaging-lab",
        from_handle="diego", from_pi="imaging_pi",
        description="we need run 5",
    )
    assert req.id == 1
    assert req.state == "pending"
    assert req.from_handle == "@diego"
    assert req.from_pi == "@imaging_pi"


def test_accept_inbound_routes_to_member(world):
    req = xg.file_inbound(
        catalog_slug="bulk_rnaseq", from_group="g", from_handle="x",
    )
    xg.accept_inbound(req, routed_to="allie")
    assert req.state == "accepted"
    assert req.routed_to == "@allie"


def test_decline_inbound_requires_reason(world):
    req = xg.file_inbound(catalog_slug="bulk_rnaseq", from_group="g", from_handle="x")
    with pytest.raises(xg.CrossGroupError):
        xg.decline_inbound(req, reason="")


def test_cannot_re_accept(world):
    req = xg.file_inbound(catalog_slug="bulk_rnaseq", from_group="g", from_handle="x")
    xg.accept_inbound(req, routed_to="allie")
    xg.write_inbound(req)
    with pytest.raises(xg.CrossGroupError):
        xg.accept_inbound(req, routed_to="bob")


# ---------------------------------------------------------------------------
# Snapshot / dashboard contract
# ---------------------------------------------------------------------------


def test_snapshot_includes_sea_catalog_for_everyone(world):
    catalog.upsert(slug="visible", title="Visible", kind="skill", contact="@a")
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    slugs = {e.slug for e in resp.sea_catalog}
    assert "visible" in slugs


def test_snapshot_inbound_only_visible_to_pi(world):
    catalog.upsert(slug="bulk_rnaseq", title="X", kind="skill", contact="@a")
    xg.file_inbound(catalog_slug="bulk_rnaseq", from_group="g", from_handle="x")
    pi = snapshot.build_response("the_pi", today=_dt.date(2026, 5, 8))
    member = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert len(pi.inbound_requests) == 1
    assert member.inbound_requests == []


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


def _client():
    from fastapi.testclient import TestClient
    from murmurent.dashboard.server import create_app
    return TestClient(create_app())


def test_endpoint_catalog_upsert_pi_only(world):
    client = _client()
    body = {
        "slug": "ep1", "title": "Test", "kind": "skill",
        "contact": "@allie", "description": "", "prerequisites": [],
        "accepting": True,
    }
    # member denied
    res = client.post("/api/sea_catalog?user=allie", json=body)
    assert res.status_code == 403
    # PI succeeds
    res = client.post("/api/sea_catalog?user=the_pi", json=body)
    assert res.status_code == 200
    assert res.json()["entry"]["slug"] == "ep1"


def test_endpoint_catalog_disable_then_enable(world):
    client = _client()
    body = {
        "slug": "ep2", "title": "Test", "kind": "skill",
        "contact": "@allie", "description": "", "prerequisites": [],
        "accepting": True,
    }
    client.post("/api/sea_catalog?user=the_pi", json=body)
    res = client.post("/api/sea_catalog/ep2/disable?user=the_pi")
    assert res.status_code == 200
    assert res.json()["accepting"] is False
    res = client.post("/api/sea_catalog/ep2/enable?user=the_pi")
    assert res.status_code == 200
    assert res.json()["accepting"] is True


def test_endpoint_catalog_delete_404_for_unknown(world):
    client = _client()
    res = client.post("/api/sea_catalog/nonexistent/delete?user=the_pi")
    assert res.status_code == 404


def test_endpoint_inbound_simulate_then_accept(world):
    client = _client()
    catalog.upsert(slug="bulk_rnaseq", title="x", kind="skill", contact="@allie")
    res = client.post(
        "/api/inbound-sea/_simulate",
        json={"catalog_slug": "bulk_rnaseq", "from_group": "imaging-lab",
              "from_handle": "@diego", "description": "y"},
    )
    assert res.status_code == 200
    rid = res.json()["request"]["id"]
    # member can't accept
    res2 = client.post(
        f"/api/inbound-sea/{rid}/accept?user=allie", json={"routed_to": "@allie"}
    )
    assert res2.status_code == 403
    # PI accepts
    res3 = client.post(
        f"/api/inbound-sea/{rid}/accept?user=the_pi", json={"routed_to": "@allie"}
    )
    assert res3.status_code == 200
    assert res3.json()["request"]["state"] == "accepted"


def test_endpoint_inbound_decline_requires_reason(world):
    client = _client()
    catalog.upsert(slug="bulk_rnaseq", title="x", kind="skill", contact="@allie")
    sim = client.post(
        "/api/inbound-sea/_simulate",
        json={"catalog_slug": "bulk_rnaseq", "from_group": "g", "from_handle": "@x"},
    ).json()
    rid = sim["request"]["id"]
    res = client.post(f"/api/inbound-sea/{rid}/decline?user=the_pi", json={})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


def test_mcp_list_returns_only_accepting(world):
    catalog.upsert(slug="open", title="Open", kind="skill", contact="@a", accepting=True)
    catalog.upsert(slug="paused", title="Paused", kind="skill", contact="@a", accepting=False)
    rows = mcp_srv.tool_list()
    slugs = {r["slug"] for r in rows}
    assert slugs == {"open"}


def test_mcp_get_returns_full_payload(world):
    catalog.upsert(slug="g1", title="G1", kind="experiment",
                   contact="@allie", description="d")
    payload = mcp_srv.tool_get("g1")
    assert payload["slug"] == "g1"
    assert payload["kind"] == "experiment"


def test_mcp_get_unknown_raises(world):
    with pytest.raises(KeyError):
        mcp_srv.tool_get("not-here")


def test_mcp_request_files_inbound(world):
    catalog.upsert(slug="r1", title="R1", kind="skill", contact="@a")
    out = mcp_srv.tool_request(
        catalog_slug="r1", from_group="other-lab",
        from_handle="@xx", description="please",
    )
    assert out["state"] == "pending"
    assert out["catalog_slug"] == "r1"
    # should be visible in iter_inbound
    assert any(r.id == out["id"] for r in xg.iter_inbound())


def test_mcp_request_refuses_paused(world):
    catalog.upsert(slug="p1", title="P1", kind="skill", contact="@a", accepting=False)
    with pytest.raises(ValueError):
        mcp_srv.tool_request(
            catalog_slug="p1", from_group="g", from_handle="@x",
        )


def test_mcp_request_refuses_unknown(world):
    with pytest.raises(KeyError):
        mcp_srv.tool_request(
            catalog_slug="nope", from_group="g", from_handle="@x",
        )
