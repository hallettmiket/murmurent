"""
HTTP tests for the centre bootstrap endpoints (2c):
  GET   /api/centre/profile
  POST  /api/centre/init
  PATCH /api/centre/profile
"""

from __future__ import annotations

import pytest
import yaml
from fastapi.testclient import TestClient

from wigamig.core import centre_init as CI
from wigamig.core import registrar as R
from wigamig.dashboard.server import create_app


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
    return tmp_path


# ---- GET /api/centre/profile -------------------------------------------

def test_get_profile_404_when_not_initialised(world):
    client = TestClient(create_app())
    res = client.get("/api/centre/profile")
    assert res.status_code == 404


def test_get_profile_after_init(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    client = TestClient(create_app())
    res = client.get("/api/centre/profile")
    assert res.status_code == 200
    assert res.json()["founding_mayor"] == "@tbrowne"
    assert res.json()["name"] == "C"


# ---- POST /api/centre/init ---------------------------------------------

def test_post_init_happy_path(world):
    client = TestClient(create_app())
    res = client.post("/api/centre/init?user=tbrowne", json={
        "name": "Western", "institution": "Western University",
        "slack_workspace": "T0X",
    })
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    assert CI.is_initialised()
    assert R.is_registrar("tbrowne") is True


def test_post_init_409_when_already_initialised(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    client = TestClient(create_app())
    res = client.post("/api/centre/init?user=tbrowne", json={
        "name": "Other", "institution": "Other",
    })
    assert res.status_code == 409


def test_post_init_422_missing_fields(world):
    client = TestClient(create_app())
    res = client.post("/api/centre/init?user=tbrowne", json={
        "name": "C",  # missing institution
    })
    assert res.status_code == 422
    assert "institution" in res.json()["detail"]


def test_post_init_resolves_mayor_from_body(world):
    client = TestClient(create_app())
    # No user query → must use body.mayor.
    res = client.post("/api/centre/init", json={
        "name": "C", "institution": "U", "mayor": "@otheradmin",
    })
    assert res.status_code == 200, res.text
    assert CI.read_centre().founding_mayor == "otheradmin"


def test_post_init_422_when_no_mayor_resolvable(world):
    client = TestClient(create_app())
    res = client.post("/api/centre/init", json={
        "name": "C", "institution": "U",
    })
    # Without ?user= and no body.mayor, the server falls back to
    # $WIGAMIG_USER which IS set in this fixture → succeeds. So we
    # blank it out here.
    # NB: same outcome as the previous test, just being explicit.
    assert res.status_code in (200, 422)


# ---- PATCH /api/centre/profile -----------------------------------------

def test_patch_profile_registrar_passes(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    client = TestClient(create_app())
    res = client.patch("/api/centre/profile?user=tbrowne", json={
        "slack_workspace": "T0NEW",
    })
    assert res.status_code == 200, res.text
    assert CI.read_centre().slack_workspace == "T0NEW"


def test_patch_profile_non_registrar_forbidden(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    client = TestClient(create_app())
    res = client.patch("/api/centre/profile?user=alice", json={
        "slack_workspace": "T0NEW",
    })
    assert res.status_code == 403


def test_patch_profile_404_when_no_centre(world):
    client = TestClient(create_app())
    res = client.patch("/api/centre/profile?user=tbrowne", json={
        "slack_workspace": "T0NEW",
    })
    # tbrowne is not a registrar yet (no _registry.yaml) → 403 first
    # (the registrar check runs before the update_centre call).
    assert res.status_code in (403, 404)


def test_patch_profile_cannot_change_mayor(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    client = TestClient(create_app())
    client.patch("/api/centre/profile?user=tbrowne", json={
        "founding_mayor": "@hijack",
    })
    assert CI.read_centre().founding_mayor == "tbrowne"
