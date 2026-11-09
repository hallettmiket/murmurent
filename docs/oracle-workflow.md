# Oracle workflow

Two tiers, one schema. The Oracle is Murmurent's institutional memory.

## Why two tiers

- **Personal Oracle** (one per user) is your private research
  memory: genes you've flagged, hypotheses you're testing, methods
  that worked for a project. Never auto-shared: it is your own
  working knowledge base.
- **Lab Oracle** (one per lab) is what the lab has agreed to
  remember: a curated, version-controlled, group-readable record.
  Read-only at the agent level; new entries land via explicit
  publish.

Promotion from personal → lab is a deliberate user action so
findings from one collaboration don't accidentally cross-contaminate
another (e.g. project A's gene list shouldn't auto-leak into
project B's lab record when both touch the same lab).

## Schema (shared)

Both tiers use [`rules/oracle_schema.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/oracle_schema.md).
Required frontmatter: `title`, `date`, `project`, `sensitivity`,
`tags`, `sources`. Optional: `related` (Obsidian wikilinks), `source_sea`, `source_exp`, `url`.

## Personal Oracle

Lives in your Obsidian vault under `oracle/`. Resolve the path on
this machine with:

```bash
murmurent oracle path
```

The [`oracle` agent](https://github.com/hallettmiket/murmurent/blob/main/agents/oracle.md) maintains it. It refuses
to write entries missing required schema fields. Every entry must
also use Obsidian `[[wikilinks]]` (not Markdown links) so the
graph view in Obsidian resolves them.

## Lab Oracle

Lives in `~/repos/murmurent_lab_mgmt_<lab>/oracle/` (the lab-mgmt git repo, in
your repositories folder: `~/repos` unless you chose another;
`murmurent config repos-root` shows it). The
[`lab_oracle` agent](https://github.com/hallettmiket/murmurent/blob/main/agents/lab_oracle.md) is read-only: its
toolset excludes Write by design. Entries arrive only via the
publish flow.

## Promoting personal → lab

```bash
# 1. In CC, ask the personal oracle to stage a draft:
#    "Oracle, stage 2026-05-16_chrm_p14 as a publish draft"
#    → writes <vault>/oracle/drafts/2026-05-16_chrm_p14.md

# 2. From a terminal:
murmurent oracle vault-drafts                       # list staged drafts
murmurent oracle publish 2026-05-16_chrm_p14        # validate + copy + commit
murmurent oracle publish 2026-05-16_chrm_p14 --push # commit + push in one shot
```

`murmurent oracle publish` **refuses `sensitivity: protected` /
`restricted` entries** (those stay personal) and never overwrites an
existing lab entry. See [obsidian-usage.md §2.4](obsidian-usage.md)
for the full mechanics (identity checks, and what happens to the draft
afterward).

## Search (MCP)

The `murmurent-oracle` MCP server (registered by `murmurent install
--hooks`) exposes:

- `oracle_search(query, kind, tags, project, sensitivity, source, limit)`
- `oracle_get(path)`
- `oracle_list(kind)`
- `oracle_publish_draft(slug, push=False)`

Every `oracle_search` / `oracle_get` / `oracle_list` call on the personal
tier first attempts a best-effort `git pull --ff-only` of your vault (once
per process), so recall always reflects your latest synced notes, even
ones you saved on another machine.

### Four tiers, one query surface

`kind` is one of `personal`, `lab`, `notebook`, `sessions`, `both`, `all`:

| kind | Reads from |
|---|---|
| `personal` | `<vault>/oracle/` (curated frontmatter-required entries) |
| `lab` | `~/repos/murmurent_lab_mgmt_<lab>/oracle/` (curated, lab-shared) |
| `notebook` | `<vault>/<notebook_subfolder>/` (your own daily notes; frontmatter optional) |
| `sessions` | `<vault>/sessions/<date>/` (the prompts you gave Claude Code, recorded by a hook) |
| `both` | `personal + lab` (legacy default; preserved for back-compat) |
| `all` | `personal + lab + notebook + sessions`, with the notes before the sessions |

The notebook has two streams because they are written by two hands: the
notes are yours, and the sessions are written automatically, one file per
Claude Code session, with each prompt's time, project, repository and commit.
Searching `notebook` finds what you thought; searching `sessions` finds what
you asked; `all` returns both and lists every note before any session, so a
prompt never outranks the note that answers the question. The sessions
stream stays in your personal vault and is never published to the lab. How
the notebook is kept, captured into and reported from:
[The lab notebook](lab_notebook.md).

The **notebook tier** is permissive: daily lab notebook files
don't need to conform to the Oracle schema. Missing fields are
derived from path conventions:

- `date`: from filename matching `YYYY-MM-DD` or `YYYY-MM-DD_<slug>`
- `project`: from the parent dir name when notebooks are nested
  per-project (`<vault>/lab-notebook/<project>/2026-05-15.md`); empty
  for flat layouts (`<vault>/lab-notebook/2026-05-15.md`)
- `title`: first `# heading` in the body, or the filename
- `tags` / `sensitivity`: from frontmatter if present, else defaults
- `audience`: from frontmatter if present, else `me` (who may read the
  entry in a `murmurent notebook report`; see [The lab notebook](lab_notebook.md))

A session file's date comes from its folder, `sessions/<date>/`, when its
frontmatter does not carry one.

This lets one MCP call (`kind=all`) return curated Oracle findings
alongside the raw notebook mentions that surfaced them, useful for
"what do I know about gene X?" queries that want both the distilled
finding and the original context.

### macOS Full Disk Access caveat

If your vault lives under `~/Library/Mobile Documents/iCloud~md~obsidian/`,
macOS may deny `ls`/`Read` on the notebook subdir even when Obsidian
itself can see it. Grant Full Disk Access to your terminal app (and
optionally the `claude` binary) in System Settings → Privacy & Security
→ Full Disk Access. The MCP server tolerates permission denials
gracefully: it just returns no notebook entries when blocked, rather
than crashing.

## See also

- [`agents/oracle.md`](https://github.com/hallettmiket/murmurent/blob/main/agents/oracle.md): personal Oracle behavior + voice.
- [`agents/lab_oracle.md`](https://github.com/hallettmiket/murmurent/blob/main/agents/lab_oracle.md): read-only lab tier.
- [`rules/oracle_schema.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/oracle_schema.md): required frontmatter.
- [`docs/obsidian-usage.md`](obsidian-usage.md): your Obsidian vault layout and what Murmurent touches (your `maps-legends`, etc.).
- [`docs/lab_notebook.md`](lab_notebook.md): the notebook's two streams, `murmurent notebook add | split | open | report`, and the `audience` field.
