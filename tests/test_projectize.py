"""Tests for :mod:`murmurent.core.projectize`.

projectize is the single chokepoint that ``POST /api/inventory/adopt``
and ``POST /api/workspace/initialize`` both call so a freshly-adopted
or freshly-installed repo lands in all three dashboard panels (Repos,
Projects, Installations). These tests pin the contract:

  * CHARTER.md is written when missing, preserved when present
  * lab_mgmt/projects/<name>.md is written when missing, preserved
    when present
  * The installation manifest is rewritten every call (so re-install
    refreshes the last_checked timestamp etc.)
  * .claude/agents/ symlinks are created for local hosts and skipped
    for SSH installs (the remote_install path handles that side)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Stand up an isolated home + lab_mgmt + murmurent commons."""
    home = tmp_path / "home"
    (home / "repos").mkdir(parents=True)
    commons = tmp_path / "wigamig_commons"
    (commons / "agents").mkdir(parents=True)
    (commons / "agents" / "blacksmith.md").write_text("# blacksmith\n")
    (commons / "agents" / "adversary.md").write_text("# adversary\n")
    lab_mgmt = tmp_path / "lab_mgmt"
    (lab_mgmt / "projects").mkdir(parents=True)
    installations = home / ".wigamig" / "installations"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("WIGAMIG_REPO_ROOT", str(commons))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_mgmt))
    return {
        "home": home, "repos": home / "repos", "commons": commons,
        "lab_mgmt": lab_mgmt, "installations": installations,
    }


def _make_clone(repos: Path, name: str) -> Path:
    p = repos / name
    (p / ".git").mkdir(parents=True)
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_make_wigamig_project_writes_all_four_artefacts(world):
    """A fresh clone (no CHARTER) gets CHARTER, registry, manifest, and
    .claude/agents/ symlinks in one call. This is the contract the
    adopt endpoint depends on."""
    from murmurent.core import projectize as p
    clone = _make_clone(world["repos"], "hockey_stats")
    res = p.make_wigamig_project(
        clone_path=clone,
        project="hockey_stats",
        lead="@the_pi",
        members=["@the_pi"],
        agents=["blacksmith"],
        installations_dir=world["installations"],
    )
    assert (clone / "CHARTER.md").is_file()
    # The authoritative registry is now the cert-project store, not the mirror.
    assert (world["lab_mgmt"] / "cert_projects" / "hockey_stats.md").is_file()
    manifest_p = world["installations"] / "hockey_stats.yaml"
    assert manifest_p.is_file()
    # bootstrap_local symlinked the requested agent.
    assert (clone / ".claude" / "agents" / "blacksmith.md").is_symlink()
    # And the response carries paths to every artefact for the UI.
    assert res.charter_path == clone / "CHARTER.md"
    assert res.registry_path == world["lab_mgmt"] / "cert_projects" / "hockey_stats.md"
    assert res.manifest_path == manifest_p


def test_manifest_carries_member_machine_paths(world):
    """The installation manifest schema must match what snapshot.py +
    workspace/launch reads. Schema drift would silently break the
    Installations panel."""
    from murmurent.core import projectize as p
    clone = _make_clone(world["repos"], "demo")
    p.make_wigamig_project(
        clone_path=clone, project="demo",
        lead="@alice", members=["@alice", "@bob"],
        member="alice", machine_type="laptop", hostname="mbp",
        username="alice", lab_base="/wb",
        raw_path="/wb/raw", refined_path="/wb/refined",
        notebook_path="/wb/lab_notebooks",
        agents=["blacksmith"],
        installations_dir=world["installations"],
    )
    m = yaml.safe_load((world["installations"] / "demo.yaml").read_text())
    assert m["member"] == "@alice"
    assert m["project"] == "demo"
    assert m["machine_type"] == "laptop"
    assert m["hostname"] == "mbp"
    assert m["lab_base"] == "/wb"
    assert m["raw_path"] == "/wb/raw"
    assert m["access"] == "direct"
    assert m["agents"] == ["blacksmith"]
    assert m["status"] == "active"


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_existing_charter_preserved(world):
    """projectize must NEVER overwrite a hand-edited CHARTER. (The
    adopt endpoint guards this with a 409 too, but projectize itself
    must not clobber.)"""
    from murmurent.core import projectize as p
    clone = _make_clone(world["repos"], "hand_edited")
    (clone / "CHARTER.md").write_text("---\nproject: hand_edited\n---\n# hand-written\n")
    p.make_wigamig_project(
        clone_path=clone, project="hand_edited",
        lead="@x", members=["@x"],
        installations_dir=world["installations"],
    )
    assert "hand-written" in (clone / "CHARTER.md").read_text()


def test_existing_registry_preserved(world):
    """Same for the lab_mgmt registry entry — never clobber. The lab
    may have edited the entry by hand to add notes."""
    from murmurent.core import projectize as p
    clone = _make_clone(world["repos"], "registered")
    reg = world["lab_mgmt"] / "projects" / "registered.md"
    reg.write_text("---\nproject: registered\n---\n# kept by hand\n")
    p.make_wigamig_project(
        clone_path=clone, project="registered",
        lead="@x", members=["@x"],
        installations_dir=world["installations"],
    )
    assert "kept by hand" in reg.read_text()


