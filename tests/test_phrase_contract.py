"""
Purpose: Unit + CLI tests for the phrase output-contract
         (:mod:`murmurent.core.phrase_contract` and ``murmurent phrase contract``).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: Synthetic contracts + ``click.testing.CliRunner`` invocations.
Output: pytest cases asserting model round-trip, validation, and CLI behaviour.
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.core import phrase_contract as pc


def _valid() -> pc.PhraseContract:
    return pc.PhraseContract(
        phrase="dock_and_filter",
        author="@member_a",
        question="optimize_sulfopin",
        candidate_key="inchikey",
        metric="binding_affinity",
        units="kcal/mol",
        direction="lower_better",
        uncertainty="stderr",
        tags=["docking", "pin1"],
        notes="Docks candidate analogues and filters by predicted energy.",
    )


# -- model round-trip -------------------------------------------------------


def test_valid_contract_has_no_problems() -> None:
    assert _valid().validate() == []
    assert _valid().is_valid()


def test_markdown_round_trip() -> None:
    c = _valid()
    parsed = pc.PhraseContract.from_markdown(c.to_markdown())
    assert parsed == c


def test_to_markdown_has_frontmatter_and_kind() -> None:
    md = _valid().to_markdown()
    assert md.startswith("---\n")
    assert "kind: phrase_contract" in md
    assert "candidate_key: inchikey" in md
    assert "Docks candidate analogues" in md  # body/notes preserved


def test_other_escape_candidate_key_is_valid() -> None:
    c = _valid()
    c.candidate_key = "other:plasmid_id"
    assert c.validate() == []


# -- validation failures ----------------------------------------------------


def test_missing_required_field_flagged() -> None:
    c = _valid()
    c.metric = ""
    problems = c.validate()
    assert any("metric" in p for p in problems)


def test_unknown_direction_flagged() -> None:
    c = _valid()
    c.direction = "sideways"
    assert any("direction" in p for p in c.validate())


def test_unknown_candidate_key_flagged() -> None:
    c = _valid()
    c.candidate_key = "pdb_id"
    assert any("candidate_key" in p for p in c.validate())


def test_empty_other_escape_flagged() -> None:
    c = _valid()
    c.candidate_key = "other:"
    assert any("candidate_key" in p for p in c.validate())


def test_author_without_handle_flagged() -> None:
    c = _valid()
    c.author = "member_a"
    assert any("author" in p for p in c.validate())


def test_from_markdown_without_frontmatter_raises() -> None:
    with pytest.raises(pc.PhraseContractError):
        pc.PhraseContract.from_markdown("no frontmatter here\n")


# -- CLI: new + validate ----------------------------------------------------


def _new_args(**overrides) -> list[str]:
    base = {
        "--phrase": "dock_and_filter",
        "--author": "@member_a",
        "--question": "optimize_sulfopin",
        "--candidate-key": "inchikey",
        "--metric": "binding_affinity",
        "--units": "kcal/mol",
        "--direction": "lower_better",
        "--uncertainty": "stderr",
    }
    base.update(overrides)
    args = ["phrase", "contract", "new"]
    for k, v in base.items():
        args += [k, v]
    return args


def test_cli_new_writes_to_vault_dir(tmp_path, monkeypatch) -> None:
    phrases = tmp_path / "phrases"
    monkeypatch.setenv(pc.ENV_CONTRACT_DIR, str(phrases))
    res = CliRunner().invoke(cli, _new_args())
    assert res.exit_code == 0, res.output
    written = phrases / "dock_and_filter_contract.md"
    assert written.is_file()
    # Round-trips back into a valid contract.
    assert pc.PhraseContract.from_file(written).is_valid()


def test_cli_new_out_path_overrides(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(pc.ENV_CONTRACT_DIR, raising=False)
    dest = tmp_path / "custom" / "c.md"
    res = CliRunner().invoke(cli, _new_args(**{"--out": str(dest)}))
    assert res.exit_code == 0, res.output
    assert dest.is_file()


def test_cli_new_bad_direction_rejected_by_choice(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(pc.ENV_CONTRACT_DIR, str(tmp_path / "phrases"))
    res = CliRunner().invoke(cli, _new_args(**{"--direction": "sideways"}))
    assert res.exit_code != 0
    assert not (tmp_path / "phrases").exists()


def test_cli_validate_ok(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(pc.ENV_CONTRACT_DIR, str(tmp_path / "phrases"))
    CliRunner().invoke(cli, _new_args())
    path = tmp_path / "phrases" / "dock_and_filter_contract.md"
    res = CliRunner().invoke(cli, ["phrase", "contract", "validate", str(path)])
    assert res.exit_code == 0, res.output
    assert "OK" in res.output


def test_cli_validate_reports_problems_nonzero(tmp_path) -> None:
    bad = tmp_path / "bad.md"
    bad.write_text(
        "---\n"
        "kind: phrase_contract\n"
        "phrase: p\n"
        "author: member_a\n"          # no leading @
        "question: q\n"
        "candidate_key: pdb_id\n"      # not in vocab
        "metric: score\n"
        "units: dimensionless\n"
        "direction: sideways\n"        # unknown
        "uncertainty: none\n"
        "tags: []\n"
        "---\n",
        encoding="utf-8",
    )
    res = CliRunner().invoke(cli, ["phrase", "contract", "validate", str(bad)])
    assert res.exit_code != 0
    assert "candidate_key" in res.output
    assert "direction" in res.output
    assert "author" in res.output


def test_cli_validate_missing_file_errors() -> None:
    res = CliRunner().invoke(cli, ["phrase", "contract", "validate", "/no/such/file.md"])
    assert res.exit_code != 0
    assert "no such file" in res.output
