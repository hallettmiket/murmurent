"""
Tests for the Overleaf-manuscript CLAUDE.md note (multi-repo stage 5): a
manuscript repo (role=manuscript, overleaf=true) cloned locally gets a per-repo
CLAUDE.md embedding the pull-first rules.
"""

from __future__ import annotations

from murmurent.core import project_cc_init as CCI


def test_writes_note_when_dir_exists_and_no_claude_md(tmp_path):
    repo = tmp_path / "x_manuscript"
    repo.mkdir()
    assert CCI.write_overleaf_manuscript_note(repo, project="x",
                                              repo_name="x_manuscript") is True
    text = (repo / "CLAUDE.md").read_text()
    assert CCI._OVERLEAF_MARKER in text
    assert "git pull" in text.lower() and "before editing" in text.lower()
    assert "no feature branches" in text.lower()
    assert "do not compile locally" in text.lower()
    assert "x_manuscript" in text


def test_preserves_a_user_authored_claude_md(tmp_path):
    repo = tmp_path / "ms"
    repo.mkdir()
    (repo / "CLAUDE.md").write_text("# my own notes\n", encoding="utf-8")
    assert CCI.write_overleaf_manuscript_note(repo, project="p") is False
    assert (repo / "CLAUDE.md").read_text() == "# my own notes\n"   # untouched


def test_noop_when_dir_missing(tmp_path):
    assert CCI.write_overleaf_manuscript_note(tmp_path / "nope") is False
