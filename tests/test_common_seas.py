"""
Tests for the centre-wide common-tools catalog (item (1) of the
post-smoke design conversation).

Covers:
  - core.common_seas CRUD + validators + idempotent updates
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

from murmurent.commands.common_seas_cmd import common_sea as cli_common_sea
from murmurent.core import common_seas as CS
from murmurent.core import registrar as R
from murmurent.dashboard.server import create_app


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("MURMURENT_USER", "alice")
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

def test_create_sea_writes_file(world):
    p = CS.create_sea(
        slug="qc_drift_routine", name="QC drift watcher",
        kind="routine", owner_lab="hallett",
        description="Posts Slack on MoM QC drift >2σ",
        install="murmurent routine install qc_drift_routine",
        url="https://github.com/hallettmiket/qc_drift_routine",
        tags=["qc", "monitoring"],
    )
    assert p.is_file()
    t = CS.get_sea("qc_drift_routine")
    assert t.kind == "routine"
    assert t.owner_lab == "hallett"
    assert "qc" in t.tags


@pytest.mark.parametrize("bad_slug", ["", "_lead", "UPPER ok",
                                        "with space", "with-dash"])
def test_create_sea_bad_slug(world, bad_slug):
    with pytest.raises(CS.CommonSeaError, match="slug"):
        CS.create_sea(slug=bad_slug, name="X", kind="skill",
                        owner_lab="hallett")


def test_create_sea_bad_kind(world):
    with pytest.raises(CS.CommonSeaError, match="kind"):
        CS.create_sea(slug="ok_slug", name="X", kind="ghost",
                        owner_lab="hallett")


def test_create_sea_refuses_duplicate(world):
    CS.create_sea(slug="t1", name="T1", kind="skill", owner_lab="hallett")
    with pytest.raises(CS.CommonSeaError, match="already exists"):
        CS.create_sea(slug="t1", name="T1 again", kind="skill",
                        owner_lab="hallett")


def test_iter_filters(world):
    CS.create_sea(slug="a_skill", name="A", kind="skill",
                    owner_lab="hallett", tags=["qc"])
    CS.create_sea(slug="b_routine", name="B", kind="routine",
                    owner_lab="hallett", tags=["qc", "monitoring"])
    CS.create_sea(slug="c_skill", name="C", kind="skill",
                    owner_lab="castellani", tags=["analysis"])
    assert len(CS.iter_seas()) == 3
    assert {t.slug for t in CS.iter_seas(kind="skill")} == \
        {"a_skill", "c_skill"}
    assert {t.slug for t in CS.iter_seas(owner_lab="castellani")} == \
        {"c_skill"}
    assert {t.slug for t in CS.iter_seas(tag="qc")} == \
        {"a_skill", "b_routine"}


def test_iter_excludes_deprecated_by_default(world):
    CS.create_sea(slug="live", name="L", kind="skill", owner_lab="hallett")
    CS.create_sea(slug="gone", name="G", kind="skill", owner_lab="hallett")
    CS.archive_sea(slug="gone")
    assert {t.slug for t in CS.iter_seas()} == {"live"}
    assert {t.slug for t in CS.iter_seas(include_deprecated=True)} == \
        {"live", "gone"}


def test_update_sea_partial(world):
    CS.create_sea(slug="t1", name="T", kind="skill", owner_lab="hallett",
                    install="old_install")
    CS.update_sea(slug="t1", patch={"install": "new_install",
                                      "tags": ["new"]})
    t = CS.get_sea("t1")
    assert t.install == "new_install"
    assert t.tags == ["new"]
    assert t.name == "T"   # untouched


def test_update_unknown_slug(world):
    with pytest.raises(CS.CommonSeaError, match="not found"):
        CS.update_sea(slug="ghost", patch={"name": "x"})


# ---- HTTP: public reads -------------------------------------------------

def test_http_public_list_anyone_can_read(world):
    CS.create_sea(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    # No ?user= — public read.
    res = client.get("/api/common_seas")
    assert res.status_code == 200
    assert any(t["slug"] == "t1" for t in res.json()["seas"])


def test_http_public_list_filters(world):
    CS.create_sea(slug="a_skill", name="A", kind="skill",
                    owner_lab="hallett", tags=["qc"])
    CS.create_sea(slug="b_routine", name="B", kind="routine",
                    owner_lab="hallett")
    client = TestClient(create_app())
    res = client.get("/api/common_seas?kind=skill")
    slugs = [t["slug"] for t in res.json()["seas"]]
    assert slugs == ["a_skill"]
    res = client.get("/api/common_seas?tag=qc")
    slugs = [t["slug"] for t in res.json()["seas"]]
    assert slugs == ["a_skill"]


def test_http_get_one(world):
    CS.create_sea(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    res = client.get("/api/common_seas/t1")
    assert res.status_code == 200
    assert res.json()["slug"] == "t1"


def test_http_get_unknown_404(world):
    client = TestClient(create_app())
    res = client.get("/api/common_seas/ghost")
    assert res.status_code == 404


# ---- HTTP: registrar-side create ---------------------------------------

def test_http_submit_defaults_owner_to_local_lab(world):
    """alice submits without owner_lab → resolves to local lab.md = hallett."""
    client = TestClient(create_app())
    res = client.post("/api/registrar/common_seas?user=alice", json={
        "slug": "t1", "name": "T", "kind": "skill",
    })
    assert res.status_code == 200, res.text
    assert res.json()["owner_lab"] == "hallett"


def test_http_submit_other_lab_refused_for_member(world):
    """alice can't submit a tool tagged owner_lab=castellani — that's
    cross-lab, requires registrar."""
    client = TestClient(create_app())
    res = client.post("/api/registrar/common_seas?user=alice", json={
        "slug": "t1", "name": "T", "kind": "skill",
        "owner_lab": "castellani",
    })
    assert res.status_code == 403


def test_http_submit_other_lab_ok_for_registrar(world):
    client = TestClient(create_app())
    res = client.post("/api/registrar/common_seas?user=the_pi", json={
        "slug": "t1", "name": "T", "kind": "skill",
        "owner_lab": "castellani",
    })
    assert res.status_code == 200, res.text


def test_http_submit_validates_kind(world):
    client = TestClient(create_app())
    res = client.post("/api/registrar/common_seas?user=alice", json={
        "slug": "t1", "name": "T", "kind": "ghost",
    })
    assert res.status_code == 422


# ---- HTTP: edit + archive gates ----------------------------------------

def test_http_patch_owner_lab_pi_ok(world):
    """@the_pi (PI of hallett) can edit a hallett-owned tool."""
    CS.create_sea(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    res = client.patch("/api/registrar/common_seas/t1?user=the_pi",
                        json={"description": "edited"})
    assert res.status_code == 200, res.text
    assert CS.get_sea("t1").description == "edited"


def test_http_patch_other_lab_member_refused(world):
    """alice (member, not PI) can't edit even her own lab's tool —
    only PI or registrar may."""
    CS.create_sea(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    res = client.patch("/api/registrar/common_seas/t1?user=alice",
                        json={"description": "edited"})
    assert res.status_code == 403


def test_http_patch_other_lab_pi_refused(world):
    """castellani's PI can't edit hallett's tool."""
    CS.create_sea(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    res = client.patch("/api/registrar/common_seas/t1?user=cast_pi",
                        json={"description": "hijack"})
    assert res.status_code == 403


def test_http_archive_owner_ok(world):
    CS.create_sea(slug="t1", name="T", kind="skill", owner_lab="hallett")
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/common_seas/t1/archive?user=the_pi")
    assert res.status_code == 200
    assert CS.get_sea("t1").status == "deprecated"


def test_http_archive_unknown_404(world):
    client = TestClient(create_app())
    res = client.post(
        "/api/registrar/common_seas/ghost/archive?user=the_pi")
    assert res.status_code == 404


# ---- CLI ---------------------------------------------------------------

def test_cli_submit_then_list_then_show(world):
    runner = CliRunner()
    res = runner.invoke(cli_common_sea, [
        "submit", "--slug", "qc_drift", "--name", "QC drift",
        "--kind", "routine",
        "--description", "demo",
        "--install", "murmurent routine install qc_drift",
        "--tag", "qc", "--tag", "monitoring",
    ])
    assert res.exit_code == 0, res.output
    assert "Submitted qc_drift" in res.output

    res = runner.invoke(cli_common_sea, ["list"])
    assert "qc_drift" in res.output
    assert "routine" in res.output

    res = runner.invoke(cli_common_sea, ["show", "qc_drift"])
    assert "QC drift" in res.output
    assert "murmurent routine install qc_drift" in res.output


def test_cli_archive(world):
    CS.create_sea(slug="t1", name="T", kind="skill", owner_lab="hallett")
    res = CliRunner().invoke(cli_common_sea, ["archive", "t1"])
    assert res.exit_code == 0
    assert CS.get_sea("t1").status == "deprecated"


def test_cli_submit_unknown_kind_clean_error(world):
    res = CliRunner().invoke(cli_common_sea, [
        "submit", "--slug", "x", "--name", "X", "--kind", "ghost",
    ])
    assert res.exit_code != 0
    assert "Invalid value" in res.output or "ghost" in res.output
