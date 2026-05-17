# Oracle workflow

Two tiers, one schema. The Oracle is wigamig's institutional memory.

## Why two tiers

- **Personal Oracle** (one per user) is your private research
  memory: genes you've flagged, hypotheses you're testing, methods
  that worked for a project. Never auto-shared — it's *your*
  working knowledge base.
- **Lab Oracle** (one per lab) is what the lab has *agreed* to
  remember: a curated, version-controlled, group-readable record.
  Read-only at the agent level; new entries land via explicit
  publish.

Promotion from personal → lab is a deliberate user action so
findings from one collaboration don't accidentally cross-contaminate
another (e.g. project A's gene list shouldn't auto-leak into
project B's lab record when both touch the same lab).

## Schema (shared)

Both tiers use [`rules/oracle_schema.md`](../rules/oracle_schema.md).
Required frontmatter: `title`, `date`, `project`, `sensitivity`,
`tags`, `sources`. Optional: `related` (Obsidian wikilinks).

## Personal Oracle

Lives in your Obsidian vault under `oracle/`. Resolve the path on
this machine with:

```bash
wigamig oracle path
```

The [`oracle` agent](../agents/oracle.md) maintains it. It refuses
to write entries missing required schema fields. Every entry must
also use Obsidian `[[wikilinks]]` (not Markdown links) so the
graph view in Obsidian resolves them.

## Lab Oracle

Lives in `~/repos/lab_mgmt/oracle/` (the lab-mgmt git repo). The
[`lab_oracle` agent](../agents/lab_oracle.md) is read-only — its
toolset excludes Write by design. Entries arrive only via the
publish flow.

## Promoting personal → lab

```bash
# 1. In CC, ask the personal oracle to stage a draft:
#    "Oracle, stage 2026-05-16_chrm_p14 as a publish draft"
#    → writes <vault>/oracle/drafts/2026-05-16_chrm_p14.md

# 2. From a terminal:
wigamig oracle vault-drafts                       # list staged drafts
wigamig oracle publish 2026-05-16_chrm_p14        # validate + copy + commit
wigamig oracle publish 2026-05-16_chrm_p14 --push # commit + push in one shot
```

`wigamig oracle publish` **refuses entries with `sensitivity:
clinical` or `restricted`** — those must stay personal. It also
refuses if the lab already has an entry at the same path (no
silent overwrite of peer-reviewed content).

## Search (MCP)

The `wigamig-oracle` MCP server (registered by `wigamig install
--hooks`) exposes:

- `oracle_search(query, kind, tags, project, sensitivity, limit)`
- `oracle_get(path)`
- `oracle_list(kind)`
- `oracle_publish_draft(slug, push=False)`

`kind` ∈ {`personal`, `lab`, `both`}. Both tiers are searched in
the same call when `kind=both`.

## See also

- [`agents/oracle.md`](../agents/oracle.md) — personal Oracle behavior + voice.
- [`agents/lab_oracle.md`](../agents/lab_oracle.md) — read-only lab tier.
- [`rules/oracle_schema.md`](../rules/oracle_schema.md) — required frontmatter.
- [`docs/obsidian-layout.md`](obsidian-layout.md) — vault-side organization (your `maps-legends`, etc.).
