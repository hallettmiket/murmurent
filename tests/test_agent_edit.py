"""MODIFY an existing agent — issue #84 item 3.

Pins the load-bearing invariants of :mod:`core.agent_edit` + its endpoints:
  * a frozen agent and a guardian agent are NOT editable (403 / refusal);
  * an editable commons agent (personal freeze) is fork-on-first-edit — the
    canonical copy lands in the vault-tracked fork home, never the commons;
  * a member's own personal agent is edited in place in the vault;
  * the item-8 save-time integrity check fires on a guardrail-weakening edit.

All state is under tmp_path/monkeypatch — never a real vault or the real commons.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from murmurent.core import agent_edit as ae
from murmurent.core import agents as _agents
from murmurent.core import personal_agents as pa
from murmurent.core import personal_audit as audit

# A tiny commons: a frozen guardian, an editable member agent that withholds a
# (non-egress) tool, and a plain editable member agent.
COMMONS = {
    "security_guard": (
        "---\nname: security_guard\ncategory: member\nfreeze: frozen\n"
        "denied_tools: [WebFetch, WebSearch]\ndescription: guardian\n---\n"
        "# security_guard\nScan for secrets and PHI. Refuse to leak.\n"),
    "blacksmith": (
        "---\nname: blacksmith\ncategory: member\nfreeze: personal\n"
        "required_tools: [Read, Bash]\ndenied_tools: [NotebookEdit]\n"
        "description: the workhorse\n---\n"
        "# blacksmith\n**MANDATORY OUTPUT RULE.** Lead with a verdict.\n"
        "You build and evaluate models.\n"),
    "adversary": (   # guardian by NAME even though it denies nothing
        "---\nname: adversary\ncategory: member\nfreeze: personal\n"
        "description: the skeptic\n---\n# adversary\nAudit methodology.\n"),
}


@pytest.fixture
def world(monkeypatch, tmp_path):
    commons = tmp_path / "repo" / "agents"
    commons.mkdir(parents=True)
    for name, text in COMMONS.items():
        (commons / f"{name}.md").write_text(text, encoding="utf-8")

    cc = tmp_path / "cc" / "agents"
    cc.mkdir(parents=True)
    for name in COMMONS:  # setup.sh leaves commons agents as symlinks
        (cc / f"{name}.md").symlink_to(commons / f"{name}.md")

    forks = tmp_path / "vault" / "agent_forks"
    vagents = tmp_path / "vault" / "agents"

    monkeypatch.setenv("MURMURENT_REPO_ROOT", str(tmp_path / "repo"))
    monkeypatch.setenv("MURMURENT_CC_AGENTS_DIR", str(cc))
    monkeypatch.setenv("MURMURENT_AGENT_FORKS_DIR", str(forks))
    monkeypatch.setenv("MURMURENT_PERSONAL_AGENTS_DIR", str(vagents))
    return {"commons": commons, "cc": cc, "forks": forks, "vagents": vagents}


# --------------------------------------------------------------------------- #
# editability gate
# --------------------------------------------------------------------------- #

def test_frozen_and_guardian_are_not_editable(world):
    frozen = ae.editability("security_guard")
    assert frozen["exists"] and not frozen["editable"] and frozen["frozen"]
    assert "frozen" in frozen["reason"].lower()

    guard = ae.editability("adversary")   # guardian by name, freeze: personal
    assert guard["exists"] and not guard["editable"] and guard["guardian"]
    assert "guardian" in guard["reason"].lower()

    ok = ae.editability("blacksmith")
    assert ok["exists"] and ok["editable"] and ok["origin"] == "commons"


def test_save_refuses_frozen_and_guardian(world):
    with pytest.raises(ae.AgentNotEditableError):
        ae.save_edit("security_guard", role="do less")
    with pytest.raises(ae.AgentNotEditableError):
        ae.save_edit("adversary", role="be nicer")


# --------------------------------------------------------------------------- #
# fork-on-first-edit lands in the vault fork home
# --------------------------------------------------------------------------- #

def test_edit_commons_forks_into_vault(world):
    res = ae.save_edit(
        "blacksmith", role="my tailored workhorse",
        required_tools=["Read", "Bash"], denied_tools=["NotebookEdit"],
        responsibilities=["load data", "train models"])
    assert res["ok"] and res["forked"] is True and res["origin"] == "commons"

    forked = world["forks"] / "blacksmith.md"
    assert forked.is_file()                       # canonical copy in the vault
    assert str(forked) == res["path"]
    # commons file itself untouched
    assert "my tailored workhorse" not in (world["commons"] / "blacksmith.md").read_text()
    # working copy in ~/.claude/agents is now a real (non-symlink) file
    installed = world["cc"] / "blacksmith.md"
    assert installed.is_file() and not installed.is_symlink()
    rec = _agents.load_agent(forked)
    assert rec.description == "my tailored workhorse" and rec.freeze == "personal"

    # a second edit reuses the existing fork (no re-fork)
    res2 = ae.save_edit("blacksmith", role="tweaked again",
                        required_tools=["Read", "Bash"], denied_tools=["NotebookEdit"])
    assert res2["forked"] is False


def test_edit_personal_in_place(world):
    p = pa.create_personal_agent("my_helper", "does my thing")
    res = ae.save_edit("my_helper", role="does my thing better",
                       persona="terse and skeptical")
    assert res["origin"] == "personal" and res["forked"] is False
    assert res["path"] == str(p)
    assert "does my thing better" in p.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# save-time integrity check fires on guardrail weakening
# --------------------------------------------------------------------------- #

def test_integrity_fires_on_guardrail_weakening(world):
    # blacksmith commons denies NotebookEdit; an edit that drops the denial
    # re-enables a withheld tool → a guardrail-weakening finding.
    proposed = pa.build_agent_md(
        "blacksmith", role="workhorse", required_tools=["Read", "Bash"],
        denied_tools=[], freeze="personal")
    findings = audit.assess_agent_edit("blacksmith", proposed)
    rules = {f.rule for f in findings}
    assert "PERSONAL-AGENT-GUARDRAIL-WEAKENED-01" in rules

    # and it surfaces as a warning through save_edit (allowed, not blocked)
    res = ae.save_edit("blacksmith", role="workhorse",
                       required_tools=["Read", "Bash"], denied_tools=[])
    assert res["ok"] is True
    assert any(w["rule"] == "PERSONAL-AGENT-GUARDRAIL-WEAKENED-01"
               for w in res["warnings"])

    # with allow_warn=False the same edit is refused
    with pytest.raises(ae.AgentEditError):
        ae.save_edit("blacksmith", role="workhorse",
                     required_tools=["Read", "Bash"], denied_tools=[],
                     allow_warn=False)


def test_no_findings_on_faithful_edit(world):
    # keeping the commons tool guardrails intact → no weakening finding
    res = ae.save_edit("blacksmith", role="workhorse, tidied",
                       required_tools=["Read", "Bash"], denied_tools=["NotebookEdit"])
    assert not any(w["rule"] == "PERSONAL-AGENT-GUARDRAIL-WEAKENED-01"
                   for w in res["warnings"])


# --------------------------------------------------------------------------- #
# edit_context pre-fill + diff
# --------------------------------------------------------------------------- #

def test_edit_context_prefills_and_diffs(world):
    ctx = ae.edit_context("blacksmith")
    assert ctx["editable"] and ctx["origin"] == "commons"
    assert ctx["fields"]["role"] == "the workhorse"
    assert ctx["fields"]["required_tools"] == ["Read", "Bash"]
    assert ctx["fields"]["denied_tools"] == ["NotebookEdit"]
    assert list(ctx["locked_fields"]) == ["name", "category", "freeze"]
    # frozen agent context still returns, flagged non-editable
    fctx = ae.edit_context("security_guard")
    assert not fctx["editable"] and fctx["frozen"]


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #

@pytest.fixture
def client(world, monkeypatch, tmp_path):
    home = tmp_path / "home"; home.mkdir()
    (home / "user").write_text("bob\n", encoding="utf-8")
    monkeypatch.setenv("MURMURENT_HOME", str(home))
    from murmurent.dashboard import server
    return TestClient(server.create_app())


def test_endpoint_modify_gates_frozen_and_edits(client, world):
    # frozen → 403
    r = client.post("/api/agent_edit/security_guard", json={"role": "less"})
    assert r.status_code == 403 and "frozen" in r.json()["detail"].lower()
    # guardian → 403
    r = client.post("/api/agent_edit/adversary", json={"role": "nicer"})
    assert r.status_code == 403 and "guardian" in r.json()["detail"].lower()
    # editable commons → 200, forked into the vault
    r = client.post("/api/agent_edit/blacksmith", json={
        "role": "tailored", "required_tools": ["Read", "Bash"],
        "denied_tools": ["NotebookEdit"]})
    assert r.status_code == 200, r.text
    assert r.json()["forked"] is True
    assert (world["forks"] / "blacksmith.md").is_file()


def test_endpoint_edit_context(client, world):
    r = client.get("/api/agent_edit/blacksmith")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["editable"] and body["fields"]["role"] == "the workhorse"
