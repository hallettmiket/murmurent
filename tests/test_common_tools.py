"""
Tests for the centre-wide common-tools catalog (item (1) of the
post-smoke design conversation).

Covers:
  - core.common_tools CRUD + validators + idempotent updates
  - HTTP: public list + get; registrar-side create/edit/archive
  - Permission gates: any active member submits on behalf of their
    own lab; only owner_lab's PI or a registrar may edit / archive;
    cross-lab submission requires registrar
  - CLI: submit / list / show / archive smoke
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import yaml
from click.testing import CliRunner
from fastapi.testclient import TestClient

from wigamig.commands.common_tools_cmd import common_tool as cli_common_tool
from wigamig.core import common_tools as CT
from wigamig.core import registrar as R
from wigamig.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "alice")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "lab.md").write_text(
        "---\nlab: hallett\npi: '@the_pi'\n---\n", encoding="utf-8",
    )
    (tmp_path / "lab_info").mkdir(parents=True)
    (tmp_path / "lab_info" / "registrar").write_text("the_pi\n",
                                                       encoding="utf-8")
    # Two labs so we can test cross-lab submission gates.
    R.create_lab(name="castellani", display_name="Castellani Lab",
                 pi_handle="@cast_pi")
    for h, lab in [("alice", "hallett"), ("bob", "hallett"),
                   ("the_pi", "hallett"), ("cast_pi", "castellani")]:
        (tmp_path / "lab-mgmt" / "members" / f"{h}.md").write_text(
            f"---\n{yaml.safe_dump({'handle': f'@{h}', 'role': 'postdoc', 'status': 'active', 'lab': lab}, sort_keys=False).rstrip()}\n---\n",
            encoding="utf-8",
        )
    return tmp_path


# ---- core CRUD ----------------------------------------------------------

def test_create_tool_writes_file(world):
    p = CT.create_tool(
        slug="qc_drift_routine", name="QC drift watcher",
        kind="routine", owner_lab="hallett",
        description="Posts Slack on MoM QC drift >2σ",
        install="wigamig routine install qc_drift_routine",
        url="https://github.com/hallettmiket/qc_drift_routine",
        tags=["qc", "monitoring"],
    )
    assert p.is_file()
    t = CT.get_tool("qc_drift_routine")
    assert t.kind == "routine"
    assert t.owner_lab == "hallett"
    assert "qc" in t.tags


@pytest.mark.parametrize("bad_slug", ["", "_lead", "UPPER ok",
                                        "with space", "with-dash"])
def test_create_tool_bad_slug(world, bad_slug):
    with pytest.raises(CT.CommonToolError, match="slug"):
        CT.create_tool(slug=bad_slug, name="X", kind="skill",
                        owner_lab="hallett")


def test_create_tool_bad_kind(world):
    with pytest.raises(CT.CommonToolError, match="kind"):
        CT.create_tool(slug="ok_slug", name="X", kind="ghost",
                        owner_lab="hallett")


def test_create_tool_refuses_duplicate(world):
    CT.create_tool(slug="t1", name="T1", kind="skill", owner_lab="hallett")
    with pytest.raises(CT.CommonToolError, match="already exists"):
        CT.create_tool(slug="t1", name="T1 again", kind="skill",
                        owner_lab="hallett")


def test_iter_filters(world):
    CT.create_tool(slug="a_skill", name="A", kind="skill",
                    owner_lab="hallett", tags=["qc"])
    CT.create_tool(slug="b_routine", name="B", kind="routine",
                    owner_lab="hallett", tags=["qc", "monitoring"])
    CT.create_tool(slug="c_skill", name="C", kind="skill",
                    owner_lab="castellani", tags=["analysis"])
    assert len(CT.iter_tools()) == 3
    assert {t.slug for t in CT.iter_tools(kind="skill")} == \
        {"a_skill", "c_skill"}
    assert {t.slug for t in CT.iter_tools(owner_lab="castellani")} == \
        {"c_skill"}
    assert {t.slug for t in CT.iter_tools(tag="qc")} == \
        {"a_skill", "b_routine"}


def test_iter_excludes_deprecated_by_default(world):
    CT.create_tool(slug="live", name="L", kind="skill", owner_lab="hallett")
    CT.create_tool(slug="gone", name="G", kind="skill", owner_lab="hallett")
    CT.archive_tool(slug="gone")
    assert {t.slug for t in CT.iter_tools()} == {"live"}
    assert {t.slug for t in CT.iter_tools(include_deprecated=True)} == \
        {"live", "gone"}


def test_update_tool_partial(world):
    CT.create_tool(slug="t1", name="T", kind="skill", owner_lab="hallett",
                    install="old_install")
    CT.update_tool(slug="t1", patch={"install": "new_install",
                                      "tags": ["new"]})
    t = CT.get_tool("t1")
    assert t.install == "new_install"
    assert t.tags == ["new"]
    assert t.name == "T"   # untouched


def test_update_unknown_slug(world):
    with pytest.raises(CT.CommonToolError, match="not found"):
        CT.update_tool(slug="ghost", patch={"name": "x"})


# ---- HTTP: public reads -------------------------------------------------

def test_http_public_list_anyone_can_read(world):
    CT.create_tool(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    # No ?user= — public read.
    res = client.get("/api/common_tools")
    assert res.status_code == 200
    assert any(t["slug"] == "t1" for t in res.json()["tools"])


def test_http_public_list_filters(world):
    CT.create_tool(slug="a_skill", name="A", kind="skill",
                    owner_lab="hallett", tags=["qc"])
    CT.create_tool(slug="b_routine", name="B", kind="routine",
                    owner_lab="hallett")
    client = TestClient(create_app())
    res = client.get("/api/common_tools?kind=skill")
    slugs = [t["slug"] for t in res.json()["tools"]]
    assert slugs == ["a_skill"]
    res = client.get("/api/common_tools?tag=qc")
    slugs = [t["slug"] for t in res.json()["tools"]]
    assert slugs == ["a_skill"]


def test_http_get_one(world):
    CT.create_tool(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    res = client.get("/api/common_tools/t1")
    assert res.status_code == 200
    assert res.json()["slug"] == "t1"


def test_http_get_unknown_404(world):
    client = TestClient(create_app())
    res = client.get("/api/common_tools/ghost")
    assert res.status_code == 404


# ---- HTTP: registrar-side create ---------------------------------------

def test_http_submit_defaults_owner_to_local_lab(world):
    """alice submits without owner_lab → resolves to local lab.md = hallett."""
    client = TestClient(create_app())
    res = client.post("/api/registrar/common_tools?user=alice", json={
        "slug": "t1", "name": "T", "kind": "skill",
    })
    assert res.status_code == 200, res.text
    assert res.json()["owner_lab"] == "hallett"


def test_http_submit_other_lab_refused_for_member(world):
    """alice can't submit a tool tagged owner_lab=castellani — that's
    cross-lab, requires registrar."""
    client = TestClient(create_app())
    res = client.post("/api/registrar/common_tools?user=alice", json={
        "slug": "t1", "name": "T", "kind": "skill",
        "owner_lab": "castellani",
    })
    assert res.status_code == 403


def test_http_submit_other_lab_ok_for_registrar(world):
    client = TestClient(create_app())
    res = client.post("/api/registrar/common_tools?user=the_pi", json={
        "slug": "t1", "name": "T", "kind": "skill",
        "owner_lab": "castellani",
    })
    assert res.status_code == 200, res.text


def test_http_submit_validates_kind(world):
    client = TestClient(create_app())
    res = client.post("/api/registrar/common_tools?user=alice", json={
        "slug": "t1", "name": "T", "kind": "ghost",
    })
    assert res.status_code == 422


# ---- HTTP: edit + archive gates ----------------------------------------

def test_http_patch_owner_lab_pi_ok(world):
    """@the_pi (PI of hallett) can edit a hallett-owned tool."""
    CT.create_tool(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    res = client.patch("/api/registrar/common_tools/t1?user=the_pi",
                        json={"description": "edited"})
    assert res.status_code == 200, res.text
    assert CT.get_tool("t1").description == "edited"


def test_http_patch_other_lab_member_refused(world):
    """alice (member, not PI) can't edit even her own lab's tool —
    only PI or registrar may."""
    CT.create_tool(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    res = client.patch("/api/registrar/common_tools/t1?user=alice",
                        json={"description": "edited"})
    assert res.status_code == 403


def test_http_patch_other_lab_pi_refused(world):
    """castellani's PI can't edit hallett's tool."""
    CT.create_tool(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    res = client.patch("/api/registrar/common_tools/t1?user=cast_pi",
                        json={"description": "hijack"})
    assert res.status_code == 403


def test_http_archive_owner_ok(world):
    CT.create_tool(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/common_tools/t1/archive?user=the_pi")
    assert res.status_code == 200
    assert CT.get_tool("t1").status == "deprecated"


def test_http_archive_unknown_404(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/common_tools/ghost/archive?user=the_pi")
    assert res.status_code == 404


# ---- CLI ---------------------------------------------------------------

def test_cli_submit_then_list_then_show(world):
    runner = CliRunner()
    res = runner.invoke(cli_common_tool, [
        "submit", "--slug", "qc_drift", "--name", "QC drift",
        "--kind", "routine",
        "--description", "demo",
        "--install", "wigamig routine install qc_drift",
        "--tag", "qc", "--tag", "monitoring",
    ])
    assert res.exit_code == 0, res.output
    assert "Submitted qc_drift" in res.output

    res = runner.invoke(cli_common_tool, ["list"])
    assert "qc_drift" in res.output
    assert "routine" in res.output

    res = runner.invoke(cli_common_tool, ["show", "qc_drift"])
    assert "QC drift" in res.output
    assert "wigamig routine install qc_drift" in res.output


def test_cli_archive(world):
    CT.create_tool(slug="t1", name="T", kind="skill", owner_lab="hallett")
    res = CliRunner().invoke(cli_common_tool, ["archive", "t1"])
    assert res.exit_code == 0
    assert CT.get_tool("t1").status == "deprecated"


def test_cli_submit_unknown_kind_clean_error(world):
    res = CliRunner().invoke(cli_common_tool, [
        "submit", "--slug", "x", "--name", "X", "--kind", "ghost",
    ])
    assert res.exit_code != 0
    assert "Invalid value" in res.output or "ghost" in res.output
