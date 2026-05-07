"""
Purpose: Load instrument profiles for the ingest classification step.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: YAML profiles in ``<wigamig>/instruments/`` (centre default) and
       ``<lab-mgmt-repo>/instruments/`` (lab override).
Output: ``InstrumentProfile`` dataclasses keyed by instrument name; a fallback
        profile for the generic-pattern layer.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from .repo import lab_mgmt_repo_root, wigamig_repo_root

INSTRUMENTS_SUBDIR = "instruments"

GENERIC_DERIVED_EXTENSIONS: frozenset[str] = frozenset({"pdf", "html"})
GENERIC_DERIVED_PATTERNS: tuple[str, ...] = (
    "*thumbnail*",
    "*preview*",
    "*summary*",
    "*report*",
    "*_qc.*",
)


@dataclass(frozen=True)
class InstrumentProfile:
    """One instrument profile loaded from YAML."""

    instrument: str
    description: str
    detect_marker: str | None
    raw_extensions: frozenset[str]
    raw_patterns: tuple[str, ...]
    derived_extensions: frozenset[str]
    derived_patterns: tuple[str, ...]
    source: Path | None = field(default=None)

    def matches_marker(self, files: Iterable[str | Path]) -> bool:
        """Return True if any of ``files`` matches ``detect_marker``."""
        if not self.detect_marker:
            return False
        for f in files:
            if fnmatch.fnmatchcase(Path(f).name, self.detect_marker):
                return True
        return False

    def classify(self, name: str) -> str | None:
        """Classify ``name`` as ``"raw"`` / ``"derived"`` / ``None`` (no decision).

        Patterns and extensions are matched case-insensitively on the basename.
        Derived patterns take precedence over raw extensions, so a ``.pdf`` summary
        sitting next to ``.fastq.gz`` raw isn't accidentally promoted to raw.
        """
        base = Path(name).name
        ext = _extension(base)

        for pattern in self.derived_patterns:
            if fnmatch.fnmatchcase(base.lower(), pattern.lower()):
                return "derived"
        if ext in self.derived_extensions:
            return "derived"

        for pattern in self.raw_patterns:
            if fnmatch.fnmatchcase(base.lower(), pattern.lower()):
                return "raw"
        if ext in self.raw_extensions:
            return "raw"

        return None


def _extension(name: str) -> str:
    """Return a normalized lowercased extension for ``name``.

    Handles double extensions like ``.fastq.gz`` (returned as ``"fastq.gz"``).
    """
    lower = name.lower()
    if lower.endswith(".fastq.gz"):
        return "fastq.gz"
    if lower.endswith(".tar.gz"):
        return "tar.gz"
    parts = lower.rsplit(".", 1)
    return parts[1] if len(parts) == 2 else ""


def load_profile_file(path: Path) -> InstrumentProfile:
    """Load a single ``InstrumentProfile`` from ``path``."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        # Strip a leading frontmatter-style fence so files written like
        # `instruments/<name>.yaml` with `---` markers also parse.
        body = text.split("---", 2)
        text = body[1] if len(body) >= 3 else text
    data = yaml.safe_load(text) or {}
    raw = data.get("raw") or {}
    derived = data.get("derived") or {}
    return InstrumentProfile(
        instrument=str(data["instrument"]),
        description=str(data.get("description", "")),
        detect_marker=str(data["detect_marker"]) if data.get("detect_marker") else None,
        raw_extensions=frozenset(_norm_ext(e) for e in raw.get("extensions") or []),
        raw_patterns=tuple(raw.get("patterns") or []),
        derived_extensions=frozenset(_norm_ext(e) for e in derived.get("extensions") or []),
        derived_patterns=tuple(derived.get("patterns") or []),
        source=path,
    )


def _norm_ext(value: str) -> str:
    """Normalize an extension entry to a lowercase string without leading dot."""
    return str(value).lstrip(".").lower()


def load_profiles(
    *,
    centre_dir: Path | None = None,
    lab_dir: Path | None = None,
) -> dict[str, InstrumentProfile]:
    """Load all instrument profiles from centre (wigamig) and lab-mgmt overrides.

    Lab profiles take precedence over centre profiles with the same ``instrument``.
    Returns a dict keyed by instrument name.
    """
    profiles: dict[str, InstrumentProfile] = {}
    centre = centre_dir if centre_dir is not None else wigamig_repo_root() / INSTRUMENTS_SUBDIR
    lab = lab_dir if lab_dir is not None else lab_mgmt_repo_root() / INSTRUMENTS_SUBDIR

    for directory in (centre, lab):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            try:
                profile = load_profile_file(path)
            except (KeyError, yaml.YAMLError):
                continue
            profiles[profile.instrument] = profile
    return profiles


def detect_profile(
    profiles: dict[str, InstrumentProfile], files: Iterable[str | Path]
) -> InstrumentProfile | None:
    """Return the first profile whose ``detect_marker`` matches any of ``files``."""
    file_list = list(files)
    for profile in profiles.values():
        if profile.matches_marker(file_list):
            return profile
    return None


def generic_classify(name: str) -> str:
    """Generic-fallback classification: derived patterns/exts first, else raw.

    Returns either ``"raw"`` or ``"derived"``.
    """
    base = Path(name).name
    ext = _extension(base)
    for pattern in GENERIC_DERIVED_PATTERNS:
        if fnmatch.fnmatchcase(base.lower(), pattern.lower()):
            return "derived"
    if ext in GENERIC_DERIVED_EXTENSIONS:
        return "derived"
    return "raw"
