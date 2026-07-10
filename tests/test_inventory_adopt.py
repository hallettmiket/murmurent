"""Tests for ``POST /api/inventory/adopt`` — the "promote a plain git
clone to a murmurent project" wizard exposed on the Repo Inventory panel.

What this endpoint must guarantee:
  - Writes a valid CHARTER.md at the clone root (uses
    :func:`murmurent.core.charter.render_charter`)
  - Runs the layer-2 CC bootstrap so ``.claude/agents/`` exists
  - Refuses paths outside ``~/repos/`` (escape guard — the dashboard
    sends absolute paths from the inventory scanner)
  - Refuses dirs that aren't a git working tree
  - Refuses to silently overwrite an existing CHARTER.md
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
    we point ``$HOME`` at tmp_path. ``$WIGAMIG_REPO_ROOT`` aims the
    layer-2 bootstrap at a fake commons that has the agents/ dir the
    real one would.
    """
    home = tmp_path / "home"
    (home / "repos").mkdir(parents=True)
    commons = tmp_path / "murmurent"
    (commons / "agents").mkdir(parents=True)
    (commons / "agents" / "blacksmith.md").write_text("# blacksmith\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("WIGAMIG_REPO_ROOT", str(commons))
    monkeypatch.setenv("WIGAMIG_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    return {"home": home, "repos": home / "repos", "commons": commons}


def _make_git_clone(repos: Path, name: str) -> Path:
    """Materialize a minimal ``~/repos/<name>`` that looks like a clone
    to the adopt endpoint (a ``.git`` dir is enough — we never invoke
    git itself)."""
    p = repos / name
    (p / ".git").mkdir(parents=True)
    return p


def test_adopt_writes_charter_and_runs_bootstrap(world):
    clone = _make_git_clone(world["repos"], "hockey_stats")
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": str(clone),
        "project": "hockey_stats",
        "lead": "@the_pi",
        "members": ["@the_pi"],
        "sensitivity": "standard",
        "description": "Personal hockey analytics.",
        "agents": ["blacksmith"],
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ok"] is True
    # CHARTER.md was written with valid frontmatter.
    charter = (clone / "CHARTER.md").read_text()
    assert "project: hockey_stats" in charter
    assert "lead: '@the_pi'" in charter
    assert "sensitivity: standard" in charter
    # .claude/agents/blacksmith.md was symlinked from the commons.
    agent_link = clone / ".claude" / "agents" / "blacksmith.md"
    assert agent_link.is_symlink()
    assert "blacksmith" in str(agent_link.readlink())
    # Probes reported back so the UI can render them inline.
    steps = {p["name"]: p["status"] for p in body["probes"]}
    assert steps["charter"] == "ok"
    assert steps["cc_agent: blacksmith"] == "ok"


def test_adopt_refuses_path_outside_repos(world):
    """Defends against ``clone_path: /etc`` shenanigans — the dashboard
    only ever sends paths from its own inventory scanner, but the
    endpoint must not trust them."""
    elsewhere = world["home"].parent / "elsewhere"
    (elsewhere / ".git").mkdir(parents=True)
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": str(elsewhere),
        "project": "x", "lead": "@the_pi", "members": ["@the_pi"],
    })
    assert res.status_code == 400
    assert "must live under" in res.json()["detail"]


def test_adopt_refuses_non_git_dir(world):
    bare = world["repos"] / "not_a_repo"
    bare.mkdir()
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": str(bare),
        "project": "x", "lead": "@the_pi", "members": ["@the_pi"],
    })
    assert res.status_code == 400
    assert "not a git working tree" in res.json()["detail"]


def test_adopt_refuses_when_charter_already_exists(world):
    """A clone that's already a murmurent project must not get its
    CHARTER.md silently overwritten — the user should edit by hand
    or remove the file and re-adopt explicitly."""
    clone = _make_git_clone(world["repos"], "already_a_project")
    (clone / "CHARTER.md").write_text("---\nproject: already\n---\n")
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": str(clone),
        "project": "already_a_project",
        "lead": "@the_pi", "members": ["@the_pi"],
    })
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


def test_adopt_propagates_charter_validation_errors(world):
    """Empty members list or unknown sensitivity must come back as a
    422 (charter-validation) rather than a 500."""
    clone = _make_git_clone(world["repos"], "badmeta")
    client = TestClient(create_app())
    res = client.post("/api/inventory/adopt", json={
        "clone_path": str(clone),
        "project": "badmeta",
        "lead": "@the_pi", "members": [],  # invalid: must be non-empty
    })
    assert res.status_code == 422
