"""
Purpose: Unit + CLI tests for the phrase spec — the authored phrase
         (:mod:`murmurent.core.phrase_spec` and ``murmurent phrase spec``).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: Synthetic specs/contracts + ``click.testing.CliRunner`` invocations.
Output: pytest cases asserting model round-trip, each validation failure, the
        referenced-contract resolution, and CLI ``new``/``validate`` behaviour.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.core import phrase_contract as pc
from murmurent.core import phrase_spec as ps


def _write_contract(directory: Path, *, key: str = "inchikey") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    contract = pc.PhraseContract(
        phrase="dock_and_filter",
        author="@member_a",
        question="optimize_sulfopin",
        candidate_key=key,
        metric="binding_affinity",
        units="kcal/mol",
        direction="lower_better",
        uncertainty="stderr",
    )
    path = directory / pc.default_contract_filename("dock_and_filter")
    path.write_text(contract.to_markdown(), encoding="utf-8")
    return path


def _spec(contract_ref: str = "dock_and_filter") -> ps.PhraseSpec:
    return ps.PhraseSpec(
        phrase="dock_and_filter",
        author="@member_a",
        question="optimize_sulfopin",
        contract=contract_ref,
        steps=[
            ps.Step("dock", "script", "vina --receptor pin1", "dock analogues"),
            ps.Step("shortlist", "agent", "blacksmith", "score + shortlist"),
        ],
        transitions=[ps.Transition("top100", "rank", {"top": 100})],
        notes="Docks candidate analogues and filters by predicted energy.",
    )


# -- model round-trip -------------------------------------------------------


def test_markdown_round_trip() -> None:
    s = _spec()
    parsed = ps.PhraseSpec.from_markdown(s.to_markdown())
    assert parsed == s


def test_to_markdown_has_frontmatter_and_kind() -> None:
    md = _spec().to_markdown()
    assert md.startswith("---\n")
    assert "kind: phrase_spec" in md
    assert "Docks candidate analogues" in md  # body/notes preserved


def test_steps_and_transitions_survive_round_trip() -> None:
    parsed = ps.PhraseSpec.from_markdown(_spec().to_markdown())
    assert [st.name for st in parsed.steps] == ["dock", "shortlist"]
    assert parsed.transitions[0].params == {"top": 100}


# -- validation (with a real, resolvable contract) --------------------------


def test_valid_spec_has_no_problems(tmp_path) -> None:
    _write_contract(tmp_path)
    assert _spec().validate(base_dir=tmp_path) == []
    assert _spec().is_valid(base_dir=tmp_path)


def test_missing_required_field_flagged(tmp_path) -> None:
    _write_contract(tmp_path)
    s = _spec()
    s.question = ""
    assert any("question" in p for p in s.validate(base_dir=tmp_path))


def test_author_without_handle_flagged(tmp_path) -> None:
    _write_contract(tmp_path)
    s = _spec()
    s.author = "member_a"
    assert any("author" in p for p in s.validate(base_dir=tmp_path))


def test_empty_steps_flagged(tmp_path) -> None:
    _write_contract(tmp_path)
    s = _spec()
    s.steps = []
    assert any("steps" in p for p in s.validate(base_dir=tmp_path))


def test_bad_step_kind_flagged(tmp_path) -> None:
    _write_contract(tmp_path)
    s = _spec()
    s.steps[0].kind = "wetlab"
    assert any("step" in p and "kind" in p for p in s.validate(base_dir=tmp_path))


def test_step_missing_run_flagged(tmp_path) -> None:
    _write_contract(tmp_path)
    s = _spec()
    s.steps[0].run = ""
    assert any("run" in p for p in s.validate(base_dir=tmp_path))


def test_bad_transition_kind_flagged(tmp_path) -> None:
    _write_contract(tmp_path)
    s = _spec()
    s.transitions[0].kind = "sort"
    assert any("transition" in p and "kind" in p for p in s.validate(base_dir=tmp_path))


def test_unresolvable_contract_flagged(tmp_path) -> None:
    # No contract on disk → resolution fails.
    s = _spec(contract_ref="nope")
    assert any("contract" in p for p in s.validate(base_dir=tmp_path))


def test_invalid_referenced_contract_bubbles_up(tmp_path) -> None:
    # A contract that exists but is itself invalid (bad candidate_key).
    bad = tmp_path / "dock_and_filter_contract.md"
    bad.write_text(
        "---\nkind: phrase_contract\nphrase: p\nauthor: '@a'\nquestion: q\n"
        "candidate_key: pdb_id\nmetric: m\nunits: u\ndirection: higher_better\n"
        "uncertainty: none\ntags: []\n---\n",
        encoding="utf-8",
    )
    problems = _spec().validate(base_dir=tmp_path)
    assert any("candidate_key" in p for p in problems)


def test_from_markdown_without_frontmatter_raises() -> None:
    with pytest.raises(ps.PhraseSpecError):
        ps.PhraseSpec.from_markdown("no frontmatter here\n")


def test_from_file_records_source_for_resolution(tmp_path) -> None:
    _write_contract(tmp_path)
    spec_path = tmp_path / "dock_and_filter_phrase.md"
    spec_path.write_text(_spec().to_markdown(), encoding="utf-8")
    loaded = ps.PhraseSpec.from_file(spec_path)
    # No explicit base_dir: resolution uses the file's own directory.
    assert loaded.validate() == []


# -- CLI: new + validate ----------------------------------------------------


def _new_args(**overrides) -> list[str]:
    base = {
        "--phrase": "dock_and_filter",
        "--author": "@member_a",
        "--question": "optimize_sulfopin",
        "--contract": "dock_and_filter",
    }
    base.update(overrides)
    args = ["phrase", "spec", "new"]
    for k, v in base.items():
        args += [k, v]
    args += ["--step", "dock:script:vina --receptor pin1"]
    args += ["--step", "shortlist:agent:blacksmith"]
    args += ["--transition", "top100:rank"]
    return args


def test_cli_new_writes_and_round_trips(tmp_path, monkeypatch) -> None:
    _write_contract(tmp_path / "phrases")
    monkeypatch.setenv(ps.ENV_SPEC_DIR, str(tmp_path / "phrases"))
    res = CliRunner().invoke(cli, _new_args())
    assert res.exit_code == 0, res.output
    written = tmp_path / "phrases" / "dock_and_filter_phrase.md"
    assert written.is_file()
    assert ps.PhraseSpec.from_file(written).is_valid()


def test_cli_new_refuses_invalid(tmp_path, monkeypatch) -> None:
    # Contract reference does not resolve → refuse to write.
    monkeypatch.setenv(ps.ENV_SPEC_DIR, str(tmp_path / "phrases"))
    res = CliRunner().invoke(cli, _new_args(**{"--contract": "missing"}))
    assert res.exit_code != 0
    assert not (tmp_path / "phrases" / "dock_and_filter_phrase.md").exists()


def test_cli_new_bad_step_rejected(tmp_path, monkeypatch) -> None:
    _write_contract(tmp_path / "phrases")
    monkeypatch.setenv(ps.ENV_SPEC_DIR, str(tmp_path / "phrases"))
    args = ["phrase", "spec", "new", "--phrase", "p", "--author", "@a",
            "--question", "q", "--contract", "dock_and_filter",
            "--step", "onlyname"]  # malformed
    res = CliRunner().invoke(cli, args)
    assert res.exit_code != 0


def test_cli_validate_ok(tmp_path, monkeypatch) -> None:
    _write_contract(tmp_path / "phrases")
    monkeypatch.setenv(ps.ENV_SPEC_DIR, str(tmp_path / "phrases"))
    CliRunner().invoke(cli, _new_args())
    path = tmp_path / "phrases" / "dock_and_filter_phrase.md"
    res = CliRunner().invoke(cli, ["phrase", "spec", "validate", str(path)])
    assert res.exit_code == 0, res.output
    assert "OK" in res.output


def test_cli_validate_reports_problems_nonzero(tmp_path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text(
        "---\nkind: phrase_spec\nphrase: p\nauthor: member_a\nquestion: q\n"
        "contract: nope\nsteps: []\ntransitions: []\n---\n",
        encoding="utf-8",
    )
    res = CliRunner().invoke(cli, ["phrase", "spec", "validate", str(bad)])
    assert res.exit_code != 0
    assert "author" in res.output
    assert "steps" in res.output


def test_cli_validate_missing_file_errors() -> None:
    res = CliRunner().invoke(cli, ["phrase", "spec", "validate", "/no/such/file.md"])
    assert res.exit_code != 0
    assert "no such file" in res.output
