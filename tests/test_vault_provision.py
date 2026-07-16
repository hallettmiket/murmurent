"""Tests for core/vault_provision.py — personal-vault (murmurent_vault)
provisioning. Injects fake repo_creator / cloner / owner_resolver seams so NO
real `gh repo create` and NO real clone ever run. machine.yaml is redirected to
a tmp path so nothing touches the developer's real ~/.murmurent or vault.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from murmurent.core import vault_provision as VP
from murmurent.dashboard import machine_settings as MS
from murmurent.dashboard.contract import MachineSettings


@pytest.fixture(autouse=True)
def _isolate_machine_yaml(monkeypatch, tmp_path):
    """Redirect machine.yaml so pinning never touches the real home."""
    monkeypatch.setattr(MS, "MACHINE_FILE", tmp_path / "_home" / "machine.yaml")


def _fake_cloner_factory(record):
    """A cloner that 'clones' by making the (empty) dest dir — no network."""
    def cloner(owner, name, dest):
        record["cloned"] = (owner, name, str(dest))
        Path(dest).mkdir(parents=True, exist_ok=True)
        return (True, "cloned")
    return cloner


def _spy_syncer(record):
    from murmurent.core.vault_sync import CommitResult

    def syncer(path, *, message):
        record["synced"] = (str(path), message)
        return CommitResult(ok=True, committed=True, pushed=True, detail="pushed")
    return syncer


# ---- seed content + scaffold -------------------------------------------------

def test_seed_claude_md_mentions_vault_paths_and_maps_legends():
    text = VP.seed_claude_md()
    assert "murmurent vault paths" in text
    assert "maps-legends/" in text
    assert "oracle/" in text and "lab-notebook/" in text


def test_scaffold_vault_creates_layout_idempotently(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    created = VP.scaffold_vault(root)
    for sub in VP.VAULT_SUBDIRS:
        assert (root / sub).is_dir()
        assert (root / sub / ".gitkeep").exists()
    assert (root / "CLAUDE.md").exists()
    assert "CLAUDE.md" in created
    # Second run is a no-op (nothing new created).
    assert VP.scaffold_vault(root) == []


def test_scaffold_never_overwrites_existing_claude_md(tmp_path):
    root = tmp_path / "vault"; root.mkdir()
    (root / "CLAUDE.md").write_text("MY OWN NOTES\n", encoding="utf-8")
    VP.scaffold_vault(root)
    assert (root / "CLAUDE.md").read_text() == "MY OWN NOTES\n"


# ---- init_personal_vault: happy path -----------------------------------------

def test_init_creates_repo_clones_scaffolds_and_pins(tmp_path):
    record = {}
    dest = tmp_path / "clone"

    def repo_creator(owner, name):
        record["created"] = (owner, name)
        return (True, "created")

    out = VP.init_personal_vault(
        path=dest, owner="@allie",
        repo_creator=repo_creator,
        cloner=_fake_cloner_factory(record),
        syncer=_spy_syncer(record),
    )
    assert out["ok"] is True
    assert out["repo"] == "allie/murmurent_vault"
    assert record["created"] == ("allie", "murmurent_vault")
    assert record["cloned"][1] == "murmurent_vault"
    assert out["created_repo"] is True and out["cloned"] is True and out["adopted"] is False
    # scaffolded into the clone
    assert (dest / "oracle" / "drafts").is_dir()
    assert (dest / "CLAUDE.md").exists()
    assert out["committed"] and out["pushed"]
    # machine.yaml pinned to the clone
    assert out["pinned"] is True
    assert MS.load().obsidian_vault_path == str(dest)


def test_init_resolves_owner_via_resolver_when_absent(tmp_path):
    out = VP.init_personal_vault(
        path=tmp_path / "c", owner=None,
        owner_resolver=lambda: "bob",
        repo_creator=lambda o, n: (True, "created"),
        cloner=_fake_cloner_factory({}),
        syncer=_spy_syncer({}),
    )
    assert out["ok"] and out["owner"] == "bob"


def test_init_no_owner_is_clean_error(tmp_path):
    out = VP.init_personal_vault(
        path=tmp_path / "c", owner=None, owner_resolver=lambda: None,
        repo_creator=lambda o, n: (True, "x"), cloner=_fake_cloner_factory({}),
        syncer=_spy_syncer({}))
    assert out["ok"] is False and out["error"] == "no_github_owner"


def test_init_default_path_uses_repos_root(monkeypatch, tmp_path):
    """No --path → clone lands at <repos>/murmurent_vault (isolated repos root)."""
    monkeypatch.setenv("MURMURENT_REPOS_ROOT", str(tmp_path / "repos"))
    out = VP.init_personal_vault(
        owner="allie", repo_creator=lambda o, n: (True, "created"),
        cloner=_fake_cloner_factory({}), syncer=_spy_syncer({}))
    assert out["ok"] and out["path"] == str(tmp_path / "repos" / "murmurent_vault")


def test_init_no_push_skips_sync(tmp_path):
    record = {}
    out = VP.init_personal_vault(
        path=tmp_path / "c", owner="allie",
        repo_creator=lambda o, n: (True, "created"),
        cloner=_fake_cloner_factory(record), syncer=_spy_syncer(record),
        commit=False)
    assert out["ok"] and "synced" not in record
    assert out["committed"] is False and out["pushed"] is False


# ---- init_personal_vault: guards + back-compat -------------------------------

def test_init_refuses_inside_lab_vm(monkeypatch, tmp_path):
    vm = tmp_path / "lab_vm"
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(vm))
    dest = vm / "refined" / "murmurent_vault"
    out = VP.init_personal_vault(
        path=dest, owner="allie",
        repo_creator=lambda o, n: (True, "x"), cloner=_fake_cloner_factory({}),
        syncer=_spy_syncer({}))
    assert out["ok"] is False and out["error"] == "inside_lab_vm"


def test_init_adopts_existing_clone_with_matching_remote(tmp_path):
    dest = tmp_path / "clone"
    dest.mkdir()
    subprocess.run(["git", "-C", str(dest), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(dest), "remote", "add", "origin",
                    "git@github.com:allie/murmurent_vault.git"], check=True)
    created = {"count": 0}

    out = VP.init_personal_vault(
        path=dest, owner="allie",
        repo_creator=lambda o, n: (created.__setitem__("count", created["count"] + 1), (True, "created"))[1],
        cloner=_fake_cloner_factory({}), syncer=_spy_syncer({}))
    assert out["ok"] and out["adopted"] is True and out["cloned"] is False
    assert created["count"] == 0            # no repo create, no clone — adopted in place
    assert (dest / "oracle").is_dir()       # still scaffolded


def test_init_refuses_existing_clone_with_different_remote(tmp_path):
    dest = tmp_path / "clone"; dest.mkdir()
    subprocess.run(["git", "-C", str(dest), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(dest), "remote", "add", "origin",
                    "https://github.com/someone/other_repo.git"], check=True)

    out = VP.init_personal_vault(
        path=dest, owner="allie", repo_creator=lambda o, n: (True, "x"),
        cloner=_fake_cloner_factory({}), syncer=_spy_syncer({}))
    assert out["ok"] is False and out["error"] == "different_remote"
    assert out["remote"] == "someone/other_repo"


def test_init_refuses_nonempty_non_git_dir(tmp_path):
    dest = tmp_path / "clone"; dest.mkdir()
    (dest / "stuff.txt").write_text("x", encoding="utf-8")
    out = VP.init_personal_vault(
        path=dest, owner="allie", repo_creator=lambda o, n: (True, "x"),
        cloner=_fake_cloner_factory({}), syncer=_spy_syncer({}))
    assert out["ok"] is False and out["error"] == "exists_not_git"


def test_init_clone_failure_is_clean(tmp_path):
    out = VP.init_personal_vault(
        path=tmp_path / "c", owner="allie",
        repo_creator=lambda o, n: (True, "created"),
        cloner=lambda o, n, d: (False, "network down"),
        syncer=_spy_syncer({}))
    assert out["ok"] is False and out["error"] == "clone_failed"


def test_init_repo_create_failure_is_clean(tmp_path):
    out = VP.init_personal_vault(
        path=tmp_path / "c", owner="allie",
        repo_creator=lambda o, n: (False, "gh CLI not installed"),
        cloner=_fake_cloner_factory({}), syncer=_spy_syncer({}))
    assert out["ok"] is False and out["error"] == "repo_create_failed"


# ---- init_lab_vault: scaffold only, no repo ----------------------------------

def test_init_lab_vault_scaffolds_existing_clone(monkeypatch, tmp_path):
    lab = tmp_path / "lab_mgmt"
    lab.mkdir()
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(lab))
    out = VP.init_lab_vault()
    assert out["ok"] is True
    assert (lab / "oracle").is_dir() and (lab / "maps-legends").is_dir()
    # crucially: no new repo directory alongside the lab-mgmt clone
    assert not (tmp_path / "murmurent_vault_lab").exists()


def test_init_lab_vault_no_clone_is_clean_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "nope"))
    out = VP.init_lab_vault()
    assert out["ok"] is False and out["error"] == "no_lab_mgmt_clone"


# ---- resolve_vault_paths (murmurent vault paths) -----------------------------

def test_resolve_vault_paths_lab_always_resolves(monkeypatch, tmp_path):
    lab = tmp_path / "lab_mgmt"; lab.mkdir()
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(lab))
    out = VP.resolve_vault_paths()
    assert out["lab"]["root"] == str(lab)
    assert out["lab"]["maps_legends"] == str(lab / "maps-legends")
    assert out["lab"]["oracle"] == str(lab / "oracle")
    # personal unregistered → nulls
    assert out["personal"]["root"] is None


def test_resolve_vault_paths_personal_from_machine_yaml(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab"))
    MS.write(MachineSettings(obsidian_vault_path=str(tmp_path / "myvault")))
    out = VP.resolve_vault_paths()
    assert out["personal"]["root"] == str(tmp_path / "myvault")
    assert out["personal"]["oracle"] == str(tmp_path / "myvault" / "oracle")
    assert out["personal"]["maps_legends"] == str(tmp_path / "myvault" / "maps-legends")
