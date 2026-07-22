"""Dashboard agent surfacing (#38): commons agents carry origin+category, and a
member's own (non-commons) agents surface as a separate Personal section."""

from __future__ import annotations

import pytest

from murmurent.dashboard import snapshot as snap


def test_commons_agents_carry_origin_and_category():
    rows = {r.name: r for r in snap._agents()}
    # A few anchors from the real commons registry.
    assert rows["judge"].origin == "commons"
    assert rows["judge"].category == "choreography-support"
    assert rows["registrar"].category == "administrative"
    assert rows["centre_cable_guy"].category == "administrative"
    assert rows["blacksmith"].category == "member"
    # The deprecated receptionist is gone.
    assert "receptionist" not in rows
    # No description still carries the old verdict boilerplate.
    assert all("MUST: first line" not in r.description for r in rows.values())


def test_personal_agents_surface_from_cc_agents_dir(monkeypatch, tmp_path):
    """A non-commons agent file in the machine's CC agents dir appears as a
    personal agent; a file whose name collides with a commons agent does not."""
    cc = tmp_path / "cc-agents"
    cc.mkdir()
    (cc / "my_helper.md").write_text(
        "---\nname: my_helper\nfreeze: personal\nmodel: fable\n"
        "description: My own little helper.\n---\n\nbody\n",
        encoding="utf-8",
    )
    # A commons name here must be ignored (it's shown under Commons, not doubled).
    (cc / "blacksmith.md").write_text(
        "---\nname: blacksmith\nfreeze: personal\n---\n\nbody\n", encoding="utf-8")
    monkeypatch.setenv("MURMURENT_CC_AGENTS_DIR", str(cc))

    personal = {r.name: r for r in snap._personal_agents()}
    assert "my_helper" in personal
    assert personal["my_helper"].origin == "personal"
    assert personal["my_helper"].model == "fable"
    assert "blacksmith" not in personal  # commons name filtered out
