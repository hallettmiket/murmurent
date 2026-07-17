"""Endpoint test for POST /api/inventory/upgrade (the Repos panel's Upgrade button)."""
from __future__ import annotations

import yaml
from fastapi.testclient import TestClient

from murmurent.dashboard.server import create_app


def _clone(repos, name):
    p = repos / name
    (p / ".git").mkdir(parents=True)
    return p


def test_upgrade_endpoint_converts_legacy_and_refuses_plain_clone(monkeypatch, tmp_path):
    repos = tmp_path / "repos"; repos.mkdir()
    commons = tmp_path / "commons"; (commons / "agents").mkdir(parents=True)
    (commons / "agents" / "blacksmith.md").write_text("# blacksmith\n")
    monkeypatch.setenv("MURMURENT_REPOS_ROOT", str(repos))
    monkeypatch.setenv("MURMURENT_REPO_ROOT", str(commons))

    client = TestClient(create_app())

    # A legacy CHARTER bootstrap gets a stamped marker; the CHARTER.md is
    # PRESERVED (it may be a project document — issue #28), and readiness now
    # comes from the .murmurent.yaml marker.
    legacy = _clone(repos, "oldie")
    (legacy / "CHARTER.md").write_text("---\nproject: oldie\nlab: mh\n---\n")
    (legacy / ".claude" / "agents").mkdir(parents=True)
    r = client.post("/api/inventory/upgrade", json={"clone_path": str(legacy)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "ready"
    assert (legacy / "CHARTER.md").exists()          # preserved, not deleted
    marker = yaml.safe_load((legacy / ".murmurent.yaml").read_text())
    assert marker["lab"] == "mh" and marker["murmurent"] == 1

    # A plain clone is NOT upgradable — it wants adopt, and the error says so.
    plain = _clone(repos, "grace")
    r = client.post("/api/inventory/upgrade", json={"clone_path": str(plain)})
    assert r.status_code == 409, r.text
    assert "adopt it first" in r.json()["detail"]
