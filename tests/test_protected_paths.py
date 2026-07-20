"""Tests for :mod:`murmurent.hooks.protected_paths` — the refined/notebook
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
  - Both the new ``append_only/`` and legacy ``refined/`` sub-dirs of the
    configured data root are protected (dual-name transition)
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from murmurent.hooks import protected_paths as pp


def _run(payload: dict) -> dict:
    """Pipe ``payload`` through the hook and return a normalised
    decision dict in the legacy ``{"decision": ..., "reason": ...}``
    shape (see test_raw_guard._run for the rationale)."""
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    code = pp.main(stdin=stdin, stdout=stdout)
    assert code == 0
    raw = stdout.getvalue().strip()
    if not raw:
        return {"decision": "allow"}
    data = json.loads(raw)
    hso = data.get("hookSpecificOutput") or {}
    if hso.get("permissionDecision") == "deny":
        return {"decision": "deny",
                "reason": hso.get("permissionDecisionReason", "")}
    return data


@pytest.fixture
def refined(monkeypatch, tmp_path):
    """Point MURMURENT_LAB_VM_ROOT at tmp; create refined/ + a file inside."""
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path))
    monkeypatch.delenv("MURMURENT_NOTEBOOK_ROOT", raising=False)
    refined_dir = tmp_path / "refined" / "proj" / "exp"
    refined_dir.mkdir(parents=True)
    existing = refined_dir / "results.csv"
    existing.write_text("a,b\n1,2\n", encoding="utf-8")
    return {"root": tmp_path, "refined": refined_dir, "existing": existing}


@pytest.fixture
def notebook(monkeypatch, tmp_path):
    """Pin MURMURENT_NOTEBOOK_ROOT so the hook protects a known vault."""
    vault = tmp_path / "Obsidian" / "lab-notebook"
    vault.mkdir(parents=True)
    existing = vault / "2026-05-13.md"
    existing.write_text("# notes\n", encoding="utf-8")
    monkeypatch.setenv("MURMURENT_NOTEBOOK_ROOT", str(vault))
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "novm"))
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


def test_prefixes_cover_both_names_and_drop_stale_branding(monkeypatch, tmp_path):
    """Dual-name: both append_only/ and legacy refined/ under the configured
    data root are protected, and the stale ``/data/lab_vm/wigamig/refined``
    branding is gone."""
    monkeypatch.delenv("MURMURENT_DATA_ROOT", raising=False)
    monkeypatch.setenv("MURMURENT_LAB_VM_ROOT", str(tmp_path / "alt"))
    monkeypatch.delenv("MURMURENT_NOTEBOOK_ROOT", raising=False)
    prefixes = pp._refined_prefixes()
    assert str(tmp_path / "alt" / "append_only") in prefixes
    assert str(tmp_path / "alt" / "refined") in prefixes
    assert "/data/lab_vm/wigamig/refined" not in prefixes


def test_append_only_overwrite_denied_new_env(monkeypatch, tmp_path):
    """New append_only/ tree is write-once, resolved via MURMURENT_DATA_ROOT."""
    monkeypatch.delenv("MURMURENT_LAB_VM_ROOT", raising=False)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("MURMURENT_NOTEBOOK_ROOT", raising=False)
    ao_dir = tmp_path / "append_only" / "proj" / "exp"
    ao_dir.mkdir(parents=True)
    existing = ao_dir / "results.csv"
    existing.write_text("a,b\n1,2\n", encoding="utf-8")
    # New file → allow
    assert _run({
        "tool_name": "Write",
        "tool_input": {"file_path": str(ao_dir / "results_2.csv")},
    })["decision"] == "allow"
    # Overwrite existing → deny
    assert _run({
        "tool_name": "Write",
        "tool_input": {"file_path": str(existing)},
    })["decision"] == "deny"


# ---------------------------------------------------------------------------
# Empty / malformed input
# ---------------------------------------------------------------------------


def test_empty_stdin_allows():
    """CC modern protocol: empty stdout == allow."""
    stdout = io.StringIO()
    pp.main(stdin=io.StringIO(""), stdout=stdout)
    assert stdout.getvalue() == ""


def test_malformed_json_allows_silently():
    """Defensive: bad input still means 'no opinion, proceed'."""
    stdout = io.StringIO()
    pp.main(stdin=io.StringIO("not json"), stdout=stdout)
    assert stdout.getvalue() == ""


# ---------------------------------------------------------------------------
# Install registration
# ---------------------------------------------------------------------------


def test_hook_is_registered_in_install_cmd():
    """The new hook must be in HOOK_REGISTRATIONS so `murmurent install --hooks`
    wires it into ~/.claude/settings.json."""
    from murmurent.commands.install_cmd import HOOK_REGISTRATIONS
    labels = {h["label"] for h in HOOK_REGISTRATIONS}
    assert "murmurent-protected-paths" in labels
    # ``module`` is only present on Python-module registrations; the
    # bash-script registrations (e.g. the agent reporter) use
    # ``command`` instead.
    modules = {h["module"] for h in HOOK_REGISTRATIONS if "module" in h}
    assert "murmurent.hooks.protected_paths" in modules
