"""Tests for murmurent VSCode + CC chrome propagation into adopted /
installed projects.

These pin the contract that ``bootstrap_local`` (and by extension
``projectize.make_wigamig_project``) lays down a consistent VSCode
personality for every murmurent project:
  * ``.vscode/settings.json`` — title template, activity bar right,
    sidebar right, terminals default to editor area
  * ``.claude/settings.json`` — hooks block pointing at the murmurent
    commons agent-reporter so subagent events from this project
    land in ``~/.wigamig/agents.log`` (which the BR pane tails)

Both files are skipped on re-bootstrap when present — user edits are
sacred. Both files are written **alongside** the existing
``.claude/agents/`` symlinks and ``CLAUDE.md`` stub, never replacing
them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from murmurent.core.project_cc_init import (
    _vscode_settings_json,
    bootstrap_local,
)


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Isolated project dir + fake murmurent commons."""
    home = tmp_path / "home"
    (home / "repos").mkdir(parents=True)
    commons = tmp_path / "murmurent"
    (commons / "agents").mkdir(parents=True)
    (commons / "agents" / "blacksmith.md").write_text("# blacksmith\n")
    (commons / "scripts").mkdir(parents=True)
    (commons / "scripts" / "wigamig_log_agent_event.sh").write_text("#!/usr/bin/env bash\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("WIGAMIG_REPO_ROOT", str(commons))
    proj = home / "repos" / "demo"
    proj.mkdir()
    return {"home": home, "commons": commons, "project": proj}


def test_bootstrap_writes_vscode_settings(world):
    """A fresh project gets `.vscode/settings.json` with the murmurent
    title template + chrome settings."""
    bootstrap_local(world["project"], world["commons"], agents=[], project_name="demo")
    f = world["project"] / ".vscode" / "settings.json"
    assert f.is_file()
    data = json.loads(f.read_text())
    assert "Murmurent" in data["window.title"]
    assert "${rootName}" in data["window.title"]
    assert data["workbench.activityBar.location"] == "end"
    assert data["workbench.sideBar.location"] == "right"
    assert data["terminal.integrated.defaultLocation"] == "editor"


def test_bootstrap_does_not_write_cc_settings(world):
    """The murmurent subagent-reporter hooks moved out of per-project
    .claude/settings.json into the user-global ~/.claude/settings.json
    on 2026-05-17 (single source of truth, no machine-absolute paths
    leaking into project repos). bootstrap_local must NOT write a
    per-project hook stub any more — that would double-fire the
    hook for every event."""
    bootstrap_local(world["project"], world["commons"], agents=[], project_name="demo")
    assert not (world["project"] / ".claude" / "settings.json").exists()


def test_bootstrap_preserves_existing_vscode_settings(world):
    """If the project already has `.vscode/settings.json`, leave it
    alone — even on re-bootstrap. The user may have added Python
    interpreter pins or workspace-specific tweaks we don't want to
    blow away."""
    proj = world["project"]
    (proj / ".vscode").mkdir()
    (proj / ".vscode" / "settings.json").write_text('{"editor.tabSize": 4}')
    bootstrap_local(proj, world["commons"], agents=[], project_name="demo")
    assert (proj / ".vscode" / "settings.json").read_text() == '{"editor.tabSize": 4}'


def test_bootstrap_preserves_existing_cc_settings(world):
    """If the user has manually authored a per-project
    .claude/settings.json (e.g. for project-specific permissions),
    bootstrap_local must NOT touch it. Even though we no longer
    write the file ourselves, we still mustn't clobber user content
    that happens to be there."""
    proj = world["project"]
    (proj / ".claude").mkdir(parents=True)
    custom = '{"permissions": {"allow": ["Bash(ls *)"]}}'
    (proj / ".claude" / "settings.json").write_text(custom)
    bootstrap_local(proj, world["commons"], agents=[], project_name="demo")
    assert (proj / ".claude" / "settings.json").read_text() == custom


def test_bootstrap_adds_cc_settings_to_gitignore(world):
    """Defensive: bootstrap appends ``.claude/settings.json`` to the
    project's .gitignore. This way a user-created per-project
    settings file (machine-absolute paths, per-machine permissions)
    can't accidentally escape to collaborators via git."""
    proj = world["project"]
    bootstrap_local(proj, world["commons"], agents=[], project_name="demo")
    gi = proj / ".gitignore"
    assert gi.is_file()
    lines = [l.strip() for l in gi.read_text().splitlines()]
    assert ".claude/settings.json" in lines


def test_bootstrap_gitignore_is_idempotent(world):
    """Re-running bootstrap must not duplicate the gitignore entry."""
    proj = world["project"]
    bootstrap_local(proj, world["commons"], agents=[], project_name="demo")
    bootstrap_local(proj, world["commons"], agents=[], project_name="demo")
    count = sum(
        1 for line in (proj / ".gitignore").read_text().splitlines()
        if line.strip() == ".claude/settings.json"
    )
    assert count == 1


def test_bootstrap_appends_to_existing_gitignore(world):
    """If the project already has a .gitignore with other patterns,
    bootstrap appends without disturbing existing entries."""
    proj = world["project"]
    (proj / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    bootstrap_local(proj, world["commons"], agents=[], project_name="demo")
    text = (proj / ".gitignore").read_text()
    assert "__pycache__/" in text
    assert "*.pyc" in text
    assert ".claude/settings.json" in text


def test_bootstrap_reports_chrome_probes(world):
    """The chrome probes (vscode_settings, gitignore) appear in the
    probes list with ok status — the dashboard renders them inline
    alongside the existing cc_agent/cc_claude_md rows. ``cc_settings``
    is no longer emitted (hooks are global now)."""
    probes = bootstrap_local(world["project"], world["commons"], agents=[], project_name="demo")
    names = {p.name for p in probes}
    assert "vscode_settings" in names
    assert "gitignore" in names
    assert "cc_settings" not in names


def test_vscode_settings_json_is_valid_json():
    """Sanity: the helper produces parseable JSON."""
    json.loads(_vscode_settings_json())


def test_ssh_chrome_writes_appear_in_remote_adopt_script():
    """The SSH adopt script must include the chrome writes too, so a
    biodatsci adopt produces the same set of artefacts a local one
    does. Pin via the script text — we exercise the bash itself in
    the real round-trip test (test_remote_adopt.py)."""
    from murmurent.core import remote_adopt as r
    s = r.build_remote_adopt_script(
        clone_path="/tmp/x", project="x",
        charter_text="---\nproject: x\nlead: '@x'\nsensitivity: standard\nmembers:\n  - '@x'\n---\n# x\n",
        agents=[],
    )
    assert ".vscode/settings.json" in s
    assert ".claude/settings.json" in s
    assert "vscode_settings:ok" in s
    assert "cc_settings:ok" in s
    # Hook path is resolved at remote-runtime via $WIG (script sets
    # it to $HOME/repos/wigamig); the literal $WIG/scripts/... must
    # appear so the unquoted heredoc expands it correctly.
    assert "$WIG/scripts/wigamig_log_agent_event.sh" in s
