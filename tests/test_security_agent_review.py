r"""
Tests for `core.security_agent_review` — the LLM-driven Phase A.2 path.

All tests use a stub LLM client (no real Anthropic call) so the suite
runs offline and free. Covers:

  - Input gathering (code/secrets/cc collectors) on a fixture repo
  - LLM response parsing (clean JSON, ```json fences, leading prose, malformed)
  - Cache hit short-circuits the second call
  - Per-category invocation routes the right prompt to the LLM
  - Guardrail: the system prompt mentions /data/lab_vm immutability
  - Cost meta arithmetic
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from murmurent.core import security_agent_review as r
from murmurent.core.security_findings import (
    SEVERITY_BLOCK,
    SEVERITY_WARN,
    SOURCE_AGENT,
)


# ---------------------------------------------------------------------------
# Stub LLM
# ---------------------------------------------------------------------------

@dataclass
class StubLLM:
    """Test double: records every prompt + returns a canned response per call."""
    responses: list[r.LLMResponse]
    calls: list[tuple[str, str]] = field(default_factory=list)

    def complete(self, *, prompt: str, system: str = "") -> r.LLMResponse:
        self.calls.append((system, prompt))
        if not self.responses:
            raise RuntimeError("StubLLM exhausted")
        return self.responses.pop(0)


def _resp(findings, tokens_in=120, tokens_out=80) -> r.LLMResponse:
    return r.LLMResponse(
        text=json.dumps({"findings": findings}),
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        model="claude-sonnet-4-6",
    )


# ---------------------------------------------------------------------------
# Fixture project
# ---------------------------------------------------------------------------

@pytest.fixture
def fixture_repo(tmp_path):
    """Build a tiny project tree with: a python file, a tracked .env
    masquerading as a real secret, and a per-project .claude/settings.json
    with one suspicious allowlist entry.
    """
    repo = tmp_path / "demo"
    repo.mkdir()
    (repo / "main.py").write_text(
        'import os\n'
        'API_KEY = "sk-live-FAKE-1234567890abcdef"\n'
        'os.system("rm -rf " + user_input)\n',
        encoding="utf-8",
    )
    (repo / "lib.py").write_text("def add(a, b): return a + b\n", encoding="utf-8")
    (repo / ".env").write_text("API_KEY=actually-leaked\n", encoding="utf-8")
    (repo / "harmless.txt").write_text("not source", encoding="utf-8")

    cc = repo / ".claude"
    cc.mkdir()
    (cc / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(sudo *)", "Bash(*)"]},
    }), encoding="utf-8")

    # Initialize a git repo so _collect_tracked_files works.
    import subprocess
    for cmd in (
        ["git", "init"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "."],
        ["git", "commit", "-m", "init"],
    ):
        subprocess.run(cmd, cwd=repo, check=True, capture_output=True)
    return repo


# ---------------------------------------------------------------------------
# Input gatherers
# ---------------------------------------------------------------------------

def test_collect_code_files_picks_source_only(fixture_repo):
    files = r._collect_code_files(fixture_repo)
    paths = [p for p, _ in files]
    assert "main.py" in paths
    assert "lib.py" in paths
    # Non-source files are dropped.
    assert all(not p.endswith(".txt") for p in paths)
    assert all(not p.endswith(".env") for p in paths)


def test_collect_code_files_skips_skip_dirs(tmp_path):
    repo = tmp_path / "p"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "junk.py").write_text("x=1\n")
    (repo / "node_modules" / "n").mkdir(parents=True)
    (repo / "node_modules" / "n" / "junk.py").write_text("x=1\n")
    (repo / "src").mkdir()
    (repo / "src" / "ok.py").write_text("y=2\n")
    files = r._collect_code_files(repo)
    assert [p for p, _ in files] == ["src/ok.py"]


def test_collect_tracked_files(fixture_repo):
    tracked = r._collect_tracked_files(fixture_repo)
    assert ".env" in tracked
    assert "main.py" in tracked
    assert ".claude/settings.json" in tracked


def test_collect_suspicious_matches_flags_dot_env(fixture_repo):
    tracked = r._collect_tracked_files(fixture_repo)
    matches = r._collect_suspicious_matches(fixture_repo, tracked)
    paths = [m["path"] for m in matches]
    assert ".env" in paths


def test_collect_cc_settings_finds_project_file(fixture_repo, monkeypatch, tmp_path):
    # Point HOME at a tmp dir so the global lookup is null.
    monkeypatch.setenv("HOME", str(tmp_path / "fake_home"))
    g, p = r._collect_cc_settings(fixture_repo)
    assert g is None
    assert p is not None
    assert "permissions" in p


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------

def test_parse_response_clean_json():
    text = json.dumps({"findings": [
        {"rule": "CODE-HARDCODED-CRED-01", "severity": "block",
         "path": "main.py", "current_state": "API_KEY = '...'",
         "suggested_fix": "load from env", "notes": "live SK"},
    ]})
    out = r._parse_response(text, host="local", project="demo",
                            category="code", model="claude-sonnet-4-6")
    assert len(out) == 1
    assert out[0].severity == SEVERITY_BLOCK
    assert out[0].rule == "CODE-HARDCODED-CRED-01"
    assert out[0].source == SOURCE_AGENT
    assert out[0].project == "demo"
    assert "model=claude-sonnet-4-6" in out[0].notes


def test_parse_response_strips_markdown_fences():
    text = "```json\n" + json.dumps({"findings": [
        {"rule": "CODE-SQLI-01", "severity": "warn", "path": "q.py",
         "current_state": "raw string concat", "suggested_fix": "parameterise"},
    ]}) + "\n```"
    out = r._parse_response(text, host="h", project="p", category="code", model="m")
    assert len(out) == 1
    assert out[0].severity == SEVERITY_WARN


def test_parse_response_tolerates_leading_prose():
    text = "Here are my findings:\n" + json.dumps({"findings": [
        {"rule": "X-1", "severity": "info", "path": "x.py",
         "current_state": "", "suggested_fix": ""}
    ]})
    out = r._parse_response(text, host="h", project="p", category="code", model="m")
    assert len(out) == 1


def test_parse_response_returns_empty_on_garbage():
    assert r._parse_response("not json at all", host="h", project="p",
                              category="code", model="m") == []


def test_parse_response_coerces_bad_severity_to_info():
    text = json.dumps({"findings": [
        {"rule": "X", "severity": "critical", "path": "y.py",
         "current_state": "", "suggested_fix": ""}
    ]})
    out = r._parse_response(text, host="h", project="p", category="code", model="m")
    assert out[0].severity == "info"


# ---------------------------------------------------------------------------
# Orchestration + caching
# ---------------------------------------------------------------------------

def test_review_project_runs_all_three_categories(fixture_repo, tmp_path):
    stub = StubLLM(responses=[
        _resp([{"rule": "CODE-CMD-INJECTION-01", "severity": "block",
                "path": "main.py", "current_state": "os.system",
                "suggested_fix": "use subprocess.run with list"}]),
        _resp([{"rule": "SECRETS-GIT-TRACKED-01", "severity": "block",
                "path": ".env", "current_state": "tracked",
                "suggested_fix": "git rm --cached + .gitignore"}]),
        _resp([{"rule": "CC-SETTINGS-PERMISSIVE-01", "severity": "warn",
                "path": ".claude/settings.json",
                "current_state": "Bash(sudo *)",
                "suggested_fix": "remove unrestricted Bash allow"}]),
    ])
    res = r.review_project(
        fixture_repo, host="local",
        categories=("code", "secrets", "cc"),
        client=stub, cache_dir=tmp_path / "cache",
    )
    assert len(stub.calls) == 3
    assert len(res.findings) == 3
    rules = {f.rule for f in res.findings}
    assert rules == {"CODE-CMD-INJECTION-01",
                     "SECRETS-GIT-TRACKED-01",
                     "CC-SETTINGS-PERMISSIVE-01"}
    assert res.meta.cache_misses == 3
    assert res.meta.cache_hits == 0
    assert res.meta.input_tokens == 360
    assert res.meta.output_tokens == 240
    assert res.meta.model == "claude-sonnet-4-6"


def test_review_project_cache_hit_short_circuits(fixture_repo, tmp_path):
    cache_dir = tmp_path / "cache"
    first_stub = StubLLM(responses=[
        _resp([{"rule": "CODE-1", "severity": "info", "path": "x",
                "current_state": "", "suggested_fix": ""}]),
    ])
    r.review_project(fixture_repo, host="h",
                     categories=("code",), client=first_stub, cache_dir=cache_dir)
    assert len(first_stub.calls) == 1
    # Second run with the same inputs must NOT call the LLM.
    second_stub = StubLLM(responses=[])
    res = r.review_project(fixture_repo, host="h",
                           categories=("code",), client=second_stub, cache_dir=cache_dir)
    assert len(second_stub.calls) == 0
    assert res.meta.cache_hits == 1
    assert res.meta.cache_misses == 0
    assert len(res.findings) == 1


def test_review_project_cache_misses_on_changed_file(fixture_repo, tmp_path):
    cache_dir = tmp_path / "cache"
    first_stub = StubLLM(responses=[_resp([])])
    r.review_project(fixture_repo, host="h",
                     categories=("code",), client=first_stub, cache_dir=cache_dir)
    # Modify a tracked source file -> hash changes -> cache miss.
    (fixture_repo / "main.py").write_text("# changed\n", encoding="utf-8")
    second_stub = StubLLM(responses=[_resp([])])
    res = r.review_project(fixture_repo, host="h",
                           categories=("code",), client=second_stub, cache_dir=cache_dir)
    assert len(second_stub.calls) == 1
    assert res.meta.cache_misses == 1


def test_unknown_category_is_dropped_silently(fixture_repo, tmp_path):
    stub = StubLLM(responses=[])
    res = r.review_project(fixture_repo, host="h",
                           categories=("nonsense",),
                           client=stub, cache_dir=tmp_path / "cache")
    assert res.findings == []
    assert stub.calls == []


def test_per_category_prompt_routing(fixture_repo, tmp_path):
    """Confirm each category sends a recognisably-tagged user prompt."""
    stub = StubLLM(responses=[_resp([]), _resp([]), _resp([])])
    r.review_project(fixture_repo, host="h",
                     categories=("code", "secrets", "cc"),
                     client=stub, cache_dir=tmp_path / "c")
    sys_prompts, user_prompts = zip(*stub.calls)
    # All three calls share the same system prompt.
    assert len(set(sys_prompts)) == 1
    assert "murmurent `security_guard` agent" in sys_prompts[0]
    # Each user prompt carries its category label.
    assert any("Category: code" in p for p in user_prompts)
    assert any("Category: secrets" in p for p in user_prompts)
    assert any("Category: cc" in p for p in user_prompts)


def test_guardrail_in_system_prompt():
    """Defence in depth: the system prompt must forbid raw/refined writes."""
    sp = r._SYSTEM_PROMPT
    assert "/data/lab_vm/raw/" in sp
    assert "/data/lab_vm/refined/" in sp
    assert "Never propose" in sp or "never propose" in sp.lower()


def test_cost_meta_arithmetic():
    m = r.AgentReviewMeta(input_tokens=1_000_000, output_tokens=500_000)
    # 1M in * $3 + 0.5M out * $15 = 3 + 7.5 = 10.5
    assert abs(m.cost_estimate_usd() - 10.5) < 1e-9
