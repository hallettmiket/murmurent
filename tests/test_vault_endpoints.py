"""Tests for the personal-vault dashboard endpoints (issue #25 §3):
  - GET  /api/vault/info    → freshness stamp (no network, no mutation)
  - POST /api/vault/refresh → ff-only pull, never a 5xx

machine.yaml is redirected to a tmp path; the vault is a real *local* git repo,
so nothing hits the network or the developer's real home.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from murmurent.dashboard import machine_settings as MS
from murmurent.dashboard.contract import MachineSettings
from murmurent.dashboard.server import create_app


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, check=False)


@pytest.fixture
def pinned_vault(monkeypatch, tmp_path):
    monkeypatch.setattr(MS, "MACHINE_FILE", tmp_path / "home" / "machine.yaml")

    def _pin(path: Path) -> None:
        MS.write(MachineSettings(obsidian_vault_path=str(path)))

    return _pin


def test_vault_info_unregistered(pinned_vault):
    client = TestClient(create_app())
    r = client.get("/api/vault/info")
    assert r.status_code == 200
    body = r.json()
    assert body["is_git"] is False and body["ok"] is False


def test_vault_info_reports_git_freshness(pinned_vault, tmp_path):
    clone = tmp_path / "vault"
    clone.mkdir()
    _git(clone, "init", "-q")
    _git(clone, "config", "user.email", "t@t"); _git(clone, "config", "user.name", "T")
    (clone / "a.md").write_text("a\n", encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-q", "-m", "seed")
    pinned_vault(clone)

    r = TestClient(create_app()).get("/api/vault/info")
    body = r.json()
    assert body["is_git"] is True and body["ok"] is True and body["as_of"]


def test_vault_refresh_no_remote_never_500(pinned_vault, tmp_path):
    clone = tmp_path / "vault"; clone.mkdir()
    _git(clone, "init", "-q")
    _git(clone, "config", "user.email", "t@t"); _git(clone, "config", "user.name", "T")
    (clone / "a.md").write_text("a\n", encoding="utf-8")
    _git(clone, "add", "-A"); _git(clone, "commit", "-q", "-m", "seed")
    pinned_vault(clone)

    r = TestClient(create_app()).post("/api/vault/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and "no remote" in body["detail"]


def test_vault_refresh_unregistered_never_500(pinned_vault):
    r = TestClient(create_app()).post("/api/vault/refresh")
    assert r.status_code == 200
    assert r.json()["ok"] is False
