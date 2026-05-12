"""Tests for the Phase A registrar layer.

Covers:
  - ``is_registrar`` honours the sentinel file
  - Registry I/O round-trip (read → write → read)
  - ``bootstrap_from_existing_lab_mgmt`` idempotency + lab.md reading
  - ``build_registrar_response`` follows pointers, deduplicates members,
    and surfaces unresolved entries without crashing
  - ``GET /api/registrar/dashboard`` gates on identity (403 for non-registrar)
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from wigamig.core import registrar
from wigamig.core.registrar import (
    CollaborationEntry,
    CoreEntry,
    LabEntry,
    Registry,
)
from wigamig.dashboard import registrar_snapshot as rs
from wigamig.dashboard.server import create_app


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    """Redirect every registrar-touched path into tmp_path."""
    monkeypatch.setenv("WIGAMIG_LAB_INFO_ROOT", str(tmp_path / "lab_info"))
    monkeypatch.setattr(
        registrar, "REGISTRAR_SENTINEL", tmp_path / "registrar_sentinel"
    )
    # Also block other resolvers so the test doesn't leak the real user.
    monkeypatch.setenv("WIGAMIG_USER", "mhallet")
    return tmp_path


def _make_lab_mgmt(root: Path, *, lab_id: str, pi: str, members: list[tuple[str, str]]) -> Path:
    """Scaffold a fake lab-mgmt repo with lab.md and members/."""
    lab_dir = root / f"{lab_id}-lab-mgmt"
    (lab_dir / "members").mkdir(parents=True)
    (lab_dir / "lab.md").write_text(
        "---\n"
        f"lab: {lab_id}\n"
        f"name: {lab_id.title()} Lab\n"
        f"pi: '@{pi}'\n"
        "institution: Western University\n"
        "created: 2026-01-01\n"
        "---\n\n# the lab\n",
        encoding="utf-8",
    )
    for handle, role in members:
        (lab_dir / "members" / f"{handle}.md").write_text(
            "---\n"
            f"handle: '@{handle}'\n"
            f"full_name: {handle.title()}\n"
            f"role: {role}\n"
            "status: active\n"
            "certifications:\n  - TCPS_2:2030-12-31\n"
            "---\n",
            encoding="utf-8",
        )
    return lab_dir


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def test_is_registrar_false_when_sentinel_missing(isolated):
    assert registrar.is_registrar("mhallet") is False
    assert registrar.registrar_handle() is None


def test_is_registrar_true_for_declared_handle(isolated):
    registrar.REGISTRAR_SENTINEL.write_text("mhallet\n", encoding="utf-8")
    assert registrar.registrar_handle() == "mhallet"
    assert registrar.is_registrar("mhallet") is True
    assert registrar.is_registrar("@mhallet") is True
    assert registrar.is_registrar("MHALLET") is True
    assert registrar.is_registrar("bob") is False


def test_is_registrar_ignores_blank_lines(isolated):
    registrar.REGISTRAR_SENTINEL.write_text("\n\n  mhallet  \n# comment\n", encoding="utf-8")
    assert registrar.registrar_handle() == "mhallet"


# ---------------------------------------------------------------------------
# Registry I/O
# ---------------------------------------------------------------------------


def test_read_registry_empty_when_file_missing(isolated):
    reg = registrar.read_registry()
    assert reg.labs == []
    assert reg.cores == []
    assert reg.collaborations == []


def test_registry_round_trip(isolated):
    original = Registry(
        labs=[
            LabEntry(name="hallett", pi="@mhallet",
                     lab_mgmt_path="/tmp/x", status="active",
                     created="2026-05-08", github_org="hallettmiket"),
        ],
        cores=[
            CoreEntry(name="imaging", pi="@cassie",
                      lab_mgmt_path="/tmp/y", status="active"),
        ],
        collaborations=[
            CollaborationEntry(
                name="dcis_imaging",
                pis=["@mhallet", "@cassie"],
                groups=["hallett", "imaging"],
                member_subset={"hallett": ["@allie"], "imaging": ["@bob"]},
            ),
        ],
    )
    registrar.write_registry(original)
    reread = registrar.read_registry()

    assert [l.name for l in reread.labs] == ["hallett"]
    assert reread.labs[0].pi == "@mhallet"
    assert reread.labs[0].github_org == "hallettmiket"
    assert [c.name for c in reread.cores] == ["imaging"]
    assert reread.collaborations[0].pis == ["@mhallet", "@cassie"]
    assert reread.collaborations[0].member_subset == {
        "hallett": ["@allie"], "imaging": ["@bob"],
    }


def test_read_registry_skips_malformed_entries(isolated):
    """One bad section shouldn't blank the whole registrar dashboard."""
    bad = {
        "version": 1,
        "labs": {
            "good": {"pi": "@x", "lab_mgmt_path": "/tmp/x"},
            "bad": "not a dict — should be skipped",
        },
    }
    registrar.registry_path().parent.mkdir(parents=True)
    registrar.registry_path().write_text(yaml.safe_dump(bad), encoding="utf-8")
    reg = registrar.read_registry()
    assert [l.name for l in reg.labs] == ["good"]


def test_read_registry_handles_completely_malformed_yaml(isolated):
    registrar.registry_path().parent.mkdir(parents=True)
    registrar.registry_path().write_text(": : :\n", encoding="utf-8")
    reg = registrar.read_registry()
    assert reg.labs == []  # fail safe — not a crash


