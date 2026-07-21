"""Tests for member-side lab_mgmt clone self-discovery.

A MEMBER machine has no ``MURMURENT_LAB_MGMT_REPO`` env var and no pinned
pointer (they never ran pi-init), and their natural clone lands at
``~/repos/murmurent_lab_mgmt_<lab>`` — the repo's real name — not
``~/repos/lab_mgmt``. Before self-healing, ``lab_mgmt_repo_root()``
resolved to a non-existent default and the Lab Members roster was empty.

These pin the discovery contract:
  * a lone natural-name clone is discovered AND pinned (runs once)
  * two candidate clones are ambiguous → no auto-pin, default fallback
  * an explicit env var still wins over discovery
  * an existing pinned pointer still wins over discovery
"""

from __future__ import annotations

from pathlib import Path

import pytest

from murmurent.core import repo as _repo


def _make_clone(root: Path, name: str, *, members: list[str]) -> Path:
    """Create a plausible lab_mgmt clone (lab.md + members/<h>.md) under root."""
    clone = root / name
    (clone / "members").mkdir(parents=True)
    lab = name.replace("murmurent_lab_mgmt_", "")
    (clone / "lab.md").write_text(
        f"---\nlab: {lab}\nname: {lab.title()} Lab\npi: '@the_pi'\n---\n",
        encoding="utf-8")
    for h in members:
        (clone / "members" / f"{h}.md").write_text(
            f"---\nhandle: '@{h}'\nfull_name: '{h.title()}'\n"
            "role: postdoc\nstatus: active\n---\n",
            encoding="utf-8")
    return clone


@pytest.fixture
def member_machine(monkeypatch, tmp_path):
    """A member machine: isolated repos root + MURMURENT_HOME, no env/pin,
    and the two default paths forced to not-exist so discovery is reached."""
    repos = tmp_path / "repos"
    repos.mkdir()
    wig_home = tmp_path / "wig_home"
    monkeypatch.setenv("MURMURENT_REPOS_ROOT", str(repos))
    monkeypatch.setenv("MURMURENT_HOME", str(wig_home))
    monkeypatch.delenv("MURMURENT_LAB_MGMT_REPO", raising=False)
    monkeypatch.setenv("MURMURENT_USER", "bob")
    # Force the built-in defaults to miss so we exercise discovery.
    monkeypatch.setattr(_repo, "DEFAULT_LAB_MGMT_REPO", tmp_path / "no_default")
    monkeypatch.setattr(_repo, "LEGACY_LAB_MGMT_REPO", tmp_path / "no_legacy")
    return repos


def test_discovery_finds_and_pins_natural_name_clone(member_machine):
    clone = _make_clone(member_machine, "murmurent_lab_mgmt_mh",
                        members=["the_pi", "allie", "bob"])

    resolved = _repo.lab_mgmt_repo_root()
    assert resolved == clone

    # It pinned, so the pointer now exists and points at the clone...
    pointer = _repo._lab_mgmt_pointer_path()
    assert pointer.is_file()
    assert pointer.read_text(encoding="utf-8").strip() == str(clone)

    # ...and a second resolution takes the pinned branch (idempotent).
    assert _repo.lab_mgmt_repo_root() == clone


def test_two_candidate_clones_are_ambiguous_no_pin(member_machine):
    # Both clones contain the viewer (bob) → nothing distinguishes them.
    _make_clone(member_machine, "murmurent_lab_mgmt_mh", members=["the_pi", "bob"])
    _make_clone(member_machine, "murmurent_lab_mgmt_bioinformatics", members=["core_lead", "bob"])

    resolved = _repo.lab_mgmt_repo_root()
    # Ambiguous → fall through to the (non-existent) default, no guessing.
    assert resolved == _repo.DEFAULT_LAB_MGMT_REPO
    assert not _repo._lab_mgmt_pointer_path().exists()


