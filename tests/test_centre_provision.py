"""
Tests for centre_cable_guy's Python surface (item 0 of the post-smoke
design conversation).

Covers:
  - core.centre_provision CRUD + parse roundtrip
  - reconcile_project: pure diff for slack / github / fs_acl
  - apply_fs_acl: runner injection (no real sudo); probe shape
  - append_log: appends + commits
  - HTTP: list / get / upsert (gates) / reconcile (gates + delta shape)
  - CLI: declare / list / show / log smoke
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner
from fastapi.testclient import TestClient

from murmurent.commands.project_centre_cmd import centre_project as cli_centre_project
from murmurent.core import centre_provision as CP
from murmurent.core import registrar as R
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "mhallet")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@mhallet'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("mhallet\n", encoding="utf-8")
    R.create_lab(name="castellani", display_name="Castellani Lab",
                  pi_handle="@cast_pi")
    for h, lab in [("alice", "hallett"), ("bob", "hallett"),
                    ("mhallet", "hallett"), ("cast_pi", "castellani"),
                    ("cara", "castellani")]:
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active', 'lab': lab}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    return tmp_path


# ---- core CRUD ----------------------------------------------------------

def test_upsert_creates_then_updates(world):
    p1 = CP.upsert_project(name="dcis", primary_lab="hallett",
                            members=["@allie"], machines=["biodatsci"])
    assert p1.is_file()
    r = CP.get_project("dcis")
    assert r.primary_lab == "hallett"
    assert r.members == ["allie"]
    assert r.machines == ["biodatsci"]

    # Update — second upsert overwrites.
    CP.upsert_project(name="dcis", primary_lab="hallett",
                       members=["@allie", "@cara"], machines=["biodatsci"])
    r = CP.get_project("dcis")
    assert sorted(r.members) == ["allie", "cara"]


def test_upsert_requires_name_and_primary_lab(world):
    with pytest.raises(CP.CentreProvisionError, match="name"):
        CP.upsert_project(name="", primary_lab="hallett")
    with pytest.raises(CP.CentreProvisionError, match="primary_lab"):
        CP.upsert_project(name="dcis", primary_lab="")


def test_iter_projects_returns_all(world):
    for n in ("a_proj", "b_proj", "c_proj"):
        CP.upsert_project(name=n, primary_lab="hallett")
    rows = CP.iter_projects()
    assert [r.name for r in rows] == ["a_proj", "b_proj", "c_proj"]


def test_set_slack_channel_id(world):
    CP.upsert_project(name="dcis", primary_lab="hallett")
    CP.set_slack_channel_id(name="dcis", channel_id="C0DCIS")
    assert CP.get_project("dcis").slack_channel_id == "C0DCIS"


def test_set_slack_channel_id_unknown_project(world):
    with pytest.raises(CP.CentreProvisionError, match="not found"):
        CP.set_slack_channel_id(name="ghost", channel_id="C0X")


# ---- reconcile pure diff -----------------------------------------------

def test_reconcile_slack_drift(world):
    CP.upsert_project(name="dcis", primary_lab="hallett",
                       members=["@allie", "@cara"])
    deltas = CP.reconcile_project(
        project="dcis",
        slack_actual_members=["allie", "stranger"],
    )
    kinds = sorted((d.summary for d in deltas))
    assert any("cara" in s and "not in Slack" in s for s in kinds)
    assert any("stranger" in s and "not in project" in s for s in kinds)


def test_reconcile_github_drift(world):
    CP.upsert_project(name="dcis", primary_lab="hallett",
                       github_org="hallettmiket", github_repo="dcis",
                       members=["@allie"])
    deltas = CP.reconcile_project(
        project="dcis",
        github_actual_collaborators=["ex_postdoc"],
    )
    assert any("allie" in d.summary and "GitHub" in d.summary for d in deltas)
    assert any("ex_postdoc" in d.summary for d in deltas)


def test_reconcile_fs_acl_per_machine(world):
    CP.upsert_project(name="dcis", primary_lab="hallett",
                       members=["@allie", "@cara"],
                       machines=["biodatsci"])
    deltas = CP.reconcile_project(
        project="dcis",
        fs_actual_acl={"biodatsci": ["allie"]},
    )
    assert any("cara" in d.summary and "FS ACL" in d.summary and "biodatsci" in d.summary for d in deltas)


def test_reconcile_no_drift_returns_empty(world):
    CP.upsert_project(name="dcis", primary_lab="hallett",
                       members=["@allie"])
    deltas = CP.reconcile_project(
        project="dcis",
        slack_actual_members=["allie"],
        github_actual_collaborators=["allie"],
        fs_actual_acl={"biodatsci": ["allie"]},
    )
    assert deltas == []


def test_reconcile_unknown_project(world):
    with pytest.raises(CP.CentreProvisionError, match="not found"):
        CP.reconcile_project(project="ghost", slack_actual_members=[])


# ---- apply_fs_acl runner injection -------------------------------------

def test_apply_fs_acl_runs_local_with_sudo(world):
    captured = {}
    def fake_runner(argv):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "ok\n", "")
    probe = CP.apply_fs_acl(
        project="dcis", members=["@allie", "@cara"],
        machine=None, sudo=True, runner=fake_runner,
    )
    assert probe.status == "ok"
    assert captured["argv"][0] == "sudo"
    assert "--project" in captured["argv"]
    assert "dcis" in captured["argv"]
    assert any("allie" in a and "cara" in a for a in captured["argv"])


def test_apply_fs_acl_remote_wraps_ssh(world):
    captured = {}
    def fake_runner(argv):
        captured["argv"] = argv
        return subprocess.CompletedProcess(argv, 0, "ok\n", "")
    probe = CP.apply_fs_acl(
        project="dcis", members=["@allie"],
        machine="biodatsci", sudo=True, runner=fake_runner,
    )
    assert probe.status == "ok"
    assert captured["argv"][0] == "ssh"
    assert "biodatsci" in captured["argv"]


def test_apply_fs_acl_failure_is_warn_not_block(world):
    def fake_runner(argv):
        return subprocess.CompletedProcess(argv, 1, "", "permission denied")
    probe = CP.apply_fs_acl(
        project="dcis", members=["@allie"],
        machine=None, sudo=True, runner=fake_runner,
    )
    assert probe.status == "warn"
    assert "permission denied" in probe.detail


def test_apply_fs_acl_runner_exception_is_block(world):
    def fake_runner(argv):
        raise FileNotFoundError("nope")
    probe = CP.apply_fs_acl(
        project="dcis", members=["@allie"],
        machine=None, sudo=True, runner=fake_runner,
    )
    assert probe.status == "block"


# ---- audit log ---------------------------------------------------------

def test_append_log_creates_file(world):
    CP.upsert_project(name="dcis", primary_lab="hallett")
    p = CP.append_log(project="dcis", actor="@mhallet",
                       action="provision", detail="initial wiring")
    assert p.is_file()
    txt = p.read_text(encoding="utf-8")
    assert "provision" in txt
    assert "@mhallet" in txt
    assert "initial wiring" in txt


def test_append_log_appends(world):
    CP.upsert_project(name="dcis", primary_lab="hallett")
    CP.append_log(project="dcis", actor="@mhallet", action="first")
    CP.append_log(project="dcis", actor="@mhallet", action="second")
    p = CP.project_log_path("dcis")
    lines = [l for l in p.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
    assert len(lines) == 2


# ---- HTTP ---------------------------------------------------------------

def test_http_list_public(world):
    CP.upsert_project(name="dcis", primary_lab="hallett")
    client = TestClient(create_app())
    res = client.get("/api/centre/projects")
    assert res.status_code == 200
    assert any(p["name"] == "dcis" for p in res.json()["projects"])


def test_http_get_unknown_404(world):
    client = TestClient(create_app())
    res = client.get("/api/centre/projects/ghost")
    assert res.status_code == 404


def test_http_upsert_pi_of_primary_passes(world):
    client = TestClient(create_app())
    res = client.post("/api/centre/projects?user=mhallet", json={
        "name": "dcis", "primary_lab": "hallett",
        "members": ["@allie"],
    })
    assert res.status_code == 200, res.text
    assert CP.get_project("dcis").members == ["allie"]


def test_http_upsert_other_lab_pi_refused(world):
    """@cast_pi is PI of castellani; can't upsert hallett-owned project."""
    client = TestClient(create_app())
    res = client.post("/api/centre/projects?user=cast_pi", json={
        "name": "dcis", "primary_lab": "hallett",
    })
    assert res.status_code == 403