# ---------------------------------------------------------------------------
# bootstrap_from_existing_lab_mgmt
# ---------------------------------------------------------------------------


def test_bootstrap_reads_labmd_and_seeds_registry(isolated, tmp_path):
    lab_dir = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi"), ("bob", "postdoc")],
    )
    reg = registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    assert [l.name for l in reg.labs] == ["hallett"]
    assert reg.labs[0].pi == "@mhallet"
    assert reg.labs[0].lab_mgmt_path == str(lab_dir)


def test_bootstrap_is_idempotent(isolated, tmp_path):
    lab_dir = _make_lab_mgmt(tmp_path, lab_id="hallett", pi="mhallet", members=[])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    reg = registrar.read_registry()
    assert len(reg.labs) == 1  # not duplicated


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------


def test_snapshot_renders_lab_with_members(isolated, tmp_path):
    lab_dir = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi"), ("bob", "postdoc"), ("cassie", "student")],
    )
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)

    resp = rs.build_registrar_response("mhallet")
    assert resp.registrar_handle == "@mhallet"
    assert len(resp.labs) == 1
    lab = resp.labs[0]
    assert lab.name == "hallett"
    assert lab.display_name == "Hallett Lab"
    assert lab.member_count == 3
    assert {m.handle for m in lab.members} == {"@mhallet", "@bob", "@cassie"}
    assert lab.unresolved is False
    assert resp.stats.total_labs == 1
    assert resp.stats.total_members == 3


def test_snapshot_dedupes_members_across_labs(isolated, tmp_path):
    lab_a = _make_lab_mgmt(
        tmp_path, lab_id="hallett", pi="mhallet",
        members=[("mhallet", "pi"), ("bob", "postdoc")],
    )
    lab_b = _make_lab_mgmt(
        tmp_path, lab_id="other", pi="otherpi",
        members=[("otherpi", "pi"), ("bob", "postdoc")],  # bob is in both
    )
    registrar.write_registry(Registry(labs=[
        LabEntry(name="hallett", pi="@mhallet", lab_mgmt_path=str(lab_a)),
        LabEntry(name="other", pi="@otherpi", lab_mgmt_path=str(lab_b)),
    ]))
    resp = rs.build_registrar_response("mhallet")
    # mhallet, bob, otherpi — deduped → 3 unique members
    assert resp.stats.total_members == 3
    assert resp.stats.total_labs == 2


def test_snapshot_flags_unresolved_pointer(isolated):
    registrar.write_registry(Registry(labs=[
        LabEntry(name="ghost", pi="@nobody", lab_mgmt_path="/does/not/exist"),
    ]))
    resp = rs.build_registrar_response("mhallet")
    assert len(resp.labs) == 1
    assert resp.labs[0].unresolved is True
    assert "does not exist" in (resp.labs[0].unresolved_reason or "")


def test_snapshot_never_reads_notebooks_or_oracles(isolated, tmp_path, monkeypatch):
    """Hard contract: the registrar dashboard must NOT call into
    notebook / oracle / sea / inventory snapshot helpers."""
    lab_dir = _make_lab_mgmt(tmp_path, lab_id="hallett", pi="mhallet", members=[])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)

    # If we ever start importing these in registrar_snapshot, the test
    # will trip — guards against accidental leakage of lab-private data
    # into the centre-level dashboard.
    blocked = []
    def _sentinel(*a, **k):
        blocked.append("called")
        raise AssertionError("registrar must not access lab-private data")

    from wigamig.dashboard import snapshot as lab_snap
    for name in ("_notebook", "_personal_oracle", "_oracle_recent",
                 "_inventory", "_seas"):
        monkeypatch.setattr(lab_snap, name, _sentinel, raising=False)

    # Should succeed without ever calling those.
    rs.build_registrar_response("mhallet")
    assert blocked == []


# ---------------------------------------------------------------------------
# Endpoint gate
# ---------------------------------------------------------------------------


def test_endpoint_403_when_not_registrar(isolated):
    """Without a registrar sentinel, the endpoint must refuse."""
    client = TestClient(create_app())
    res = client.get("/api/registrar/dashboard")
    assert res.status_code == 403
    assert "registrar" in res.text.lower()


def test_endpoint_200_when_registrar(isolated, tmp_path):
    registrar.REGISTRAR_SENTINEL.write_text("mhallet\n", encoding="utf-8")
    lab_dir = _make_lab_mgmt(tmp_path, lab_id="hallett", pi="mhallet", members=[("mhallet", "pi")])
    registrar.bootstrap_from_existing_lab_mgmt(lab_mgmt_path=lab_dir)
    client = TestClient(create_app())
    res = client.get("/api/registrar/dashboard")
    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["registrar_handle"] == "@mhallet"
    assert len(payload["labs"]) == 1
    assert payload["labs"][0]["name"] == "hallett"


def test_endpoint_user_override_query_param(isolated):
    """``?user=bob`` against a sentinel of ``mhallet`` must still 403."""
    registrar.REGISTRAR_SENTINEL.write_text("mhallet\n", encoding="utf-8")
    client = TestClient(create_app())
    res = client.get("/api/registrar/dashboard?user=bob")
    assert res.status_code == 403
