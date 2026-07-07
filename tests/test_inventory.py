"""Tests for :mod:`wigamig.core.inventory` and the inventory MCP tool layer."""

from __future__ import annotations

import datetime as _dt

import pytest

from wigamig.core import inventory
from wigamig.mcp import inventory_server


@pytest.fixture
def inv(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    # The lab_manager is the PI declared in lab.md. Declare it explicitly — the
    # hardcoded "the_pi" default was removed, so a real lab.md is required.
    lab_mgmt = tmp_path / "lab-mgmt"
    lab_mgmt.mkdir(parents=True, exist_ok=True)
    (lab_mgmt / "lab.md").write_text(
        "---\nlab: hallett\nname: Hallett Lab\npi: '@the_pi'\n---\n\n# group\n",
        encoding="utf-8")
    items = [
        inventory.InventoryItem(name="anti_cd31", status="in_stock", expiry="2027-03-01"),
        inventory.InventoryItem(name="4_oht", status="expired", expiry="2026-04-01"),
        inventory.InventoryItem(name="nebnext_kit", status="low", expiry="2026-12-31"),
        inventory.InventoryItem(name="livedead_stain", status="in_stock", expiry="2026-05-21"),
        inventory.InventoryItem(name="dmso", status="in_stock", expiry="2030-01-01"),
    ]
    for it in items:
        inventory.write_item(it)
    return tmp_path


def test_iter_items_loads_all(inv):
    items = inventory.iter_items()
    names = {i.name for i in items}
    assert {"anti_cd31", "4_oht", "nebnext_kit", "livedead_stain", "dmso"} <= names


def test_filter_low(inv):
    low = inventory.filter_low(inventory.iter_items())
    assert {i.name for i in low} == {"nebnext_kit"}


def test_filter_expired(inv):
    expired = inventory.filter_expired(inventory.iter_items(), today=_dt.date(2026, 5, 7))
    assert "4_oht" in {i.name for i in expired}


def test_filter_expiring(inv):
    expiring = inventory.filter_expiring(
        inventory.iter_items(), within_days=30, today=_dt.date(2026, 5, 7)
    )
    assert "livedead_stain" in {i.name for i in expiring}


def test_provision_gaps_and_expiring(inv):
    plan = ["anti_cd31", "4_oht", "nebnext_kit", "livedead_stain", "ghost_reagent"]
    result = inventory.provision(plan, inventory.iter_items(), today=_dt.date(2026, 5, 7))
    assert "ghost_reagent" in result["gaps"]
    assert "4_oht" in result["gaps"]  # expired
    assert "livedead_stain" in result["expiring"]
    assert "anti_cd31" in result["ok"]


# ---------------------------------------------------------------------------
# MCP tool layer (callable directly without spinning up a server)
# ---------------------------------------------------------------------------


def test_mcp_tool_list_no_filter(inv):
    rows = inventory_server.tool_list()
    assert any(r["name"] == "anti_cd31" for r in rows)


def test_mcp_tool_list_low(inv):
    rows = inventory_server.tool_list("low")
    assert {r["name"] for r in rows} == {"nebnext_kit"}


def test_mcp_tool_list_expiring(inv, monkeypatch):
    rows = inventory_server.tool_list("expiring:60")
    assert any(r["name"] == "livedead_stain" for r in rows)


def test_mcp_tool_show(inv):
    payload = inventory_server.tool_show("anti_cd31")
    assert payload["name"] == "anti_cd31"
    assert "body" in payload


def test_mcp_set_requires_lab_manager(inv, monkeypatch):
    monkeypatch.setenv("WIGAMIG_USER", "allie")  # not lab_manager
    with pytest.raises(PermissionError):
        inventory_server.tool_set("anti_cd31", {"status": "low"})


def test_mcp_set_as_lab_manager(inv, monkeypatch):
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
    inventory_server.tool_set("anti_cd31", {"status": "low"})
    item = inventory.parse_item(inventory.item_path("anti_cd31"))
    assert item.status == "low"
    assert item.last_updated  # auto-bumped


def test_mcp_provision_reads_notebook_reagents(inv, tmp_path):
    plan = tmp_path / "plan.md"
    plan.write_text(
        "---\nreagents:\n  - anti_cd31\n  - 4_oht\n  - ghost\n---\n\n# plan\n",
        encoding="utf-8",
    )
    result = inventory_server.tool_provision(str(plan))
    assert "ghost" in result["gaps"]
    assert "4_oht" in result["gaps"]
