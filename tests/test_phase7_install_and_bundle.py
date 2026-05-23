"""
Phase 7 tests: MCP install wiring + bundle_job tool/endpoint.

7a: ``wigamig install --hooks`` must register ``wigamig-core-data``
    alongside ``wigamig-inventory`` and ``wigamig-oracle``.

7b: bundle_job — pure helper, MCP tool, HTTP endpoint.
    Verifies tar.gz roundtrip, permission gating, size cap, and the
    exclude_manifest flag.
"""

from __future__ import annotations

import base64
import io
import json
import tarfile
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from wigamig.core import jobs as J
from wigamig.core import registrar as R
from wigamig.core import service_requests as SR
from wigamig.core import services as S
from wigamig.dashboard.server import create_app
from wigamig.mcp import core_data_server as MCP


# ---- Phase 7a: install registration ------------------------------------

def test_install_registers_core_data_mcp(tmp_path):
    """A fresh `wigamig install --hooks` populates mcpServers with
    wigamig-core-data so members get the MCP without manual config."""
    from wigamig.commands import install_cmd
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    install_cmd.cmd_install(hooks=True, settings_path=settings, backup=False)
    data = json.loads(settings.read_text())
    assert "wigamig-core-data" in data["mcpServers"]
    spec = data["mcpServers"]["wigamig-core-data"]
    assert spec["args"] == ["-m", "wigamig.mcp.core_data_server"]


# ---- Phase 7b: bundle_job ---------------------------------------------

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
    for h in ("alice", "the_pi", "gary"):
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active'}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    S.create_service(core="biocore", slug="itc", name="ITC")
    return tmp_path


def _make_job_with_files(world, requester_lab="hallett"):
    req = SR.create_request(
        core="biocore", service="itc",
        requester="@alice", requester_lab=requester_lab,
        booked_slot=SR.BookingSlot(start="2026-05-23T10:00-04:00",
                                     end="2026-05-23T11:00-04:00"),
    )
    J.write_file("biocore", req.request_id, "raw/sample1.itc", b"RAW1")
    J.write_file("biocore", req.request_id, "refined/fit.png", b"PNGSTUB")
    return req


def _untar(blob: bytes) -> dict[str, bytes]:
    """tar.gz blob -> {arcname: bytes}."""
    out: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            f = tar.extractfile(m)
            if f is not None:
                out[m.name] = f.read()
    return out


# helper -----------------------------------------------------------------

def test_bundle_helper_roundtrip(world):
    req = _make_job_with_files(world)
    blob = J.bundle_job_tarball("biocore", req.request_id)
    files = _untar(blob)
    keys = sorted(files)
    # arcname is "<job_id>/<rel>"
    assert f"{req.request_id}/raw/sample1.itc" in keys
    assert f"{req.request_id}/refined/fit.png" in keys
    assert f"{req.request_id}/manifest.json" in keys
    assert files[f"{req.request_id}/raw/sample1.itc"] == b"RAW1"


def test_bundle_helper_exclude_manifest(world):
    req = _make_job_with_files(world)
    blob = J.bundle_job_tarball("biocore", req.request_id,
                                   exclude_manifest=True)
    files = _untar(blob)
    assert all(not k.endswith("/manifest.json") for k in files)


def test_bundle_helper_unknown_job(world):
    with pytest.raises(J.JobError, match="not found"):
        J.bundle_job_tarball("biocore", "ghost")


# MCP tool ---------------------------------------------------------------

def test_mcp_bundle_returns_base64_tarball(world, monkeypatch):
    req = _make_job_with_files(world)
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_bundle_job("biocore", req.request_id)
    assert out["ok"] is True
    assert out["format"] == "tar.gz"
    files = _untar(base64.b64decode(out["content_base64"]))
    assert f"{req.request_id}/raw/sample1.itc" in files


def test_mcp_bundle_denied_for_other_lab(world, monkeypatch):
    req = _make_job_with_files(world)
    # Hand-craft manifest from a different lab.
    p = J.manifest_path("biocore", req.request_id)
    m = json.loads(p.read_text())
    m["requester_lab"] = "castellani"
    p.write_text(json.dumps(m))
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_bundle_job("biocore", req.request_id)
    assert out["ok"] is False
    assert "not in the job" in out["error"]


def test_mcp_bundle_size_cap(world, monkeypatch):
    req = _make_job_with_files(world)
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_bundle_job("biocore", req.request_id, max_bytes=10)
    assert out["ok"] is False
    assert "max" in out["error"]


def test_mcp_bundle_unknown_job(world, monkeypatch):
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    out = MCP.tool_bundle_job("biocore", "ghost")
    assert out["ok"] is False
    assert "not found" in out["error"]


# HTTP endpoint ----------------------------------------------------------

def test_http_bundle_requester_lab_ok(world):
    req = _make_job_with_files(world)
    client = TestClient(create_app())
    res = client.get(
        f"/api/core/biocore/jobs/{req.request_id}/bundle?user=alice",
    )
    assert res.status_code == 200
    assert "gzip" in res.headers.get("content-type", "")
    files = _untar(res.content)
    assert any(k.endswith("/refined/fit.png") for k in files)
    assert f"{req.request_id}.tar.gz" in res.headers.get("content-disposition", "")


def test_http_bundle_leader_ok(world):
    req = _make_job_with_files(world)
    client = TestClient(create_app())
    res = client.get(
        f"/api/core/biocore/jobs/{req.request_id}/bundle?user=gary",
    )
    assert res.status_code == 200


def test_http_bundle_size_cap_413(world):
    req = _make_job_with_files(world)
    client = TestClient(create_app())
    res = client.get(
        f"/api/core/biocore/jobs/{req.request_id}/bundle?user=alice&max_bytes=10",
    )
    assert res.status_code == 413


def test_http_bundle_unknown_job_404(world):
    client = TestClient(create_app())
    res = client.get(
        "/api/core/biocore/jobs/ghost/bundle?user=alice",
    )
    assert res.status_code == 404


def test_http_bundle_outsider_forbidden(world):
    req = _make_job_with_files(world)
    # Patch manifest to a different lab.
    p = J.manifest_path("biocore", req.request_id)
    m = json.loads(p.read_text())
    m["requester_lab"] = "castellani"
    p.write_text(json.dumps(m))
    client = TestClient(create_app())
    res = client.get(
        f"/api/core/biocore/jobs/{req.request_id}/bundle?user=alice",
    )
    assert res.status_code == 403
