# Obsidian vault layout (wigamig side)

Your personal Oracle, lab notebook, and cross-project knowledge live
in your Obsidian vault. This doc covers the **wigamig-side**
conventions — what subfolders wigamig writes to and reads from. For
**vault-side** organization (how *you* organize your notes overall,
including the `maps-legends/` folder), see the `CLAUDE.md` at the
root of your vault.

## Where the vault lives

Resolve the absolute path on this machine with:

```bash
wigamig vault path
```

The resolver reads Obsidian's `obsidian.json` registry (the most
recently opened vault), or `$WIGAMIG_OBSIDIAN_VAULT` if set.

## Subfolders wigamig knows about

| Subfolder | What lives there | Written by |
|---|---|---|
| `oracle/` | Personal Oracle entries (per-entry .md files, `MEMORY.md` index) | `oracle` agent |
| `oracle/drafts/` | Entries staged for `wigamig oracle publish` | `oracle` agent |
| `lab-notebook/` (default — see your `~/.wigamig/machine.yaml` `notebook_subfolder`) | Daily lab-notebook entries | the notebook tooling (`wigamig notebook ...`) |

The rest of the vault is yours. Wigamig never writes outside the
folders listed here.

**Path naming gotcha.** There are two superficially-similar
directories at different layers — don't confuse them:

| Path | Purpose |
|---|---|
| `<vault>/lab-notebook/` (hyphen, singular) | Obsidian-side daily notebook entries. Configured per-machine via `~/.wigamig/machine.yaml: notebook_subfolder`. |
| `$WIGAMIG_LAB_VM_ROOT/lab_notebooks/` (underscore, plural) | Wigamig data-storage layer's notebook directory under the lab-VM root. Part of the `raw/refined/lab_notebooks` triad. |

The Obsidian one is where humans browse + edit. The lab-VM one is
the staging/aggregation tier for cross-user notebook collation
(future work).

## Personal vs lab Oracle storage

| Tier | Path | Writable by |
|---|---|---|
| Personal | `<vault>/oracle/<YYYY-MM-DD>_<slug>.md` | `oracle` agent (your machine) |
| Lab | `~/repos/lab_mgmt/oracle/<YYYY-MM-DD>_<slug>.md` | `wigamig oracle publish` (gated) |

Both tiers use the same frontmatter schema
([`rules/oracle_schema.md`](../rules/oracle_schema.md)) and are
searched together by the `wigamig-oracle` MCP server.

## `maps-legends/` (vault-side)

Your vault has a `maps-legends/` folder that explains your
personal organization (categories, conventions, where things go).
Wigamig doesn't write there — that's purely yours — but Oracle
entries may reference it via `[[wikilinks]]` so the graph view
threads them in.

If your vault's `CLAUDE.md` exists at the vault root, CC will
pick it up automatically the next time it opens a file in the
vault (per the standard CC CLAUDE.md discovery walk).

## Why we didn't add a third-party Obsidian MCP

Community Obsidian MCP servers (e.g. `obsidian-mcp-server`,
`mcp-obsidian`) exist and would give CC `search_notes` / `get_note`
tools. We decided against pulling one in because:

- The `wigamig-oracle` MCP already exposes search + get + list
  over the vault's `oracle/` subfolder (and the lab tier), with
  filters for our specific frontmatter schema.
- Adding a generic Obsidian MCP would search the whole vault
  including notebooks + your personal notes — broader than
  Oracle's intent.
- One less dependency to maintain.

If you ever want generic vault search (not just Oracle), the path
is to add a third-party Obsidian MCP alongside `wigamig-oracle`.
The two won't collide — they expose differently-named tools.
