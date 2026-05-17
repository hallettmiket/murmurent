"""Tests for wigamig VSCode + CC chrome propagation into adopted /
installed projects.

These pin the contract that ``bootstrap_local`` (and by extension
``projectize.make_wigamig_project``) lays down a consistent VSCode
personality for every wigamig project:
  * ``.vscode/settings.json`` — title template, activity bar right,
    sidebar right, terminals default to editor area
  * ``.claude/settings.json`` — hooks block pointing at the wigamig
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

from wigamig.core.project_cc_init import (
    _cc_settings_json,
    _vscode_settings_json,
    bootstrap_local,
)


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Isolated project dir + fake wigamig commons."""
    home = tmp_path / "home"
    (home / "repos").mkdir(parents=True)
    commons = tmp_path / "wigamig"
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
    """A fresh project gets `.vscode/settings.json` with the wigamig
    title template + chrome settings."""
    bootstrap_local(world["project"], world["commons"], agents=[], project_name="demo")
    f = world["project"] / ".vscode" / "settings.json"
    assert f.is_file()
    data = json.loads(f.read_text())
    assert "Wigamig" in data["window.title"]
    assert "${rootName}" in data["window.title"]
    assert data["workbench.activityBar.location"] == "end"
    assert data["workbench.sideBar.location"] == "right"
    assert data["terminal.integrated.defaultLocation"] == "editor"


def test_bootstrap_writes_cc_settings_with_hook(world):
    """`.claude/settings.json` carries the hooks block pointing at the
    wigamig commons agent-reporter script."""
    bootstrap_local(world["project"], world["commons"], agents=[], project_name="demo")
    f = world["project"] / ".claude" / "settings.json"
    assert f.is_file()
    data = json.loads(f.read_text())
    assert "permissions" not in data, "hooks-only file — permissions grow per-project"
    pre = data["hooks"]["PreToolUse"][0]
    assert pre["matcher"] == "Agent"
    assert pre["hooks"][0]["command"].endswith("/wigamig_log_agent_event.sh")
    stop = data["hooks"]["SubagentStop"][0]
    assert stop["hooks"][0]["command"].endswith("/wigamig_log_agent_event.sh")


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
    """Same for `.claude/settings.json` — the user may have added
    permissions that we should not clobber."""
    proj = world["project"]
    (proj / ".claude").mkdir(parents=True)
    custom = '{"permissions": {"allow": ["Bash(ls *)"]}}'
    (proj / ".claude" / "settings.json").write_text(custom)
    bootstrap_local(proj, world["commons"], agents=[], project_name="demo")
    assert (proj / ".claude" / "settings.json").read_text() == custom


def test_bootstrap_reports_chrome_probes(world):
    """The new probes (vscode_settings, cc_settings) appear in the
    probes list with ok status — the dashboard renders them inline
    alongside the existing cc_agent/cc_claude_md rows."""
    probes = bootstrap_local(world["project"], world["commons"], agents=[], project_name="demo")
    names = {p.name for p in probes}
    assert "vscode_settings" in names
    assert "cc_settings" in names


def test_vscode_settings_json_is_valid_json():
    """Sanity: the helper produces parseable JSON."""
    json.loads(_vscode_settings_json())


def test_cc_settings_json_includes_hook_path():
    """The hook path is interpolated; sanity-check the produced JSON."""
    j = _cc_settings_json(hook_path=Path("/wig/scripts/hook.sh"))
    data = json.loads(j)
    assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == "/wig/scripts/hook.sh"


def test_ssh_chrome_writes_appear_in_remote_adopt_script():
    """The SSH adopt script must include the chrome writes too, so a
    biodatsci adopt produces the same set of artefacts a local one
    does. Pin via the script text — we exercise the bash itself in
    the real round-trip test (test_remote_adopt.py)."""
    from wigamig.core import remote_adopt as r
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
