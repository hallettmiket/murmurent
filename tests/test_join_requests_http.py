"""
HTTP tests for the join-request endpoints (2f).
"""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core import centre_init as CI
from murmurent.core import centre_provision as CP
from murmurent.core import join_requests as JR
from murmurent.core import registrar as R
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "tbrowne")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@tbrowne'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab-mgmt" / "members" / "tbrowne.md").write_text(
        "---\nhandle: '@tbrowne'\nrole: lead\nstatus: active\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "lab-mgmt" / "members" / "alice.md").write_text(
        "---\nhandle: '@alice'\nrole: postdoc\nstatus: active\n---\n",
        encoding="utf-8",
    )
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL",
                         fake_home / ".wigamig" / "registrar")
    CI.init_centre(
        name="C", institution="U", founding_mayor="@tbrowne",
        slack_workspace="T0X", github_org="centre-x",
        data_server="biodatsci",
        write_sentinel=False,
    )
    # Patch the live Slack creator to a deterministic fake. (No GitHub creator
    # to patch — the mayor onboarding path never creates the group's repo.)
    monkeypatch.setattr(CP, "_live_slack_create_channel",
                         lambda n, w: "C0FAKE")
    # Patch the acl runner via the public function — call apply_fs_acl
    # with our own runner.
    real_apply = CP.apply_fs_acl
    import subprocess
    def patched_apply(**kw):
        kw["runner"] = lambda argv: subprocess.CompletedProcess(
            argv, 0, "ok\n", "")
        return real_apply(**kw)
    monkeypatch.setattr(CP, "apply_fs_acl", patched_apply)
    return tmp_path


def _client():
    return TestClient(create_app())


# ---- public submit -----------------------------------------------------

def test_public_submit_happy_path(world):
    res = _client().post("/api/centre/join_requests", json={
        "kind": "lab", "proposed_name": "demo",
        "proposed_pi": "@dpi",
        "requester_email": "dpi@uwo.ca",
        "institution_affiliation": "Western",
        "justification": "I run a small lab.",
    })
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert res.json()["state"] == "pending"
    assert "dpi@uwo.ca" in res.json()["message"]


def test_public_submit_validates_kind(world):
    res = _client().post("/api/centre/join_requests", json={
        "kind": "weird", "proposed_name": "demo",
        "proposed_pi": "@dpi", "requester_email": "x@y",
    })
    assert res.status_code == 422


def test_public_submit_lab_requires_pi(world):
    res = _client().post("/api/centre/join_requests", json={
        "kind": "lab", "proposed_name": "demo",
        "proposed_pi": "", "requester_email": "x@y",
    })
    assert res.status_code == 422
    assert "proposed_pi" in res.json()["detail"]


# ---- list (registrar vs other) -----------------------------------------

def test_list_registrar_sees_all(world):
    JR.file_request(kind="lab", requester_email="a@x",
                     proposed_name="alpha", proposed_pi="@a")
    res = _client().get("/api/centre/join_requests?user=tbrowne")
    assert res.status_code == 200
    assert len(res.json()["join_requests"]) == 1


def test_list_non_registrar_sees_empty(world):
    JR.file_request(kind="lab", requester_email="a@x",
                     proposed_name="alpha", proposed_pi="@a")
    res = _client().get("/api/centre/join_requests?user=alice")
    assert res.json()["join_requests"] == []


# ---- approve -----------------------------------------------------------

def test_approve_lab_end_to_end(world):
    JR.file_request(kind="lab", requester_email="dpi@uwo.ca",
                     proposed_name="demo", proposed_pi="@dpi")
    res = _client().post(
        "/api/registrar/join_request/1/approve?user=tbrowne",
    )
    assert res.status_code == 200, res.text
    rj = res.json()["request"]
    assert rj["state"] == "provisioned"
    kinds = [p["kind"] for p in rj["probes"]]
    assert "slack-channel" in kinds and "github-repo" in kinds
    assert any(k.startswith("fs-acl") for k in kinds)


def test_approve_non_registrar_forbidden(world):
    JR.file_request(kind="lab", requester_email="x@y",
                     proposed_name="demo", proposed_pi="@p")
    res = _client().post(
        "/api/registrar/join_request/1/approve?user=alice",
    )
    assert res.status_code == 403


def test_approve_unknown_404(world):
    res = _client().post(
        "/api/registrar/join_request/99/approve?user=tbrowne",
    )
    assert res.status_code == 404


def test_approve_already_resolved_422(world):
    JR.file_request(kind="admin", requester_email="x@y",
                     proposed_name="role", proposed_pi="@p")
    _client().post("/api/registrar/join_request/1/approve?user=tbrowne",
                     json={"provision": False})
    res = _client().post(
        "/api/registrar/join_request/1/approve?user=tbrowne",
        json={"provision": False},
    )
    assert res.status_code == 422


# ---- decline -----------------------------------------------------------

def test_decline_happy_path(world):
    JR.file_request(kind="lab", requester_email="x@y",
                     proposed_name="demo", proposed_pi="@p")
    res = _client().post(
        "/api/registrar/join_request/1/decline?user=tbrowne",
        json={"reason": "duplicate of a prior request"},
    )
    assert res.status_code == 200
    assert res.json()["request"]["state"] == "declined"


def test_decline_requires_reason(world):
    JR.file_request(kind="lab", requester_email="x@y",
                     proposed_name="demo", proposed_pi="@p")
    res = _client().post(
        "/api/registrar/join_request/1/decline?user=tbrowne",
        json={"reason": ""},
    )
    assert res.status_code == 422


def test_decline_non_registrar_forbidden(world):
    JR.file_request(kind="lab", requester_email="x@y",
                     proposed_name="demo", proposed_pi="@p")
    res = _client().post(
        "/api/registrar/join_request/1/decline?user=alice",
        json={"reason": "no"},
    )
    assert res.status_code == 403


# ---- probes long-poll --------------------------------------------------

def test_probes_endpoint_returns_state_and_probes(world):
    JR.file_request(kind="lab", requester_email="x@y",
                     proposed_name="demo", proposed_pi="@p")
    _client().post(
        "/api/registrar/join_request/1/approve?user=tbrowne",
    )
    res = _client().get("/api/registrar/join_request/1/probes?user=tbrowne")
    assert res.status_code == 200
    assert res.json()["state"] == "provisioned"
    assert len(res.json()["probes"]) >= 3
