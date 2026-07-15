"""
Tests for the member-machine half of identity-card import: the registry's
``lab_mgmt_path`` must point at the member's REAL lab_mgmt clone whenever one
exists, and the synthesized one-person stub must never shadow it.

Regression context (2026-07): a member (@nsimsam, lab ``mh``) imported her card
and her dashboard listed only herself. ``import_card`` had materialized a stub
under ``lab_info/labs/mh/lab-mgmt/`` holding a single member record (her own)
and pointed the registry at it. The dashboard enters
``repo.use_lab_mgmt_root(<registry lab_mgmt_path>)`` per request — step 1 of
``repo.lab_mgmt_repo_root()``'s resolution order — so the stub shadowed her real
read-only clone and ``_discover_lab_mgmt_clone()`` could never rescue it. Her
only escape was hand-editing ``lab_mgmt_path``.
"""

from __future__ import annotations

import pytest

from murmurent.core import centre_init as CI
from murmurent.core import identity_card as IC
from murmurent.core import registrar as R


ROSTER = ("yxia266", "vick", "noorish")


@pytest.fixture
def mayor_world(monkeypatch, tmp_path):
    """The MAYOR's machine: a centre registry with a lab whose roster has 3 people."""
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / "mayor_lab_info"))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(tmp_path / "mayor_lab_mgmt"))
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "mayor_home"))
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL", tmp_path / "sentinel")
    CI.init_centre(name="Western QA", institution="U", founding_mayor="@tbrowne5",
                   unique_name="western-qa", write_sentinel=False)
    R.create_lab(name="yxia_lab", display_name="Xia Lab",
                 pi_handle="@yxia266", pi_email="y@x.edu")
    # The PI's lab_mgmt (mayor side) carries the whole roster, so build_card's
    # member probe finds @noorish.
    _write_roster(R.read_registry().labs[0].lab_mgmt_path, "yxia_lab")
    return tmp_path


def _write_roster(lab_mgmt_dir, group: str, handles=ROSTER) -> None:
    from pathlib import Path
    d = Path(lab_mgmt_dir)
    (d / "members").mkdir(parents=True, exist_ok=True)
    for h in handles:
        (d / "members" / f"{h}.md").write_text(
            f"---\nhandle: '@{h}'\nstatus: active\nlab: {group}\n---\n\n# @{h}\n",
            encoding="utf-8")


def _make_real_clone(repos_root, group: str, handles=ROSTER, name: str | None = None):
    """A member's read-only lab_mgmt clone: lab.md + full members/ + .git."""
    from pathlib import Path
    root = Path(repos_root)
    clone = root / (name or f"murmurent_lab_mgmt_{group}")
    (clone / ".git").mkdir(parents=True, exist_ok=True)
    clone.joinpath("lab.md").write_text(
        f"---\nlab: {group}\nname: Xia Lab\npi: '@yxia266'\nkind: lab\n---\n\n# Xia Lab\n",
        encoding="utf-8")
    _write_roster(clone, group, handles)
    return clone


def _become_member(monkeypatch, tmp_path, netname: str):
    """Move to a FRESH member machine: own home, own lab_info, own repos root.

    Critically, ``MURMURENT_LAB_MGMT_REPO`` is unset — a member never exports it
    (they never ran pi-init), which is exactly the machine shape that lets the
    registry's ``lab_mgmt_path`` decide what their dashboard sees.
    """
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / f"{netname}_home"))
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(tmp_path / f"{netname}_lab_info"))
    monkeypatch.setenv("MURMURENT_REPOS_ROOT", str(tmp_path / f"{netname}_repos"))
    monkeypatch.delenv("MURMURENT_LAB_MGMT_REPO", raising=False)
    repos = tmp_path / f"{netname}_repos"
    repos.mkdir(parents=True, exist_ok=True)
    return repos


# ---- the reported bug --------------------------------------------------

def test_import_card_points_at_real_clone_not_stub(mayor_world, monkeypatch, tmp_path):
    """A member with a real clone on disk gets the registry pointed AT it."""
    card = IC.build_card("noorish", issued_by="@tbrowne5")
    assert any(r["kind"] == "member" and r["group"] == "yxia_lab" for r in card["roles"])

    repos = _become_member(monkeypatch, tmp_path, "noorish")
    clone = _make_real_clone(repos, "yxia_lab")

    IC.import_card(card)

    match = R.lab_mgmt_path_for_handle("noorish")
    assert match is not None and match[0] == "yxia_lab"
    from pathlib import Path
    assert Path(match[1]).resolve() == clone.resolve(), (
        f"registry points at {match[1]} — a stub shadowing the real clone at {clone}")


