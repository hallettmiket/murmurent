"""
Phase 8 tests: audit log slice + deliverables overview.

8a: slice_for_core reads lab_info git log; filters to ``core <c>:``
    prefix; returns newest first; tolerates missing git/repo.

8b: deliverables.overview aggregates per-job file count + bytes +
    last upload + last access (parsed from MCP access.log).

HTTP: both endpoints leader/registrar gated; 404 unknown core;
       outsider 403.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from wigamig.core import audit_slice as AUDIT
from wigamig.core import deliverables as DLV
from wigamig.core import jobs as J
from wigamig.core import registrar as R
from wigamig.core import service_requests as SR
from wigamig.core import services as S
from wigamig.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "wigamig_home"))
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("mhallet\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    for h in ("alice", "mhallet", "gary", "bob"):
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active'}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    S.create_service(core="biocore", slug="itc", name="ITC")
    return tmp_path


# ---- 8a: audit slice ---------------------------------------------------

def test_slice_returns_empty_when_no_git(world, monkeypatch, tmp_path):
    """Point lab_info at a non-repo dir — slice must return [] not crash."""
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "empty_no_git"))
    (tmp_path / "empty_no_git").mkdir()
    assert AUDIT.slice_for_core("biocore") == []


def test_slice_filters_to_core_prefix(world):
    """create_core + create_service already produced commits with the
    'core biocore:' prefix; slice should pick them up."""
    rows = AUDIT.slice_for_core("biocore")
    assert len(rows) >= 1
    subjects = [r.subject for r in rows]
    # Latest commit should be the service creation.
    assert any("service" in s.lower() and "itc" in s.lower() for s in subjects)


def test_slice_picks_up_request_lifecycle(world):
    req = SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
        booked_slot=SR.BookingSlot(start="2026-05-23T10:00-04:00",
                                     end="2026-05-23T11:00-04:00"),
    )
    SR.transition_request(core="biocore", request_id=req.request_id,
                            to_state=SR.STATE_IN_PROGRESS)
    rows = AUDIT.slice_for_core("biocore")
    subjects = [r.subject for r in rows]
    assert any("created" in s for s in subjects)
    assert any("in_progress" in s for s in subjects)


def test_slice_limit_respected(world):
    """Generate 5 trivial commits; ask for 2 → get exactly 2."""
    for i in range(5):
        SR.create_request(
            core="biocore", service="itc",
            requester=f"@u{i}", requester_lab="hallett",
        )
    rows = AUDIT.slice_for_core("biocore", limit=2)
    assert len(rows) == 2


def test_slice_other_core_filtered_out(world):
    """A commit with 'core other:' prefix must not appear for biocore."""
    R.create_core(name="other_core", display_name="Other",
                   leader_handle="@sam")
    rows = AUDIT.slice_for_core("biocore")
    assert all("other" not in r.subject.lower()
                or "biocore" in r.subject.lower() for r in rows)


# ---- 8b: deliverables overview -----------------------------------------

def test_overview_counts_files_and_bytes(world):
    req = SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
        booked_slot=SR.BookingSlot(start="2026-05-23T10:00-04:00",
                                     end="2026-05-23T11:00-04:00"),
    )
    J.write_file("biocore", req.request_id, "raw/x.bin", b"X" * 100)
    J.write_file("biocore", req.request_id, "refined/y.bin", b"Y" * 250)
    rows = DLV.overview(core="biocore")
    assert len(rows) == 1
    r = rows[0]
    # manifest.json + raw/x + refined/y = 3 files; sizes include manifest
    assert r.file_count == 3
    assert r.bytes_total >= 350
    assert r.last_upload_at != ""


def test_overview_empty_when_no_jobs(world):
    assert DLV.overview(core="biocore") == []


def test_overview_reads_access_log(world):
    req = SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
    )
    # Hand-write an access log entry as the MCP would.
    home = world / "wigamig_home" / "cores" / "biocore"
    home.mkdir(parents=True, exist_ok=True)
    (home / "access.log").write_text(
        json.dumps({"ts": "2026-05-23T12:00:00Z", "caller": "alice",
                     "event": "read_job_file",
                     "job_id": req.request_id}) + "\n",
        encoding="utf-8",
    )
    rows = DLV.overview(core="biocore")
    assert rows[0].last_access_at == "2026-05-23T12:00:00Z"
    assert rows[0].accessed_by == ["alice"]


def test_overview_ignores_denied_events(world):
    req = SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
    )
    home = world / "wigamig_home" / "cores" / "biocore"
    home.mkdir(parents=True, exist_ok=True)
    (home / "access.log").write_text(
        json.dumps({"ts": "2026-05-23T12:00:00Z", "caller": "bob",
                     "event": "read_job_file_denied",
                     "job_id": req.request_id}) + "\n",
        encoding="utf-8",
    )
    rows = DLV.overview(core="biocore")
    assert rows[0].last_access_at == ""
    assert rows[0].accessed_by == []


def test_overview_live_first_then_terminal(world):
    """Two requests, one scheduled, one cancelled — live row sorts first."""
    a = SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
        booked_slot=SR.BookingSlot(start="2026-05-24T10:00-04:00",
                                     end="2026-05-24T11:00-04:00"),
    )
    b = SR.create_request(
        core="biocore", service="itc",
        requester="@bob", requester_lab="hallett",
        booked_slot=SR.BookingSlot(start="2026-05-23T10:00-04:00",
                                     end="2026-05-23T11:00-04:00"),
    )
    SR.transition_request(core="biocore", request_id=b.request_id,
                            to_state=SR.STATE_CANCELLED)
    rows = DLV.overview(core="biocore")
    assert rows[0].job_id == a.request_id   # live first
    assert rows[-1].job_id == b.request_id  # terminal last


# ---- HTTP --------------------------------------------------------------

def test_http_audit_leader_ok(world):
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/audit?user=gary")
    assert res.status_code == 200
    assert "entries" in res.json()


def test_http_audit_outsider_forbidden(world):
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/audit?user=alice")
    assert res.status_code == 403


def test_http_audit_unknown_core(world):
    client = TestClient(create_app())
    res = client.get("/api/core/ghost/audit?user=gary")
    assert res.status_code == 404


def test_http_deliverables_leader_ok(world):
    req = SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab="hallett",
    )
    J.write_file("biocore", req.request_id, "refined/a.bin", b"x")
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/deliverables?user=gary")
    assert res.status_code == 200
    rows = res.json()["rows"]
    assert len(rows) == 1
    assert rows[0]["file_count"] >= 2   # manifest + a.bin


def test_http_deliverables_outsider_forbidden(world):
    client = TestClient(create_app())
    res = client.get("/api/core/biocore/deliverables?user=alice")
    assert res.status_code == 403


def test_http_deliverables_unknown_core(world):
    client = TestClient(create_app())
    res = client.get("/api/core/ghost/deliverables?user=gary")
    assert res.status_code == 404
