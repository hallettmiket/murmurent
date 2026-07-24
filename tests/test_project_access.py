"""Tests for core.project_access — the PROJECT-LEVEL access check (issue #95
Phase 4; also the deferred project-level slice of #63 item 2/3).

The check is a lead/PI standing pass: for every project the viewer LEADS, does
each project MEMBER still have read (and, for append_only + repos, write) access
to the project's governed data directories? These tests use real tmp_path dirs
(so the POSIX-mode evaluation runs against a real ``stat``) with an injected
member->OS-user resolver + OS-identity resolver, so no real ``pwd``/``grp`` or
roster is needed. They assert:

  * a member who cannot READ a project dir -> warn finding (BLOCK on clinical);
  * a member with correct access -> ok finding;
  * an unknown member->OS-user mapping -> unverifiable finding;
  * the check NEVER mutates directory permissions.
"""

from __future__ import annotations

import os
import stat as _stat
from pathlib import Path

import pytest

from murmurent.core import cert_projects as CP
from murmurent.core import lab_vm as LAB_VM
from murmurent.core import project_access as PACC
from murmurent.core.project_access import Access, OsIdentity


# ---------------------------------------------------------------------------
# builders
# ---------------------------------------------------------------------------


def _proj(name="proj1", *, lead="@alice", members=("@alice", "@bob"),
          sensitivity="standard", repos=(), lab="hallett"):
    return CP.CertProject(name=name, lab=lab, status="active", lead=lead,
                          sensitivity=sensitivity, members=tuple(members),
                          repos=tuple(repos))


@pytest.fixture()
def data_root(monkeypatch, tmp_path):
    """A tmp data root with immutable/ + append_only/ for ``proj1``."""
    root = tmp_path / "data"
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(root))
    imm = root / "immutable" / "proj1"
    app = root / "append_only" / "proj1"
    imm.mkdir(parents=True)
    app.mkdir(parents=True)
    return root, imm, app


def _owner_ident() -> OsIdentity:
    """An identity that OWNS whatever the test process creates (uid = current)."""
    return OsIdentity(name="alice", uid=os.getuid(),
                      gids=frozenset({os.getgid()}), group_names=frozenset())


def _stranger_ident() -> OsIdentity:
    """An identity that is neither owner nor in the owning group — falls to the
    'other' POSIX class."""
    return OsIdentity(name="bob", uid=os.getuid() + 4242,
                      gids=frozenset({os.getgid() + 4242}),
                      group_names=frozenset({"strangers"}))


def _resolver(mapping: dict[str, "str | None"]):
    """Build an os_user_resolver from a {handle: os_user-or-None} map."""
    return lambda h: mapping.get(PACC._norm(h))


def _idents(mapping: dict[str, "OsIdentity | None"]):
    """Build an os_identity_resolver from an {os_user: OsIdentity-or-None} map."""
    return lambda u: mapping.get(u)


# ---------------------------------------------------------------------------
# member who cannot READ -> warn (block on clinical)
# ---------------------------------------------------------------------------


def test_member_cannot_read_warns(data_root):
    _root, imm, app = data_root
    # Lock the immutable dir to owner-only so a stranger cannot read it.
    imm.chmod(0o700)
    app.chmod(0o770)
    p = _proj(members=("@bob",))
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"bob": "bob"}),
        os_identity_resolver=_idents({"bob": _stranger_ident()}))
    no_read = [f for f in out if f.rule == "PROJECT-ACCESS-NO-READ-01"]
    assert no_read, "expected a NO-READ finding for the locked-out member"
    assert all(f.severity == "warn" for f in no_read)
    assert any(str(imm) == f.path for f in no_read)
    assert all(f.verify_state == "verified" for f in no_read)


def test_member_cannot_read_clinical_blocks(data_root):
    _root, imm, app = data_root
    imm.chmod(0o700)
    app.chmod(0o700)
    p = _proj(members=("@bob",), sensitivity="clinical")
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"bob": "bob"}),
        os_identity_resolver=_idents({"bob": _stranger_ident()}))
    no_read = [f for f in out if f.rule == "PROJECT-ACCESS-NO-READ-01"]
    assert no_read
    assert all(f.severity == "block" for f in no_read)  # clinical escalates


def test_member_can_read_cannot_write_append_only_warns(data_root):
    _root, imm, app = data_root
    imm.chmod(0o755)   # world-readable: stranger can read
    app.chmod(0o755)   # world-readable but NOT world-writable
    p = _proj(members=("@bob",))
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"bob": "bob"}),
        os_identity_resolver=_idents({"bob": _stranger_ident()}))
    no_write = [f for f in out if f.rule == "PROJECT-ACCESS-NO-WRITE-01"]
    assert no_write, "append_only needs write; a read-only member should warn"
    assert all(str(app) == f.path for f in no_write)
    # The immutable dir is read-only for everyone, so no NO-WRITE for it.
    assert all(f.path != str(imm) for f in no_write)


