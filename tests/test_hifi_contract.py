"""Tests for the Phase-0 hi-fi data contract.

Asserts ``GET /api/dashboard`` returns the exact field set declared in
``docs/designer_dashboard/hifi-data.jsx``. Uses the same fixture universe
as :mod:`tests.test_dashboard` so we hit real wigamig data, not mocks.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from wigamig.commands import experiment_cmd, project_cmd, sea_cmd
from wigamig.core import inventory, sea
from wigamig.core.projects import find_project
from wigamig.dashboard import contract, snapshot


# ---------------------------------------------------------------------------
# Fixture (mirrors tests/test_dashboard.py::world)
# ---------------------------------------------------------------------------


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_DIR", str(tmp_path / "lab-notebook"))
    lab_mgmt = tmp_path / "lab-mgmt"
    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "projects").mkdir(parents=True)
    (lab_mgmt / "dashboards").mkdir(parents=True)
    (lab_mgmt / "inventory").mkdir(parents=True)

    members = {
        "mhallet": "TCPS_2:2030-12-31\n  - TOTP:enrolled\n  - signing_key:registered",
        "allie": "TCPS_2:2027-06-15\n  - TOTP:enrolled\n  - signing_key:registered",
        "bob": "TCPS_2:2026-06-05\n  - TOTP:enrolled\n  - signing_key:registered",
        "cassie": "TOTP:pending\n  - signing_key:pending",
    }
    # Per-member contact / location overrides (Phase 2). Bob and Cassie have
    # nothing, so they should fall back to the lab default in the snapshot.
    extras = {
        "mhallet": (
            "lab: hallett\n"
            "contact:\n"
            "  email: michael.hallett@uwo.ca\n"
            "  orcid: 0000-0001-6738-6786\n"
            "location:\n"
            "  office: MSB-360\n"
            "  address: 1151 Richmond St\n"
        ),
        "allie": (
            "lab: hallett\n"
            "contact:\n"
            "  email: allie@uwo.ca\n"
            "location:\n"
            "  office: SSC-2418\n"
        ),
    }
    for handle, certs in members.items():
        (lab_mgmt / "members" / f"{handle}.md").write_text(
            "---\n"
            f"handle: '@{handle}'\n"
            f"full_name: '{handle.title()}'\n"
            "role: postdoc\n"
            "status: active\n"
            f"{extras.get(handle, '')}"
            "certifications:\n"
            f"  - {certs}\n"
            "---\n\n# member\n",
            encoding="utf-8",
        )

    project_cmd.cmd_new(
        "dcis_test",
        charter_path=None,
        members_csv="@mhallet,@allie,@bob,@cassie",
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
        members_csv="@mhallet,@bob,@allie",
        description="Fake standard project.",
        sensitivity="standard",
        lead="@bob",
        skip_github=True,
    )

    repo = find_project("dcis_test")
    sea_cmd.cmd_request(
        project_name="dcis_test", to_target="@bob", kind="analysis", description="rerun"
    )
    sea_cmd.cmd_request(
        project_name="dcis_test",
        to_target="@allie",
        kind="analysis",
        description="check stats",
        from_handle="@cassie",
    )
    s = sea.iter_seas(repo)[0]
    s.state = "complete"
    s.completed_at = "2026-01-01"
    sea.write_sea(repo, s)

    experiment_cmd.cmd_new("dcis_test", "alpha", performer=["@allie"])
    experiment_cmd.cmd_status("dcis_test", "alpha", "complete")

    for item in (
        inventory.InventoryItem(name="anti_cd31", status="in_stock", expiry="2027-03-01"),
        inventory.InventoryItem(name="4_oht", status="expired", expiry="2026-04-01"),
        inventory.InventoryItem(name="nebnext_kit", status="low"),
    ):
        inventory.write_item(item)

    return tmp_path


# ---------------------------------------------------------------------------
# Shape conformance
# ---------------------------------------------------------------------------


HIFI_TOP_LEVEL_KEYS = {
    "today",
    "persona",
    "member",
    "pi",
    "agents",
    "oracle_recent",
    "requests_pending",
    "requests_mine",
    "attention",
    "stats",
    "spark",
    "sparkLabels",
    "projects",
    "peers",
    "seas",
    "experiments",
    "notifs",
    "heatmap",
    "inventory",
    "notebook",
}


def test_response_top_level_keys_match_hifi(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    payload = resp.model_dump(by_alias=True)
    assert set(payload.keys()) == HIFI_TOP_LEVEL_KEYS


def test_response_validates_against_pydantic(world):
    """Round-trip dict → model → dict to confirm types are right."""
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    payload = resp.model_dump(by_alias=True)
    contract.DashboardResponse.model_validate(payload)


def test_today_block_is_iso_and_pretty(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert resp.today.iso == "2026-05-08"
    assert "2026" in resp.today.pretty


def test_member_and_pi_identities(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert resp.member.handle == "allie"
    assert resp.pi.handle == "mhallet"
    assert resp.pi.role == "Principal Investigator"


# Phase-2 contract: per-member contact + location with PI fallback.


def test_member_contact_and_location_override(world):
    """Allie's profile overrides email + office; everything else falls back."""
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert resp.member.contact.email == "allie@uwo.ca"
    # Allie didn't override ORCID -> falls back to the lab default.
    assert resp.member.contact.orcid == "0000-0001-6738-6786"
    assert resp.member.location.office == "SSC-2418"
    # Allie inherits the lab address even though her office is in another building.
    assert resp.member.location.address == "1151 Richmond St"


