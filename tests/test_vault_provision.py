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


# ---------------------------------------------------------------------------
# --adopt: back an existing (non-git) vault, excluding clinical (issue #25)
# ---------------------------------------------------------------------------


def _vault_with_content(root: Path) -> Path:
    """A believable existing Obsidian vault: one standard + one clinical note."""
    (root / "oracle").mkdir(parents=True)
    (root / "lab-notebook").mkdir(parents=True)
    (root / "oracle" / "2026-05-01_qc_finding.md").write_text(
        "---\ntitle: QC finding\nsensitivity: standard\n---\n\nkeep me\n", encoding="utf-8")
    (root / "oracle" / "2026-05-02_patient_note.md").write_text(
        "---\ntitle: patient note\nsensitivity: clinical\n---\n\nPHI — stay local\n",
        encoding="utf-8")
    (root / "lab-notebook" / "2026-05-03.md").write_text(
        "---\nsensitivity: standard\n---\n\nday notes\n", encoding="utf-8")
    return root


def test_scan_sensitive_finds_only_clinical(tmp_path):
    v = _vault_with_content(tmp_path / "vault")
    hits = VP.scan_sensitive(v)
    assert hits == ["oracle/2026-05-02_patient_note.md"]


def test_plan_adopt_murmurent_scope_allowlists_folders(tmp_path):
    v = _vault_with_content(tmp_path / "vault")
    (v / "health").mkdir()
    (v / "health" / "private.md").write_text("---\n---\npersonal\n", encoding="utf-8")
    plan = VP.plan_adopt(v)                       # default scope = murmurent
    assert plan["scope"] == "murmurent"
    assert plan["tracked_folders"] == ["oracle", "lab-notebook", "maps-legends",
                                       "murmurent_data", "agents", "agent_forks"]
    assert "health" in plan["kept_local_folders"]
    assert "/*" in plan["gitignore"] and "!/oracle/" in plan["gitignore"]
    # pure: nothing written
    assert not (v / ".git").exists() and not (v / ".gitignore").exists()


def test_plan_adopt_all_scope_denylists_clinical(tmp_path):
    v = _vault_with_content(tmp_path / "vault")
    plan = VP.plan_adopt(v, scope="all")
    assert plan["excluded_files"] == ["oracle/2026-05-02_patient_note.md"]
    assert "/oracle/2026-05-02_patient_note.md" in plan["gitignore"]


def test_adopt_excludes_clinical_before_push(tmp_path, monkeypatch):
    v = _vault_with_content(tmp_path / "vault")
    seen = {}

    def fake_pusher(dest, owner, name, *, message):
        # .gitignore MUST already exist + exclude the clinical file when the
        # pusher runs — that's the PHI guarantee (never staged).
        gi = (Path(dest) / ".gitignore").read_text()
        seen["gitignore"] = gi
        seen["called"] = (str(dest), owner, name)
        return (True, True, "created + pushed")

    # Whole-vault ("all") scope: clinical must be gitignored before the push.
    out = VP.init_personal_vault(
        path=str(v), owner="octocat", adopt=True, adopt_scope="all",
        adopt_pusher=fake_pusher,
        repo_creator=lambda o, n: (True, "created"),  # unused on adopt path
    )
    assert out["ok"] and out["adopted"] and out["pushed"]
    assert "/oracle/2026-05-02_patient_note.md" in seen["gitignore"]
    assert seen["called"][1:] == ("octocat", "murmurent_vault")
    # machine.yaml pinned to the adopted vault
    assert MS.load().obsidian_vault_path == str(v)


def test_adopt_refused_without_flag(tmp_path):
    v = _vault_with_content(tmp_path / "vault")
    out = VP.init_personal_vault(path=str(v), owner="octocat",
                                 repo_creator=lambda o, n: (True, "created"),
                                 cloner=lambda o, n, d: (True, "cloned"))
    assert out["ok"] is False and out["error"] == "exists_not_git"
    assert "--adopt" in out["detail"]


def test_precommit_guard_blocks_clinical(tmp_path):
    """The installed pre-commit hook refuses a clinical-tagged staged file."""
    v = tmp_path / "vault"
    v.mkdir()
    subprocess.run(["git", "-C", str(v), "init", "-b", "main"], check=True,
                   capture_output=True)
    assert VP._install_precommit_guard(v)
    (v / "note.md").write_text("---\nsensitivity: clinical\n---\nPHI\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(v), "add", "note.md"], check=True, capture_output=True)
    r = subprocess.run(["git", "-C", str(v), "commit", "-m", "x"],
                       capture_output=True, text=True,
                       env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    assert r.returncode != 0
    assert "clinical" in (r.stdout + r.stderr).lower()


def test_adopt_murmurent_scope_only_tracks_murmurent_folders(tmp_path):
    """Default --adopt (murmurent scope): the .gitignore is an allowlist so a
    personal folder like health/ is never pushed."""
    v = _vault_with_content(tmp_path / "vault")
    (v / "health").mkdir()
    (v / "health" / "private.md").write_text("---\n---\npersonal\n", encoding="utf-8")
    seen = {}

    def fake_pusher(dest, owner, name, *, message):
        seen["gitignore"] = (Path(dest) / ".gitignore").read_text()
        return (True, True, "created + pushed")

    out = VP.init_personal_vault(path=str(v), owner="octocat", adopt=True,
                                 adopt_pusher=fake_pusher)
    assert out["ok"] and out["scope"] == "murmurent"
    gi = seen["gitignore"]
    assert "/*" in gi and "!/oracle/" in gi and "!/lab-notebook/" in gi
    assert "health" not in gi          # personal folder not re-included → stays local
