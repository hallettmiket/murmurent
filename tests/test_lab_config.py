"""Tests for the <lab-mgmt>/lab.md group config (Phase 7+).

The PI handle and lab manager are no longer hardcoded constants — they're
read fresh from lab.md per call. These tests confirm:

  1. Reading lab.md returns the declared PI handle.
  2. Missing lab.md falls back to a sensible default.
  3. Overriding the PI in lab.md flips ``can_pi`` on the dashboard
     response (so a different lab can use the same wigamig install).
  4. The inventory MCP's ``lab_manager`` check honours the same source.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from wigamig.commands import project_cmd
from wigamig.core.lab import load_lab_config, pi_handle
from wigamig.dashboard import snapshot


@pytest.fixture
def lab_world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    return tmp_path


def _write_lab(path, *, lab="hallett", pi="mhallet"):
    (path / "lab-mgmt" / "lab.md").write_text(
        "---\n"
        f"lab: {lab}\n"
        f"name: '{lab.title()} Lab'\n"
        f"pi: '@{pi}'\n"
        "institution: Western University\n"
        "---\n\n# group config\n",
        encoding="utf-8",
    )


def _seed_member(path, handle, role="postdoc"):
    (path / "lab-mgmt" / "members" / f"{handle}.md").write_text(
        f"---\nhandle: '@{handle}'\nrole: {role}\nstatus: active\n"
        f"certifications:\n  - TCPS_2:2030-12-31\n---\n",
        encoding="utf-8",
    )


def test_load_lab_config_reads_pi_from_file(lab_world):
    _write_lab(lab_world, lab="hallett", pi="mhallet")
    cfg = load_lab_config()
    assert cfg.pi == "mhallet"
    assert cfg.lab == "hallett"
    assert cfg.name == "Hallett Lab"


def test_pi_handle_helper_strips_at_sign(lab_world):
    _write_lab(lab_world, pi="@mhallet")
    assert pi_handle() == "mhallet"


def test_load_lab_config_falls_back_when_file_missing(lab_world):
    """No lab.md → default fallback so wigamig still boots fresh."""
    cfg = load_lab_config()
    assert cfg.pi == "mhallet"  # default fallback handle
    assert cfg.lab == "hallett"


def test_alternate_pi_flips_can_pi_on_dashboard(lab_world):
    """Different lab.md PI → different person sees the persona toggle."""
    _write_lab(lab_world, lab="example", pi="alice")
    _seed_member(lab_world, "alice", role="pi")
    _seed_member(lab_world, "bob", role="student")
    project_cmd.cmd_new(
        "p_alt", charter_path=None, members_csv="@alice,@bob",
        description="x", sensitivity="standard", lead="@alice",
        skip_github=True,
    )

    # alice (the PI per the new lab.md) gets can_pi=True
    resp_alice = snapshot.build_response("alice", today=_dt.date(2026, 5, 8))
    assert resp_alice.member.can_pi is True
    assert resp_alice.pi.handle == "alice"

    # bob (a member) does not
    resp_bob = snapshot.build_response("bob", today=_dt.date(2026, 5, 8))
    assert resp_bob.member.can_pi is False


def test_inventory_mcp_uses_lab_md_for_lab_manager(lab_world, monkeypatch):
    """Permission check follows the lab.md PI."""
    from wigamig.core import inventory
    from wigamig.mcp import inventory_server

    _write_lab(lab_world, pi="alice")
    inventory.write_item(inventory.InventoryItem(name="thing", status="in_stock"))

    # bob (not the PI) should get a permission error.
    monkeypatch.setenv("WIGAMIG_USER", "bob")
    with pytest.raises(PermissionError) as excinfo:
        inventory_server.tool_set("thing", {"status": "low"})
    assert "alice" in str(excinfo.value).lower()

    # alice (is the PI) succeeds.
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    inventory_server.tool_set("thing", {"status": "low"})
    item = inventory.parse_item(inventory.item_path("thing"))
    assert item.status == "low"
