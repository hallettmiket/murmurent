"""Tests for :mod:`wigamig.core.sea` and :mod:`wigamig.commands.sea_cmd`."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from wigamig.cli import cli
from wigamig.commands import project_cmd, sea_cmd
from wigamig.core import sea
from wigamig.core.projects import find_project


@pytest.fixture
def project(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_PROJECTS_ROOT", str(tmp_path / "repos"))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "lab_vm"))
    (tmp_path / "lab-mgmt" / "projects").mkdir(parents=True)
    project_cmd.cmd_new(
        "p",
        charter_path=None,
        members_csv="@allie,@bob,@cassie",
        description="x",
        sensitivity="standard",
        skip_github=True,
    )
    return find_project("p")


def test_request_then_list(project, monkeypatch):
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    sea_cmd.cmd_request(project_name="p", to_target="@bob", kind="experiment", description="run X")
    seas = sea.iter_seas(project)
    assert len(seas) == 1
    s = seas[0]
    assert s.id == 1
    assert s.from_handle == "@allie"
    assert s.to_handle == "@bob"
    assert s.state == "requested"


def test_lifecycle_claim_complete(project, monkeypatch):
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    sea_cmd.cmd_request(project_name="p", to_target="@bob", kind="analysis", description="x")
    monkeypatch.setenv("WIGAMIG_USER", "bob")
    sea_cmd.cmd_claim(1)
    s = sea.iter_seas(project)[0]
    assert s.state == "claimed" and s.claimed_at is not None
    sea_cmd.cmd_complete(1, delivery="findings/x.md")
    s = sea.iter_seas(project)[0]
    assert s.state == "complete" and s.delivery == "findings/x.md"


def test_decline_blocks_claim(project, monkeypatch):
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    sea_cmd.cmd_request(project_name="p", to_target="@bob", kind="skill", description="x")
    sea_cmd.cmd_decline(1, reason="out of scope")
    s = sea.iter_seas(project)[0]
    assert s.state == "declined"
    with pytest.raises(Exception):
        sea_cmd.cmd_claim(1)


def test_list_filters_by_direction(project, monkeypatch):
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    sea_cmd.cmd_request(project_name="p", to_target="@bob", kind="skill", description="a")
    monkeypatch.setenv("WIGAMIG_USER", "cassie")
    sea_cmd.cmd_request(project_name="p", to_target="@allie", kind="skill", description="b")

    runner = CliRunner()
    monkeypatch.setenv("WIGAMIG_USER", "bob")
    result = runner.invoke(cli, ["sea", "list", "--incoming"])
    assert result.exit_code == 0, result.output
    assert "1" in result.output
    assert "2" not in result.output  # bob is not on SEA 2

    monkeypatch.setenv("WIGAMIG_USER", "allie")
    result = runner.invoke(cli, ["sea", "list", "--outgoing"])
    assert result.exit_code == 0, result.output
    assert "1" in result.output  # allie filed SEA 1
    assert "2" not in result.output  # allie did not file SEA 2


def test_examine_then_conclude(project, monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_USER", "allie")
    sea_cmd.cmd_request(project_name="p", to_target="@bob", kind="analysis", description="x")
    sea_cmd.cmd_claim(1)
    sea_cmd.cmd_complete(1, delivery="findings/x.md")
    sea_cmd.cmd_examine(1)
    delib = project.path / "deliberations" / "sea" / "1.md"
    assert delib.is_file()
    text = delib.read_text()
    assert "## Agent contributions" in text
    assert "### bookworm" in text  # roster includes lowercase agent names

    statement = tmp_path / "stmt.md"
    statement.write_text("Final statement: nothing surprising.\n")
    sea_cmd.cmd_conclude(1, statement=str(statement))
    s = sea.iter_seas(project)[0]
    assert s.state == "concluded"
    final_text = delib.read_text()
    assert "Final statement: nothing surprising." in final_text


def test_filter_for_member_helper():
    seas = [
        sea.Sea(id=1, from_handle="@allie", to_handle="@bob", kind="skill", description="x"),
        sea.Sea(id=2, from_handle="@bob", to_handle="@allie", kind="skill", description="y"),
        sea.Sea(id=3, from_handle="@cassie", to_handle="@the_pi", kind="skill", description="z"),
    ]
    inc = sea.filter_for_member(seas, "bob", direction="incoming")
    assert [s.id for s in inc] == [1]
    out = sea.filter_for_member(seas, "allie", direction="outgoing")
    assert [s.id for s in out] == [1]
    mine = sea.filter_for_member(seas, "allie", direction="mine")
    assert [s.id for s in mine] == [1, 2]
