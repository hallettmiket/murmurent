"""
Purpose: Resolve the data root and project/experiment data dirs.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: ``$MURMURENT_DATA_ROOT`` (new) or ``$MURMURENT_LAB_VM_ROOT`` (legacy,
       back-compat) env var (default ``~/lab_vm/data``); project + experiment
       slugs.
Output: Helpers that return canonical immutable / append-only / clinical paths
        and create the per-experiment directory tree.

Dual-name transition (2026-07): the data tree was renamed
``raw/`` -> ``immutable/`` and ``refined/`` -> ``append_only/``, and the env
var ``MURMURENT_LAB_VM_ROOT`` -> ``MURMURENT_DATA_ROOT``. Both spellings keep
working during the transition:

- **Env var**: ``MURMURENT_DATA_ROOT`` is preferred; if it is unset we fall
  back to the legacy ``MURMURENT_LAB_VM_ROOT`` (emitting a one-time
  deprecation note).
- **Sub-directories**: new writes go to ``immutable/`` / ``append_only/``, but
  if only the legacy ``raw/`` / ``refined/`` dir exists on disk (an
  un-migrated deployment) we resolve to that instead, so existing data keeps
  working until ``murmurent data migrate`` renames it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_LAB_VM_ROOT = Path("~/lab_vm/data").expanduser()

ENV_VAR = "MURMURENT_DATA_ROOT"
LEGACY_ENV_VAR = "MURMURENT_LAB_VM_ROOT"

IMMUTABLE_SUBDIR = "immutable"
APPEND_ONLY_SUBDIR = "append_only"
LEGACY_IMMUTABLE_SUBDIR = "raw"
LEGACY_APPEND_ONLY_SUBDIR = "refined"

# Backwards-compatible aliases (some callers still import these names).
RAW_SUBDIR = IMMUTABLE_SUBDIR
REFINED_SUBDIR = APPEND_ONLY_SUBDIR
CLINICAL_SUBDIR = "clinical"
INSTRUMENT_OUTPUTS_SUBDIR = "instrument_outputs"

_LEGACY_ENV_WARNED = False


def _warn_legacy_env_once() -> None:
    """Emit a single deprecation note when only the legacy env var is set."""
    global _LEGACY_ENV_WARNED
    if _LEGACY_ENV_WARNED:
        return
    _LEGACY_ENV_WARNED = True
    print(
        f"[murmurent] note: ${LEGACY_ENV_VAR} is deprecated; "
        f"set ${ENV_VAR} instead (falling back to the legacy var for now).",
        file=sys.stderr,
    )


def data_root(env: dict[str, str] | None = None) -> Path:
    """Return the data root, honouring ``$MURMURENT_DATA_ROOT``.

    Resolution order: ``$MURMURENT_DATA_ROOT`` (new canonical name), then the
    legacy ``$MURMURENT_LAB_VM_ROOT`` (with a one-time deprecation note), then
    the ``~/lab_vm/data`` default. Production deployments set the env var to
    ``/data/lab_vm/`` (per the lab data-storage rule).
    """
    source = os.environ if env is None else env
    value = source.get(ENV_VAR)
    if value:
        return Path(value).expanduser()
    legacy = source.get(LEGACY_ENV_VAR)
    if legacy:
        _warn_legacy_env_once()
        return Path(legacy).expanduser()
    return DEFAULT_LAB_VM_ROOT


def lab_vm_root(env: dict[str, str] | None = None) -> Path:
    """Legacy alias for :func:`data_root`."""
    return data_root(env)


def _resolve_subdir(root: Path, new_name: str, legacy_name: str) -> Path:
    """Return ``root/new_name``, unless only ``root/legacy_name`` exists.

    New writes land under the new name; un-migrated deployments (where only
    the legacy dir is present) keep resolving to the legacy dir.
    """
    new_path = root / new_name
    legacy_path = root / legacy_name
    if not new_path.exists() and legacy_path.exists():
        return legacy_path
    return new_path


def immutable_root(env: dict[str, str] | None = None) -> Path:
    """Return ``<data-root>/immutable`` (or legacy ``raw`` if only that exists)."""
    return _resolve_subdir(data_root(env), IMMUTABLE_SUBDIR, LEGACY_IMMUTABLE_SUBDIR)


def append_only_root(env: dict[str, str] | None = None) -> Path:
    """Return ``<data-root>/append_only`` (or legacy ``refined`` if only that exists)."""
    return _resolve_subdir(data_root(env), APPEND_ONLY_SUBDIR, LEGACY_APPEND_ONLY_SUBDIR)


def raw_root(env: dict[str, str] | None = None) -> Path:
    """Legacy alias for :func:`immutable_root`."""
    return immutable_root(env)


def refined_root(env: dict[str, str] | None = None) -> Path:
    """Legacy alias for :func:`append_only_root`."""
    return append_only_root(env)


def clinical_root(env: dict[str, str] | None = None) -> Path:
    """Return ``<data-root>/clinical``."""
    return data_root(env) / CLINICAL_SUBDIR


def project_immutable_dir(project: str, env: dict[str, str] | None = None) -> Path:
    """Return ``<data-root>/immutable/<project>``."""
    return immutable_root(env) / project


def project_append_only_dir(project: str, env: dict[str, str] | None = None) -> Path:
    """Return ``<data-root>/append_only/<project>``."""
    return append_only_root(env) / project


# Legacy aliases.
project_raw_dir = project_immutable_dir
project_refined_dir = project_append_only_dir


def experiment_immutable_dir(
    project: str, experiment: str, env: dict[str, str] | None = None
) -> Path:
    """Return ``<data-root>/immutable/<project>/<experiment>``."""
    return project_immutable_dir(project, env) / experiment


def experiment_append_only_dir(
    project: str, experiment: str, env: dict[str, str] | None = None
) -> Path:
    """Return ``<data-root>/append_only/<project>/<experiment>``."""
    return project_append_only_dir(project, env) / experiment


# Legacy aliases.
experiment_raw_dir = experiment_immutable_dir
experiment_refined_dir = experiment_append_only_dir


def experiment_instrument_outputs_dir(
    project: str, experiment: str, env: dict[str, str] | None = None
) -> Path:
    """Return ``<data-root>/append_only/<project>/<experiment>/instrument_outputs``."""
    return experiment_append_only_dir(project, experiment, env) / INSTRUMENT_OUTPUTS_SUBDIR


def ensure_experiment_dirs(
    project: str, experiment: str, env: dict[str, str] | None = None
) -> tuple[Path, Path]:
    """Create immutable + append-only dirs for an experiment.

    Return ``(immutable_dir, append_only_dir)``. The immutable dir is created
    writeable (so ``ingest`` can copy into it); ingest is responsible for the
    ``chmod a-w`` after copy. The append-only dir stays writeable.
    """
    immutable_dir = experiment_immutable_dir(project, experiment, env)
    append_only_dir = experiment_append_only_dir(project, experiment, env)
    immutable_dir.mkdir(parents=True, exist_ok=True)
    append_only_dir.mkdir(parents=True, exist_ok=True)
    return immutable_dir, append_only_dir


def is_under_raw(path: str | Path, env: dict[str, str] | None = None) -> bool:
    """Return True if ``path`` resolves under the immutable (raw) data tree.

    Symlinks are *not* resolved here — callers that need symlink resolution should
    use :func:`pathlib.Path.resolve` first. Lexical containment is sufficient for
    most CLI checks; the raw-data guard hook does its own normalization.
    """
    target = Path(path).expanduser()
    immutable = immutable_root(env)
    try:
        target_str = str(target)
        immutable_str = str(immutable).rstrip("/") + "/"
        return target_str == str(immutable) or target_str.startswith(immutable_str)
    except (TypeError, ValueError):
        return False
