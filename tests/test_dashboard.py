"""Tests for :mod:`wigamig.core.dashboard`."""

from __future__ import annotations

import datetime as _dt

import pytest

from wigamig.commands import experiment_cmd, project_cmd, sea_cmd
from wigamig.core import dashboard, inventory, sea
from wigamig.core.projects import find_project


@pytest.fixture
def world(monkeypatch, tmp_path):
    """A complete fake universe — lab-mgmt, two projects, member files, inventory."""
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    lab_mgmt = tmp_path / "lab-mgmt"
    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "projects").mkdir(parents=True)
    (lab_mgmt / "dashboards").mkdir(parents=True)
    (lab_mgmt / "inventory").mkdir(parents=True)
    # Declare the lab + PI explicitly (a real install always has lab.md; tests
    # used to lean on the removed hardcoded "the_pi"/"hallett" defaults).
    (lab_mgmt / "lab.md").write_text(
        "---\nlab: hallett\nname: Hallett Lab\npi: '@the_pi'\n"
        "institution: Western University\n---\n\n# group config\n",
        encoding="utf-8")

    # Member files mirror the seed's umbrella state.
    members = {
        "the_pi": "TCPS_2:2030-12-31\n  - TOTP:enrolled\n  - signing_key:registered",
        "allie": "TCPS_2:2027-06-15\n  - TOTP:enrolled\n  - signing_key:registered",
        "bob": "TCPS_2:2026-06-05\n  - TOTP:enrolled\n  - signing_key:registered",
        "cassie": "TOTP:pending\n  - signing_key:pending",
    }
    for handle, certs in members.items():
        (lab_mgmt / "members" / f"{handle}.md").write_text(
            "---\n"
            f"handle: '@{handle}'\n"
            f"full_name: '{handle.title()}'\n"
            "role: pi\n"
            "status: active\n"
            "certifications:\n"
            f"  - {certs}\n"
            "---\n\n# member\n",
            encoding="utf-8",
        )

    project_cmd.cmd_new(
        "dcis_test",
        charter_path=None,
        members_csv="@the_pi,@allie,@bob,@cassie",
        description="Fake clinical project.",
        sensitivity="clinical",
        choreography="clinical_cohort",
        reb_number="WREM-1",
        reb_expires="2027-01-01",
        data_residency="ca",
        lead="@allie",
        skip_github=True,
    )
    project_cmd.cmd_new(
        "bbb_test",
        charter_path=None,
        members_csv="@the_pi,@bob,@allie",
        description="Fake standard project.",
        sensitivity="standard",
        lead="@bob",
        skip_github=True,
    )

    # Two SEAs — one assigned to allie (incoming), one filed by allie (outgoing
    # in dcis), plus a complete-not-examined SEA where allie is the to_handle
    # to exercise the outstanding-analysis panel.
    repo = find_project("dcis_test")
    sea_cmd.cmd_request(
        project_name="dcis_test", to_target="@bob", kind="analysis", description="rerun"
    )  # outgoing
    sea_cmd.cmd_request(
        project_name="dcis_test",
        to_target="@allie",
        kind="analysis",
        description="check stats",
        from_handle="@cassie",
    )  # incoming
    # Force one SEA into "complete" with an old completed_at to trigger red.
    s = sea.iter_seas(repo)[0]
    s.state = "complete"
    s.completed_at = "2026-01-01"  # >60d before today (today=2026-05-07)
    sea.write_sea(repo, s)

    # An experiment that's complete but not concluded (also outstanding).
    experiment_cmd.cmd_new("dcis_test", "alpha", performer=["@allie"])
    experiment_cmd.cmd_status("dcis_test", "alpha", "complete")

    # Inventory items.
    for item in (
        inventory.InventoryItem(name="anti_cd31", status="in_stock", expiry="2027-03-01"),
        inventory.InventoryItem(name="4_oht", status="expired", expiry="2026-04-01"),
        inventory.InventoryItem(name="nebnext_kit", status="low"),
    ):
        inventory.write_item(item)

    return tmp_path


def test_build_snapshot_for_lead(world):
    snap = dashboard.build_snapshot("allie", today=_dt.date(2026, 5, 7))
    assert snap.role == "lead"
    assert {p.name for p in snap.projects} == {"dcis_test", "bbb_test"}
    assert snap.is_pi is False


def test_outstanding_red_on_old_complete(world):
    snap = dashboard.build_snapshot("allie", today=_dt.date(2026, 5, 7))
    severities = [item.severity for item in snap.outstanding]
    assert "red" in severities, [(i.scope, i.target, i.severity) for i in snap.outstanding]


def test_compliance_for_cassie_flags_clinical(world):
    snap = dashboard.build_snapshot("cassie", today=_dt.date(2026, 5, 7))
    rows = {row.project: row for row in snap.compliance}
    assert rows["dcis_test"].sensitivity == "clinical"
    notes = " ".join(rows["dcis_test"].notes)
    assert "TCPS_2 missing" in notes


def test_compliance_for_bob_marks_expiring(world):
    snap = dashboard.build_snapshot("bob", today=_dt.date(2026, 5, 7))
    tcps = [c for r in snap.compliance for c in r.member_certs if c.name == "TCPS_2"]
    assert any(c.status == "expiring" for c in tcps)


def test_pi_view_includes_clinical_grid(world):
    snap = dashboard.build_snapshot("the_pi", today=_dt.date(2026, 5, 7))
    assert snap.is_pi
    grid = snap.pi_view.get("clinical_compliance", [])
    assert any(row["member"] == "@cassie" and row["tcps_status"] == "missing" for row in grid)


def test_render_markdown_includes_sections(world):
    snap = dashboard.build_snapshot("the_pi", today=_dt.date(2026, 5, 7))
    text = dashboard.render_markdown(snap)
    assert "## Outstanding analysis" in text
    assert "## Security and compliance" in text
    assert "PI view" in text


def test_render_outstanding_terminal(world):
    snap = dashboard.build_snapshot("allie", today=_dt.date(2026, 5, 7))
    text = dashboard.render_outstanding(snap)
    assert "Outstanding analysis" in text


def test_write_member_dashboard_idempotent(world):
    p1 = dashboard.write_member_dashboard("allie", today=_dt.date(2026, 5, 7))
    body = p1.read_text(encoding="utf-8")
    p2 = dashboard.write_member_dashboard("allie", today=_dt.date(2026, 5, 7))
    assert p1 == p2
    assert p2.read_text(encoding="utf-8") == body
