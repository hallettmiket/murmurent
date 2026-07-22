"""
Purpose: Unit + CLI tests for compositional-choreography *runs*
         (:mod:`murmurent.core.contribution_run` and the ``choreography prepare-run`` /
         ``freeze-run`` subcommands).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: Synthetic choreographies + contributions with produced output tables in
       ``tmp_path`` + ``click.testing.CliRunner``.
Output: pytest cases asserting prepare-run assembles a package (contracts +
        outputs + judge version), refuses on missing output / invalid
        choreography, and freeze-run writes an append-only run record.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.core import choreography as ch
from murmurent.core import contribution_contract as pc
from murmurent.core import contribution_run as run
from murmurent.core import contribution_spec as ps

_HEADER = "inchikey,binding_affinity,uncertainty"


def _make_contribution(
    directory: Path, *, name: str, key: str = "inchikey", with_output: bool = True
) -> Path:
    """Write a contract, an output table, and a spec referencing both."""
    directory.mkdir(parents=True, exist_ok=True)
    contract = pc.ContributionContract(
        contribution=name,
        author="@member_a",
        question="optimize_sulfopin",
        candidate_key=key,
        metric="binding_affinity",
        units="kcal/mol",
        direction="lower_better",
        uncertainty="stderr",
    )
    (directory / pc.default_contract_filename(name)).write_text(
        contract.to_markdown(), encoding="utf-8"
    )
    output = ""
    if with_output:
        out_name = f"{name}_out.csv"
        (directory / out_name).write_text(
            "\n".join([_HEADER, "AAA-1,-9.2,0.3", "BBB-2,-8.1,0.4"]) + "\n",
            encoding="utf-8",
        )
        output = out_name
    spec = ps.ContributionSpec(
        contribution=name,
        author="@member_a",
        question="optimize_sulfopin",
        contract=pc.default_contract_filename(name),
        steps=[ps.Step("dock", "script", "vina")],
        output=output,
    )
    spec_path = directory / ps.default_spec_filename(name)
    spec_path.write_text(spec.to_markdown(), encoding="utf-8")
    return spec_path


def _make_choreography(directory: Path, *contribution_refs: str) -> Path:
    obj = ch.pose(
        question="optimize_sulfopin",
        poser="@the_pi",
        title="optimize sulfopin",
        candidate_key="inchikey",
        criteria="rank by measured affinity; flag single-contribution favourites",
    )
    for ref in contribution_refs:
        obj.attach_contribution(ref)
    path = directory / "optimize_sulfopin.md"
    path.write_text(obj.to_markdown(), encoding="utf-8")
    return path


# -- prepare_run ------------------------------------------------------------


def test_prepare_run_assembles_package(tmp_path) -> None:
    spec = _make_contribution(tmp_path, name="dock_and_filter")
    choreo = _make_choreography(tmp_path, spec.name)
    out = tmp_path / "runs"

    dest = run.prepare_run(choreo, out_dir=out, timestamp="2026-07-21T10-00")

    assert dest.is_dir()
    manifest = yaml.safe_load((dest / "run.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == run.PACKAGE_KIND
    assert manifest["candidate_key"] == "inchikey"
    assert manifest["criteria"].startswith("rank by measured affinity")
    # The choreography copy is frozen.
    assert (dest / "choreography.md").is_file()
    # One contribution entry, with its contract + output copied in and hashed.
    assert len(manifest["contributions"]) == 1
    entry = manifest["contributions"][0]
    assert entry["contract"]["metric"] == "binding_affinity"
    assert (dest / entry["contract"]["file"]).is_file()
    assert (dest / entry["output"]["file"]).is_file()
    assert len(entry["output"]["sha256"]) == 64
    # The judge-definition version is recorded (agents/judge.md exists in-repo).
    assert manifest["judge"]["agent"] == "judge"
    assert manifest["judge"]["version_sha256"]


def test_prepare_run_refuses_missing_output(tmp_path) -> None:
    spec = _make_contribution(tmp_path, name="no_output", with_output=False)
    choreo = _make_choreography(tmp_path, spec.name)
    try:
        run.prepare_run(choreo, out_dir=tmp_path / "runs")
    except run.RunError as exc:
        assert "no output" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RunError for a contribution with no output")


def test_prepare_run_refuses_invalid_choreography(tmp_path) -> None:
    # A contribution whose candidate key does not join → choreography invalid.
    spec = _make_contribution(tmp_path, name="wrong_key", key="smiles")
    choreo = _make_choreography(tmp_path, spec.name)
    try:
        run.prepare_run(choreo, out_dir=tmp_path / "runs")
    except run.RunError as exc:
        assert "invalid" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RunError for an invalid choreography")


def test_prepare_run_prefers_append_only_when_present(tmp_path, monkeypatch) -> None:
    # With a data root whose append_only/ tree exists, the package lands there.
    data_root = tmp_path / "data"
    (data_root / "append_only").mkdir(parents=True)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(data_root))
    spec = _make_contribution(tmp_path, name="dock_and_filter")
    choreo = _make_choreography(tmp_path, spec.name)

    dest = run.prepare_run(choreo)  # no --out
    assert str(dest).startswith(str(data_root / "append_only"))


# -- freeze_run -------------------------------------------------------------


def test_freeze_run_writes_record(tmp_path) -> None:
    spec = _make_contribution(tmp_path, name="dock_and_filter")
    choreo = _make_choreography(tmp_path, spec.name)
    pkg = run.prepare_run(choreo, out_dir=tmp_path / "runs")
    result = tmp_path / "combined.md"
    result.write_text("# Combined presentation\nAAA-1 leads.\n", encoding="utf-8")

    record = run.freeze_run(
        choreo, result_path=result, run_package=pkg, out_dir=tmp_path / "records"
    )

    assert record.is_dir()
    manifest = yaml.safe_load((record / "record.yaml").read_text(encoding="utf-8"))
    assert manifest["kind"] == run.RECORD_KIND
    assert manifest["criteria"].startswith("rank by measured affinity")
    assert manifest["judge"]["agent"] == "judge"
    # The judge's result is frozen with a sha256.
    assert (record / manifest["result"]["file"]).is_file()
    assert len(manifest["result"]["sha256"]) == 64
    # The whole package is copied in (choreography + contract + output + manifest).
    assert (record / "package" / "run.yaml").is_file()
    assert manifest["package"]["files"]


def test_freeze_run_assembles_package_when_omitted(tmp_path) -> None:
    spec = _make_contribution(tmp_path, name="dock_and_filter")
    choreo = _make_choreography(tmp_path, spec.name)
    result = tmp_path / "combined.md"
    result.write_text("combined\n", encoding="utf-8")

    record = run.freeze_run(choreo, result_path=result, out_dir=tmp_path / "out")
    assert (record / "package" / "run.yaml").is_file()


def test_freeze_run_does_not_overwrite(tmp_path) -> None:
    spec = _make_contribution(tmp_path, name="dock_and_filter")
    choreo = _make_choreography(tmp_path, spec.name)
    pkg = run.prepare_run(choreo, out_dir=tmp_path / "runs")
    result = tmp_path / "combined.md"
    result.write_text("combined\n", encoding="utf-8")
    records = tmp_path / "records"

    r1 = run.freeze_run(choreo, result_path=result, run_package=pkg, out_dir=records)
    r2 = run.freeze_run(choreo, result_path=result, run_package=pkg, out_dir=records)
    assert r1 != r2  # a second freeze makes a new dir, never overwrites


def test_freeze_run_missing_result_errors(tmp_path) -> None:
    spec = _make_contribution(tmp_path, name="dock_and_filter")
    choreo = _make_choreography(tmp_path, spec.name)
    try:
        run.freeze_run(choreo, result_path=tmp_path / "nope.md", out_dir=tmp_path / "o")
    except run.RunError as exc:
        assert "result" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected RunError for a missing result file")


# -- CLI --------------------------------------------------------------------


def test_cli_prepare_run(tmp_path) -> None:
    spec = _make_contribution(tmp_path, name="dock_and_filter")
    choreo = _make_choreography(tmp_path, spec.name)
    res = CliRunner().invoke(
        cli,
        ["choreography", "prepare-run", str(choreo), "--out", str(tmp_path / "runs")],
    )
    assert res.exit_code == 0, res.output
    assert "Prepared run package" in res.output


def test_cli_prepare_run_refuses_missing_output(tmp_path) -> None:
    spec = _make_contribution(tmp_path, name="no_output", with_output=False)
    choreo = _make_choreography(tmp_path, spec.name)
    res = CliRunner().invoke(
        cli,
        ["choreography", "prepare-run", str(choreo), "--out", str(tmp_path / "runs")],
    )
    assert res.exit_code != 0
    assert "no output" in res.output


def test_cli_freeze_run(tmp_path) -> None:
    spec = _make_contribution(tmp_path, name="dock_and_filter")
    choreo = _make_choreography(tmp_path, spec.name)
    result = tmp_path / "combined.md"
    result.write_text("combined\n", encoding="utf-8")
    res = CliRunner().invoke(
        cli,
        [
            "choreography", "freeze-run", str(choreo),
            "--result", str(result), "--out", str(tmp_path / "records"),
        ],
    )
    assert res.exit_code == 0, res.output
    assert "Froze run record" in res.output
