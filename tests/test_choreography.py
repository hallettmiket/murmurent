"""
Purpose: Unit + CLI tests for the compositional choreography object
         (:mod:`murmurent.core.choreography` and ``murmurent choreography``).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: Synthetic choreographies + contribution specs/contracts + ``CliRunner``.
Output: pytest cases asserting model round-trip, each validation failure, the
        candidate-key joinability check, and the CLI pose→offer→validate→show flow.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from murmurent.cli import cli
from murmurent.core import choreography as ch
from murmurent.core import contribution_contract as pc
from murmurent.core import contribution_spec as ps


def _make_contribution(directory: Path, *, name: str, key: str) -> Path:
    """Write a contract + a contribution spec referencing it; return the spec path."""
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
    spec = ps.ContributionSpec(
        contribution=name,
        author="@member_a",
        question="optimize_sulfopin",
        contract=pc.default_contract_filename(name),
        steps=[ps.Step("dock", "script", "vina")],
    )
    spec_path = directory / ps.default_spec_filename(name)
    spec_path.write_text(spec.to_markdown(), encoding="utf-8")
    return spec_path


def _choreo() -> ch.Choreography:
    return ch.pose(
        question="optimize_sulfopin",
        poser="@the_pi",
        title="optimize sulfopin for potency + BBB permeability",
        candidate_key="inchikey",
        criteria="rank by measured affinity; flag single-contribution favourites",
    )


# -- model round-trip -------------------------------------------------------


def test_markdown_round_trip() -> None:
    c = _choreo()
    c.attach_contribution("a_contribution.md")
    parsed = ch.Choreography.from_markdown(c.to_markdown())
    assert parsed == c


def test_to_markdown_has_frontmatter_and_kind() -> None:
    md = _choreo().to_markdown()
    assert md.startswith("---\n")
    assert "kind: choreography" in md
    assert "candidate_key: inchikey" in md


def test_attach_contribution_is_idempotent() -> None:
    c = _choreo()
    assert c.attach_contribution("p.md") is True
    assert c.attach_contribution("p.md") is False
    assert c.contributions == ["p.md"]


# -- validation failures ----------------------------------------------------


def test_missing_required_field_flagged() -> None:
    c = _choreo()
    c.title = ""
    assert any("title" in p for p in c.validate())


def test_poser_without_handle_flagged() -> None:
    c = _choreo()
    c.poser = "the_pi"
    assert any("poser" in p for p in c.validate())


def test_bad_candidate_key_flagged() -> None:
    c = _choreo()
    c.candidate_key = "pdb_id"
    assert any("candidate_key" in p for p in c.validate())


# -- the candidate-key joinability check ------------------------------------


def test_joinable_contribution_passes(tmp_path) -> None:
    spec_path = _make_contribution(tmp_path, name="dock_and_filter", key="inchikey")
    c = _choreo()
    c.attach_contribution(spec_path.name)
    assert c.validate(base_dir=tmp_path) == []


def test_non_joinable_contribution_flagged(tmp_path) -> None:
    # Contribution declares a different candidate key → not combinable.
    spec_path = _make_contribution(tmp_path, name="wrong_key", key="smiles")
    c = _choreo()  # choreography key is inchikey
    c.attach_contribution(spec_path.name)
    problems = c.validate(base_dir=tmp_path)
    assert any("does not join" in p for p in problems)
    assert any("smiles" in p for p in problems)


def test_mixed_contributions_reports_only_the_offender(tmp_path) -> None:
    good = _make_contribution(tmp_path, name="good", key="inchikey")
    bad = _make_contribution(tmp_path, name="bad", key="gene_symbol")
    c = _choreo()
    c.attach_contribution(good.name)
    c.attach_contribution(bad.name)
    problems = c.validate(base_dir=tmp_path)
    assert len(problems) == 1
    assert "bad" in problems[0]


def test_unresolvable_contribution_flagged(tmp_path) -> None:
    c = _choreo()
    c.attach_contribution("ghost_contribution.md")
    assert any("could not be resolved" in p for p in c.validate(base_dir=tmp_path))


# -- CLI flow: pose → offer → validate → show -------------------------------


def _pose_args(out: Path, **overrides) -> list[str]:
    base = {
        "--question": "optimize_sulfopin",
        "--poser": "@the_pi",
        "--title": "optimize sulfopin for potency + BBB permeability",
        "--candidate-key": "inchikey",
        "--criteria": "rank by measured affinity; flag single-contribution favourites",
    }
    base.update(overrides)
    args = ["choreography", "new"]
    for k, v in base.items():
        args += [k, str(v)]
    args += ["--out", str(out)]
    return args


def test_cli_full_flow(tmp_path) -> None:
    spec_path = _make_contribution(tmp_path, name="dock_and_filter", key="inchikey")
    choreo_path = tmp_path / "optimize_sulfopin.md"
    runner = CliRunner()

    r1 = runner.invoke(cli, _pose_args(choreo_path))
    assert r1.exit_code == 0, r1.output
    assert choreo_path.is_file()

    r2 = runner.invoke(
        cli, ["choreography", "offer", str(choreo_path), "--contribution", str(spec_path)]
    )
    assert r2.exit_code == 0, r2.output

    r3 = runner.invoke(cli, ["choreography", "validate", str(choreo_path)])
    assert r3.exit_code == 0, r3.output
    assert "OK" in r3.output

    r4 = runner.invoke(cli, ["choreography", "show", str(choreo_path)])
    assert r4.exit_code == 0, r4.output
    assert "optimize sulfopin" in r4.output
    assert "binding_affinity" in r4.output
    assert "@the_pi" in r4.output


def test_cli_validate_flags_non_joinable(tmp_path) -> None:
    spec_path = _make_contribution(tmp_path, name="wrong", key="smiles")
    choreo_path = tmp_path / "optimize_sulfopin.md"
    runner = CliRunner()
    runner.invoke(cli, _pose_args(choreo_path))
    runner.invoke(
        cli, ["choreography", "offer", str(choreo_path), "--contribution", str(spec_path)]
    )
    res = runner.invoke(cli, ["choreography", "validate", str(choreo_path)])
    assert res.exit_code != 0
    assert "does not join" in res.output


def test_cli_new_criteria_from_file(tmp_path) -> None:
    crit = tmp_path / "criteria.txt"
    crit.write_text("weight potency 0.6, permeability 0.4\n", encoding="utf-8")
    choreo_path = tmp_path / "c.md"
    res = CliRunner().invoke(cli, _pose_args(choreo_path, **{"--criteria": f"@{crit}"}))
    assert res.exit_code == 0, res.output
    loaded = ch.Choreography.from_file(choreo_path)
    assert "weight potency" in loaded.criteria


def test_cli_new_refuses_invalid_poser(tmp_path) -> None:
    choreo_path = tmp_path / "c.md"
    res = CliRunner().invoke(cli, _pose_args(choreo_path, **{"--poser": "the_pi"}))
    assert res.exit_code != 0
    assert not choreo_path.exists()


def test_cli_offer_missing_file_errors() -> None:
    res = CliRunner().invoke(
        cli, ["choreography", "offer", "/no/such.md", "--contribution", "p.md"]
    )
    assert res.exit_code != 0
    assert "no such file" in res.output
