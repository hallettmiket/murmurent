# Oracle entry schema

Every Oracle entry — personal (`<vault>/oracle/*.md`) or lab
(`lab_mgmt/oracle/*.md`) — must start with YAML frontmatter conforming
to this schema. The schema is enforced by the Oracle and Lab Oracle
agents and parsed by `src/wigamig/mcp/oracle_server.py` for structured
search.

## Why a schema

Without frontmatter, retrieval degrades to grep — useful only when you
already remember the keyword. With frontmatter, the murmurent Oracle MCP
can answer:

- "What did I learn about DCIS in 2026?"  → filter `project: dcis_*`
  + `date >= 2026-01-01`
- "Show me everything tagged `qc`."      → filter `tags: contains 'qc'`
- "What did `@bob` publish?"             → filter `sources: contains '@bob'`

Without frontmatter, none of these queries are reliable.

## Required fields

```yaml
---
title:        <one-line human-readable headline>
date:         <YYYY-MM-DD>            # when the finding was recorded
project:      <project_name | "general">
sensitivity:  standard | restricted | clinical
tags:         [comma-sep, list, of, tags]
sources:      ['@handle']             # who observed / contributed
---
```

- **title**: full prose, not the filename. Used as the entry's display
  name in Oracle digests and MCP responses.
- **date**: ISO date the entry was first written. Not auto-updated on
  subsequent edits — for revision history, append a dated section to
  the body instead.
- **project**: the project that surfaced this finding. Use `general`
  when the entry is not project-specific (tooling assessments,
  cross-cutting methods, etc.). Multiple projects: pick the primary,
  list the others under `related:`.
- **sensitivity**: matches the CHARTER.md vocabulary. **A clinical
  entry MUST stay in the personal vault — never publish to Lab
  Oracle.** The publish CLI refuses `sensitivity: clinical`.
- **tags**: open vocabulary, but prefer reuse. Common axes: subject
  area (`dcis`, `imaging`, `genomics`), artefact type (`gene`,
  `method`, `tool`, `decision`), and lifecycle stage (`hypothesis`,
  `observation`, `decision`).
- **sources**: handles of people whose work produced this finding.
  Usually `['@<your-handle>']` for personal entries. Lab entries may
  list multiple authors.

## Optional fields

```yaml
related:      ['[[other_entry]]', '[[methods/qc_drift]]']
source_sea:   <SEA #>                 # if surfaced via a cross-group SEA
source_exp:   <experiment_id>         # if surfaced in a specific experiment
url:          <DOI or link>           # for literature-derived entries
```

- **related**: Obsidian wikilinks to other oracle entries. Drives the
  graph view in Obsidian and the `oracle_related()` MCP tool.
- **source_sea** / **source_exp**: precise provenance when known.
- **url**: source URL or DOI when the entry annotates external work.

## File naming

- **Personal vault**: prefer one entry per file, named
  `<YYYY-MM-DD>_<slug>.md` (matches the lab pattern).
  Legacy topic-files-with-anchors (e.g. `genes_of_interest.md` with
  `### MMP11` subheadings) are still readable but no longer the
  recommended shape.
- **Lab oracle**: always one entry per file, `<YYYY-MM-DD>_<slug>.md`.
  The date prefix is what the lab uses to skim chronologically.

## Worked example

```markdown
---
title: GRCh38.p14 fixes the chrM contig issue for run 17
date: 2026-05-08
project: dcis_sc_tutorial
sensitivity: standard
tags: [reference-genome, chrm, dcis]
sources: ['@allie']
source_sea: 4
related: ['[[2026-05-01_chrm_artefact_p13]]']
---

# GRCh38.p14 fixes the chrM contig issue

The chrM artefact we hit in February with GRCh38.p13 is patched in
**p14**. For DCIS run 17 we are aligning against p14, not p13, and
not T2T-CHM13 — switching reference mid-cohort would invalidate
cross-sample comparison.
```

## Migration of pre-schema entries

When you encounter a topic-file-with-anchors style entry without
frontmatter (e.g. the original `genes_of_interest.md`), prepend the
required fields at the file level, leaving the body untouched.
Anchors inside the file remain valid Obsidian links.

If a topic file contains multiple substantively-different entries,
prefer splitting into per-entry files over backfilling a single
frontmatter block — the per-entry schema is what makes MCP search
useful.
