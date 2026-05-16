"""Tests for the ``wigamig-oracle`` MCP server's tool implementations.

We exercise the python-level ``tool_*`` functions directly — same
pattern as ``tests/test_inventory.py`` for ``wigamig-inventory``. The
FastMCP wiring is exercised only when the SDK is actually installed
and the server runs, which is out of scope for unit tests.

Coverage:
  - ``tool_list`` returns entries from each tier with one-line metadata
  - ``tool_search`` filters by query, project (glob), tags, source,
    sensitivity, and respects ``limit``
  - ``tool_get`` returns the full body for a known path
  - ``tool_publish_draft`` reuses the same publish contract as the CLI
  - Drafts under ``<vault>/oracle/drafts/`` are excluded from search
    (those are not-yet-promoted and would leak in lab-wide queries)
  - Missing personal vault degrades gracefully (returns [] for that tier)

Also a separate test for the install_cmd registration so the MCP
server appears in ~/.claude/settings.json after `wigamig install`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wigamig.mcp import oracle_server as srv
from wigamig.core import oracle_publish as _op


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_entry(
    dest_dir: Path,
    name: str,
    *,
    title: str = "Test entry",
    date: str = "2026-05-16",
    project: str = "general",
    sensitivity: str = "standard",
    tags: list[str] | None = None,
    sources: list[str] | None = None,
    body: str = "Body content.",
) -> Path:
    """Write a schema-compliant entry. Returns the path."""
    fm_lines = [
        "---",
        f"title: {title}",
        f"date: {date}",
        f"project: {project}",
        f"sensitivity: {sensitivity}",
        f"tags: {tags or ['test']}",
        f"sources: {sources or ['@the_pi']}",
        "---",
        "",
        body,
        "",
    ]
    p = dest_dir / f"{name}.md"
    p.write_text("\n".join(fm_lines), encoding="utf-8")
    return p


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Set up both tiers with a handful of entries spanning projects + tags."""
    vault_oracle = tmp_path / "vault" / "oracle"
    (vault_oracle / "drafts").mkdir(parents=True)
    lab_root = tmp_path / "lab_mgmt"
    lab_oracle = lab_root / "oracle"
    lab_oracle.mkdir(parents=True)

    monkeypatch.setenv("WIGAMIG_PERSONAL_ORACLE_DIR", str(vault_oracle))
    monkeypatch.setenv("WIGAMIG_LAB_MGMT_REPO", str(lab_root))

    # Personal entries
    _write_entry(vault_oracle, "2026-04-16_mmp11",
                 title="MMP11 flagged for DCIS",
                 date="2026-04-16",
                 project="dcis",
                 tags=["gene", "dcis"],
                 sources=["@the_pi"])
    _write_entry(vault_oracle, "2026-04-25_obsidian_validated",
                 title="Obsidian validated as the wigamig knowledge vault",
                 date="2026-04-25",
                 project="general",
                 tags=["tool", "infrastructure"],
                 sources=["@the_pi"])
    # A draft — must be excluded from search.
    _write_entry(vault_oracle / "drafts", "draft_in_progress",
                 title="Should not appear in search",
                 tags=["draft"])
    # An index file — must be excluded.
    (vault_oracle / "MEMORY.md").write_text("# Index\n")

    # Lab entries (mirror the real wigamig lab_mgmt/oracle samples)
    _write_entry(lab_oracle, "2026-05-07_drift_correction",
                 title="Drift correction belongs in run_all, not in QC",
                 date="2026-05-07",
                 project="method_bench_24",
                 tags=["drift", "qc", "methods"],
                 sources=["@bob"])
    _write_entry(lab_oracle, "2026-05-08_dcis_chrm_p14",
                 title="GRCh38.p14 fixes the chrM contig issue for run 17",
                 date="2026-05-08",
                 project="dcis_sc_tutorial",
                 tags=["reference-genome", "chrm", "dcis"],
                 sources=["@allie"])

    return {"vault": vault_oracle, "lab": lab_oracle, "lab_root": lab_root}


