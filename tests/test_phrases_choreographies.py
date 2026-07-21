"""Dashboard Phases B/C (#38): stating phrases to the group, and the
choreographies surface that assembles them.

Covers the core publish flow (`phrase_publish`), the snapshot readers
(`_my_phrases` / `_choreographies`), and the three endpoints (state / pose /
attach), including the candidate-key joinability gate.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from murmurent.core import phrase_contract as pc
from murmurent.core import phrase_publish as pp
from murmurent.core import phrase_spec as ps
from murmurent.dashboard import snapshot as snap
from murmurent.dashboard.server import create_app


def _author(vault, name, key, metric="m", units="u", direction="lower_better"):
    """Write a contract + spec pair into the member's vault dir."""
    c = pc.PhraseContract(phrase=name, author="@bob", question=f"Q {name}",
                          candidate_key=key, metric=metric, units=units, direction=direction)
    (vault / pc.default_contract_filename(name)).write_text(c.to_markdown(), encoding="utf-8")
    s = ps.PhraseSpec(phrase=name, author="@bob", question=f"Q {name}",
                      contract=pc.slugify(name),
                      steps=[ps.Step(name="s", kind="script", run="x.py", description="d")],
                      transitions=[ps.Transition(name="rank", kind="rank", params={})])
    (vault / ps.default_spec_filename(name)).write_text(s.to_markdown(), encoding="utf-8")


@pytest.fixture
def world(monkeypatch, tmp_path):
    vault = tmp_path / "vault"; vault.mkdir()
    home = tmp_path / "home"; home.mkdir()
    (home / "user").write_text("bob\n", encoding="utf-8")   # machine owner, no card → no gate
    group = tmp_path / "group"; (group / "members").mkdir(parents=True)
    (group / "lab.md").write_text("---\nlab: mh\nname: mh\npi: '@the_pi'\n---\n", encoding="utf-8")
    for h in ("bob", "the_pi"):
        (group / "members" / f"{h}.md").write_text(
            f"---\nhandle: '@{h}'\nrole: pi\nstatus: active\nlab: mh\n---\n", encoding="utf-8")
    monkeypatch.setenv("MURMURENT_PHRASE_SPEC_DIR", str(vault))
    monkeypatch.setenv("MURMURENT_PHRASE_CONTRACT_DIR", str(vault))
    monkeypatch.setenv("MURMURENT_LAB_MGMT_REPO", str(group))
    monkeypatch.setenv("MURMURENT_HOME", str(home))
    monkeypatch.setenv("MURMURENT_USER", "bob")
    return {"vault": vault, "group": group}


# -- core publish -----------------------------------------------------------

def test_state_copies_spec_and_contract_into_group(world):
    _author(world["vault"], "Docking affinity", "inchikey")
    assert not pp.is_stated("Docking affinity")
    res = pp.state_phrase_to_group("docking-affinity")
    assert res.spec_path.is_file() and res.contract_path.is_file()
    assert res.spec_path.parent == world["group"] / "phrases"
    assert pp.is_stated("Docking affinity")
    grp = {s.phrase: s for s in pp.list_group_phrases()}
    assert "Docking affinity" in grp
    assert grp["Docking affinity"].resolved_contract().candidate_key == "inchikey"


def test_state_refuses_phrase_without_contract(world, monkeypatch):
    # A spec whose contract reference can't resolve.
    (world["vault"] / "orphan_phrase.md").write_text(
        "---\nphrase: orphan\nauthor: '@bob'\nquestion: q\ncontract: nope\n"
        "steps:\n- name: s\n  kind: script\n  run: x.py\n---\n", encoding="utf-8")
    with pytest.raises(pp.PhrasePublishError):
        pp.state_phrase_to_group("orphan")


# -- snapshot readers -------------------------------------------------------

def test_my_phrases_reports_contract_and_stated(world):
    _author(world["vault"], "Docking affinity", "inchikey")
    rows = {r.phrase: r for r in snap._my_phrases()}
    r = rows["Docking affinity"]
    assert r.slug == "docking-affinity" and r.stated is False
    assert r.contract.candidate_key == "inchikey" and r.steps == 1 and r.transitions == 1
    pp.state_phrase_to_group("docking-affinity")
    assert snap._my_phrases()[0].stated is True


def test_choreographies_join_status_and_pool(world):
    _author(world["vault"], "Docking affinity", "inchikey")
    _author(world["vault"], "Expression delta", "gene_symbol")
    pp.state_phrase_to_group("docking-affinity")
    pp.state_phrase_to_group("expression-delta")
    from murmurent.core import choreography as ch
    cdir = world["group"] / "choreographies"; cdir.mkdir()
    obj = ch.Choreography(question="Best binders?", poser="@the_pi", title="Binders",
                          candidate_key="inchikey", criteria="lowest")
    (cdir / "best-binders.md").write_text(obj.to_markdown(), encoding="utf-8")
    row = snap._choreographies()[0]
    assert row.candidate_key == "inchikey"
    # The inchikey phrase is joinable; the gene_symbol one is not in the pool.
    pool = {j.phrase for j in row.joinable}
    assert "Docking affinity" in pool and "Expression delta" not in pool


# -- endpoints --------------------------------------------------------------

def test_endpoints_state_pose_attach_flow(world):
    _author(world["vault"], "Docking affinity", "inchikey")
    client = TestClient(create_app())

    assert client.post("/api/phrases/docking-affinity/state").json()["ok"] is True
    r = client.post("/api/choreography", json={
        "question": "Best binders for X?", "title": "X binders",
        "candidate_key": "inchikey", "criteria": "lowest score"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert client.post(f"/api/choreography/{cid}/attach?phrase=docking-affinity").json()["attached"] is True

    ch = client.get("/api/dashboard").json()["choreographies"]
    assert ch[0]["all_join"] is True
    assert [a["phrase"] for a in ch[0]["attached"]] == ["Docking affinity"]


def test_attach_rejects_non_joining_phrase(world):
    _author(world["vault"], "Docking affinity", "inchikey")
    _author(world["vault"], "Expression delta", "gene_symbol")
    client = TestClient(create_app())
    client.post("/api/phrases/docking-affinity/state")
    client.post("/api/phrases/expression-delta/state")
    cid = client.post("/api/choreography", json={
        "question": "Best binders?", "title": "Binders",
        "candidate_key": "inchikey", "criteria": "lowest"}).json()["id"]
    # gene_symbol phrase must NOT join an inchikey choreography.
    r = client.post(f"/api/choreography/{cid}/attach?phrase=expression-delta")
    assert r.status_code == 422
    assert "join" in r.json()["detail"].lower()


def test_pose_rejects_missing_fields(world):
    client = TestClient(create_app())
    r = client.post("/api/choreography", json={
        "question": "q", "title": "t", "candidate_key": "", "criteria": "c"})
    assert r.status_code == 422
