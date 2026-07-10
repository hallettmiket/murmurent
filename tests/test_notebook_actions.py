"""Tests for the Phase-6 notebook editor handoff.

Covers ``notebook_actions`` (path resolution, default template, editor
resolver fallbacks), and ``POST /api/notebook/edit`` (creates file +
returns the resolved command).

We never actually spawn an editor — every test goes through ``spawn=False``
or sets ``WIGAMIG_NOTEBOOK_EDITOR=true`` (the unix ``true`` binary is a
silent no-op).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

import pytest

from murmurent.dashboard import notebook_actions


@pytest.fixture
def lab_notebook(monkeypatch, tmp_path):
    """Redirect ``~/lab-notebook`` to a tmp dir for the test."""
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_DIR", str(tmp_path / "lab-notebook"))
    monkeypatch.delenv("WIGAMIG_NOTEBOOK_EDITOR", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    return tmp_path / "lab-notebook"


# ---------------------------------------------------------------------------
# resolve_editor_cmd()
# ---------------------------------------------------------------------------


def test_explicit_override_with_path_placeholder(lab_notebook, monkeypatch):
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_EDITOR", "myedit --line 1 {path}")
    cmd = notebook_actions.resolve_editor_cmd(lab_notebook / "x.md")
    assert cmd[0] == "myedit"
    assert "--line" in cmd
    assert str(lab_notebook / "x.md") in cmd


def test_explicit_override_plain_command(lab_notebook, monkeypatch):
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_EDITOR", "vim")
    cmd = notebook_actions.resolve_editor_cmd(lab_notebook / "x.md")
    assert cmd[0] == "vim"
    assert cmd[-1] == str(lab_notebook / "x.md")


def test_explicit_override_obsidian_keyword(lab_notebook, monkeypatch):
    """``WIGAMIG_NOTEBOOK_EDITOR=obsidian`` builds an obsidian:// URL command."""
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_EDITOR", "obsidian")
    path = lab_notebook / "2026-05-08.md"
    cmd = notebook_actions.resolve_editor_cmd(path)
    # On macOS / linux this becomes ``["open"|"xdg-open", "obsidian://..."]``.
    assert any("obsidian://" in arg for arg in cmd)
    assert "2026-05-08" in " ".join(cmd)


def test_editor_env_fallback(lab_notebook, monkeypatch):
    monkeypatch.setenv("EDITOR", "nano")
    cmd = notebook_actions.resolve_editor_cmd(lab_notebook / "x.md")
    assert cmd[0] == "nano"


def test_obsidian_wins_when_file_inside_registered_vault(monkeypatch, tmp_path):
    """When the file is in a registered Obsidian vault, Obsidian opens
    even if $EDITOR is set — the file lives in the user's Obsidian world."""
    from murmurent.core import obsidian as _obs

    vault = _obs.Vault(name="lab-vault", path=tmp_path / "lab-vault", ts=1234)
    monkeypatch.setattr(_obs, "discover_vaults", lambda: [vault])
    monkeypatch.setenv("EDITOR", "nano")  # would win in the old order
    monkeypatch.delenv("WIGAMIG_NOTEBOOK_EDITOR", raising=False)
    nb = vault.path / "lab-notebook"
    nb.mkdir(parents=True)
    target = nb / "2026-05-08.md"

    cmd = notebook_actions.resolve_editor_cmd(target)
    assert any("obsidian://" in arg for arg in cmd)
    # URL should point at the right vault + relative path:
    full = " ".join(cmd)
    assert "vault=lab-vault" in full
    assert "lab-notebook/2026-05-08" in full


def test_obsidian_url_skipped_when_file_outside_any_vault(monkeypatch, tmp_path):
    """File outside vaults -> Obsidian doesn't fire; $EDITOR wins."""
    from murmurent.core import obsidian as _obs

    monkeypatch.setattr(_obs, "discover_vaults", lambda: [])
    monkeypatch.setenv("EDITOR", "nano")
    monkeypatch.delenv("WIGAMIG_NOTEBOOK_EDITOR", raising=False)
    cmd = notebook_actions.resolve_editor_cmd(tmp_path / "elsewhere" / "x.md")
    assert cmd[0] == "nano"


