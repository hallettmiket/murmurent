"""
Sentinel hygiene: is_registrar resolves via the scoped <lab_info>/registrar file
(so fixtures are hermetic, not dependent on the real ~/.murmurent sentinel), the
registry list still takes precedence, and the machine sentinel honours
MURMURENT_HOME.
"""

from __future__ import annotations

from pathlib import Path

from murmurent.core import registrar as R


def test_wig_home_honours_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MURMURENT_HOME", str(tmp_path / "wh"))
    assert R._wig_home() == tmp_path / "wh"
    monkeypatch.delenv("MURMURENT_HOME", raising=False)
    assert R._wig_home() == Path.home() / ".murmurent"


def test_is_registrar_via_scoped_lab_info(monkeypatch, tmp_path):
    li = tmp_path / "lab_info"
    li.mkdir()
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(li))
    # machine sentinel points at nothing → prove independence from the real home
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL", tmp_path / "nope")
    assert R.is_registrar("the_pi") is False
    (li / "registrar").write_text("the_pi\n", encoding="utf-8")
    assert R.is_registrar("the_pi") is True
    assert R.is_registrar("@the_pi") is True      # normalization
    assert R.is_registrar("someone_else") is False


def test_registry_list_takes_precedence_over_scoped(monkeypatch, tmp_path):
    li = tmp_path / "lab_info"
    li.mkdir()
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(li))
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL", tmp_path / "nope")
    (li / "_registry.yaml").write_text("registrars: [alice]\n", encoding="utf-8")
    (li / "registrar").write_text("the_pi\n", encoding="utf-8")  # present but ignored
    assert R.is_registrar("alice") is True
    assert R.is_registrar("the_pi") is False       # declared list wins


def test_falls_back_to_machine_sentinel(monkeypatch, tmp_path):
    li = tmp_path / "lab_info"
    li.mkdir()
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(li))
    # a centre must exist for the legacy machine sentinel to apply
    (li / "centre.md").write_text(
        "---\nname: T\ninstitution: U\nfounding_mayor: '@bob'\ncreated: 2026-01-01\n---\n",
        encoding="utf-8")
    sentinel = tmp_path / "machine_registrar"
    sentinel.write_text("bob\n", encoding="utf-8")
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL", sentinel)
    # centre present, no registry list, no scoped file → legacy per-machine sentinel
    assert R.is_registrar("bob") is True
    assert R.is_registrar("alice") is False


def test_machine_sentinel_ignored_without_a_centre(monkeypatch, tmp_path):
    """Regression: a stale ~/.murmurent/registrar must NOT confer registrar access
    on a fresh / centre-less install (the 'signed in as registrar with no centre'
    bug)."""
    li = tmp_path / "lab_info"
    li.mkdir()
    monkeypatch.setenv("MURMURENT_LAB_INFO_ROOT", str(li))
    sentinel = tmp_path / "machine_registrar"
    sentinel.write_text("the_pi\n", encoding="utf-8")   # leftover from a removed centre
    monkeypatch.setattr(R, "REGISTRAR_SENTINEL", sentinel)
    # no centre.md anywhere → nobody is a registrar, sentinel or not
    assert R.is_registrar("the_pi") is False
