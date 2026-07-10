"""
Tests for the centre bootstrap module (item 2 of the post-smoke plan).

Covers:
  - centre.md round-trip (read missing → None; read malformed → None)
  - init_centre writes centre.md + adds mayor to registrars + commits
  - init_centre refuses on re-run (CentreAlreadyInitialised)
  - init_centre rejects missing required fields
  - update_centre allows post-init edits except founding_mayor
  - is_initialised reflects state
"""

from __future__ import annotations

import pytest
import yaml

from murmurent.core import centre_init as CI
from murmurent.core import registrar as R


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "tbrowne")
    # Redirect the per-machine sentinel away from the real ~/.wigamig.
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL",
                         fake_home / ".wigamig" / "registrar")
    return tmp_path


# ---- empty state -------------------------------------------------------

def test_read_centre_missing_returns_none(world):
    assert CI.read_centre() is None


def test_is_initialised_false_on_fresh(world):
    assert CI.is_initialised() is False


def test_read_centre_malformed_returns_none(world):
    p = CI.centre_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nname: oops\n---\n", encoding="utf-8")
    # Missing institution + founding_mayor → invalid → None.
    assert CI.read_centre() is None


# ---- init_centre happy path --------------------------------------------

def test_init_writes_centre_md(world):
    profile = CI.init_centre(
        name="Western Bioconvergence Centre",
        institution="Western University",
        founding_mayor="@tbrowne",
        slack_workspace="T0WESTERN",
        github_org="centre-westernu",
        data_server="lab-server.example.edu",
        raw_root="/data/lab_vm/raw",
        refined_root="/data/lab_vm/refined",
        write_sentinel=False,
    )
    assert profile.path.is_file()
    assert profile.founding_mayor == "tbrowne"
    assert CI.is_initialised() is True
    # Round-trip read returns the same data.
    rt = CI.read_centre()
    assert rt.name == "Western Bioconvergence Centre"
    assert rt.institution == "Western University"
    assert rt.founding_mayor == "tbrowne"
    assert rt.slack_workspace == "T0WESTERN"


def test_init_adds_mayor_to_registrars(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    assert R.is_registrar("tbrowne") is True
    assert R.is_registrar("@tbrowne") is True
    assert R.is_registrar("not_tbrowne") is False


def test_init_writes_sentinel_when_requested(world, tmp_path):
    fake_sentinel = tmp_path / "home" / ".wigamig" / "registrar"
    import murmurent.core.registrar as R
    R.REGISTRAR_SENTINEL = fake_sentinel  # already monkeypatched
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=True)
    assert fake_sentinel.is_file()
    assert fake_sentinel.read_text().strip() == "tbrowne"


def test_init_creates_git_audit_commit(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    import subprocess
    log = subprocess.run(
        ["git", "-C", str(world / "lab_info"), "log", "--oneline"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "centre initialised: C" in log


# ---- init_centre validation --------------------------------------------

def test_init_refuses_empty_name(world):
    with pytest.raises(CI.CentreInitError, match="name"):
        CI.init_centre(name="", institution="U",
                        founding_mayor="@tbrowne", write_sentinel=False)


def test_init_refuses_empty_institution(world):
    with pytest.raises(CI.CentreInitError, match="institution"):
        CI.init_centre(name="C", institution="",
                        founding_mayor="@tbrowne", write_sentinel=False)


def test_init_refuses_empty_mayor(world):
    with pytest.raises(CI.CentreInitError, match="founding_mayor"):
        CI.init_centre(name="C", institution="U",
                        founding_mayor="", write_sentinel=False)


def test_init_refuses_rerun(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    with pytest.raises(CI.CentreAlreadyInitialised):
        CI.init_centre(name="Other", institution="Other",
                        founding_mayor="@other", write_sentinel=False)


# ---- update_centre -----------------------------------------------------

def test_update_centre_partial_edit(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    CI.update_centre({"slack_workspace": "T0NEW"})
    p = CI.read_centre()
    assert p.slack_workspace == "T0NEW"
    assert p.founding_mayor == "tbrowne"   # untouched


def test_update_centre_cannot_change_founding_mayor(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    CI.update_centre({"founding_mayor": "@other"})
    assert CI.read_centre().founding_mayor == "tbrowne"


def test_update_centre_refuses_when_no_centre(world):
    with pytest.raises(CI.CentreInitError, match="no centre"):
        CI.update_centre({"slack_workspace": "T0X"})


def test_update_centre_ignores_unknown_keys(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    CI.update_centre({"random_key": "ignored",
                        "slack_workspace": "T0SET"})
    p = CI.read_centre()
    assert p.slack_workspace == "T0SET"
    # Reading the file directly, no random_key present.
    raw = p.path.read_text(encoding="utf-8")
    assert "random_key" not in raw