def test_visual_env_fallback(lab_notebook, monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setenv("VISUAL", "ed")
    cmd = notebook_actions.resolve_editor_cmd(lab_notebook / "x.md")
    assert cmd[0] == "ed"


def test_resolver_raises_when_nothing_available(lab_notebook, monkeypatch):
    """Empty PATH + no env vars -> NotebookEditorNotAvailable."""
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("WIGAMIG_NOTEBOOK_EDITOR", raising=False)
    with pytest.raises(notebook_actions.NotebookEditorNotAvailable):
        notebook_actions.resolve_editor_cmd(lab_notebook / "x.md")


# ---------------------------------------------------------------------------
# entry_path / default_entry_text
# ---------------------------------------------------------------------------


def test_entry_path_uses_overridden_folder(lab_notebook):
    p = notebook_actions.entry_path("2026-05-08")
    assert p == lab_notebook / "2026-05-08.md"


def test_notebook_folder_prefers_obsidian_vault(monkeypatch, tmp_path):
    """When a vault is registered and no $WIGAMIG_NOTEBOOK_DIR override,
    the notebook lives inside the vault."""
    from murmurent.core import obsidian as _obs

    vault = _obs.Vault(name="my-vault", path=tmp_path / "my-vault", ts=1)
    vault.path.mkdir()
    monkeypatch.delenv("WIGAMIG_NOTEBOOK_DIR", raising=False)
    monkeypatch.setattr(_obs, "preferred_vault", lambda: vault)

    folder = notebook_actions.notebook_folder()
    assert folder == vault.path / "lab-notebook"


def test_notebook_folder_migrates_legacy_into_vault(monkeypatch, tmp_path):
    """First call with a vault registered moves stale ~/lab-notebook entries in."""
    from murmurent.core import obsidian as _obs

    vault = _obs.Vault(name="v", path=tmp_path / "v", ts=1)
    vault.path.mkdir()
    legacy = tmp_path / "home" / "lab-notebook"
    legacy.mkdir(parents=True)
    (legacy / "2026-05-01.md").write_text("hello", encoding="utf-8")
    (legacy / "2026-05-02.md").write_text("world", encoding="utf-8")

    monkeypatch.delenv("WIGAMIG_NOTEBOOK_DIR", raising=False)
    monkeypatch.setattr(_obs, "preferred_vault", lambda: vault)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    folder = notebook_actions.notebook_folder()
    assert folder == vault.path / "lab-notebook"
    assert (folder / "2026-05-01.md").is_file()
    assert (folder / "2026-05-02.md").is_file()
    # Legacy dir should now be empty of .md files (moved, not copied).
    assert not list(legacy.glob("*.md"))


def test_notebook_folder_falls_back_to_home_when_no_vault(monkeypatch, tmp_path):
    from murmurent.core import obsidian as _obs

    monkeypatch.delenv("WIGAMIG_NOTEBOOK_DIR", raising=False)
    monkeypatch.setattr(_obs, "preferred_vault", lambda: None)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    folder = notebook_actions.notebook_folder()
    assert folder == tmp_path / "lab-notebook"


def test_default_entry_text_has_required_frontmatter(lab_notebook):
    text = notebook_actions.default_entry_text("2026-05-08")
    assert "date: 2026-05-08" in text
    assert "tags: []" in text
    assert "links_seas: []" in text
    assert "Plan for today" in text


# ---------------------------------------------------------------------------
# open_entry()
# ---------------------------------------------------------------------------


def test_open_entry_creates_missing_file(lab_notebook, monkeypatch):
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_EDITOR", "true")
    result = notebook_actions.open_entry(date_iso="2026-05-08", spawn=False)
    assert result.created is True
    assert result.path == lab_notebook / "2026-05-08.md"
    assert result.path.is_file()
    body = result.path.read_text()
    assert "date: 2026-05-08" in body


def test_open_entry_does_not_overwrite_existing(lab_notebook, monkeypatch):
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_EDITOR", "true")
    lab_notebook.mkdir(parents=True, exist_ok=True)
    p = lab_notebook / "2026-05-08.md"
    p.write_text("MY OWN CONTENT", encoding="utf-8")
    result = notebook_actions.open_entry(date_iso="2026-05-08", spawn=False)
    assert result.created is False
    assert result.path.read_text() == "MY OWN CONTENT"


def test_open_entry_defaults_to_today(lab_notebook, monkeypatch):
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_EDITOR", "true")
    today = _dt.date(2026, 5, 8)
    result = notebook_actions.open_entry(today=today, spawn=False)
    assert result.path.name == "2026-05-08.md"


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def _client():
    from fastapi.testclient import TestClient
    from murmurent.dashboard.server import create_app
    return TestClient(create_app())


def test_endpoint_creates_today_entry(lab_notebook, monkeypatch):
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_EDITOR", "true")
    client = _client()
    res = client.post("/api/notebook/edit", json={})
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["ok"] is True
    assert payload["path"].endswith(".md")
    today_path = lab_notebook / f"{_dt.date.today().isoformat()}.md"
    assert today_path.is_file()


def test_endpoint_opens_specific_date(lab_notebook, monkeypatch):
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_EDITOR", "true")
    client = _client()
    res = client.post("/api/notebook/edit", json={"date": "2025-12-25"})
    assert res.status_code == 200
    assert (lab_notebook / "2025-12-25.md").is_file()


def test_endpoint_500_when_no_editor(lab_notebook, monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("WIGAMIG_NOTEBOOK_EDITOR", raising=False)
    client = _client()
    res = client.post("/api/notebook/edit", json={})
    assert res.status_code == 500