def test_member_dashboard_sees_whole_roster_not_just_themselves(
        mayor_world, monkeypatch, tmp_path):
    """The end-to-end symptom Noor reported: roster of 1 instead of 3."""
    from murmurent.core import membership as M
    from murmurent.core import repo as _repo

    card = IC.build_card("noorish", issued_by="@tbrowne5")
    repos = _become_member(monkeypatch, tmp_path, "noorish")
    _make_real_clone(repos, "yxia_lab")
    IC.import_card(card)

    # Exactly what dashboard/server.py does per request.
    match = R.lab_mgmt_path_for_handle("noorish")
    with _repo.use_lab_mgmt_root(match[1] if match else None):
        handles = {m.handle.lstrip("@") for m in M.iter_members()}
    assert handles == set(ROSTER), f"member sees roster {handles}, expected {set(ROSTER)}"


def test_import_card_finds_non_canonically_named_clone(mayor_world, monkeypatch, tmp_path):
    """Noor's actual clone is ``~/repos/lab_mgmt`` (the old documented name).
    Discovery matches on SHAPE (lab.md + members/), so it must still be found."""
    card = IC.build_card("noorish", issued_by="@tbrowne5")
    repos = _become_member(monkeypatch, tmp_path, "noorish")
    clone = _make_real_clone(repos, "yxia_lab", name="lab_mgmt")

    IC.import_card(card)

    from pathlib import Path
    match = R.lab_mgmt_path_for_handle("noorish")
    assert match is not None
    assert Path(match[1]).resolve() == clone.resolve()


# ---- the stub is still a valid last resort -----------------------------

def test_import_card_still_stubs_when_no_clone_exists(mayor_world, monkeypatch, tmp_path):
    """No clone yet (invite not accepted / offline): the stub keeps is_member
    resolving so the member isn't locked out of their own dashboard."""
    card = IC.build_card("noorish", issued_by="@tbrowne5")
    _become_member(monkeypatch, tmp_path, "noorish")  # empty repos root

    IC.import_card(card)

    match = R.lab_mgmt_path_for_handle("noorish")
    assert match is not None and match[0] == "yxia_lab"
    from pathlib import Path
    assert (Path(match[1]) / "members" / "noorish.md").is_file()


def test_clone_that_does_not_list_the_member_is_not_preferred(
        mayor_world, monkeypatch, tmp_path):
    """A clone whose roster lacks the member (PI hasn't pushed their record yet,
    or they cloned early) must NOT be adopted: `is_member` would resolve False
    and the scoping gate would refuse them their own dashboard. The stub — whose
    whole job is making `is_member` resolve — is the better answer here."""
    from pathlib import Path
    card = IC.build_card("noorish", issued_by="@tbrowne5")
    repos = _become_member(monkeypatch, tmp_path, "noorish")
    _make_real_clone(repos, "yxia_lab", handles=("yxia266", "vick"))  # no noorish

    IC.import_card(card)

    match = R.lab_mgmt_path_for_handle("noorish")
    assert match is not None and match[0] == "yxia_lab", "member locked out of own lab"
    assert (Path(match[1]) / "members" / "noorish.md").is_file()


# ---- self-heal: machines already broken in the field -------------------

def _break_machine(mayor_card, monkeypatch, tmp_path, *, legacy: bool):
    """Reproduce a member machine carded BEFORE the fix: registry → stub.

    ``legacy=True`` strips the stub marker, which is the true field state on
    @nsimsam's / @vgupta88's machines — their stubs predate the marker, so the
    heal has to recognise them by shape alone.
    """
    from pathlib import Path
    from murmurent.core import repo as _repo

    repos = _become_member(monkeypatch, tmp_path, "noorish")
    IC.import_card(mayor_card)  # no clone on disk yet → stub
    stub = Path(R.lab_mgmt_path_for_handle("noorish")[1])
    assert _repo.is_card_import_stub(stub)
    if legacy:
        (stub / _repo.CARD_STUB_MARKER).unlink()
        assert _repo.is_card_import_stub(stub), "shape heuristic must still catch it"
    return repos, stub


