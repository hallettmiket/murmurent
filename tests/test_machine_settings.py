"""Tests for per-machine settings load, focused on the derived presentation
names added for issue #99 / #80 Part 1a.

The machine window shows each root ONCE and nests its governed children as bare
folder names. The names the UI cannot derive on its own are computed server-side
and surfaced on ``MachineSettings``:

  - ``murmurent_data_subfolder`` — the fixed vault reference-file folder, shown
    nested under BOTH the personal and lab vault roots.
  - ``data_immutable_name`` / ``data_append_only_name`` — the two governed
    children under the Files (data) root, resolved against disk so a legacy
    raw/refined deployment renders its real names.
"""

from __future__ import annotations

import pytest

from murmurent.core.vault_provision import VAULT_SUBDIRS
from murmurent.dashboard import machine_settings as MS
from murmurent.dashboard.contract import MachineSettings


@pytest.fixture
def pinned_machine_file(monkeypatch, tmp_path):
    """Redirect machine.yaml to a tmp path so the dev's real config is untouched."""
    monkeypatch.setattr(MS, "MACHINE_FILE", tmp_path / "home" / "machine.yaml")
    return tmp_path


def _clear_data_env(monkeypatch):
    monkeypatch.delenv("MURMURENT_DATA_ROOT", raising=False)
    monkeypatch.delenv("MURMURENT_LAB_VM_ROOT", raising=False)


def test_murmurent_data_subfolder_is_a_real_vault_subdir(pinned_machine_file, monkeypatch):
    """The folder the maintainer asked for twice is a genuine VAULT_SUBDIRS member,
    and it is surfaced on the payload for the machine window to nest under a vault."""
    _clear_data_env(monkeypatch)
    settings = MS.load()
    assert settings.murmurent_data_subfolder == "murmurent_data"
    assert settings.murmurent_data_subfolder in VAULT_SUBDIRS


def test_murmurent_data_subfolder_round_trips(pinned_machine_file, monkeypatch):
    """A custom ``murmurent_data_subfolder`` is persisted by ``write`` and read
    back by ``load`` — editable + persisted exactly like oracle/notebook (issue
    #99), not pinned to the hardcoded default."""
    _clear_data_env(monkeypatch)
    MS.write(MachineSettings(murmurent_data_subfolder="mm_data"))
    settings = MS.load()
    assert settings.murmurent_data_subfolder == "mm_data"


def test_murmurent_data_subfolder_defaults_when_unset(pinned_machine_file, monkeypatch):
    """With nothing stored, ``load`` falls back to the canonical default."""
    _clear_data_env(monkeypatch)
    settings = MS.load()
    assert settings.murmurent_data_subfolder == "murmurent_data"


def test_notebook_and_oracle_subfolders_round_trip(pinned_machine_file, monkeypatch):
    """Sibling personal-vault subfolders persist symmetrically — the three
    (oracle/notebook/murmurent_data) are now edited + stored the same way."""
    _clear_data_env(monkeypatch)
    MS.write(MachineSettings(
        notebook_subfolder="nb",
        oracle_subfolder="orc",
        murmurent_data_subfolder="mm_data",
    ))
    settings = MS.load()
    assert settings.notebook_subfolder == "nb"
    assert settings.oracle_subfolder == "orc"
    assert settings.murmurent_data_subfolder == "mm_data"


def test_data_children_default_names(pinned_machine_file, monkeypatch):
    """A fresh data root resolves to the canonical immutable/append_only names."""
    _clear_data_env(monkeypatch)
    monkeypatch.setenv("MURMURENT_DATA_ROOT", str(pinned_machine_file / "data"))
    settings = MS.load()
    assert settings.data_immutable_name == "immutable"
    assert settings.data_append_only_name == "append_only"


def test_data_children_show_canonical_even_when_legacy_on_disk(pinned_machine_file, monkeypatch):
    """Even when the machine's wigamig_base still uses raw/refined on disk, the
    display shows the CANONICAL immutable/append_only terms murmurent is
    standardising on (raw/refined are recognised synonyms; the hooks keep
    resolving the real dirs)."""
    _clear_data_env(monkeypatch)
    base = pinned_machine_file / "wigamig"
    (base / "raw").mkdir(parents=True)
    (base / "refined").mkdir()
    MS.write(MachineSettings(wigamig_base=str(base)))
    settings = MS.load()
    assert settings.data_immutable_name == "immutable"
    assert settings.data_append_only_name == "append_only"
    # The vault subfolder name is unaffected by the Files-root migration state.
    assert settings.murmurent_data_subfolder == "murmurent_data"
