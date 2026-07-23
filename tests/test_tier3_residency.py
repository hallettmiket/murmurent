"""Tests for the tier-3 data-residency preflight (issue #80 Wave 3, Part B).

Policy: clinical / tier-3 data is server-resident and must never be bound as a
laptop's data root — reach it over SSH, don't replicate it. The decision
combines the machine ROLE (``machine_registry.machine_kind``) with the project
sensitivity (``cert_projects``). These are pure-function tests: no git, no
network, no disk.
"""

from __future__ import annotations

from murmurent.core import machine_registry as MR
from murmurent.core.preflight import probe_tier3_residency


# --- the preflight decision itself -----------------------------------------

def test_refuses_clinical_on_laptop():
    p = probe_tier3_residency(sensitivity="clinical", role="laptop", project="dcis_clin")
    assert p.status == "fail"
    assert p.required is True
    assert "laptop" in p.detail.lower()
    assert "ssh" in p.detail.lower()


def test_allows_clinical_on_host():
    p = probe_tier3_residency(sensitivity="clinical", role="host", project="dcis_clin")
    assert p.status == "ok"
    assert p.required is False


def test_allows_standard_on_laptop():
    p = probe_tier3_residency(sensitivity="standard", role="laptop", project="toy")
    assert p.status == "ok"
    assert p.required is False


def test_allows_restricted_on_laptop():
    # Only clinical is tier-3 today; restricted is unrestricted on any machine.
    p = probe_tier3_residency(sensitivity="restricted", role="laptop", project="cohort")
    assert p.status == "ok"
    assert p.required is False


def test_allows_standard_on_host():
    p = probe_tier3_residency(sensitivity="standard", role="host", project="toy")
    assert p.status == "ok"


def test_missing_sensitivity_defaults_to_standard():
    # An unknown/None sensitivity must not be treated as tier-3.
    p = probe_tier3_residency(sensitivity=None, role="laptop", project="x")
    assert p.status == "ok"


# --- the machine-role heuristic feeding it ---------------------------------

def test_machine_kind_env_override(monkeypatch):
    monkeypatch.setenv(MR.ENV_MACHINE_ROLE, "host")
    assert MR.machine_kind() == "host"
    monkeypatch.setenv(MR.ENV_MACHINE_ROLE, "laptop")
    assert MR.machine_kind() == "laptop"


def test_machine_kind_server_hostname_is_host(monkeypatch):
    monkeypatch.delenv(MR.ENV_MACHINE_ROLE, raising=False)
    monkeypatch.setattr(MR, "_short_hostname", lambda: "biodatsci-server")
    assert MR.machine_kind() == "host"


def test_machine_kind_laptop_hostname_default(monkeypatch):
    monkeypatch.delenv(MR.ENV_MACHINE_ROLE, raising=False)
    monkeypatch.setattr(MR, "_short_hostname", lambda: "mike-mbp")
    assert MR.machine_kind() == "laptop"


def test_machine_kind_bad_override_falls_back_to_hostname(monkeypatch):
    monkeypatch.setenv(MR.ENV_MACHINE_ROLE, "banana")
    monkeypatch.setattr(MR, "_short_hostname", lambda: "lab-server")
    assert MR.machine_kind() == "host"
