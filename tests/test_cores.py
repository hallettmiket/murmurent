"""
Tests for `core.cores` — the cores registry enumerator.

Covers Phase 0c of the cores rollout (docs/cores_plan.md §11):

  - iter_cores returns empty list when lab_mgmt has no cores/ dir
  - iter_cores reads frontmatter + body from cores/<name>/core.md
  - iter_cores skips files whose kind isn't "core"
  - iter_cores filters archived entries by default; include_archived=True
    surfaces them
  - get_core returns the right summary by short id
  - Malformed frontmatter is silently skipped (defensive)

Fixture mirrors the convention used by tests/test_membership.py +
tests/test_lab_config.py: a tmp_path lab_mgmt with the dirs the
modules expect.
"""

from __future__ import annotations

import pytest

from wigamig.core import cores as C


@pytest.fixture
def cores_world(monkeypatch, tmp_path):
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(tmp_path / "lab-mgmt"))
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
    (tmp_path / "lab-mgmt" / "members").mkdir(parents=True)
    (tmp_path / "lab-mgmt" / "cores").mkdir(parents=True)
    return tmp_path / "lab-mgmt"


def _write_core(lab_mgmt, name, *, leader="@biocore_leader",
                kind="core", status="active",
                display_name=None, extra=""):
    d = lab_mgmt / "cores" / name
    d.mkdir(parents=True, exist_ok=True)
    fm_lines = [
        "---",
        f"core: {name}",
        f"name: '{display_name or name.title()}'",
        f"kind: {kind}",
        f"leader: '{leader}'",
        "members:",
        f"  - '{leader}'",
        f"status: {status}",
        "capabilities:",
        "  - dummy_capability",
        "service_modes:",
        "  - independent_data_collection",
        "data_root: /tmp/test/" + name,
    ]
    if extra:
        fm_lines.append(extra)
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append(f"# {name}")
    fm_lines.append("body text")
    (d / "core.md").write_text("\n".join(fm_lines), encoding="utf-8")


# ---- iter_cores -----------------------------------------------------------

def test_iter_cores_empty_when_dir_missing(cores_world):
    (cores_world / "cores").rmdir()  # remove the dir entirely
    assert C.iter_cores() == []


def test_iter_cores_empty_when_dir_present_but_no_entries(cores_world):
    assert C.iter_cores() == []


def test_iter_cores_reads_single_core(cores_world):
    _write_core(cores_world, "biocore", display_name="BioCORE",
                leader="@biocore_leader")
    out = C.iter_cores()
    assert len(out) == 1
    c = out[0]
    assert c.name == "biocore"
    assert c.display_name == "BioCORE"
    assert c.leader == "@biocore_leader"
    assert c.members == ["@biocore_leader"]
    assert c.status == "active"
    assert "independent_data_collection" in c.service_modes
    assert c.data_root == "/tmp/test/biocore"
    assert c.body.lstrip().startswith("# biocore")


def test_iter_cores_sorted_by_name(cores_world):
    _write_core(cores_world, "zeta")
    _write_core(cores_world, "alpha")
    names = [c.name for c in C.iter_cores()]
    assert names == ["alpha", "zeta"]


def test_iter_cores_skips_kind_other_than_core(cores_world):
    """Defensive: if a stale lab.md ends up under cores/ by mistake,
    don't surface it as a core."""
    _write_core(cores_world, "real_core", kind="core")
    _write_core(cores_world, "stale_lab", kind="lab")
    names = [c.name for c in C.iter_cores()]
    assert names == ["real_core"]


def test_iter_cores_archived_excluded_by_default(cores_world):
    _write_core(cores_world, "active1", status="active")
    _write_core(cores_world, "archived1", status="archived")
    names = [c.name for c in C.iter_cores()]
    assert names == ["active1"]


def test_iter_cores_include_archived(cores_world):
    _write_core(cores_world, "active1", status="active")
    _write_core(cores_world, "archived1", status="archived")
    names = sorted(c.name for c in C.iter_cores(include_archived=True))
    assert names == ["active1", "archived1"]


def test_iter_cores_silently_skips_malformed_frontmatter(cores_world):
    """A core.md whose YAML is broken shouldn't take down the listing."""
    _write_core(cores_world, "good")
    bad_dir = cores_world / "cores" / "broken"
    bad_dir.mkdir()
    (bad_dir / "core.md").write_text(
        "---\n: invalid yaml: : :\n---\n", encoding="utf-8",
    )
    names = [c.name for c in C.iter_cores()]
    assert names == ["good"]


# ---- get_core -------------------------------------------------------------

def test_get_core_returns_match(cores_world):
    _write_core(cores_world, "biocore")
    assert C.get_core("biocore").name == "biocore"


def test_get_core_returns_none_when_missing(cores_world):
    _write_core(cores_world, "biocore")
    assert C.get_core("genomics_core") is None


def test_get_core_finds_archived(cores_world):
    _write_core(cores_world, "old", status="archived")
    # get_core uses include_archived=True so registrar tooling can still
    # rotate state on an archived core (e.g. reactivate).
    assert C.get_core("old").status == "archived"


# ---- path helpers ---------------------------------------------------------

def test_cores_dir_and_core_path(cores_world):
    assert C.cores_dir() == cores_world / "cores"
    assert C.core_path("biocore") == cores_world / "cores" / "biocore" / "core.md"
