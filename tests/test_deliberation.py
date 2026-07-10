"""Tests for :mod:`murmurent.core.deliberation`."""

from __future__ import annotations

import pytest

from murmurent.core import deliberation


def test_render_includes_required_sections():
    text = deliberation.render_deliberation(
        scope="sea",
        target="3",
        operational_status="complete",
    )
    deliberation.assert_sections_present(text)
    for agent in ("bookworm", "adversary", "artist"):
        assert f"### {agent}" in text


def test_render_with_members_lists_subsections():
    text = deliberation.render_deliberation(
        scope="sea",
        target="3",
        operational_status="complete",
        members=["@allie", "@bob"],
    )
    assert "### @allie" in text
    assert "### @bob" in text


def test_assert_sections_present_raises():
    with pytest.raises(ValueError):
        deliberation.assert_sections_present("# nothing here")


def test_update_status_writes_dates(tmp_path):
    delib = tmp_path / "x.md"
    delib.write_text(
        deliberation.render_deliberation(scope="sea", target="1", operational_status="complete"),
        encoding="utf-8",
    )
    deliberation.update_status(delib, analysis_status="examined")
    text = delib.read_text()
    assert "examined_at:" in text
    deliberation.update_status(delib, analysis_status="concluded")
    text = delib.read_text()
    assert "concluded_at:" in text


def test_path_resolution(tmp_path):
    from murmurent.core.repo import ProjectRepo

    repo = ProjectRepo(path=tmp_path, charter_path=tmp_path / "CHARTER.md", members_path=None)
    assert (
        deliberation.deliberation_path(repo, "sea", "3")
        == tmp_path / "deliberations" / "sea" / "3.md"
    )
    assert (
        deliberation.deliberation_path(repo, "experiment", "1_x")
        == tmp_path / "deliberations" / "exp" / "1_x.md"
    )
    assert (
        deliberation.deliberation_path(repo, "project", "ignored")
        == tmp_path / "deliberations" / "project.md"
    )
