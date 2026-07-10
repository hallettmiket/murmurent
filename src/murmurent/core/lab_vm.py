"""
Purpose: Resolve the simulated lab-VM root and project/experiment data dirs.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: ``$MURMURENT_LAB_VM_ROOT`` env var (default ``~/lab_vm/data``); project +
       experiment slugs.
Output: Helpers that return canonical raw / refined / clinical paths and create
        the per-experiment directory tree.
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_LAB_VM_ROOT = Path("~/lab_vm/data").expanduser()
ENV_VAR = "MURMURENT_LAB_VM_ROOT"
RAW_SUBDIR = "raw"
REFINED_SUBDIR = "refined"
CLINICAL_SUBDIR = "clinical"
INSTRUMENT_OUTPUTS_SUBDIR = "instrument_outputs"


def lab_vm_root(env: dict[str, str] | None = None) -> Path:
    """Return the simulated lab-VM root, honouring ``$MURMURENT_LAB_VM_ROOT``.

    Production deployments set this to ``/data/lab_vm/`` (per the lab data-storage
    rule). Tutorial / smoke-test deployments default to ``~/lab_vm/data``.
    """
    source = os.environ if env is None else env
    return Path(source.get(ENV_VAR, DEFAULT_LAB_VM_ROOT)).expanduser()


def raw_root(env: dict[str, str] | None = None) -> Path:
    """Return ``<lab-vm-root>/raw``."""
    return lab_vm_root(env) / RAW_SUBDIR


def refined_root(env: dict[str, str] | None = None) -> Path:
    """Return ``<lab-vm-root>/refined``."""
    return lab_vm_root(env) / REFINED_SUBDIR


def clinical_root(env: dict[str, str] | None = None) -> Path:
    """Return ``<lab-vm-root>/clinical``."""
    return lab_vm_root(env) / CLINICAL_SUBDIR


def project_raw_dir(project: str, env: dict[str, str] | None = None) -> Path:
    """Return ``<lab-vm-root>/raw/<project>``."""
    return raw_root(env) / project


def project_refined_dir(project: str, env: dict[str, str] | None = None) -> Path:
    """Return ``<lab-vm-root>/refined/<project>``."""
    return refined_root(env) / project


def experiment_raw_dir(project: str, experiment: str, env: dict[str, str] | None = None) -> Path:
    """Return ``<lab-vm-root>/raw/<project>/<experiment>``."""
    return project_raw_dir(project, env) / experiment


def experiment_refined_dir(
    project: str, experiment: str, env: dict[str, str] | None = None
) -> Path:
    """Return ``<lab-vm-root>/refined/<project>/<experiment>``."""
    return project_refined_dir(project, env) / experiment


def experiment_instrument_outputs_dir(
    project: str, experiment: str, env: dict[str, str] | None = None
) -> Path:
    """Return ``<lab-vm-root>/refined/<project>/<experiment>/instrument_outputs``."""
    return experiment_refined_dir(project, experiment, env) / INSTRUMENT_OUTPUTS_SUBDIR


def ensure_experiment_dirs(
    project: str, experiment: str, env: dict[str, str] | None = None
) -> tuple[Path, Path]:
    """Create raw + refined dirs for an experiment. Return ``(raw_dir, refined_dir)``.

    The raw dir is created writeable (so ``ingest`` can copy into it); ingest is
    responsible for the ``chmod a-w`` after copy. The refined dir stays writeable.
    """
    raw_dir = experiment_raw_dir(project, experiment, env)
    refined_dir = experiment_refined_dir(project, experiment, env)
    raw_dir.mkdir(parents=True, exist_ok=True)
    refined_dir.mkdir(parents=True, exist_ok=True)
    return raw_dir, refined_dir


def is_under_raw(path: str | Path, env: dict[str, str] | None = None) -> bool:
    """Return True if ``path`` resolves under the lab-VM raw tree.

    Symlinks are *not* resolved here — callers that need symlink resolution should
    use :func:`pathlib.Path.resolve` first. Lexical containment is sufficient for
    most CLI checks; the raw-data guard hook does its own normalization.
    """
    target = Path(path).expanduser()
    raw = raw_root(env)
    try:
        target_str = str(target)
        raw_str = str(raw).rstrip("/") + "/"
        return target_str == str(raw) or target_str.startswith(raw_str)
    except (TypeError, ValueError):
        return False
