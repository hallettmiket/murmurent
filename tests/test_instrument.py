"""Tests for :mod:`murmurent.core.instrument`."""

from __future__ import annotations

from pathlib import Path

from murmurent.core.instrument import (
    GENERIC_DERIVED_PATTERNS,
    detect_profile,
    generic_classify,
    load_profile_file,
    load_profiles,
)


def test_load_illumina_profile():
    """The shipped illumina-novaseq.yaml parses and classifies."""
    repo_root = Path(__file__).resolve().parent.parent
    profile_path = repo_root / "instruments" / "illumina-novaseq.yaml"
    assert profile_path.is_file()
    profile = load_profile_file(profile_path)
    assert profile.instrument == "illumina-novaseq"
    assert profile.classify("S001_R1.fastq.gz") == "raw"
    assert profile.classify("RunInfo.xml") == "raw"
    assert profile.classify("run_qc.html") == "derived"
    assert profile.classify("run_summary.pdf") == "derived"
    assert profile.classify("run_thumbnail_001.png") == "derived"
    assert profile.classify("notes.txt") is None


def test_detect_profile_with_marker(tmp_path):
    repo_root = Path(__file__).resolve().parent.parent
    profiles = load_profiles(centre_dir=repo_root / "instruments")
    found = detect_profile(profiles, [Path("S001_R1.fastq.gz")])
    assert found is not None and found.instrument == "illumina-novaseq"
    none = detect_profile(profiles, [Path("notes.txt")])
    assert none is None


def test_generic_fallback():
    assert generic_classify("strange.bin") == "raw"
    assert generic_classify("run_summary.pdf") == "derived"
    assert generic_classify("preview_chip.png") == "derived"


def test_generic_patterns_include_qc():
    """The generic fallback covers `_qc.*` per the design."""
    assert any("_qc" in p for p in GENERIC_DERIVED_PATTERNS)