# ---------------------------------------------------------------------------
# tool_list
# ---------------------------------------------------------------------------


def test_list_both_returns_personal_and_lab(world):
    """Default kind=both surfaces every entry from each tier, no drafts,
    no MEMORY.md."""
    rows = srv.tool_list("both")
    titles = sorted(r["title"] for r in rows)
    assert "MMP11 flagged for DCIS" in titles
    assert "Obsidian validated as the wigamig knowledge vault" in titles
    assert "Drift correction belongs in run_all, not in QC" in titles
    assert "GRCh38.p14 fixes the chrM contig issue for run 17" in titles
    assert "Should not appear in search" not in titles
    assert len(rows) == 4


def test_list_personal_only(world):
    rows = srv.tool_list("personal")
    kinds = {r["kind"] for r in rows}
    assert kinds == {"personal"}
    assert len(rows) == 2


def test_list_lab_only(world):
    rows = srv.tool_list("lab")
    kinds = {r["kind"] for r in rows}
    assert kinds == {"lab"}
    assert len(rows) == 2


def test_list_sorted_newest_first(world):
    rows = srv.tool_list("both")
    dates = [r["date"] for r in rows]
    assert dates == sorted(dates, reverse=True)


def test_list_invalid_kind_raises(world):
    with pytest.raises(ValueError, match="kind must be one of"):
        srv.tool_list("nonsense")


# ---------------------------------------------------------------------------
# tool_search
# ---------------------------------------------------------------------------


def test_search_by_keyword_in_title(world):
    """Keyword hits in title rank highest; only matching entries returned."""
    rows = srv.tool_search("Obsidian")
    assert len(rows) == 1
    assert "Obsidian" in rows[0]["title"]


def test_search_by_keyword_in_body(world):
    """Body-only hit still returns — lower rank than title but present."""
    rows = srv.tool_search("body content")
    # All 4 entries share body text; with no other filter that's expected.
    assert len(rows) == 4


def test_search_filter_by_project_exact(world):
    rows = srv.tool_search("", project="dcis")
    titles = [r["title"] for r in rows]
    assert titles == ["MMP11 flagged for DCIS"]


def test_search_filter_by_project_glob(world):
    """``dcis_*`` should match dcis_sc_tutorial but not bare 'dcis'."""
    rows = srv.tool_search("", project="dcis_*")
    titles = {r["title"] for r in rows}
    assert "GRCh38.p14 fixes the chrM contig issue for run 17" in titles
    assert "MMP11 flagged for DCIS" not in titles


def test_search_filter_by_tag_overlap(world):
    """Tag filter is set-overlap, not strict equality."""
    rows = srv.tool_search("", tags=["dcis"])
    titles = {r["title"] for r in rows}
    # Both 'dcis' tag (personal) and the lab entry tagged 'dcis' should hit.
    assert "MMP11 flagged for DCIS" in titles
    assert "GRCh38.p14 fixes the chrM contig issue for run 17" in titles
    assert "Drift correction belongs in run_all, not in QC" not in titles


def test_search_filter_by_source_handle(world):
    """Source filter normalises @ prefix + case."""
    rows = srv.tool_search("", source="bob")
    assert len(rows) == 1
    assert rows[0]["sources"] == ["@bob"]
    rows2 = srv.tool_search("", source="@BOB")
    assert rows == rows2


def test_search_filter_by_sensitivity(world):
    """All test entries are 'standard'; an unmatched sensitivity returns []."""
    rows = srv.tool_search("", sensitivity="clinical")
    assert rows == []
    rows = srv.tool_search("", sensitivity="standard")
    assert len(rows) == 4


def test_search_respects_limit(world):
    rows = srv.tool_search("", limit=2)
    assert len(rows) == 2


