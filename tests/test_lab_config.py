"""Tests for the <lab-mgmt>/lab.md group config (Phase 7+).

The PI handle and lab manager are no longer hardcoded constants — they're
read fresh from lab.md per call. These tests confirm:

  1. Reading lab.md returns the declared PI handle.
  2. Missing lab.md falls back to a sensible default.
  3. Overriding the PI in lab.md flips ``can_pi`` on the dashboard
     response (so a different lab can use the same murmurent install).
  4. The inventory MCP's ``lab_manager`` check honours the same source.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from murmurent.commands import project_cmd
from murmurent.core.lab import load_lab_config, pi_handle
from murmurent.dashboard import snapshot


@pytest.fixture
def lab_world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    return tmp_path


def _write_lab(path, *, lab="hallett", pi="the_pi"):
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
    _write_lab(lab_world, lab="hallett", pi="the_pi")
    cfg = load_lab_config()
    assert cfg.pi == "the_pi"
    assert cfg.lab == "hallett"
    assert cfg.name == "Hallett Lab"


def test_pi_handle_helper_strips_at_sign(lab_world):
    _write_lab(lab_world, pi="@the_pi")
    assert pi_handle() == "the_pi"


def test_load_lab_config_falls_back_when_file_missing(lab_world):
    """No lab.md → a NEUTRAL config so murmurent still boots, but it must NOT
    fabricate a specific lab's identity (no hardcoded pi/lab/institution)."""
    cfg = load_lab_config()
    assert cfg.pi == ""     # institution-agnostic: never invent a PI
    assert cfg.lab == ""    # never invent a lab name
    assert cfg.institution == ""


# ---- Phase 0b (cores rollout) ---------------------------------------------

def test_lab_settings_defaults_kind_to_lab(lab_world):
    """A lab.md without an explicit ``kind:`` field is treated as a
    research lab (back-compat with every existing murmurent install)."""
    _write_lab(lab_world, lab="hallett", pi="the_pi")
    settings = snapshot._lab_settings("hallett")
    assert settings.kind == "lab"


def test_lab_settings_reads_kind_core(lab_world):
    """An entry with ``kind: core`` in frontmatter surfaces as kind=core,
    so the dashboard can render 'Leader' instead of 'PI'."""
    (lab_world / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: biocore\nname: 'BioCORE'\npi: '@biocore_leader'\n"
        "kind: core\n---\n",
        encoding="utf-8",
    )
    settings = snapshot._lab_settings("biocore")
    assert settings.kind == "core"
    assert settings.pi_handle.lstrip("@") == "biocore_leader"


def test_lab_settings_rejects_unknown_kind_value(lab_world):
    """Defensive: only 'lab' and 'core' are valid; anything else falls
    back to 'lab' so a typo doesn't render a broken dashboard."""
    (lab_world / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: oops\npi: '@x'\nkind: department\n---\n",
        encoding="utf-8",
    )
    settings = snapshot._lab_settings("oops")
    assert settings.kind == "lab"


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
    from murmurent.core import inventory
    from murmurent.mcp import inventory_server

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
