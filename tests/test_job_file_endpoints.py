"""
Phase 5b tests: HTTP endpoints for per-job file delivery.

Covers:
  - GET /manifest: leader, registrar, requester-lab pass; outsider 403
  - GET /files: same gating; returns relpath + size
  - POST /files: leader/registrar only; requester forbidden
  - POST /files: validates relpath, base64 content; refuses '..'
  - GET /files/{relpath}: leader + requester-lab download;
    outsider 403; missing file 404
  - GET /files/{relpath}: enforces max_bytes (413)
  - 404 on unknown core/job
"""

from __future__ import annotations

import base64
from unittest.mock import patch

import pytest
import yaml
from fastapi.testclient import TestClient

from murmurent.core import jobs as J
from murmurent.core import registrar as R
from murmurent.core import service_requests as SR
from murmurent.core import services as S
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "wigamig_home"))
    monkeypatch.setenv("MURMURENT_USER", "alice")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("the_pi\n", encoding="utf-8")
    R.create_core(name="biocore", display_name="BioCORE", leader_handle="@gary")
    for h in ("alice", "bob", "the_pi", "gary"):
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active'}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    S.create_service(core="biocore", slug="itc", name="ITC")
    return tmp_path


@patch("murmurent.dashboard.slack_notify._post")
def _book(mock_post, client, user="alice"):
    res = client.post(
        f"/api/core/biocore/services/itc/book?user={user}",
        json={"slot": {"start": "2026-05-23T10:00-04:00",
                       "end":   "2026-05-23T11:00-04:00"}},
    )
    return res.json()["request_id"]


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


# ---- manifest ----------------------------------------------------------

def test_manifest_leader_ok(world):
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    res = client.get(
        f"/api/core/biocore/jobs/{rid}/manifest?user=gary",
    )
    assert res.status_code == 200, res.text
    assert res.json()["manifest"]["requester_lab"] == "hallett"


def test_manifest_requester_lab_ok(world):
    """alice is a hallett-lab member booking — her own lab can read."""
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    res = client.get(
        f"/api/core/biocore/jobs/{rid}/manifest?user=alice",
    )
    assert res.status_code == 200, res.text


def test_manifest_unknown_job(world):
    client = TestClient(create_app())
    res = client.get(
        "/api/core/biocore/jobs/ghost/manifest?user=gary",
    )
    assert res.status_code == 404


def test_manifest_unknown_core(world):
    client = TestClient(create_app())
    res = client.get(
        "/api/core/ghost/jobs/anything/manifest?user=gary",
    )
    assert res.status_code == 404


# ---- list files --------------------------------------------------------

def test_files_list_leader_sees_uploads(world):
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    J.write_file("biocore", rid, "refined/fit.png", b"PNGSTUB")
    res = client.get(
        f"/api/core/biocore/jobs/{rid}/files?user=gary",
    )
    assert res.status_code == 200
    rels = sorted(f["relpath"] for f in res.json()["files"])
    assert "refined/fit.png" in rels


# ---- upload ------------------------------------------------------------

def test_upload_leader_ok(world):
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    res = client.post(
        f"/api/core/biocore/jobs/{rid}/files?user=gary",
        json={"relpath": "refined/fit.png", "content_base64": _b64(b"PNGSTUB")},
    )
    assert res.status_code == 200, res.text
    assert res.json()["size_bytes"] == 7
    assert (J.job_dir("biocore", rid) / "refined" / "fit.png").read_bytes() == b"PNGSTUB"


def test_upload_requester_forbidden(world):
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    res = client.post(
        f"/api/core/biocore/jobs/{rid}/files?user=alice",
        json={"relpath": "refined/x.bin", "content_base64": _b64(b"x")},
    )
    assert res.status_code == 403


def test_upload_missing_relpath(world):
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    res = client.post(
        f"/api/core/biocore/jobs/{rid}/files?user=gary",
        json={"content_base64": _b64(b"x")},
    )
    assert res.status_code == 422


def test_upload_bad_base64(world):
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    res = client.post(
        f"/api/core/biocore/jobs/{rid}/files?user=gary",
        json={"relpath": "refined/x.bin", "content_base64": "!!!not-base64!!!"},
    )
    assert res.status_code == 422


def test_upload_path_escape_refused(world):
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    res = client.post(
        f"/api/core/biocore/jobs/{rid}/files?user=gary",
        json={"relpath": "../../oops.txt", "content_base64": _b64(b"x")},
    )
    assert res.status_code == 422


# ---- download ----------------------------------------------------------

def test_download_requester_lab_ok(world):
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    J.write_file("biocore", rid, "refined/fit.png", b"PNGSTUB")
    res = client.get(
        f"/api/core/biocore/jobs/{rid}/files/refined/fit.png?user=alice",
    )
    assert res.status_code == 200
    assert res.content == b"PNGSTUB"
    assert "fit.png" in res.headers.get("content-disposition", "")


def test_download_outsider_forbidden(world):
    """bob is in hallett lab too in this fixture (lab.md says lab=hallett);
    we need a true outsider. We don't have another lab in lab_mgmt, but a
    job from a different lab gives the right test."""
    # Hand-craft a job whose requester_lab differs from the local lab.
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    J.write_file("biocore", rid, "refined/fit.png", b"x")
    # Patch the manifest on disk to look like it came from a different lab.
    p = J.manifest_path("biocore", rid)
    import json
    m = json.loads(p.read_text())
    m["requester_lab"] = "castellani"
    p.write_text(json.dumps(m))
    # Now alice (in 'hallett') is neither leader, nor registrar, nor in
    # the castellani lab → 403.
    res = client.get(
        f"/api/core/biocore/jobs/{rid}/files/refined/fit.png?user=alice",
    )
    assert res.status_code == 403


def test_download_missing_file_404(world):
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    res = client.get(
        f"/api/core/biocore/jobs/{rid}/files/refined/never.bin?user=alice",
    )
    assert res.status_code == 404


def test_download_size_cap(world):
    client = TestClient(create_app())
    rid = _book.__wrapped__(None, client)
    J.write_file("biocore", rid, "refined/big.bin", b"x" * 1000)
    res = client.get(
        f"/api/core/biocore/jobs/{rid}/files/refined/big.bin"
        f"?user=alice&max_bytes=100",
    )
    assert res.status_code == 413
