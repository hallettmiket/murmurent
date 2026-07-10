"""
Tests for ``murmurent centre-init`` + ``murmurent centre-status`` (2b).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from murmurent.commands.centre_cmd import centre_init as cli_centre_init
from murmurent.commands.centre_cmd import centre_status as cli_centre_status
from murmurent.core import centre_init as CI
from murmurent.core import registrar as R


@pytest.fixture
def world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "tbrowne")
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL",
                         fake_home / ".wigamig" / "registrar")
    return tmp_path


# ---- centre-init: scripted (--no-prompt) -------------------------------

def test_no_prompt_happy_path(world):
    res = CliRunner().invoke(cli_centre_init, [
        "--no-prompt",
        "--name", "Western Bioconvergence Centre",
        "--institution", "Western University",
        "--slack-workspace", "T0WESTERN",
        "--github-org", "centre-westernu",
        "--data-server", "biodatsci.uwo.ca",
        "--raw-root", "/data/lab_vm/raw",
        "--refined-root", "/data/lab_vm/refined",
        "--no-sentinel",
    ])
    assert res.exit_code == 0, res.output
    assert "Centre initialised" in res.output
    assert CI.is_initialised()


def test_no_prompt_defaults_mayor_from_env(world):
    res = CliRunner().invoke(cli_centre_init, [
        "--no-prompt", "--name", "C", "--institution", "U", "--no-sentinel",
    ])
    assert res.exit_code == 0, res.output
    p = CI.read_centre()
    assert p.founding_mayor == "tbrowne"


def test_no_prompt_requires_name(world):
    res = CliRunner().invoke(cli_centre_init, [
        "--no-prompt", "--institution", "U", "--no-sentinel",
    ])
    assert res.exit_code != 0
    assert "name" in res.output.lower()


def test_no_prompt_requires_institution(world):
    res = CliRunner().invoke(cli_centre_init, [
        "--no-prompt", "--name", "C", "--no-sentinel",
    ])
    assert res.exit_code != 0
    assert "institution" in res.output.lower()


def test_rerun_exits_9(world):
    CliRunner().invoke(cli_centre_init, [
        "--no-prompt", "--name", "C", "--institution", "U", "--no-sentinel",
    ])
    res = CliRunner().invoke(cli_centre_init, [
        "--no-prompt", "--name", "Other", "--institution", "Other",
        "--no-sentinel",
    ])
    assert res.exit_code == 9
    assert "already initialised" in res.output.lower()


def test_explicit_mayor_overrides_env(world):
    res = CliRunner().invoke(cli_centre_init, [
        "--no-prompt", "--name", "C", "--institution", "U",
        "--mayor", "@otheradmin", "--no-sentinel",
    ])
    assert res.exit_code == 0, res.output
    assert CI.read_centre().founding_mayor == "otheradmin"


# ---- centre-init: interactive ------------------------------------------

def test_interactive_uses_prompts(world):
    res = CliRunner().invoke(cli_centre_init, ["--no-sentinel"],
                              input="\n".join([
                                  "Test Centre",        # name
                                  "Test University",    # institution
                                  "",                    # unique_name
                                  "",                    # join_email
                                  "",                    # slack ws
                                  "",                    # github org
                                  "",                    # public_hub
                                  "",                    # server_host
                                  "",                    # server_account
                                  "",                    # cc_install_path
                                  "",                    # obsidian_vault
                                  "",                    # mayor_root
                                  "",                    # data server
                                  "/data/lab_vm/raw",   # raw_root default accepted
                                  "/data/lab_vm/refined",
                              ]) + "\n")
    assert res.exit_code == 0, res.output
    assert CI.read_centre().name == "Test Centre"


# ---- centre-status -----------------------------------------------------

def test_status_no_centre_exits_2(world):
    res = CliRunner().invoke(cli_centre_status)
    assert res.exit_code == 2
    assert "no centre" in res.output.lower()


def test_status_after_init(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)
    res = CliRunner().invoke(cli_centre_status)
    assert res.exit_code == 0, res.output
    assert "C" in res.output
    assert "@tbrowne" in res.output
    assert "Labs:             0" in res.output


# ---- join-request CLI -------------------------------------------------

from murmurent.commands.centre_cmd import join_request_group as cli_jr


def _init(world):
    CI.init_centre(name="C", institution="U",
                    founding_mayor="@tbrowne", write_sentinel=False)


def test_jr_submit_then_list_then_show(world):
    _init(world)
    runner = CliRunner()
    res = runner.invoke(cli_jr, [
        "submit", "--kind", "lab", "--name", "demo",
        "--pi", "@dpi", "--email", "dpi@uwo.ca",
        "--institution", "Western",
    ])
    assert res.exit_code == 0, res.output
    assert "Filed join request #0001" in res.output

    res = runner.invoke(cli_jr, ["list"])
    assert "demo" in res.output and "@dpi" in res.output

    res = runner.invoke(cli_jr, ["show", "1"])
    assert "Western" in res.output


def test_jr_decline_requires_reason(world):
    _init(world)
    CliRunner().invoke(cli_jr, [
        "submit", "--kind", "lab", "--name", "demo",
        "--pi", "@dpi", "--email", "x@y",
    ])
    res = CliRunner().invoke(cli_jr, ["decline", "1", "--reason", "duplicate"])
    assert res.exit_code == 0, res.output
    assert "declined" in res.output.lower()


def test_jr_approve_no_provision(world):
    _init(world)
    CliRunner().invoke(cli_jr, [
        "submit", "--kind", "admin", "--name", "newadmin",
        "--pi", "@newadmin", "--email", "newadmin@x",
    ])
    res = CliRunner().invoke(cli_jr, ["approve", "1", "--no-provision"])
    assert res.exit_code == 0, res.output
    assert "approved" in res.output.lower()
