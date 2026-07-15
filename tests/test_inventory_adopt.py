"""Tests for ``POST /api/inventory/adopt`` — "make this clone
murmurent-READY" from the Repo Inventory panel.

What this endpoint must guarantee (post readiness/project split):
  - Writes the ``.murmurent.yaml`` readiness marker at the clone root
  - Runs the layer-2 CC bootstrap so ``.claude/agents/`` exists
  - Creates NO project (no CHARTER.md, no registry record, no manifest)
  - Refuses paths outside ``~/repos/`` and non-git dirs
  - Points a legacy CHARTER.md bootstrap at `murmurent repo upgrade`
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Stand up an isolated ~/repos and a fake murmurent commons.

    The adopt endpoint resolves clone paths against ``Path.home()``, so
    we point ``$HOME`` at tmp_path. ``$MURMURENT_REPO_ROOT`` aims the
    layer-2 bootstrap at a fake commons that has the agents/ dir the
    real one would.
    """
    home = tmp_path / "home"
    (home / "repos").mkdir(parents=True)
    commons = tmp_path / "murmurent"
    (commons / "agents").mkdir(parents=True)
    (commons / "agents" / "blacksmith.md").write_text("# blacksmith\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("MURMURENT_REPO_ROOT", str(commons))
    monkeypatch.setenv("MURMURENT_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    return {"home": home, "repos": home / "repos", "commons": commons}


def _make_git_clone(repos: Path, name: str) -> Path:
    """Materialize a minimal ``~/repos/<name>`` that looks like a clone
    to the adopt endpoint (a ``.git`` dir is enough — we never invoke
    git itself)."""
    p = repos / name
    (p / ".git").mkdir(parents=True)
    return p


def test_adopt_writes_marker_and_runs_bootstrap(world):
    clone = _make_git_clone(world["repos"], "hockey_stats")
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": str(clone),
        "lab": "mh",
        "agents": ["blacksmith"],
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True and body["repo"] == "hockey_stats"
    # Readiness marker written; NO project artefacts.
    import yaml as _yaml
    marker = _yaml.safe_load((clone / ".murmurent.yaml").read_text())
    assert marker["murmurent"] == 1
    assert marker["lab"] == "mh"
    assert marker["agents"] == ["blacksmith"]
    assert not (clone / "CHARTER.md").exists()
    # .claude/agents/blacksmith.md was symlinked from the commons.
    agent_link = clone / ".claude" / "agents" / "blacksmith.md"
    assert agent_link.is_symlink()
    assert "blacksmith" in str(agent_link.readlink())
    # Probes reported back so the UI can render them inline.
    steps = {p["name"]: p["status"] for p in body["probes"]}
    assert steps["marker"] == "ok"
    assert steps["cc_agent: blacksmith"] == "ok"


def test_adopt_refuses_path_outside_repos(world):
    """Defends against ``clone_path: /etc`` shenanigans — the dashboard
    only ever sends paths from its own inventory scanner, but the
    endpoint must not trust them."""
    elsewhere = world["home"].parent / "elsewhere"
    (elsewhere / ".git").mkdir(parents=True)
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={"clone_path": str(elsewhere)})
    assert res.status_code == 400
    assert "must live under" in res.json()["detail"]


def test_adopt_refuses_non_git_dir(world):
    bare = world["repos"] / "not_a_repo"
    bare.mkdir()
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={"clone_path": str(bare)})
    assert res.status_code == 400
    assert "not a git working tree" in res.json()["detail"]


def test_adopt_points_legacy_charter_at_upgrade(world):
    """A pre-split bootstrap (CHARTER.md) shouldn't be re-adopted over —
    the conversion path is `murmurent repo upgrade`."""
    clone = _make_git_clone(world["repos"], "already_a_project")
    (clone / "CHARTER.md").write_text("---\nproject: already\n---\n")
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={"clone_path": str(clone)})
    assert res.status_code == 409
    assert "murmurent repo upgrade" in res.json()["detail"]


def test_adopt_is_idempotent_on_marker(world):
    """Re-adopting a marker-ready repo refreshes the bootstrap instead of
    erroring — the marker (and its agent picks) are preserved."""
    clone = _make_git_clone(world["repos"], "again")
    client = TestClient(create_app())
    first = client.post("/api/inventory/adopt",
                        json={"clone_path": str(clone), "agents": ["blacksmith"]})
    assert first.status_code == 200
    second = client.post("/api/inventory/adopt", json={"clone_path": str(clone)})
    assert second.status_code == 200, second.text
    import yaml as _yaml
    marker = _yaml.safe_load((clone / ".murmurent.yaml").read_text())
    assert marker["agents"] == ["blacksmith"]           # pick preserved
