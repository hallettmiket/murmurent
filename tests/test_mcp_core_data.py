"""
Phase 5d tests: murmurent-core-data MCP server tool shims.

We test the ``tool_*`` Python entry points directly (no MCP SDK
needed) — the FastMCP wrapper is a thin JSON shim around these.

Covers:
  - list_my_jobs returns only jobs the caller's lab can see
  - core staff (leader, registrar) see every job
  - get_job_manifest: hit / 404 / denied
  - list_job_files: hit / denied
  - read_job_file: hit (base64); denied; missing file; size cap
  - safe_resolve path-escape refused
  - access.log appended for every call
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
import yaml

from murmurent.core import jobs as J
from murmurent.core import registrar as R
from murmurent.core import service_requests as SR
from murmurent.core import services as S
from murmurent.mcp import core_data_server as MCP


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("WIGAMIG_HOME", str(tmp_path / "wigamig_home"))
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("the_pi\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    S.create_service(core="biocore", slug="itc", name="ITC")
    return tmp_path


def _book(requester="@alice", lab="hallett"):
    return SR.create_request(
        core="biocore", service="itc",
        requester=requester, requester_lab=lab,
        booked_slot=SR.BookingSlot(start="2026-05-23T10:00-04:00",
                                     end="2026-05-23T11:00-04:00"),
    )


# ---- list_my_jobs ------------------------------------------------------

def test_list_my_jobs_filters_by_caller_lab(world, monkeypatch):
    _book(requester="@alice", lab="hallett")
    _book(requester="@bob",   lab="castellani")
    # alice (hallett) sees only the hallett job.
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_list_my_jobs(core="biocore")
    assert out["count"] == 1
    assert out["jobs"][0]["requester_lab"] == "hallett"


def test_list_my_jobs_core_leader_sees_all(world, monkeypatch):
    _book(requester="@alice", lab="hallett")
    _book(requester="@bob",   lab="castellani")
    monkeypatch.setenv("WIGAMIG_USER", "gary")
    out = MCP.tool_list_my_jobs(core="biocore")
    assert out["count"] == 2


def test_list_my_jobs_registrar_sees_all(world, monkeypatch):
    _book(requester="@alice", lab="hallett")
    _book(requester="@bob",   lab="castellani")
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
    out = MCP.tool_list_my_jobs(core="biocore")
    assert out["count"] == 2


def test_list_my_jobs_unknown_user_empty(world, monkeypatch):
    _book(requester="@alice", lab="hallett")
    monkeypatch.setenv("WIGAMIG_USER", "")
    monkeypatch.setenv("USER", "")
    out = MCP.tool_list_my_jobs(core="biocore")
    assert out["count"] == 0


# ---- get_job_manifest --------------------------------------------------

def test_get_manifest_hit(world, monkeypatch):
    req = _book()
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_get_job_manifest("biocore", req.request_id)
    assert out["ok"] is True
    assert out["manifest"]["requester_lab"] == "hallett"


def test_get_manifest_404(world):
    out = MCP.tool_get_job_manifest("biocore", "ghost")
    assert out["ok"] is False
    assert "not found" in out["error"]


def test_get_manifest_denied(world, monkeypatch):
    """Hand-craft a manifest from a different lab; alice can't read it."""
    req = _book()
    p = J.manifest_path("biocore", req.request_id)
    m = json.loads(p.read_text())
    m["requester_lab"] = "castellani"
    p.write_text(json.dumps(m))
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_get_job_manifest("biocore", req.request_id)
    assert out["ok"] is False
    assert "not in the job" in out["error"]


# ---- list_job_files ----------------------------------------------------

def test_list_job_files_hit(world, monkeypatch):
    req = _book()
    J.write_file("biocore", req.request_id, "refined/fit.png", b"X" * 50)
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_list_job_files("biocore", req.request_id)
    assert out["ok"] is True
    rels = sorted(f["relpath"] for f in out["files"])
    assert "refined/fit.png" in rels


def test_list_job_files_denied(world, monkeypatch):
    req = _book()
    p = J.manifest_path("biocore", req.request_id)
    m = json.loads(p.read_text())
    m["requester_lab"] = "castellani"
    p.write_text(json.dumps(m))
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_list_job_files("biocore", req.request_id)
    assert out["ok"] is False


# ---- read_job_file -----------------------------------------------------

def test_read_job_file_hit_base64(world, monkeypatch):
    req = _book()
    J.write_file("biocore", req.request_id, "refined/fit.png", b"PNGDATA")
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_read_job_file("biocore", req.request_id,
                                    "refined/fit.png")
    assert out["ok"] is True
    assert base64.b64decode(out["content_base64"]) == b"PNGDATA"
    assert out["size_bytes"] == 7


def test_read_job_file_missing(world, monkeypatch):
    req = _book()
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_read_job_file("biocore", req.request_id,
                                    "refined/never.bin")
    assert out["ok"] is False


def test_read_job_file_size_cap(world, monkeypatch):
    req = _book()
    J.write_file("biocore", req.request_id, "refined/big.bin", b"x" * 1000)
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_read_job_file("biocore", req.request_id,
                                    "refined/big.bin", max_bytes=100)
    assert out["ok"] is False
    assert "too large" in out["error"]


def test_read_job_file_path_escape(world, monkeypatch):
    req = _book()
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_read_job_file("biocore", req.request_id,
                                    "../../etc/passwd")
    assert out["ok"] is False
    assert "escape" in out["error"]


# ---- access log --------------------------------------------------------

def test_access_log_records_calls(world, monkeypatch):
    req = _book()
    J.write_file("biocore", req.request_id, "refined/fit.png", b"x")
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    MCP.tool_list_my_jobs(core="biocore")
    MCP.tool_get_job_manifest("biocore", req.request_id)
    MCP.tool_read_job_file("biocore", req.request_id, "refined/fit.png")
    log = world / "wigamig_home" / "cores" / "biocore" / "access.log"
    assert log.is_file()
    lines = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines() if l]
    events = {l["event"] for l in lines}
    assert "get_job_manifest" in events
    assert "read_job_file" in events
    assert all(l["caller"] == "alice" for l in lines)
