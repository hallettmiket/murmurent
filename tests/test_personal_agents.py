"""Personal (net-new) agents — #38 item 3.

A member creates their own agent; it lands in their vault (backed up to their
GitHub via `vault sync`), is symlinked into ~/.claude/agents so CC loads it, and
shows in the dashboard's Personal section. Distinct from a *fork* of a commons
agent. Covers the core, the endpoint, the snapshot surfacing, and the vault
scaffold.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from murmurent.core import agents as _agents
from murmurent.core import personal_agents as pa
from murmurent.core.frontmatter import parse_file


@pytest.fixture
def env(monkeypatch, tmp_path):
    vagents = tmp_path / "vault" / "agents"
    cc = tmp_path / "cc-agents"
    cc.mkdir(parents=True)
    monkeypatch.setenv("MURMURENT_PERSONAL_AGENTS_DIR", str(vagents))
    monkeypatch.setenv("MURMURENT_CC_AGENTS_DIR", str(cc))
    return {"vault_agents": vagents, "cc": cc}


def test_create_writes_vault_symlinks_and_validates(env):
    p = pa.create_personal_agent(
        "my_helper", "Runs my custom pipeline.", model="fable", tools=["Read", "Bash"])
    assert p == env["vault_agents"] / "my_helper.md" and p.is_file()
    # Installed into the CC dir as a symlink back to the vault file.
    installed = env["cc"] / "my_helper.md"
    assert installed.is_symlink() and os.readlink(installed) == str(p)
    # Parses as a valid personal, member-category agent.
    rec = _agents.load_agent(p)
    assert rec.freeze == "personal" and rec.category == "member"
    assert rec.required_tools == ("Read", "Bash")
    assert parse_file(p).meta.get("model") == "fable"


def test_create_wizard_fields_persist(env):
    """The richer DEFINE wizard (#84 item 2): optional fields land in a valid,
    commons-shaped MD, and only name+role are required."""
    p = pa.create_personal_agent(
        "wiz_agent", "Prepares docking inputs.",
        model="sonnet", tools=["Read", "Bash"], denied_tools=["WebFetch"],
        responsibilities=["fetch structures", "clean geometry"],
        non_goals="Does not run the docking itself — hands that to the blacksmith.",
        persona="Terse and exacting.",
        output_format="Markdown tables.",
        guardrails="Never write outside outputs/.",
        example="Request: prep 4HHB → Response: cleaned PDB + report.",
        verdict="Prepared / Skipped / Failed")
    rec = _agents.load_agent(p)
    assert rec.freeze == "personal" and rec.category == "member"
    assert rec.required_tools == ("Read", "Bash")
    assert rec.denied_tools == ("WebFetch",)
    assert rec.description == "Prepares docking inputs."
    text = p.read_text(encoding="utf-8")
    for marker in ("MANDATORY OUTPUT RULE", "Prepared / Skipped / Failed",
                   "## Scope & non-goals", "hands that to the blacksmith",
                   "## Guardrails", "## Example", "Terse and exacting"):
        assert marker in text, marker


def test_create_minimal_still_works(env):
    """Backward-compatible: name + description only, no wizard fields."""
    p = pa.create_personal_agent("bare", "just a role line")
    rec = _agents.load_agent(p)
    assert rec.freeze == "personal"
    text = p.read_text(encoding="utf-8")
    assert "MANDATORY OUTPUT RULE" in text and "## Your responsibilities" in text


def test_create_refusals(env):
    with pytest.raises(pa.PersonalAgentError):        # commons name → should fork
        pa.create_personal_agent("oracle", "x")
    with pytest.raises(pa.PersonalAgentError):        # invalid name
        pa.create_personal_agent("My Helper!", "x")
    with pytest.raises(pa.PersonalAgentError):        # bad model
        pa.create_personal_agent("m2", "x", model="gpt")
    pa.create_personal_agent("dup", "x")
    with pytest.raises(pa.PersonalAgentError):        # already exists
        pa.create_personal_agent("dup", "y")


def test_list_and_remove(env):
    pa.create_personal_agent("a1", "one")
    pa.create_personal_agent("a2", "two")
    assert {p.stem for p in pa.list_personal_agents()} == {"a1", "a2"}
    pa.remove_personal_agent("a1")
    assert {p.stem for p in pa.list_personal_agents()} == {"a2"}
    assert not (env["cc"] / "a1.md").exists()
    with pytest.raises(pa.PersonalAgentError):        # never remove a commons agent
        pa.remove_personal_agent("oracle")


def test_snapshot_surfaces_personal_with_origin(env):
    from murmurent.dashboard import snapshot as snap
    pa.create_personal_agent("my_helper", "mine", model="fable")
    personal = {r.name: r for r in snap._personal_agents()}
    assert "my_helper" in personal
    assert personal["my_helper"].origin == "personal"
    assert personal["my_helper"].model == "fable"


def test_vault_scaffold_includes_agents():
    from murmurent.core import vault_provision as vp
    assert "agents" in vp.VAULT_SUBDIRS


def test_endpoint_creates_and_rejects(env, monkeypatch, tmp_path):
    home = tmp_path / "home"; home.mkdir()
    (home / "user").write_text("bob\n", encoding="utf-8")   # owner, no card → no gate
    monkeypatch.setenv("MURMURENT_HOME", str(home))
    client = TestClient(__import__("murmurent.dashboard.server", fromlist=["create_app"]).create_app())

    r = client.post("/api/agents/new", json={
        "name": "my_helper", "description": "mine", "model": "fable"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert (env["vault_agents"] / "my_helper.md").is_file()
    # A commons-name collision is a 422 (told to fork instead).
    r2 = client.post("/api/agents/new", json={"name": "oracle", "description": "x"})
    assert r2.status_code == 422 and "fork" in r2.json()["detail"].lower()
    # The endpoint accepts + persists the richer DEFINE wizard fields.
    r3 = client.post("/api/agents/new", json={
        "name": "wiz_ep", "description": "prep inputs",
        "non_goals": "does not run the analysis",
        "denied_tools": ["WebFetch"], "verdict": "Prepared / Failed",
        "guardrails": "stay in outputs/"})
    assert r3.status_code == 200, r3.text
    text = (env["vault_agents"] / "wiz_ep.md").read_text(encoding="utf-8")
    assert "does not run the analysis" in text and "Prepared / Failed" in text
