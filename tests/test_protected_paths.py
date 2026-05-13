"""Tests for :mod:`wigamig.hooks.protected_paths` — the refined/notebook
write-once guard.

Contract this hook must enforce:
  - Write to a NEW path under refined/notebook → ALLOW
  - Write to an EXISTING path under refined/notebook → DENY (overwrite)
  - Edit / NotebookEdit on any path under refined/notebook → DENY
  - Bash rm/rmdir/truncate/shred/chmod/chown on protected → DENY
  - Bash mv that removes source FROM protected → DENY
  - Bash mv/cp/rsync whose destination is an EXISTING protected file → DENY
  - Bash `> path` redirect into an EXISTING protected file → DENY
  - Bash `>> path` append to a protected file → DENY (modifies)
  - Reads / Glob / Grep / outside-of-protected calls → ALLOW
  - The production ``/data/lab_vm/refined/`` is protected regardless of env
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from wigamig.hooks import protected_paths as pp


def _run(payload: dict) -> dict:
    """Pipe ``payload`` through the hook and return the parsed decision."""
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    code = pp.main(stdin=stdin, stdout=stdout)
    assert code == 0
    return json.loads(stdout.getvalue())


@pytest.fixture
def refined(monkeypatch, tmp_path):
    """Point WIGAMIG_LAB_VM_ROOT at tmp; create refined/ + a file inside."""
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path))
    monkeypatch.delenv("WIGAMIG_NOTEBOOK_ROOT", raising=False)
    refined_dir = tmp_path / "refined" / "proj" / "exp"
    refined_dir.mkdir(parents=True)
    existing = refined_dir / "results.csv"
    existing.write_text("a,b\n1,2\n", encoding="utf-8")
    return {"root": tmp_path, "refined": refined_dir, "existing": existing}


@pytest.fixture
def notebook(monkeypatch, tmp_path):
    """Pin WIGAMIG_NOTEBOOK_ROOT so the hook protects a known vault."""
    vault = tmp_path / "Obsidian" / "lab-notebook"
    vault.mkdir(parents=True)
    existing = vault / "2026-05-13.md"
    existing.write_text("# notes\n", encoding="utf-8")
    monkeypatch.setenv("WIGAMIG_NOTEBOOK_ROOT", str(vault))
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "novm"))
    return {"vault": vault, "existing": existing}


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------


def test_write_new_file_under_refined_allowed(refined):
    new_file = refined["refined"] / "results_2.csv"
    decision = _run({
        "tool_name": "Write",
        "tool_input": {"file_path": str(new_file)},
    })
    assert decision["decision"] == "allow"


def test_write_existing_file_under_refined_denied(refined):
    decision = _run({
        "tool_name": "Write",
        "tool_input": {"file_path": str(refined["existing"])},
    })
    assert decision["decision"] == "deny"
    assert "overwrite" in decision["reason"].lower()
    assert "versioned" in decision["reason"].lower() or "_2" in decision["reason"]


def test_write_new_file_under_notebook_allowed(notebook):
    new_note = notebook["vault"] / "2026-05-14.md"
    decision = _run({
        "tool_name": "Write",
        "tool_input": {"file_path": str(new_note)},
    })
    assert decision["decision"] == "allow"


def test_write_existing_notebook_denied(notebook):
    decision = _run({
        "tool_name": "Write",
        "tool_input": {"file_path": str(notebook["existing"])},
    })
    assert decision["decision"] == "deny"


def test_write_outside_protected_allowed(refined, tmp_path):
    decision = _run({
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "outside.txt")},
    })
    assert decision["decision"] == "allow"


# ---------------------------------------------------------------------------
# Edit / NotebookEdit
# ---------------------------------------------------------------------------


def test_edit_on_refined_always_denied(refined):
    decision = _run({
        "tool_name": "Edit",
        "tool_input": {"file_path": str(refined["existing"])},
    })
    assert decision["decision"] == "deny"


def test_edit_outside_protected_allowed(refined, tmp_path):
    decision = _run({
        "tool_name": "Edit",
        "tool_input": {"file_path": str(tmp_path / "code.py")},
    })
    assert decision["decision"] == "allow"


def test_notebook_edit_on_protected_denied(notebook):
    decision = _run({
        "tool_name": "NotebookEdit",
        "tool_input": {"notebook_path": str(notebook["existing"])},
    })
    assert decision["decision"] == "deny"
    assert "notebook" in decision["reason"].lower()


# ---------------------------------------------------------------------------
# Bash — destructive commands
# ---------------------------------------------------------------------------


def test_bash_rm_on_protected_denied(refined):
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"rm {refined['existing']}"},
    })
    assert decision["decision"] == "deny"
    assert "rm" in decision["reason"]


def test_bash_rmdir_on_protected_denied(refined):
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"rmdir {refined['refined']}"},
    })
    assert decision["decision"] == "deny"


def test_bash_chmod_on_protected_denied(refined):
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"chmod -R u+w {refined['existing']}"},
    })
    assert decision["decision"] == "deny"


def test_bash_truncate_on_protected_denied(refined):
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"truncate -s 0 {refined['existing']}"},
    })
    assert decision["decision"] == "deny"


# ---------------------------------------------------------------------------
# Bash — mv
# ---------------------------------------------------------------------------


def test_bash_mv_from_protected_denied(refined, tmp_path):
    """Moving a file OUT of refined effectively deletes it from refined."""
    elsewhere = tmp_path / "elsewhere.csv"
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"mv {refined['existing']} {elsewhere}"},
    })
    assert decision["decision"] == "deny"
    assert "remove" in decision["reason"].lower() or "protected" in decision["reason"].lower()


def test_bash_mv_to_existing_protected_denied(refined, tmp_path):
    src = tmp_path / "src.csv"
    src.write_text("x", encoding="utf-8")
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"mv {src} {refined['existing']}"},
    })
    assert decision["decision"] == "deny"
    assert "overwrite" in decision["reason"].lower()


def test_bash_mv_to_new_protected_allowed(refined, tmp_path):
    """Moving INTO a protected dir at a brand-new path is allowed."""
    src = tmp_path / "src.csv"
    src.write_text("x", encoding="utf-8")
    dest = refined["refined"] / "results_new.csv"
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"mv {src} {dest}"},
    })
    assert decision["decision"] == "allow"


# ---------------------------------------------------------------------------
# Bash — cp / rsync
# ---------------------------------------------------------------------------


def test_bash_cp_to_existing_protected_denied(refined, tmp_path):
    src = tmp_path / "src.csv"
    src.write_text("x", encoding="utf-8")
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"cp {src} {refined['existing']}"},
    })
    assert decision["decision"] == "deny"


def test_bash_cp_to_new_protected_allowed(refined, tmp_path):
    src = tmp_path / "src.csv"
    src.write_text("x", encoding="utf-8")
    dest = refined["refined"] / "fresh.csv"
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"cp {src} {dest}"},
    })
    assert decision["decision"] == "allow"


def test_bash_rsync_overwrite_protected_denied(refined, tmp_path):
    src = tmp_path / "src.csv"
    src.write_text("x", encoding="utf-8")
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"rsync -av {src} {refined['existing']}"},
    })
    assert decision["decision"] == "deny"


# ---------------------------------------------------------------------------
# Bash — shell redirects
# ---------------------------------------------------------------------------


def test_bash_redirect_overwrite_protected_denied(refined):
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"echo broken > {refined['existing']}"},
    })
    assert decision["decision"] == "deny"


def test_bash_redirect_new_file_allowed(refined):
    new_file = refined["refined"] / "log.txt"
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"echo first > {new_file}"},
    })
    assert decision["decision"] == "allow"


def test_bash_append_to_protected_denied(refined):
    """`>>` appends to (and thus modifies) an existing protected file."""
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"echo extra >> {refined['existing']}"},
    })
    assert decision["decision"] == "deny"


def test_bash_append_to_new_file_allowed(refined):
    """`>>` to a NEW file is fine — same as Write of a new file."""
    new_file = refined["refined"] / "log.txt"
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"echo first >> {new_file}"},
    })
    assert decision["decision"] == "allow"


def test_bash_tee_pipe_to_existing_protected_denied(refined):
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"echo hi | tee {refined['existing']}"},
    })
    assert decision["decision"] == "deny"


# ---------------------------------------------------------------------------
# mkdir / read / outside
# ---------------------------------------------------------------------------


def test_bash_mkdir_under_protected_allowed(refined):
    """The lab convention is mkdir-as-needed for experiment folders."""
    new_dir = refined["refined"].parent / "new_exp"
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"mkdir -p {new_dir}"},
    })
    assert decision["decision"] == "allow"


def test_bash_read_only_command_allowed(refined):
    decision = _run({
        "tool_name": "Bash",
        "tool_input": {"command": f"cat {refined['existing']}"},
    })
    assert decision["decision"] == "allow"


def test_read_tool_on_protected_allowed(refined):
    decision = _run({
        "tool_name": "Read",
        "tool_input": {"file_path": str(refined["existing"])},
    })
    assert decision["decision"] == "allow"


def test_glob_on_protected_allowed(refined):
    decision = _run({
        "tool_name": "Glob",
        "tool_input": {"pattern": str(refined["refined"] / "*.csv")},
    })
    assert decision["decision"] == "allow"


# ---------------------------------------------------------------------------
# Production root protected regardless of env
# ---------------------------------------------------------------------------


def test_production_refined_blocked_even_with_env(monkeypatch, tmp_path):
    """A Write to /data/lab_vm/refined/<existing>/ would deny IF that file
    actually exists. The path can't reliably exist on a CI box, so we
    instead verify that the lexical protection is in place (Write to a
    well-known production subpath that has no special status today still
    routes through this hook; only the existence check stops the deny)."""
    monkeypatch.setenv("WIGAMIG_LAB_VM_ROOT", str(tmp_path / "alt"))
    monkeypatch.delenv("WIGAMIG_NOTEBOOK_ROOT", raising=False)
    prefixes = pp._refined_prefixes()
    assert "/data/lab_vm/refined" in prefixes  # always present


# ---------------------------------------------------------------------------
# Empty / malformed input
# ---------------------------------------------------------------------------


def test_empty_stdin_allows():
    stdout = io.StringIO()
    pp.main(stdin=io.StringIO(""), stdout=stdout)
    assert json.loads(stdout.getvalue())["decision"] == "allow"


def test_malformed_json_allows_with_warning():
    stdout = io.StringIO()
    pp.main(stdin=io.StringIO("not json"), stdout=stdout)
    body = json.loads(stdout.getvalue())
    assert body["decision"] == "allow"
    assert "parse error" in body["warning"].lower()


# ---------------------------------------------------------------------------
# Install registration
# ---------------------------------------------------------------------------


def test_hook_is_registered_in_install_cmd():
    """The new hook must be in HOOK_REGISTRATIONS so `wigamig install --hooks`
    wires it into ~/.claude/settings.json."""
    from wigamig.commands.install_cmd import HOOK_REGISTRATIONS
    labels = {h["label"] for h in HOOK_REGISTRATIONS}
    assert "wigamig-protected-paths" in labels
    modules = {h["module"] for h in HOOK_REGISTRATIONS}
    assert "wigamig.hooks.protected_paths" in modules