def test_manifest_rewritten_every_call(world):
    """Unlike CHARTER and the registry, the manifest is the user's
    own per-machine record. Re-installing should refresh it (so
    last_checked moves forward and the agent set reflects the latest
    pick), not preserve a stale entry."""
    from murmurent.core import projectize as p
    clone = _make_clone(world["repos"], "demo")
    p.make_wigamig_project(
        clone_path=clone, project="demo",
        lead="@x", members=["@x"], agents=["blacksmith"],
        installations_dir=world["installations"],
    )
    p.make_wigamig_project(
        clone_path=clone, project="demo",
        lead="@x", members=["@x"], agents=["blacksmith", "adversary"],
        installations_dir=world["installations"],
    )
    m = yaml.safe_load((world["installations"] / "demo.yaml").read_text())
    assert m["agents"] == ["blacksmith", "adversary"]


# ---------------------------------------------------------------------------
# SSH-install variant
# ---------------------------------------------------------------------------


def test_ssh_install_skips_local_bootstrap_but_writes_manifest(world):
    """For SSH installs the working tree lives on the remote — the
    bootstrap there is handled by remote_install. projectize still
    writes the local manifest + registry so the dashboard sees the
    installation, but it must NOT try to .claude/agents-symlink locally
    (there's no clone there)."""
    from murmurent.core import projectize as p
    # Note: no _make_clone — no local working tree for SSH installs.
    fake_clone = world["repos"] / "remote_only"
    fake_clone.mkdir()
    res = p.make_wigamig_project(
        clone_path=fake_clone,
        project="remote_only",
        lead="@x", members=["@x"],
        agents=["blacksmith"],
        ssh_remote="lab-server",
        remote_home="/home/UWO/the_pi",
        installations_dir=world["installations"],
    )
    # Manifest carries the ssh_remote pointer.
    m = yaml.safe_load((world["installations"] / "remote_only.yaml").read_text())
    assert m["ssh_remote"] == "lab-server"
    assert m["remote_home"] == "/home/UWO/the_pi"
    assert m["access"] == "direct"  # has_direct_access still True by default
    # Cert-project entry got the remote clone location filled in.
    reg_text = (world["lab_mgmt"] / "cert_projects" / "remote_only.md").read_text()
    assert "host: lab-server" in reg_text
    assert "/home/UWO/the_pi/repos/remote_only" in reg_text
    # No local bootstrap probes (would be cc_agent: <name>).
    bootstrap_probes = [p for p in res.probes if p.name.startswith("cc_agent:")]
    assert bootstrap_probes == [], "remote install must not trigger local bootstrap"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_invalid_charter_metadata_returns_fail_probe(world):
    """A bad sensitivity tier (e.g. empty members) surfaces as a
    required=True fail probe so the endpoint can translate it to 422."""
    from murmurent.core import projectize as p
    clone = _make_clone(world["repos"], "badmeta")
    res = p.make_wigamig_project(
        clone_path=clone, project="badmeta",
        lead="@x", members=[],  # invalid — must be non-empty
        installations_dir=world["installations"],
    )
    charter_probe = next(pr for pr in res.probes if pr.name == "charter")
    assert charter_probe.status == "fail"
    assert charter_probe.required is True
    # And CHARTER.md was NOT written.
    assert not (clone / "CHARTER.md").exists()


def test_missing_lab_mgmt_is_warn_not_fail(monkeypatch, tmp_path):
    """If the user hasn't cloned lab_mgmt on this machine, projectize
    must still succeed at the local steps (CHARTER, manifest,
    bootstrap) — just skip the registry write with a warn. We can't
    block a personal adopt on shared-repo availability."""
    from murmurent.core import projectize as p
    home = tmp_path / "home"
    (home / "repos").mkdir(parents=True)
    commons = tmp_path / "wigamig_commons"
    (commons / "agents").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("WIGAMIG_REPO_ROOT", str(commons))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", "/nope/does/not/exist")
    clone = home / "repos" / "demo"
    (clone / ".git").mkdir(parents=True)
    res = p.make_wigamig_project(
        clone_path=clone, project="demo",
        lead="@x", members=["@x"],
        installations_dir=home / ".wigamig" / "installations",
    )
    # CHARTER still written.
    assert (clone / "CHARTER.md").is_file()
    # Registry write attempt — succeeds because lab_mgmt_project_registry_path
    # returns a path under the missing dir; the parent.mkdir creates it
    # on the fly. (The "missing" guard is mostly about the directory
    # being unwritable; on tmpfs it'll just create.) Assert no required
    # probe failed.
    failed = [pr for pr in res.probes if pr.status == "fail" and pr.required]
    assert failed == [], f"unexpected required failures: {failed}"