@pytest.mark.parametrize("legacy", [True, False], ids=["legacy_stub", "marked_stub"])
def test_stub_self_heals_once_a_real_clone_appears(
        mayor_world, monkeypatch, tmp_path, legacy):
    """The Noor recovery path: she clones the repo, and the NEXT dashboard load
    repoints her registry at it. No hand-editing of lab_mgmt_path."""
    from pathlib import Path
    card = IC.build_card("noorish", issued_by="@tbrowne5")
    repos, stub = _break_machine(card, monkeypatch, tmp_path, legacy=legacy)

    # Broken state: the member sees only herself.
    assert R.lab_mgmt_path_for_handle("noorish")[1] == str(stub)

    # She clones the roster repo. Next resolution heals.
    clone = _make_real_clone(repos, "yxia_lab")
    match = R.resolve_viewer_lab_mgmt("noorish")
    assert match is not None
    assert Path(match[1]).resolve() == clone.resolve()

    # ...and it is PERSISTED, so the repair happens once, not every request.
    assert Path(R.lab_mgmt_path_for_handle("noorish")[1]).resolve() == clone.resolve()


def test_self_heal_survives_noors_non_canonical_clone_name(
        mayor_world, monkeypatch, tmp_path):
    """Noor cloned to ``~/repos/lab_mgmt``, not the canonical
    ``~/repos/murmurent_lab_mgmt_<lab>``. Shape-based discovery must heal it."""
    from pathlib import Path
    card = IC.build_card("noorish", issued_by="@tbrowne5")
    repos, _ = _break_machine(card, monkeypatch, tmp_path, legacy=True)
    clone = _make_real_clone(repos, "yxia_lab", name="lab_mgmt")

    match = R.resolve_viewer_lab_mgmt("noorish")
    assert Path(match[1]).resolve() == clone.resolve()


def test_no_clone_means_no_heal_and_no_lockout(mayor_world, monkeypatch, tmp_path):
    """A member who hasn't accepted the GitHub invite keeps their stub and
    still resolves as a member — degrade gracefully, never 403."""
    card = IC.build_card("noorish", issued_by="@tbrowne5")
    _break_machine(card, monkeypatch, tmp_path, legacy=True)

    match = R.resolve_viewer_lab_mgmt("noorish")
    assert match is not None and match[0] == "yxia_lab"


def test_heal_never_touches_a_pi_entry(mayor_world, monkeypatch, tmp_path):
    """A registrar-scaffolded lab on the PI's own machine is stub-SHAPED (under
    lab_info, no .git, one-person roster) but is authoritative. Healing it would
    repoint a PI at some unrelated clone — guard: card role must be `member`."""
    from pathlib import Path
    card = IC.build_card("yxia266", issued_by="@tbrowne5")   # the PI
    assert any(r["kind"] == "lab_pi" for r in card["roles"])

    repos = _become_member(monkeypatch, tmp_path, "yxia266")
    # A decoy clone sits in repos_root; the PI entry must ignore it.
    _make_real_clone(repos, "yxia_lab")
    IC.import_card(card)
    before = R.lab_mgmt_path_for_handle("yxia266")[1]
    # Force the stub-shaped case: point the PI entry at a lab_info lab-mgmt.
    R._repoint_lab_mgmt_path("yxia_lab", "labs", str(tmp_path / "yxia266_lab_info"
                                                     / "labs" / "yxia_lab" / "lab-mgmt"))
    pi_path = R.lab_mgmt_path_for_handle("yxia266")[1]
    assert R.resolve_viewer_lab_mgmt("yxia266")[1] == pi_path, "PI entry was healed"
    assert before  # sanity


def test_member_dashboard_self_heals_end_to_end(mayor_world, monkeypatch, tmp_path):
    """The whole reported symptom, through the real HTTP surface: a broken
    machine + a clone on disk → the dashboard serves the full roster."""
    from fastapi.testclient import TestClient
    from murmurent.dashboard.server import create_app

    card = IC.build_card("noorish", issued_by="@tbrowne5")
    repos, _ = _break_machine(card, monkeypatch, tmp_path, legacy=True)
    _make_real_clone(repos, "yxia_lab")

    client = TestClient(create_app())
    res = client.get("/api/dashboard?user=noorish")
    assert res.status_code == 200, res.text
    handles = {h.lstrip("@") for h in (res.json().get("group_members") or [])}
    assert handles == set(ROSTER), f"dashboard roster {handles}, expected {set(ROSTER)}"