def test_search_drafts_excluded(world):
    """The draft entry must not appear even on a broad query."""
    rows = srv.tool_search("Should not appear")
    assert rows == []


def test_search_results_omit_body(world):
    """List/search are cheap — body lives behind tool_get to keep
    response payloads small for the model."""
    rows = srv.tool_search("MMP11")
    assert "body" not in rows[0]


# ---------------------------------------------------------------------------
# tool_get
# ---------------------------------------------------------------------------


def test_get_returns_full_entry(world):
    p = world["lab"] / "2026-05-08_dcis_chrm_p14.md"
    entry = srv.tool_get(str(p))
    assert entry["kind"] == "lab"
    assert entry["title"] == "GRCh38.p14 fixes the chrM contig issue for run 17"
    assert "Body content" in entry["body"]


def test_get_detects_personal_vs_lab(world):
    personal = srv.tool_get(str(world["vault"] / "2026-04-16_mmp11.md"))
    assert personal["kind"] == "personal"


def test_get_missing_file_raises(world):
    with pytest.raises(FileNotFoundError):
        srv.tool_get(str(world["lab"] / "nope.md"))


def test_get_malformed_frontmatter_raises(world):
    bad = world["lab"] / "no_frontmatter.md"
    bad.write_text("# Just a heading\nNo YAML here.\n")
    with pytest.raises(ValueError, match="no parseable YAML frontmatter"):
        srv.tool_get(str(bad))


# ---------------------------------------------------------------------------
# tool_publish_draft (smoke test — full coverage is in test_oracle_publish.py)
# ---------------------------------------------------------------------------


def test_publish_draft_routes_to_core(world, monkeypatch):
    """The MCP tool must delegate to core.oracle_publish so semantics
    stay consistent with the CLI. Real git is required for the commit."""
    # Initialise lab_mgmt as a git repo so the commit step works.
    subprocess.run(["git", "init", "-q"], cwd=world["lab_root"], check=True)
    subprocess.run(["git", "config", "user.email", "t@e"], cwd=world["lab_root"], check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=world["lab_root"], check=True)
    # Track existing lab entries so the first commit isn't empty.
    subprocess.run(["git", "add", "."], cwd=world["lab_root"], check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=world["lab_root"], check=True)

    # Write a draft to promote.
    _write_entry(world["vault"] / "drafts", "publishable_via_mcp",
                 title="Published via MCP",
                 date="2026-05-16",
                 project="general")

    monkeypatch.setenv("WIGAMIG_USER", "the_pi")
    result = srv.tool_publish_draft("publishable_via_mcp")
    assert "2026-05-16_publishable_via_mcp.md" in result["target"]
    assert result["commit_sha"]
    # The lab file now exists and was committed.
    assert Path(result["target"]).is_file()


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_missing_personal_dir_degrades_to_lab_only(monkeypatch, world):
    """If the user's vault isn't resolvable, search still works — just
    over the lab tier alone, no exception."""
    monkeypatch.setenv("WIGAMIG_PERSONAL_ORACLE_DIR", "/nonexistent/path")
    rows = srv.tool_list("both")
    kinds = {r["kind"] for r in rows}
    assert kinds == {"lab"}


# ---------------------------------------------------------------------------
# Install registration
# ---------------------------------------------------------------------------


def test_install_registers_oracle_mcp(tmp_path, monkeypatch):
    """`wigamig install --hooks` must add wigamig-oracle to mcpServers
    alongside wigamig-inventory — otherwise the agents have no way to
    reach the MCP."""
    from wigamig.commands import install_cmd
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    install_cmd.cmd_install(hooks=True, settings_path=settings, backup=False)
    data = json.loads(settings.read_text())
    assert "wigamig-oracle" in data["mcpServers"]
    spec = data["mcpServers"]["wigamig-oracle"]
    assert spec["args"] == ["-m", "wigamig.mcp.oracle_server"]