# ---------------------------------------------------------------------------
# member with correct access -> ok
# ---------------------------------------------------------------------------


def test_member_with_access_is_ok(data_root):
    _root, imm, app = data_root
    imm.chmod(0o700)
    app.chmod(0o700)
    p = _proj(members=("@alice",))          # owner of the tmp dirs
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"alice": "alice"}),
        os_identity_resolver=_idents({"alice": _owner_ident()}))
    assert out and all(f.rule == "PROJECT-ACCESS-OK-01" for f in out)
    assert all(f.severity == "info" and f.verify_state == "verified" for f in out)


# ---------------------------------------------------------------------------
# unknown member->OS-user mapping -> unverifiable (never a false clean)
# ---------------------------------------------------------------------------


def test_unknown_os_user_mapping_is_unverifiable(data_root):
    _root, imm, app = data_root
    p = _proj(members=("@carol",))
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"carol": None}),   # no mapping
        os_identity_resolver=_idents({}))
    unv = [f for f in out if f.rule == "PROJECT-ACCESS-UNVERIFIABLE-01"]
    assert unv, "unknown mapping must be unverifiable, not clean"
    assert all(f.verify_state == "unverifiable" for f in unv)
    assert all(f.severity == "info" for f in unv)
    # No access verdict was fabricated for that member.
    assert not any(f.rule in ("PROJECT-ACCESS-OK-01", "PROJECT-ACCESS-NO-READ-01")
                   for f in out)


def test_os_user_present_but_account_absent_is_unverifiable(data_root):
    _root, imm, app = data_root
    p = _proj(members=("@dave",))
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"dave": "dave"}),
        os_identity_resolver=_idents({"dave": None}))   # login not on this host
    unv = [f for f in out if f.rule == "PROJECT-ACCESS-UNVERIFIABLE-01"]
    assert unv and all(f.verify_state == "unverifiable" for f in unv)


# ---------------------------------------------------------------------------
# missing directory -> unverifiable dir-missing (not a false clean)
# ---------------------------------------------------------------------------


def test_missing_data_dir_is_unverifiable(monkeypatch, tmp_path):
    # A data root with NO project dirs created.
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(tmp_path / "empty_data"))
    p = _proj(members=("@bob",))
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"bob": "bob"}),
        os_identity_resolver=_idents({"bob": _stranger_ident()}))
    missing = [f for f in out if f.rule == "PROJECT-ACCESS-DIR-MISSING-01"]
    assert missing and all(f.verify_state == "unverifiable" for f in missing)


# ---------------------------------------------------------------------------
# NEVER mutates permissions
# ---------------------------------------------------------------------------


def test_check_never_mutates_permissions(data_root):
    _root, imm, app = data_root
    imm.chmod(0o700)
    app.chmod(0o750)
    before = (_stat.S_IMODE(imm.stat().st_mode),
              _stat.S_IMODE(app.stat().st_mode))
    p = _proj(members=("@alice", "@bob"), sensitivity="clinical")
    PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"alice": "alice", "bob": "bob"}),
        os_identity_resolver=_idents({"alice": _owner_ident(),
                                      "bob": _stranger_ident()}))
    after = (_stat.S_IMODE(imm.stat().st_mode),
             _stat.S_IMODE(app.stat().st_mode))
    assert before == after, "the check must be read-only (no chmod)"


# ---------------------------------------------------------------------------
# repo paths in the project are checked (write required)
# ---------------------------------------------------------------------------


def test_local_repo_dir_checked_for_write(data_root, tmp_path):
    _root, imm, app = data_root
    imm.chmod(0o755)
    app.chmod(0o775)
    repo_dir = tmp_path / "repos" / "proj1"
    repo_dir.mkdir(parents=True)
    repo_dir.chmod(0o755)   # readable but not writable by a stranger
    ref = CP.RepoRef(name="proj1", role="code", host="local", path=str(repo_dir))
    p = _proj(members=("@bob",), repos=(ref,))
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"bob": "bob"}),
        os_identity_resolver=_idents({"bob": _stranger_ident()}))
    repo_findings = [f for f in out if f.path == str(repo_dir)]
    assert repo_findings, "the project's local repo dir should be checked"
    assert any(f.rule == "PROJECT-ACCESS-NO-WRITE-01" for f in repo_findings)


def test_remote_host_repo_is_skipped(data_root):
    _root, imm, app = data_root
    imm.chmod(0o755)
    app.chmod(0o775)
    ref = CP.RepoRef(name="proj1", role="code", host="lab-server",
                     path="/pointer", remote_path="/data/proj1")
    p = _proj(members=("@alice",), repos=(ref,))
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"alice": "alice"}),
        os_identity_resolver=_idents({"alice": _owner_ident()}))
    assert all(f.path != "/pointer" for f in out), "remote repos are audited on their host"


