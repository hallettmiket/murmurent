"""
Purpose: Assemble + freeze a compositional-choreography *run*. Combining contribution
         outputs is the judge's job — an agent that reasons in a Claude Code
         session — so this module does NOT compute the combination. It mirrors
         the finalisation choreography's shape: ASSEMBLE the inputs the judge
         needs (prepare-run), then FREEZE the run for reproducibility once the
         judge has produced its combined presentation (freeze-run).
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: A validated choreography file (its attached contributions must each carry a
       produced ``output`` table), and — for freezing — the judge's result file.
Output: :func:`prepare_run` writes a *run package* (choreography + each contribution's
        contract + output + the judge-definition version) and returns its path;
        :func:`freeze_run` copies that package together with the judge's result
        into an append-only *run record* and returns its path.

Reproducibility (see ``docs/choreography.md`` § Reproducibility): a run record
freezes the judge's definition version, the poser's criteria, and every contribution's
declared output, so the same choreography can be re-run and reconstructed.

Boundary: assemble + freeze only. No judging, no aligning, no consensus — that
is :doc:`agents/judge`. Library code here takes an injected ``timestamp`` and
never calls ``datetime.now`` itself, so it is deterministic under test.
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from . import contribution_contract as _pc
from . import contribution_output as _po
from . import contribution_spec as _ps
from .choreography import Choreography
from .lab_vm import append_only_root
from .notebook import sha256_file

#: Manifest / record markers so tooling can recognise the artefacts.
PACKAGE_KIND = "choreography_run_package"
RECORD_KIND = "choreography_run_record"

#: Basenames used inside a package / record.
MANIFEST_NAME = "run.yaml"
RECORD_MANIFEST_NAME = "record.yaml"
CHOREOGRAPHY_COPY = "choreography.md"

#: Subdir names under the resolved run/record root.
PACKAGE_SUBDIR = "choreography_runs"
RECORD_SUBDIR = "choreography_run_records"

#: The commons agent whose definition version is frozen into every run.
JUDGE_AGENT = "judge"


class RunError(ValueError):
    """Raised when a run cannot be assembled or frozen (invalid inputs)."""


# ---------------------------------------------------------------------------
# Judge-definition version
# ---------------------------------------------------------------------------


def judge_definition_sha256() -> str | None:
    """SHA-256 of the commons ``agents/judge.md``, or ``None`` if unresolved.

    The judge is a markdown-defined agent; freezing its content hash pins the
    exact decision strategy a run was combined under, so a later re-run can tell
    whether the judge definition has since changed.
    """
    try:
        from .agent_forks import commons_agent_path  # deferred: optional deps

        path = commons_agent_path(JUDGE_AGENT)
    except Exception:
        return None
    return sha256_file(path) if path.is_file() else None


# ---------------------------------------------------------------------------
# Assembling a run package (prepare-run)
# ---------------------------------------------------------------------------


@dataclass
class _ContributionInputs:
    """The resolved artefacts for one attached contribution."""

    ref: str
    spec: _ps.ContributionSpec
    spec_path: Path
    contract: _pc.ContributionContract
    contract_path: Path
    output_path: Path


def _resolve_run_root(
    out_dir: str | Path | None, subdir: str, env: dict[str, str] | None
) -> Path:
    """Where a run package / record is written.

    Priority: an explicit ``out_dir`` wins; otherwise the Tier-3
    ``append_only/`` tree when it exists on disk; otherwise a temp-style
    default. (append_only writes are new-files-only, so the protected-paths
    append-only hook is respected.)
    """
    if out_dir is not None:
        return Path(out_dir).expanduser()
    ao = append_only_root(env)
    if ao.exists():
        return ao / subdir
    return Path(tempfile.gettempdir()) / f"murmurent_{subdir}"


def _unique_dir(root: Path, stem: str) -> Path:
    """A not-yet-existing directory ``<root>/<stem>`` (append an integer suffix).

    Keeps runs append-only: an existing directory is never reused or overwritten.
    """
    dest = root / stem
    n = 2
    while dest.exists():
        dest = root / f"{stem}_{n}"
        n += 1
    return dest


def _gather_contribution_inputs(choreo: Choreography, base: Path) -> list[_ContributionInputs]:
    """Resolve each attached contribution's spec, contract, and produced output.

    Raises :class:`RunError` if a contribution cannot be resolved or has no output.
    """
    gathered: list[_ContributionInputs] = []
    for ref in choreo.contributions:
        spec_path = _ps.resolve_spec_reference(ref, base)
        if spec_path is None:
            raise RunError(f"contribution {ref!r}: spec could not be resolved")
        spec = _ps.ContributionSpec.from_file(spec_path)
        spec_dir = spec_path.parent

        contract_path = _pc.resolve_contract_reference(spec.contract, spec_dir)
        contract = spec.resolved_contract(spec_dir)
        if contract is None or contract_path is None:
            raise RunError(f"contribution {ref!r}: output contract could not be resolved")

        if not (spec.output and spec.output.strip()):
            raise RunError(
                f"contribution {ref!r}: no output table declared — run the contribution and "
                f"record its 'output' before preparing a run"
            )
        output_path = spec.resolved_output(spec_dir)
        if output_path is None:
            raise RunError(
                f"contribution {ref!r}: declared output {spec.output!r} could not be resolved"
            )
        out_problems = _po.validate_output(contract, output_path)
        if out_problems:
            joined = "; ".join(out_problems)
            raise RunError(f"contribution {ref!r}: output does not conform to contract: {joined}")

        gathered.append(
            _ContributionInputs(
                ref=ref,
                spec=spec,
                spec_path=spec_path,
                contract=contract,
                contract_path=contract_path,
                output_path=output_path,
            )
        )
    return gathered


def prepare_run(
    choreography_path: str | Path,
    *,
    out_dir: str | Path | None = None,
    timestamp: str | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """Assemble a run package for a valid choreography; return its directory.

    The choreography must pass ``validate()`` (joinability holds) and every
    attached contribution must carry a produced ``output`` table conforming to its
    contract; otherwise :class:`RunError` is raised. The package contains:

      - ``choreography.md`` — a copy of the choreography (question, poser,
        candidate_key, criteria, attached contributions);
      - ``contributions/<slug>/contract.md`` + the contribution's output table, for each
        contributed contribution;
      - ``run.yaml`` — a manifest tying it together, including the
        judge-definition version (sha256 of ``agents/judge.md``) and a sha256
        for each frozen file. ``timestamp`` is recorded when supplied (callers
        inject it; library code never reads the clock).
    """
    ch_path = Path(choreography_path).expanduser()
    if not ch_path.is_file():
        raise RunError(f"no such choreography file: {ch_path}")
    choreo = Choreography.from_file(ch_path)
    base = ch_path.parent

    problems = choreo.validate()
    if problems:
        joined = "\n  - ".join(problems)
        raise RunError(
            f"choreography is invalid; refusing to prepare a run:\n  - {joined}"
        )
    if not choreo.contributions:
        raise RunError("choreography has no attached contributions; nothing to run")

    contributions = _gather_contribution_inputs(choreo, base)

    root = _resolve_run_root(out_dir, PACKAGE_SUBDIR, env)
    root.mkdir(parents=True, exist_ok=True)
    stem = f"{_pc.slugify(choreo.question) or 'choreography'}_run"
    if timestamp:
        stem = f"{stem}_{_pc.slugify(timestamp)}"
    dest = _unique_dir(root, stem)
    (dest / "contributions").mkdir(parents=True)

    # Copy the choreography itself.
    shutil.copyfile(ch_path, dest / CHOREOGRAPHY_COPY)

    contribution_entries: list[dict[str, Any]] = []
    for pin in contributions:
        slug = _pc.slugify(pin.spec.contribution) or _pc.slugify(pin.ref) or "contribution"
        pdir = _unique_dir(dest / "contributions", slug)
        pdir.mkdir(parents=True)
        contract_copy = pdir / "contract.md"
        output_copy = pdir / f"output{pin.output_path.suffix or '.csv'}"
        shutil.copyfile(pin.contract_path, contract_copy)
        shutil.copyfile(pin.output_path, output_copy)
        contribution_entries.append(
            {
                "ref": pin.ref,
                "contribution": pin.spec.contribution,
                "author": pin.spec.author,
                "contract": {
                    "file": str(contract_copy.relative_to(dest)),
                    "sha256": sha256_file(contract_copy),
                    "candidate_key": pin.contract.candidate_key,
                    "metric": pin.contract.metric,
                    "units": pin.contract.units,
                    "direction": pin.contract.direction,
                    "uncertainty": pin.contract.uncertainty,
                },
                "output": {
                    "file": str(output_copy.relative_to(dest)),
                    "sha256": sha256_file(output_copy),
                },
            }
        )

    manifest: dict[str, Any] = {
        "kind": PACKAGE_KIND,
        "question": choreo.question,
        "title": choreo.title,
        "poser": choreo.poser,
        "candidate_key": choreo.candidate_key,
        "criteria": choreo.criteria,
        "choreography": {
            "file": CHOREOGRAPHY_COPY,
            "sha256": sha256_file(dest / CHOREOGRAPHY_COPY),
        },
        "judge": {
            "agent": JUDGE_AGENT,
            "version_sha256": judge_definition_sha256(),
        },
        "contributions": contribution_entries,
    }
    if timestamp:
        manifest["created"] = timestamp
    (dest / MANIFEST_NAME).write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return dest


# ---------------------------------------------------------------------------
# Freezing a run record (freeze-run)
# ---------------------------------------------------------------------------


def _iter_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*") if p.is_file())


def freeze_run(
    choreography_path: str | Path,
    *,
    result_path: str | Path,
    run_package: str | Path | None = None,
    out_dir: str | Path | None = None,
    timestamp: str | None = None,
    env: dict[str, str] | None = None,
) -> Path:
    """Freeze a run as an append-only record; return the record directory.

    Copies the run package (choreography, each contribution's contract + output, the
    judge-definition version, the criteria) together with the judge's produced
    ``result_path`` (the combined presentation) into a new record directory, and
    writes ``record.yaml`` summarising the frozen files with their sha256s.

    ``run_package`` may be an existing package (from :func:`prepare_run`); if
    omitted, one is assembled first. New files only — an existing record is never
    overwritten, so the protected-paths append-only hook is respected.
    """
    res = Path(result_path).expanduser()
    if not res.is_file():
        raise RunError(f"no such result file: {res}")

    if run_package is not None:
        pkg = Path(run_package).expanduser()
        if not (pkg / MANIFEST_NAME).is_file():
            raise RunError(
                f"{pkg} is not a run package (no {MANIFEST_NAME}); "
                f"run 'choreography prepare-run' first"
            )
    else:
        pkg = prepare_run(
            choreography_path, out_dir=out_dir, timestamp=timestamp, env=env
        )

    manifest = yaml.safe_load((pkg / MANIFEST_NAME).read_text(encoding="utf-8")) or {}
    question = str(manifest.get("question") or "")

    root = _resolve_run_root(out_dir, RECORD_SUBDIR, env)
    root.mkdir(parents=True, exist_ok=True)
    stem = f"{_pc.slugify(question) or 'choreography'}_record"
    if timestamp:
        stem = f"{stem}_{_pc.slugify(timestamp)}"
    dest = _unique_dir(root, stem)
    dest.mkdir(parents=True)

    # Freeze the package (copy the whole tree) and the judge's result.
    pkg_copy = dest / "package"
    shutil.copytree(pkg, pkg_copy)
    result_copy = dest / "result" / res.name
    result_copy.parent.mkdir(parents=True)
    shutil.copyfile(res, result_copy)

    package_files = [
        {"file": str(p.relative_to(dest)), "sha256": sha256_file(p)}
        for p in _iter_files(pkg_copy)
    ]
    record: dict[str, Any] = {
        "kind": RECORD_KIND,
        "question": question,
        "title": manifest.get("title", ""),
        "poser": manifest.get("poser", ""),
        "candidate_key": manifest.get("candidate_key", ""),
        "criteria": manifest.get("criteria", ""),
        "judge": manifest.get("judge", {}),
        "package": {
            "manifest": str((pkg_copy / MANIFEST_NAME).relative_to(dest)),
            "files": package_files,
        },
        "result": {
            "file": str(result_copy.relative_to(dest)),
            "sha256": sha256_file(result_copy),
        },
    }
    if timestamp:
        record["created"] = timestamp
    (dest / RECORD_MANIFEST_NAME).write_text(
        yaml.safe_dump(record, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return dest
