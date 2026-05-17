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


@pytest.fixture
def world_with_notebook(world, monkeypatch, tmp_path):
    """Adds a notebook tier on top of ``world`` so notebook-specific
    tests can exercise both the schema-required (personal+lab) path
    and the schema-optional (notebook) path side by side."""
    notebook_dir = tmp_path / "vault" / "lab-notebook"
    notebook_dir.mkdir(parents=True)
    # Flat daily entry — no project subdir, no frontmatter.
    (notebook_dir / "2026-05-15.md").write_text(
        "# Friday lab notes\n\n"
        "Ran MMP11 expression analysis on the new DCIS samples.\n"
        "Drift correction looks clean after the run_all fix.\n",
        encoding="utf-8",
    )
    # Nested per-project entry with light frontmatter.
    (notebook_dir / "dcis" / "2026-05-16.md").parent.mkdir()
    (notebook_dir / "dcis" / "2026-05-16.md").write_text(
        "---\ntags: [dcis, qc]\n---\n\n# DCIS run 18 QC review\n\n"
        "Numbers came in. cohort comparable to run 17.\n",
        encoding="utf-8",
    )
    # An index file that should be excluded.
    (notebook_dir / "README.md").write_text("# Notebook index\n")
    # Make _safe_notebook_dir return this tmp path. Monkeypatch the
    # function directly — simpler than reaching into machine_settings.
    monkeypatch.setattr(srv, "_safe_notebook_dir", lambda: notebook_dir)
    return {**world, "notebook": notebook_dir}


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
# Notebook tier (kind="notebook" + kind="all")
# ---------------------------------------------------------------------------


def test_list_notebook_only(world_with_notebook):
    """`kind="notebook"` returns just the daily-notebook entries.
    The flat 2026-05-15 entry and the nested dcis/2026-05-16 entry
    both appear; the README index is excluded."""
    rows = srv.tool_list("notebook")
    titles = sorted(r["title"] for r in rows)
    assert "Friday lab notes" in titles
    assert "DCIS run 18 QC review" in titles
    assert "Notebook index" not in titles
    assert all(r["kind"] == "notebook" for r in rows)


def test_list_all_returns_three_tiers(world_with_notebook):
    """`kind="all"` returns personal + lab + notebook in one call.
    Existing callers using `kind="both"` (personal + lab only) still
    see exactly 4 rows; `all` sees those plus the 2 notebooks."""
    both_rows = srv.tool_list("both")
    all_rows = srv.tool_list("all")
    assert len(both_rows) == 4
    assert len(all_rows) == 6
    kinds = {r["kind"] for r in all_rows}
    assert kinds == {"personal", "lab", "notebook"}


def test_notebook_date_derived_from_filename(world_with_notebook):
    """Notebooks without frontmatter still get a date — derived from
    the YYYY-MM-DD filename convention. Without this, ordering and
    date filters wouldn't work on legacy daily entries."""
    rows = srv.tool_list("notebook")
    friday = next(r for r in rows if r["title"] == "Friday lab notes")
    assert friday["date"] == "2026-05-15"


def test_notebook_project_derived_from_parent_dir(world_with_notebook):
    """Nested-layout notebooks (lab-notebook/<project>/<date>.md)
    inherit `project` from the parent directory when frontmatter
    doesn't say. Flat-layout notebooks (lab-notebook/<date>.md) get
    project="" — same as the schema doc allows."""
    rows = srv.tool_list("notebook")
    by_title = {r["title"]: r for r in rows}
    assert by_title["DCIS run 18 QC review"]["project"] == "dcis"
    assert by_title["Friday lab notes"]["project"] == ""


def test_notebook_search_finds_keyword_in_body(world_with_notebook):
    """`oracle_search("MMP11", kind="notebook")` returns the daily
    that mentioned MMP11 even though the notebook has no `tags:` for
    it. Body search is the main fallback for unstructured notebooks."""
    rows = srv.tool_search("MMP11", kind="notebook")
    titles = [r["title"] for r in rows]
    assert "Friday lab notes" in titles


def test_search_all_returns_personal_and_notebook_mentions(world_with_notebook):
    """`kind="all"` lets one query stitch the curated Oracle finding
    AND the raw notebook mention together. This is the whole point of
    integrating notebooks — show structured + unstructured side by
    side."""
    rows = srv.tool_search("MMP11", kind="all")
    kinds = {r["kind"] for r in rows}
    titles = {r["title"] for r in rows}
    assert "personal" in kinds          # the 2026-04-16_mmp11 entry
    assert "notebook" in kinds          # the friday notebook mention
    assert "MMP11 flagged for DCIS" in titles
    assert "Friday lab notes" in titles


def test_notebook_filter_by_tag(world_with_notebook):
    """The nested notebook DOES have `tags: [dcis, qc]`. A tag
    filter should match it; flat-no-frontmatter notebooks (no tags)
    should not match."""
    rows = srv.tool_search(tags=["qc"], kind="notebook")
    titles = [r["title"] for r in rows]
    assert "DCIS run 18 QC review" in titles
    assert "Friday lab notes" not in titles


def test_get_notebook_by_path_includes_body(world_with_notebook):
    """`oracle_get(notebook_path)` works even on frontmatter-less
    notebooks; the body is the full markdown."""
    p = world_with_notebook["notebook"] / "2026-05-15.md"
    entry = srv.tool_get(str(p))
    assert entry["kind"] == "notebook"
    assert "MMP11 expression" in entry["body"]


def test_notebook_dir_unreadable_does_not_crash(monkeypatch, world):
    """If the notebook dir exists but iCloud/sandbox denies reads
    (the user's actual situation today), search must not crash —
    just return no notebook entries."""
    class _BoomPath:
        """Stub that satisfies the ``is None`` check but raises on
        rglob, mimicking a permission-denied iCloud-backed path."""
        def __init__(self, *_a, **_kw): pass
        def rglob(self, *_a):
            raise PermissionError("Operation not permitted")
        def exists(self): return True
    monkeypatch.setattr(srv, "_safe_notebook_dir", lambda: _BoomPath())
    rows = srv.tool_list("all")
    # personal + lab still work; notebook tier silently returned []
    kinds = {r["kind"] for r in rows}
    assert "notebook" not in kinds
    assert "personal" in kinds and "lab" in kinds


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


def test_install_does_not_emit_null_matcher(tmp_path):
    """Regression test for the 2026-05-17 bug that left
    ``matcher: null`` on the SubagentStop hook in ~/.claude/settings.json,
    which CC's settings parser rejects with:

        Settings file failed to parse … Expected strings, but received null.

    The fix: matcher-less hooks (SubagentStop, Stop, …) must OMIT the
    matcher key, not set it to null. This test fails if any
    serialised hook entry carries a null matcher.
    """
    from wigamig.commands import install_cmd
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    install_cmd.cmd_install(hooks=True, settings_path=settings, backup=False)
    data = json.loads(settings.read_text())
    for event, bucket in (data.get("hooks") or {}).items():
        for entry in bucket:
            assert entry.get("matcher") is not None or "matcher" not in entry, (
                f"hooks.{event} contains an entry with matcher: null "
                f"— CC's parser will reject the whole settings file. "
                f"Either set a real matcher string or omit the key. "
                f"Bad entry: {entry}"
            )
