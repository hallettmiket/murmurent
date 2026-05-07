"""
Purpose: Classify, copy, and finalise instrument-export files for an experiment.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: A source directory of files; instrument profiles loaded from
       :mod:`wigamig.core.instrument`; project + experiment slugs.
Output: ``IngestPlan`` describing the proposed classification; ``IngestResult``
        after copying, ``chmod a-w`` of the raw dir, and SHA-256 computation.
"""

from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from . import lab_vm
from .instrument import InstrumentProfile, detect_profile, generic_classify, load_profiles
from .notebook import ChecksumEntry, sha256_file


@dataclass
class IngestPlan:
    """Proposed classification of source files prior to copying."""

    project: str
    experiment: str
    source: Path
    raw_files: list[Path] = field(default_factory=list)
    derived_files: list[Path] = field(default_factory=list)
    profile: InstrumentProfile | None = None
    fallback_used: bool = False
    skipped: list[Path] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.raw_files) + len(self.derived_files)


@dataclass
class IngestResult:
    """Outcome of a confirmed ingest: paths copied + their SHA-256 sums."""

    raw_dir: Path
    refined_dir: Path
    raw: list[ChecksumEntry] = field(default_factory=list)
    instrument_outputs: list[ChecksumEntry] = field(default_factory=list)


def collect_source_files(source: Path) -> list[Path]:
    """Return all regular files under ``source`` (recursive)."""
    if not source.is_dir():
        raise FileNotFoundError(f"ingest source is not a directory: {source}")
    files: list[Path] = []
    for root, _dirs, names in os.walk(source):
        for n in names:
            p = Path(root) / n
            if p.is_file() and not p.is_symlink():
                files.append(p)
    files.sort()
    return files


def plan_ingest(
    *,
    project: str,
    experiment: str,
    source: str | Path,
    instrument: str | None = None,
    profiles: dict[str, InstrumentProfile] | None = None,
) -> IngestPlan:
    """Build an :class:`IngestPlan` for ``source``.

    Resolution order matches the design:
    1. Explicit ``--instrument`` (``instrument`` parameter), if given.
    2. Auto-detection via each profile's ``detect_marker``.
    3. Generic fallback patterns (with ``fallback_used=True`` set).
    """
    source_path = Path(source).expanduser().resolve()
    files = collect_source_files(source_path)

    profile_map = profiles if profiles is not None else load_profiles()
    selected: InstrumentProfile | None = None
    if instrument is not None:
        if instrument not in profile_map:
            raise KeyError(
                f"unknown instrument profile: {instrument!r}; " f"known: {sorted(profile_map)}"
            )
        selected = profile_map[instrument]
    else:
        selected = detect_profile(profile_map, files)

    plan = IngestPlan(
        project=project,
        experiment=experiment,
        source=source_path,
        profile=selected,
    )

    for f in files:
        decision: str | None = None
        if selected is not None:
            decision = selected.classify(f.name)
        if decision is None:
            decision = generic_classify(f.name)
            plan.fallback_used = True
        if decision == "raw":
            plan.raw_files.append(f)
        elif decision == "derived":
            plan.derived_files.append(f)
        else:  # pragma: no cover - generic_classify always returns raw or derived
            plan.skipped.append(f)
    return plan


def execute_ingest(
    plan: IngestPlan,
    *,
    env: dict[str, str] | None = None,
) -> IngestResult:
    """Copy classified files into the lab-VM, chmod raw read-only, hash everything.

    Raw files go to ``$WIGAMIG_LAB_VM_ROOT/raw/<project>/<experiment>/``;
    derived files to ``.../refined/<project>/<experiment>/instrument_outputs/``.
    After copy, the raw directory tree is set ``a-w`` (owner can still ``rm`` since
    parent perms are unchanged, but files inside are read-only — matches the
    design's "raw is immutable" rule for code-driven mutation).
    """
    raw_dir = lab_vm.experiment_raw_dir(plan.project, plan.experiment, env=env)
    refined_dir = lab_vm.experiment_refined_dir(plan.project, plan.experiment, env=env)
    instr_dir = lab_vm.experiment_instrument_outputs_dir(plan.project, plan.experiment, env=env)
    raw_dir.mkdir(parents=True, exist_ok=True)
    refined_dir.mkdir(parents=True, exist_ok=True)
    instr_dir.mkdir(parents=True, exist_ok=True)

    result = IngestResult(raw_dir=raw_dir, refined_dir=refined_dir)

    for src in plan.raw_files:
        dest = raw_dir / src.name
        _copy_temporary_writeable(src, dest)
        result.raw.append(ChecksumEntry(path=dest, sha256=sha256_file(dest)))

    for src in plan.derived_files:
        dest = instr_dir / src.name
        _copy_temporary_writeable(src, dest)
        result.instrument_outputs.append(ChecksumEntry(path=dest, sha256=sha256_file(dest)))

    chmod_readonly_recursive(raw_dir)
    return result


def _copy_temporary_writeable(src: Path, dest: Path) -> None:
    """Copy ``src`` to ``dest``, ensuring ``dest`` is writeable mid-copy.

    If ``dest`` already exists and is read-only (e.g. from a prior ingest), the
    copy would otherwise fail. Strip write back on the file before write, then
    let :func:`chmod_readonly_recursive` re-apply the read-only state.
    """
    if dest.exists():
        try:
            dest.chmod(0o644)
        except PermissionError:
            pass
    shutil.copy2(src, dest)


def chmod_readonly_recursive(directory: Path) -> None:
    """Set every regular file under ``directory`` to mode 0444 (a-w).

    The directory itself is left writeable so subsequent ingests of *new* files
    can still place them; the design's contract is that *files* once copied to
    raw cannot be mutated.
    """
    for root, _dirs, names in os.walk(directory):
        for n in names:
            p = Path(root) / n
            try:
                p.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            except (PermissionError, FileNotFoundError):
                pass


def format_plan(plan: IngestPlan) -> str:
    """Return a human-readable proposed classification block."""
    lines: list[str] = []
    if plan.profile is not None:
        lines.append(
            f"Detected instrument: {plan.profile.instrument} "
            f"(profile: {plan.profile.source.name if plan.profile.source else '?'})"
        )
    else:
        lines.append("No instrument profile matched; using generic fallback patterns.")
    if plan.fallback_used:
        lines.append("WARNING: at least one file classified by generic fallback only.")
    lines.append("")
    lines.append("Proposed classification:")
    lines.append(f"  RAW ({len(plan.raw_files)} files)")
    for f in plan.raw_files:
        lines.append(f"    {f.name}")
    lines.append(f"  DERIVED ({len(plan.derived_files)} files)")
    for f in plan.derived_files:
        lines.append(f"    {f.name}")
    return "\n".join(lines) + "\n"


def relpath_under(target: Path, ancestor: Path) -> str:
    """Return ``target`` rendered relative to ``ancestor`` if possible, else absolute."""
    try:
        return str(target.resolve().relative_to(ancestor.resolve()))
    except ValueError:
        return str(target)


def absolute_paths(entries: Iterable[ChecksumEntry]) -> list[Path]:
    """Return absolute paths from a list of :class:`ChecksumEntry`."""
    return [e.path for e in entries]