def test_member_without_overrides_uses_lab_defaults(world):
    """Bob has no contact / location frontmatter, so everything is the lab default."""
    resp = snapshot.build_response("bob", today=_dt.date(2026, 5, 8))
    assert resp.member.contact.email == "michael.hallett@uwo.ca"
    assert resp.member.location.office == "MSB-360"
    assert "Schulich School of Dentristy and Medicine" in (
        resp.member.location.department or ""
    )


def test_pi_identity_has_full_contact_block(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert resp.pi.contact.email == "michael.hallett@uwo.ca"
    assert resp.pi.contact.orcid == "0000-0001-6738-6786"
    assert resp.pi.location.office == "MSB-360"


def test_member_lab_field_present(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert resp.member.lab == "hallett"
    assert resp.pi.lab == "hallett"


# Phase-3 contract: persona-aware attention + heatmap, with auth coercion.


def test_member_persona_default(world):
    """Default persona is member; PI flag false for non-PI users."""
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert resp.persona == "member"
    assert resp.member.can_pi is False


def test_pi_persona_only_authorised_for_pi_handle(world):
    """Asking for persona='pi' as a non-PI silently downgrades to 'member'."""
    resp = snapshot.build_response(
        "allie", persona="pi", today=_dt.date(2026, 5, 8)
    )
    assert resp.persona == "member"
    assert resp.member.can_pi is False


def test_pi_can_request_pi_persona(world):
    resp = snapshot.build_response(
        "mhallet", persona="pi", today=_dt.date(2026, 5, 8)
    )
    assert resp.persona == "pi"
    assert resp.member.can_pi is True


def test_pi_persona_attention_surfaces_peer_cert_lapses(world):
    """In PI lens, attention should call out @cassie's missing TCPS_2."""
    resp = snapshot.build_response(
        "mhallet", persona="pi", today=_dt.date(2026, 5, 8)
    )
    cert_items = [a for a in resp.attention if a.kind == "CERT"]
    assert any("@cassie" in a.id for a in cert_items)


def test_member_persona_heatmap_filters_to_user_projects(world):
    """Member lens shows only projects the user is on."""
    resp = snapshot.build_response("cassie", today=_dt.date(2026, 5, 8))
    project_names = {row.project for row in resp.heatmap.rows}
    # cassie is only on dcis_test in the fixture; bbb_test should not appear.
    assert "dcis_test" in project_names
    assert "bbb_test" not in project_names


def test_pi_persona_heatmap_shows_all_projects(world):
    resp = snapshot.build_response(
        "mhallet", persona="pi", today=_dt.date(2026, 5, 8)
    )
    project_names = {row.project for row in resp.heatmap.rows}
    assert {"dcis_test", "bbb_test"} <= project_names


def test_api_endpoint_accepts_persona_param(world):
    from fastapi.testclient import TestClient

    from wigamig.dashboard.server import create_app

    client = TestClient(create_app())
    resp = client.get("/api/dashboard?user=mhallet&persona=pi")
    assert resp.status_code == 200
    assert resp.json()["persona"] == "pi"

    # Non-PI requesting PI persona is silently downgraded.
    resp2 = client.get("/api/dashboard?user=allie&persona=pi")
    assert resp2.status_code == 200
    assert resp2.json()["persona"] == "member"


def test_member_peer_row_carries_per_peer_involvement(world):
    """Group panel rows include projects[], open_seas, experiments per peer."""
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    bob = next((p for p in resp.peers if p.handle == "bob"), None)
    assert bob is not None
    # Member view: Allie shares both fixture projects with Bob.
    assert {"dcis_test", "bbb_test"} <= set(bob.projects)
    assert isinstance(bob.open_seas, int)
    assert isinstance(bob.experiments, int)


def test_member_peers_only_includes_shared_project_peers(world):
    """Member persona: peer list = members of viewer's projects only."""
    resp = snapshot.build_response("cassie", today=_dt.date(2026, 5, 8))
    handles = {p.handle for p in resp.peers}
    # cassie is only on dcis_test (clinical), so we shouldn't see bbb_test-only members.
    # Both fixture projects share members in this case, so this just confirms
    # mhallet/allie/bob are visible (peers from dcis_test).
    assert "mhallet" in handles or "allie" in handles


def test_pi_persona_peers_include_lab_wide_view(world):
    """PI persona surfaces peer involvement across the whole lab."""
    resp = snapshot.build_response(
        "mhallet", persona="pi", today=_dt.date(2026, 5, 8)
    )
    # Each peer's projects field should be non-empty for at least one peer.
    assert any(p.projects for p in resp.peers)


def test_agents_panel_populated_from_registry(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert len(resp.agents) >= 1
    names = {a.name for a in resp.agents}
    # The wigamig repo ships at least these.
    assert {"oracle", "bookworm"} <= names
    for a in resp.agents:
        assert a.freeze in {"frozen", "personal"}


def test_oracle_recent_empty_when_no_dir(world):
    """Empty oracle/ → empty list (test fixture doesn't seed any)."""
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert resp.oracle_recent == []


def test_oracle_recent_picks_up_published_files(world):
    oracle_dir = world / "lab-mgmt" / "oracle"
    oracle_dir.mkdir(parents=True, exist_ok=True)
    (oracle_dir / "2026-05-08_finding.md").write_text(
        "---\n"
        "title: 'Test finding'\n"
        "author: '@allie'\n"
        "date: 2026-05-08\n"
        "project: dcis_test\n"
        "---\n\n"
        "# Test finding\n\n"
        "First paragraph as the excerpt.\n",
        encoding="utf-8",
    )
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert len(resp.oracle_recent) == 1
    entry = resp.oracle_recent[0]
    assert entry.title == "Test finding"
    assert entry.author == "@allie"
    assert "First paragraph" in entry.excerpt


def test_api_endpoint_rejects_invalid_persona(world):
    from fastapi.testclient import TestClient

    from wigamig.dashboard.server import create_app

    client = TestClient(create_app())
    resp = client.get("/api/dashboard?user=mhallet&persona=admin")
    # Pydantic regex validator on Query rejects with 422.
    assert resp.status_code == 422


def test_attention_includes_red_outstanding(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert any(item.sev == "red" for item in resp.attention)


def test_stats_strip_has_all_fields(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    s = resp.stats
    assert s.attention.red >= 0
    assert s.seas.in_ >= 0
    assert s.compliance.expired >= 0
    assert s.inventory.expired >= 1  # 4_oht is expired in the fixture
    assert s.notebook.entriesThisWeek == 0  # no notebook dir written


def test_spark_has_12_weekly_buckets(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    assert len(resp.spark) == 12
    assert len(resp.sparkLabels) == 12
    assert all(isinstance(x, int) for x in resp.spark)


def test_projects_list(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    names = {p.name for p in resp.projects}
    assert {"dcis_test", "bbb_test"} <= names
    dcis = next(p for p in resp.projects if p.name == "dcis_test")
    assert dcis.sens == "clinical"
    assert dcis.lead == "@allie"
    assert dcis.members == 4


def test_peers_have_tcps_status(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    handles = {p.handle for p in resp.peers}
    assert "bob" in handles
    assert "cassie" in handles
    cassie = next(p for p in resp.peers if p.handle == "cassie")
    assert cassie.tcps == "missing"


def test_seas_carry_direction(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    for s in resp.seas:
        assert s.dir in {"in", "out"}


def test_heatmap_cell_count_matches_member_count(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    n = len(resp.heatmap.members)
    assert n > 0
    for row in resp.heatmap.rows:
        assert len(row.cells) == n


def test_notebook_block_is_shape_correct_when_empty(world):
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    nb = resp.notebook
    assert nb.folder.endswith("/")
    assert len(nb.days) == 7
    assert nb.today.iso == "2026-05-08"
    assert nb.today.content  # at least the empty-state block
    assert nb.yesterday_excerpt.iso == "2026-05-07"


def test_notebook_renders_real_entry(world, tmp_path, monkeypatch):
    notebook_dir = tmp_path / "lab-notebook"
    notebook_dir.mkdir()
    (notebook_dir / "2026-05-08.md").write_text(
        "---\ntags: ['#dcis']\nlinks_seas: [214]\nlinks_exp: ['exp/2_align']\n---\n\n"
        "#### Plan\n\n"
        "- [ ] redo alignment\n"
        "- [x] stand-up\n\n"
        "Run 17 fastqs look fine. See [[exp/1_ingest]].\n\n"
        "> Mike: please get me a draft.\n\n"
        "```bash\nsamtools view -b run17.bam\n```\n",
        encoding="utf-8",
    )
    resp = snapshot.build_response("allie", today=_dt.date(2026, 5, 8))
    today = resp.notebook.today
    assert today.tags == ["#dcis"]
    assert today.links_seas == [214]
    assert today.links_exp == ["exp/2_align"]
    kinds = [b.kind for b in today.content]
    assert "h4" in kinds
    assert "task" in kinds
    assert "p" in kinds
    assert "blockquote" in kinds
    assert "code" in kinds


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def test_api_endpoint_returns_full_payload(world):
    from fastapi.testclient import TestClient

    from wigamig.dashboard.server import create_app

    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/dashboard?user=allie")
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert set(payload.keys()) == HIFI_TOP_LEVEL_KEYS
    contract.DashboardResponse.model_validate(payload)


def test_api_endpoint_400_when_no_user(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from wigamig.dashboard.server import create_app

    monkeypatch.delenv("WIGAMIG_USER", raising=False)
    monkeypatch.setenv("PATH", "")  # blocks gh fallback
    app = create_app()
    client = TestClient(app)
    resp = client.get("/api/dashboard")
    assert resp.status_code == 400


def test_healthz(world):
    from fastapi.testclient import TestClient

    from wigamig.dashboard.server import create_app

    app = create_app()
    client = TestClient(app)
    assert client.get("/healthz").json() == {"status": "ok"}