# ---------------------------------------------------------------------------
# NFSv4-ACL refinement (parses security_acl output; overrides POSIX)
# ---------------------------------------------------------------------------


def test_nfs4_acl_grants_read_overrides_posix(data_root):
    _root, imm, app = data_root
    # POSIX says owner-only (stranger would be denied)...
    imm.chmod(0o700)
    app.chmod(0o700)
    # ...but an NFSv4 ACL explicitly allows the named user read+write.
    def getfacl(path: Path):
        return (f"# file: {path}\n"
                "A::OWNER@:rwaDdxtTnNcCoy\n"
                "A::bob@example.edu:rwaxtcy\n"
                "A::EVERYONE@:rtcy\n")
    p = _proj(members=("@bob",))
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        getfacl_provider=getfacl,
        os_user_resolver=_resolver({"bob": "bob"}),
        os_identity_resolver=_idents({"bob": _stranger_ident()}))
    ok = [f for f in out if f.rule == "PROJECT-ACCESS-OK-01"]
    assert ok, "the ACL grants access even though POSIX mode would deny it"
    assert all("nfs4" in f.current_state for f in ok)


def test_nfs4_acl_deny_flags_read(data_root):
    _root, imm, app = data_root
    imm.chmod(0o777)  # POSIX would allow everyone...
    app.chmod(0o777)
    def getfacl(path: Path):
        # A leading Deny for the user wins over the later EVERYONE allow.
        return (f"# file: {path}\n"
                "D::bob@example.edu:r\n"
                "A::EVERYONE@:rwaxtcy\n")
    p = _proj(members=("@bob",))
    out = PACC.check_project_access(
        "alice", None, projects=[p],
        getfacl_provider=getfacl,
        os_user_resolver=_resolver({"bob": "bob"}),
        os_identity_resolver=_idents({"bob": _stranger_ident()}))
    assert any(f.rule == "PROJECT-ACCESS-NO-READ-01" for f in out)


# ---------------------------------------------------------------------------
# report + scoping helpers
# ---------------------------------------------------------------------------


def test_only_led_projects_are_scoped(monkeypatch, data_root):
    led = _proj(name="proj1", lead="@alice", members=("@alice",))
    other = _proj(name="proj2", lead="@zoe", members=("@alice",))
    monkeypatch.setattr(CP, "iter_projects", lambda env=None: [led, other])
    scoped = PACC._projects_i_lead("alice", None)
    assert [p.name for p in scoped] == ["proj1"]


def test_resolve_member_os_user_prefers_frontmatter_override(monkeypatch, tmp_path):
    from murmurent.core import membership as MEM
    mfile = tmp_path / "bob.md"
    mfile.write_text("---\nhandle: bob\nofficial_handle: bnet\nos_user: bsrv\n---\n",
                     encoding="utf-8")
    rec = MEM.MemberRecord(handle="bob", full_name="Bob", role="student",
                           status="active", official_handle="bnet", path=mfile)
    monkeypatch.setattr(MEM, "get", lambda h: rec)
    assert PACC.resolve_member_os_user("bob") == "bsrv"


def test_resolve_member_os_user_falls_back_to_official_handle(monkeypatch, tmp_path):
    from murmurent.core import membership as MEM
    mfile = tmp_path / "bob.md"
    mfile.write_text("---\nhandle: bob\nofficial_handle: bnet\n---\n", encoding="utf-8")
    rec = MEM.MemberRecord(handle="bob", full_name="Bob", role="student",
                           status="active", official_handle="bnet", path=mfile)
    monkeypatch.setattr(MEM, "get", lambda h: rec)
    assert PACC.resolve_member_os_user("bob") == "bnet"


def test_resolve_member_os_user_none_when_no_mapping(monkeypatch):
    from murmurent.core import membership as MEM
    def _raise(h):
        raise MEM.MemberNotFound("nope")
    monkeypatch.setattr(MEM, "get", _raise)
    assert PACC.resolve_member_os_user("ghost") is None


def test_report_headline_and_counts(data_root):
    _root, imm, app = data_root
    imm.chmod(0o700)
    app.chmod(0o700)
    p = _proj(members=("@bob",), sensitivity="clinical")
    findings = PACC.check_project_access(
        "alice", None, projects=[p],
        os_user_resolver=_resolver({"bob": "bob"}),
        os_identity_resolver=_idents({"bob": _stranger_ident()}))
    rep = PACC.ProjectAccessReport(handle="alice", generated_at="2026-07-24T00:00:00Z",
                                   findings=findings)
    assert rep.counts()["block"] >= 1
    assert rep.headline().startswith("BLOCKED")
    assert len(rep.headline()) <= 200
