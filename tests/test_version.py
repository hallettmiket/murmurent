"""The version has a single source of truth (issue #24).

``pyproject.toml`` reads its version from ``src/murmurent/__init__.py`` via
Hatchling, so there is exactly one hand-maintained version string. It used to be
two, and they drifted (pyproject ``1.0.0`` vs runtime ``0.1.0``); these tests
make that regression loud.

We assert the *wiring* (pyproject declares a dynamic version sourced from
``__init__.py``) rather than ``importlib.metadata.version`` — an editable
install's ``.dist-info`` metadata only refreshes on rebuild, so it lags the
source and would make the check flaky in dev.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from murmurent import __version__

_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def test_pyproject_sources_version_from_init_not_a_static_string():
    data = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))
    # No static [project].version — that's the second source that used to drift.
    assert "version" not in data["project"], "remove the static version; it drifts"
    assert "version" in data["project"].get("dynamic", [])
    # Hatchling reads it straight out of __init__.py.
    assert data["tool"]["hatch"]["version"]["path"] == "src/murmurent/__init__.py"


def test_version_is_calver_shaped():
    """CalVer YYYY.M.MICRO — a plausibility check, not a date assertion (the
    test can't know 'today', and shouldn't)."""
    assert re.fullmatch(r"\d{4}\.\d{1,2}\.\d+", __version__), __version__


def test_cli_reports_the_same_version():
    from click.testing import CliRunner

    from murmurent.cli import cli

    res = CliRunner().invoke(cli, ["--version"])
    assert res.exit_code == 0, res.output
    assert __version__ in res.output