def test_handle_match_breaks_the_tie(member_machine):
    """Two clones, but only one has the viewer in its roster → unique hit."""
    mine = _make_clone(member_machine, "murmurent_lab_mgmt_mh",
                       members=["the_pi", "bob"])
    _make_clone(member_machine, "murmurent_lab_mgmt_bioinformatics",
                members=["core_lead", "steve"])

    assert _repo.lab_mgmt_repo_root() == mine
    assert _repo._lab_mgmt_pointer_path().is_file()


def test_env_var_still_wins_over_discovery(member_machine, tmp_path):
    _make_clone(member_machine, "murmurent_lab_mgmt_mh", members=["bob"])
    explicit = tmp_path / "explicit-lab-mgmt"
    explicit.mkdir()
    import os
    os.environ["MURMURENT_LAB_MGMT_REPO"] = str(explicit)
    try:
        assert _repo.lab_mgmt_repo_root() == explicit
        # Env wins BEFORE discovery runs → no pin written.
        assert not _repo._lab_mgmt_pointer_path().exists()
    finally:
        os.environ.pop("MURMURENT_LAB_MGMT_REPO", None)


def test_pinned_pointer_still_wins_over_discovery(member_machine, tmp_path):
    _make_clone(member_machine, "murmurent_lab_mgmt_mh", members=["bob"])
    already = tmp_path / "already-pinned"
    already.mkdir()
    _repo.set_lab_mgmt_path(already)  # e.g. a prior pi-init or discovery run

    assert _repo.lab_mgmt_repo_root() == already


# --- registry-authoritative net (#31/#33: canonical resolution, no legacy name) -----

def test_registry_owner_claim_wins_over_discovery_even_when_absent(
    member_machine, tmp_path, monkeypatch
):
    """The machine owner's registered group is authoritative: it outranks
    shape-discovery AND is returned even when the clone isn't on disk yet — the
    honest answer that never silently resolves to some other lab's roster."""
    # A discoverable clone exists on disk (bob is in it)...
    _make_clone(member_machine, "murmurent_lab_mgmt_bioinformatics", members=["bob"])
    # ...but the registry claims bob for a DIFFERENT (not-yet-cloned) lab.
    from murmurent.core import registrar as _reg
    registry_path = tmp_path / "canonical" / "murmurent_lab_mgmt_mh"
    monkeypatch.setattr(
        _reg, "resolve_viewer_lab_mgmt",
        lambda handle, env=None: ("mh", str(registry_path)),
    )

    resolved = _repo.lab_mgmt_repo_root()
    assert resolved == registry_path          # registry beats discovery...
    assert not registry_path.exists()         # ...and is returned though absent.


def test_registry_miss_falls_through_to_discovery(member_machine, monkeypatch):
    """No registry claim → discovery still self-heals the member machine."""
    clone = _make_clone(member_machine, "murmurent_lab_mgmt_mh", members=["bob"])
    from murmurent.core import registrar as _reg
    monkeypatch.setattr(_reg, "resolve_viewer_lab_mgmt", lambda handle, env=None: None)

    assert _repo.lab_mgmt_repo_root() == clone


def test_pre_convention_repos_lab_mgmt_resolved_by_shape_not_name(
    member_machine, monkeypatch
):
    """An un-migrated clone literally named ``lab_mgmt`` still resolves — via
    SHAPE (lab.md + members/), the same path as any canonical clone. Proves
    dropping the hardcoded name doesn't strand the couple of un-migrated users."""
    legacy = _make_clone(member_machine, "lab_mgmt", members=["bob"])
    from murmurent.core import registrar as _reg
    monkeypatch.setattr(_reg, "resolve_viewer_lab_mgmt", lambda handle, env=None: None)

    assert _repo.lab_mgmt_repo_root() == legacy


def test_last_resort_default_is_canonical_never_repos_lab_mgmt():
    """The honest last-resort default follows the ``murmurent_lab_mgmt`` naming
    convention and is never the pre-convention ``~/repos/lab_mgmt`` — that path
    is no longer one murmurent ever falls back to (#31/#33)."""
    default = _repo.DEFAULT_LAB_MGMT_REPO
    assert default.name == "murmurent_lab_mgmt"
    assert default != Path("~/repos/lab_mgmt").expanduser()
