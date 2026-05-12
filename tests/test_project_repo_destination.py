"""Tests for the generalised repo-destination (Phase 16) feature.

Covers:
  - ``ensure_remote(kind="local")`` creates a bare repo and wires origin
  - ``cmd_new(repo_kind="local")`` persists ``repo_kind`` in CHARTER
  - ``cmd_new(repo_kind="github")`` is the existing default behaviour
  - ``_lab_settings`` reads ``github_org`` from ``lab.md`` and falls back
  - The project-create request round-trips repo_kind through to cmd_new
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from wigamig.commands import project_cmd
from wigamig.core import requests as req_core
from wigamig.core.frontmatter import parse_file


@pytest.fixture
def world(monkeypatch, tmp_path):
    repos = tmp_path / "repos"
    lab_mgmt = tmp_path / "lab-mgmt"
    lab_vm = tmp_path / "lab_vm"
    bare_root = tmp_path / "lab_vm_bare" / "git_repos"

    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(repos))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_mgmt))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(lab_vm))
    monkeypatch.setenv("WIGAMIG_USER", "the_pi")

    (lab_mgmt / "members").mkdir(parents=True)
    (lab_mgmt / "projects").mkdir(parents=True)
    (lab_mgmt / "requests").mkdir(parents=True)
    (lab_mgmt / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n---\n",
        encoding="utf-8",
    )
    (lab_mgmt / "members" / "the_pi.md").write_text(
        "---\nhandle: '@the_pi'\nfull_name: 'Mike Hallett'\nrole: pi\nstatus: active\nlab: hallett\n---\n",
        encoding="utf-8",
    )

    return {
        "tmp": tmp_path,
        "repos": repos,
        "lab_mgmt": lab_mgmt,
        "bare_root": bare_root,
    }


# ---------------------------------------------------------------------------
# ensure_remote (kind-aware)
# ---------------------------------------------------------------------------


def test_ensure_remote_local_creates_bare_repo(world):
    """``kind="local"`` runs ``git init --bare`` and wires origin to it."""
    project_cmd.cmd_new(
        "demo_local",
        charter_path=None,
        members_csv="@the_pi",
        sensitivity="standard",
        description="A local-only project.",
        skip_github=True,  # we'll call ensure_remote ourselves below
    )
    repo_dir = world["repos"] / "demo_local"
    bare = world["bare_root"] / "demo_local.git"

    url = project_cmd.ensure_remote(
        repo_dir, "demo_local", kind="local", bare_repo_path=bare,
    )

    assert url == str(bare)
    assert (bare / "HEAD").is_file(), "bare repo not initialised"
    # origin points at the bare path.
    origin = subprocess.check_output(
        ["git", "-C", str(repo_dir), "remote", "get-url", "origin"],
        text=True,
    ).strip()
    assert origin == str(bare)


def test_ensure_remote_local_is_idempotent(world):
    """Re-running ``ensure_remote(kind="local")`` must not error."""
    project_cmd.cmd_new(
        "demo_idem",
        charter_path=None,
        members_csv="@the_pi",
        sensitivity="standard",
        description="x",
        skip_github=True,
    )
    repo_dir = world["repos"] / "demo_idem"
    bare = world["bare_root"] / "demo_idem.git"
    project_cmd.ensure_remote(repo_dir, "demo_idem", kind="local", bare_repo_path=bare)
    # second call should be a no-op for the bare, and just re-push origin.
    project_cmd.ensure_remote(repo_dir, "demo_idem", kind="local", bare_repo_path=bare)
    assert (bare / "HEAD").is_file()


def test_ensure_remote_local_requires_bare_path(world):
    """Forgetting ``bare_repo_path`` for kind=local is an explicit error."""
    project_cmd.cmd_new(
        "x", charter_path=None, members_csv="@the_pi",
        sensitivity="standard", description="x", skip_github=True,
    )
    with pytest.raises(ValueError, match="bare_repo_path"):
        project_cmd.ensure_remote(world["repos"] / "x", "x", kind="local")


def test_ensure_remote_unknown_kind_raises(world):
    project_cmd.cmd_new(
        "y", charter_path=None, members_csv="@the_pi",
        sensitivity="standard", description="y", skip_github=True,
    )
    with pytest.raises(ValueError, match="unknown repo kind"):
        project_cmd.ensure_remote(world["repos"] / "y", "y", kind="bogus")


# ---------------------------------------------------------------------------
# cmd_new persists repo_kind in CHARTER
# ---------------------------------------------------------------------------


def test_cmd_new_local_persists_repo_kind_in_charter(world):
    bare = world["bare_root"] / "demo_local2.git"
    project_cmd.cmd_new(
        "demo_local2",
        charter_path=None,
        members_csv="@the_pi",
        sensitivity="standard",
        description="A local-only project.",
        repo_kind="local",
        local_repo_root=str(bare.parent),
    )
    charter = world["repos"] / "demo_local2" / "CHARTER.md"
    assert charter.is_file()
    body = charter.read_text(encoding="utf-8")
    assert "repo_kind: local" in body
    # And the bare repo was actually created (skip_github default = False).
    assert (bare / "HEAD").is_file()


def test_cmd_new_github_repo_kind_recorded_too(world, monkeypatch):
    """Even for the github default, repo_kind is written so readers don't
    have to special-case "absent means github"."""
    # Block gh CLI so we don't try to push to a real GitHub during the test.
    monkeypatch.setattr(project_cmd, "_gh_available", lambda: False)
    project_cmd.cmd_new(
        "demo_gh",
        charter_path=None,
        members_csv="@the_pi",
        sensitivity="standard",
        description="default",
        repo_kind="github",
    )
    body = (world["repos"] / "demo_gh" / "CHARTER.md").read_text(encoding="utf-8")
    assert "repo_kind: github" in body


# ---------------------------------------------------------------------------
# Lab-level github_org from lab.md
# ---------------------------------------------------------------------------


def test_lab_settings_reads_github_org_from_labmd(world):
    """``_lab_settings()`` returns the github_org declared in lab.md."""
    (world["lab_mgmt"] / "lab.md").write_text(
        "---\nlab: hallett\nname: 'Hallett Lab'\npi: '@the_pi'\n"
        "github_org: someoneelse\n"
        "git_repos_subpath: bare\n---\n",
        encoding="utf-8",
    )
    from wigamig.dashboard import snapshot
    s = snapshot._lab_settings("hallett")
    assert s.github_org == "someoneelse"
    assert s.git_repos_subpath == "bare"


def test_lab_settings_github_org_falls_back(world):
    """Missing ``github_org`` falls back to the historic literal."""
    from wigamig.dashboard import snapshot
    s = snapshot._lab_settings("hallett")
    assert s.github_org == "hallettmiket"
    assert s.git_repos_subpath == "git_repos"


# ---------------------------------------------------------------------------
# Request flow round-trips repo_kind
# ---------------------------------------------------------------------------


def test_create_request_roundtrip_repo_kind(world):
    req = req_core.file_create_request(
        requester="the_pi",
        project="demo_req",
        proposed_members=["@the_pi"],
        sensitivity="standard",
        justification="local-only project",
        repo_kind="local",
        local_repo_root="/tmp/some/path",
    )
    # Persisted on disk:
    on_disk = parse_file(req.path).meta
    assert on_disk["repo_kind"] == "local"
    assert on_disk["local_repo_root"] == "/tmp/some/path"
    # And re-parsing yields the same JoinRequest:
    reparsed = req_core.parse_request(req.path)
    assert reparsed.repo_kind == "local"
    assert reparsed.local_repo_root == "/tmp/some/path"


def test_create_request_default_repo_kind_is_github(world):
    """Old clients that don't send the field still work."""
    req = req_core.file_create_request(
        requester="the_pi",
        project="demo_req_default",
        proposed_members=["@the_pi"],
        sensitivity="standard",
        justification="x",
    )
    assert req.repo_kind == "github"
    assert req.local_repo_root is None
