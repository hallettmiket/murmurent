"""
Tests for the extended centre.md schema (admin-install program, Phase 1)
and the ``scripts/seed_centre.py`` "create the world" seeder.

Covers:
  - the new server-setup fields round-trip through write → read
  - ``server`` / ``install_id`` back-compat properties
  - unknown/empty fields are stripped from the rendered frontmatter
  - update_centre can edit the new fields (but not founding_mayor)
  - seed_centre builds a full demo centre, preserves the mayor as a
    registrar (regression guard for the create_core / create_collaboration
    ``registrars=`` bug), is idempotent, and refuses the real centre root.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from wigamig.core import centre_init as CI
from wigamig.core import registrar as R


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_HOSTS_FILE", str(tmp_path / "hosts.yaml"))
    monkeypatch.setenv("WIGAMIG_USER", "tbrowne")
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL",
                        fake_home / ".wigamig" / "registrar")
    return tmp_path


EXTENDED = dict(
    name="Demo Centre",
    institution="Demo University",
    founding_mayor="@tbrowne",
    unique_name="demo",
    slack_workspace="T0DEMO",
    github_org="wigamig-demo",
    server_host="lab-server.demo.edu",
    server_account="wigamig",
    cc_install_path="/opt/claude",
    obsidian_vault="/mayor/obsidian",
    mayor_root="/mayor/wigamig",
    public_hub="github.com/x/wigamig_public#demo",
    raw_root="/data/lab_vm/raw",
    refined_root="/data/lab_vm/refined",
)


# ---- extended schema round-trip ----------------------------------------

def test_extended_fields_round_trip(world):
    CI.init_centre(write_sentinel=False, **EXTENDED)
    got = CI.read_centre()
    assert got is not None
    for field in ("unique_name", "server_host", "server_account",
                  "cc_install_path", "obsidian_vault", "mayor_root",
                  "public_hub"):
        assert getattr(got, field) == EXTENDED[field], field


def test_server_property_prefers_server_host(world):
    p = CI.init_centre(write_sentinel=False, **{**EXTENDED,
                                                "data_server": "legacy.host"})
    assert p.server == "lab-server.demo.edu"


def test_server_property_falls_back_to_data_server(world):
    fields = {k: v for k, v in EXTENDED.items() if k != "server_host"}
    p = CI.init_centre(write_sentinel=False, data_server="legacy.host", **fields)
    assert p.server == "legacy.host"


def test_install_id_falls_back_to_institution(world):
    fields = {k: v for k, v in EXTENDED.items() if k != "unique_name"}
    p = CI.init_centre(write_sentinel=False, **fields)
    assert p.install_id == "Demo University"


def test_empty_optionals_stripped_from_frontmatter(world):
    CI.init_centre(
        name="Bare", institution="Bare U", founding_mayor="@tbrowne",
        write_sentinel=False,
    )
    text = CI.centre_path().read_text(encoding="utf-8")
    # An unset optional must not appear as an empty key.
    assert "server_host:" not in text
    assert "obsidian_vault:" not in text
    # Required keys always present.
    assert "name:" in text and "institution:" in text


def test_update_centre_edits_new_fields(world):
    CI.init_centre(write_sentinel=False, **EXTENDED)
    CI.update_centre({"server_account": "svc", "obsidian_vault": "/new/vault",
                      "founding_mayor": "@intruder"})
    got = CI.read_centre()
    assert got.server_account == "svc"
    assert got.obsidian_vault == "/new/vault"
    # founding_mayor stays immutable.
    assert got.founding_mayor == "tbrowne"


# ---- seed_centre.py ----------------------------------------------------

def _load_seed():
    path = Path(__file__).resolve().parents[1] / "scripts" / "seed_centre.py"
    spec = importlib.util.spec_from_file_location("seed_centre", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_builds_full_centre(world, monkeypatch):
    seed = _load_seed()
    root = str(world / "lab_info")
    seed.seed(root)

    reg = R.read_registry()
    assert {lab.name for lab in reg.labs} == {"mm", "mh"}
    assert {core.name for core in reg.cores} == {"em"}
    # Regression guard: the mayor survives the core/collab creation paths.
    assert "tbrowne" in reg.registrars

    # EM core has its non-leader members on disk.
    em = next(c for c in reg.cores if c.name == "em")
    members = {p.stem for p in (Path(em.lab_mgmt_path) / "members").glob("*.md")}
    assert {"elisios", "hagar", "tim"} <= members


def test_seed_queues_pending_joins(world):
    seed = _load_seed()
    seed.seed(str(world / "lab_info"))
    from wigamig.core import join_requests as JR
    pend = [r for r in JR.iter_requests() if r.state == "pending"]
    assert len(pend) >= 2


def test_seed_is_idempotent(world):
    seed = _load_seed()
    root = str(world / "lab_info")
    seed.seed(root)
    seed.seed(root)  # must not raise on duplicate lab/core/host names
    reg = R.read_registry()
    assert len(reg.labs) == 2 and len(reg.cores) == 1


def test_seed_refuses_real_centre(world, monkeypatch):
    seed = _load_seed()
    real = Path.home() / ".wigamig" / "lab_info"
    with pytest.raises(SystemExit):
        seed.seed(str(real))


# ---- registrars= preservation across every Registry rebuild ------------

def test_registrars_survive_core_and_collaboration_creation(world):
    """Regression: create_core and create_collaboration rebuilt the
    Registry without carrying registrars=, silently dropping the mayor."""
    CI.init_centre(name="C", institution="U", founding_mayor="@tbrowne",
                   write_sentinel=False)
    assert "tbrowne" in R.read_registry().registrars

    R.create_core(name="em", display_name="EM", leader_handle="@elisios")
    assert "tbrowne" in R.read_registry().registrars, "create_core dropped registrars"

    R.create_lab(name="mm", display_name="MM", pi_handle="@yubing")
    R.create_lab(name="mh", display_name="MH", pi_handle="@harry")
    R.create_collaboration(name="mm_mh", pis=["@yubing", "@harry"],
                           groups=["mm", "mh"],
                           member_subset={"mm": ["@yubing"], "mh": ["@harry"]})
    assert "tbrowne" in R.read_registry().registrars, \
        "create_collaboration dropped registrars"
