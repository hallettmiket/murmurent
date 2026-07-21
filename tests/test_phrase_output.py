"""
Purpose: Unit tests for the phrase output-table validator
         (:mod:`murmurent.core.phrase_output`) and the ``PhraseSpec.output``
         extension that validates a produced output when present.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: Synthetic contracts + hand-written CSV/TSV result tables in ``tmp_path``.
Output: pytest cases asserting a conforming table validates clean and each
        non-conforming case (missing columns, empty, non-numeric metric, blank
        key, missing uncertainty, bad format, missing file) is flagged.
"""

from __future__ import annotations

from pathlib import Path

from murmurent.core import phrase_contract as pc
from murmurent.core import phrase_output as po
from murmurent.core import phrase_spec as ps


def _contract(*, uncertainty: str = "stderr") -> pc.PhraseContract:
    return pc.PhraseContract(
        phrase="dock_and_filter",
        author="@member_a",
        question="optimize_sulfopin",
        candidate_key="inchikey",
        metric="binding_affinity",
        units="kcal/mol",
        direction="lower_better",
        uncertainty=uncertainty,
    )


def _write_csv(path: Path, header: str, *rows: str) -> Path:
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


_GOOD_HEADER = "inchikey,binding_affinity,uncertainty"
_GOOD_ROWS = ("AAA-1,-9.2,0.3", "BBB-2,-8.1,0.4")


# -- conforming -------------------------------------------------------------


def test_conforming_csv_validates_clean(tmp_path) -> None:
    out = _write_csv(tmp_path / "out.csv", _GOOD_HEADER, *_GOOD_ROWS)
    assert po.validate_output(_contract(), out) == []


def test_conforming_tsv_validates_clean(tmp_path) -> None:
    out = tmp_path / "out.tsv"
    out.write_text(
        "inchikey\tbinding_affinity\tuncertainty\nAAA-1\t-9.2\t0.3\n",
        encoding="utf-8",
    )
    assert po.validate_output(_contract(), out) == []


def test_uncertainty_column_named_after_kind_accepted(tmp_path) -> None:
    # Column named 'stderr' (the estimate kind) instead of the canonical name.
    out = _write_csv(
        tmp_path / "out.csv", "inchikey,binding_affinity,stderr", "AAA-1,-9.2,0.3"
    )
    assert po.validate_output(_contract(uncertainty="stderr"), out) == []


def test_no_uncertainty_column_needed_when_contract_says_none(tmp_path) -> None:
    out = _write_csv(
        tmp_path / "out.csv", "inchikey,binding_affinity", "AAA-1,-9.2"
    )
    assert po.validate_output(_contract(uncertainty="none"), out) == []


# -- non-conforming ---------------------------------------------------------


def test_missing_file_flagged(tmp_path) -> None:
    problems = po.validate_output(_contract(), tmp_path / "nope.csv")
    assert any("not found" in p for p in problems)


def test_empty_table_flagged(tmp_path) -> None:
    out = _write_csv(tmp_path / "out.csv", _GOOD_HEADER)  # header only
    problems = po.validate_output(_contract(), out)
    assert any("empty" in p for p in problems)


def test_missing_candidate_key_column_flagged(tmp_path) -> None:
    out = _write_csv(
        tmp_path / "out.csv", "smiles,binding_affinity,uncertainty", "CCO,-9.2,0.3"
    )
    problems = po.validate_output(_contract(), out)
    assert any("candidate-key column 'inchikey'" in p for p in problems)


def test_missing_metric_column_flagged(tmp_path) -> None:
    out = _write_csv(
        tmp_path / "out.csv", "inchikey,score,uncertainty", "AAA-1,-9.2,0.3"
    )
    problems = po.validate_output(_contract(), out)
    assert any("metric column 'binding_affinity'" in p for p in problems)


def test_missing_uncertainty_column_flagged(tmp_path) -> None:
    out = _write_csv(
        tmp_path / "out.csv", "inchikey,binding_affinity", "AAA-1,-9.2"
    )
    problems = po.validate_output(_contract(uncertainty="stderr"), out)
    assert any("uncertainty column" in p for p in problems)


def test_non_numeric_metric_flagged(tmp_path) -> None:
    out = _write_csv(
        tmp_path / "out.csv", _GOOD_HEADER, "AAA-1,-9.2,0.3", "BBB-2,strong,0.4"
    )
    problems = po.validate_output(_contract(), out)
    assert any("non-numeric" in p and "2" in p for p in problems)


def test_blank_candidate_key_flagged(tmp_path) -> None:
    out = _write_csv(
        tmp_path / "out.csv", _GOOD_HEADER, "AAA-1,-9.2,0.3", ",-8.1,0.4"
    )
    problems = po.validate_output(_contract(), out)
    assert any("blank" in p for p in problems)


def test_empty_metric_cell_flagged(tmp_path) -> None:
    out = _write_csv(
        tmp_path / "out.csv", _GOOD_HEADER, "AAA-1,,0.3"
    )
    problems = po.validate_output(_contract(), out)
    assert any("empty" in p and "binding_affinity" in p for p in problems)


def test_unsupported_format_flagged(tmp_path) -> None:
    out = tmp_path / "out.xlsx"
    out.write_bytes(b"not really xlsx")
    problems = po.validate_output(_contract(), out)
    assert any("unsupported output format" in p for p in problems)


# -- PhraseSpec.output integration ------------------------------------------


def _write_contract(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / pc.default_contract_filename("dock_and_filter")).write_text(
        _contract().to_markdown(), encoding="utf-8"
    )


def _spec(output: str = "") -> ps.PhraseSpec:
    return ps.PhraseSpec(
        phrase="dock_and_filter",
        author="@member_a",
        question="optimize_sulfopin",
        contract="dock_and_filter",
        steps=[ps.Step("dock", "script", "vina")],
        output=output,
    )


def test_spec_without_output_is_valid_and_omits_key(tmp_path) -> None:
    _write_contract(tmp_path)
    s = _spec()
    assert s.validate(base_dir=tmp_path) == []
    assert "output:" not in s.to_markdown()


def test_spec_output_round_trips_when_set() -> None:
    s = _spec(output="out.csv")
    assert "output: out.csv" in s.to_markdown()
    assert ps.PhraseSpec.from_markdown(s.to_markdown()) == s


def test_spec_with_conforming_output_validates(tmp_path) -> None:
    _write_contract(tmp_path)
    _write_csv(tmp_path / "out.csv", _GOOD_HEADER, *_GOOD_ROWS)
    assert _spec(output="out.csv").validate(base_dir=tmp_path) == []


def test_spec_with_nonconforming_output_flagged(tmp_path) -> None:
    _write_contract(tmp_path)
    _write_csv(tmp_path / "out.csv", "smiles,binding_affinity,uncertainty", "CCO,-9,0.3")
    problems = _spec(output="out.csv").validate(base_dir=tmp_path)
    assert any("output out.csv" in p and "candidate-key" in p for p in problems)


def test_spec_with_missing_output_file_flagged(tmp_path) -> None:
    _write_contract(tmp_path)
    problems = _spec(output="ghost.csv").validate(base_dir=tmp_path)
    assert any("could not be resolved" in p for p in problems)