def test_http_upsert_member_refused(world):
    client = TestClient(create_app())
    res = client.post("/api/centre/projects?user=alice", json={
        "name": "dcis", "primary_lab": "hallett",
    })
    assert res.status_code == 403


def test_http_reconcile_returns_deltas(world):
    CP.upsert_project(name="dcis", primary_lab="hallett",
                       members=["@allie", "@cara"])
    client = TestClient(create_app())
    res = client.post("/api/centre/projects/dcis/reconcile?user=mhallet",
                       json={"slack_actual_members": ["allie"]})
    assert res.status_code == 200, res.text
    summaries = [d["summary"] for d in res.json()["deltas"]]
    assert any("cara" in s for s in summaries)


def test_http_reconcile_no_drift(world):
    CP.upsert_project(name="dcis", primary_lab="hallett",
                       members=["@allie"])
    client = TestClient(create_app())
    res = client.post("/api/centre/projects/dcis/reconcile?user=mhallet",
                       json={"slack_actual_members": ["allie"]})
    assert res.json()["deltas"] == []


def test_http_reconcile_unknown_project_404(world):
    client = TestClient(create_app())
    res = client.post("/api/centre/projects/ghost/reconcile?user=mhallet",
                       json={})
    assert res.status_code == 404


# ---- CLI ---------------------------------------------------------------

def test_cli_declare_then_list_then_show(world):
    runner = CliRunner()
    res = runner.invoke(cli_centre_project, [
        "declare", "--name", "dcis", "--primary-lab", "hallett",
        "--member", "@allie", "--member", "@cara",
        "--machine", "biodatsci",
    ])
    assert res.exit_code == 0, res.output
    assert "Declared dcis" in res.output

    res = runner.invoke(cli_centre_project, ["list"])
    assert "dcis" in res.output
    assert "hallett" in res.output

    res = runner.invoke(cli_centre_project, ["show", "dcis"])
    assert "@allie" in res.output
    assert "@cara" in res.output
    assert "biodatsci" in res.output


def test_cli_reconcile_dry_run(world):
    CP.upsert_project(name="dcis", primary_lab="hallett",
                       members=["@allie"])
    res = CliRunner().invoke(cli_centre_project, ["reconcile", "dcis"])
    assert res.exit_code == 0
    assert "dry-run" in res.output


def test_cli_log_appends(world):
    CP.upsert_project(name="dcis", primary_lab="hallett")
    res = CliRunner().invoke(cli_centre_project, [
        "log", "dcis", "--actor", "@mhallet",
        "--action", "manual_fix",
        "--detail", "test entry",
    ])
    assert res.exit_code == 0, res.output
    p = CP.project_log_path("dcis")
    assert "manual_fix" in p.read_text()
