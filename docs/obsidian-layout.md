# Obsidian vault layout (Murmurent side)

Your personal Oracle, lab notebook, and cross-project knowledge live
in your Obsidian vault. This doc covers the **murmurent-side**
conventions — what subfolders Murmurent writes to and reads from. For
**vault-side** organization (how *you* organize your notes overall,
including the `maps-legends/` folder), see the `CLAUDE.md` at the
root of your vault.

## Two vaults: personal and lab (issue #25)

Murmurent distinguishes **two** kinds of Obsidian vault. Each has a
machine-independent *identity* (a GitHub repo) and a per-machine
*location* (where the clone lives on this laptop/server):

| Vault | GitHub repo (identity) | Owned by | Set the clone path in | Everyone-can-clone? |
|---|---|---|---|---|
| **Personal** | `murmurent_vault` (private, on the **person's** GitHub) | the individual (incl. the PI) | Machine window · Personal vault | no — private to the person |
| **Lab (group)** | `murmurent_lab_mgmt_<lab>` (private, on the **lab's** GitHub) | the lab / core | Machine window · Lab vault | yes — every member gets read access |

**The lab vault is the existing lab-management repo.** Per the PI's
decision on issue #25 there is *no* separate `murmurent_vault_lab`
repo — the group oracle, lab-notebook, and `maps-legends/` for the
group all live under `murmurent_lab_mgmt_<lab>`, which members already
clone (read-only via `group_reconcile.grant_lab_mgmt_read`) and which
`roster_sync` already keeps fresh (ff-only pull). The issue's proposed
`murmurent_vault_lab` name is therefore superseded by
`murmurent_lab_mgmt_<lab>`.

Identity vs location:
- **Identity** (the GitHub repo) is machine-independent — the personal
  repo is shown in the Profile window, the lab repo in Lab Settings.
- **Location** (the clone path + oracle/lab-notebook subfolders) is
  per-machine — set in the **Machine** window. The personal vault path
  is editable there; the lab vault path is the resolved lab-mgmt clone
  (read-only in the Machine window, managed at install / via the
  `lab_mgmt` pin), so there is a single source of truth for "where the
  lab vault clone is".

Naming helpers live in `core/repo.py`: `personal_vault_repo_name()`
(`murmurent_vault`), `lab_vault_repo_name(<lab>)`
(`murmurent_lab_mgmt_<lab>`), plus `personal_vault_path()` /
`lab_vault_path(<lab>)` for the canonical clone locations.

## Where the vault lives

Resolve the path on this machine with:

```bash
murmurent oracle path
```

This prints your personal Oracle dir (`<vault>/oracle`); the **vault
root** is its parent directory. The resolver reads Obsidian's
`obsidian.json` registry (the most recently opened vault), or
`$MURMURENT_OBSIDIAN_VAULT` if set.

To check that Murmurent can actually *read* the vault on this machine
(the common macOS Full Disk Access failure on iCloud-backed vaults),
run `murmurent oracle doctor`.

## Subfolders Murmurent knows about

| Subfolder | What lives there | Written by |
|---|---|---|
| `oracle/` | Personal Oracle entries (per-entry .md files, `MEMORY.md` index) | `oracle` agent |
| `oracle/drafts/` | Entries staged for `murmurent oracle publish` | `oracle` agent |
| `lab-notebook/` (default — see your `~/.murmurent/machine.yaml` `notebook_subfolder`) | Daily lab-notebook entries | the dashboard's "Lab notebook · today" **edit** button (creates the day's file from a template) |

The rest of the vault is yours. Murmurent never writes outside the
folders listed here.

**Path naming gotcha.** There are two superficially-similar
directories at different layers — don't confuse them:

| Path | Purpose |
|---|---|
| `<vault>/lab-notebook/` (hyphen, singular) | Obsidian-side daily notebook entries. Configured per-machine via `~/.murmurent/machine.yaml: notebook_subfolder`. |
| `$MURMURENT_LAB_VM_ROOT/lab_notebooks/` (underscore, plural) | Murmurent data-storage layer's notebook directory under the lab-VM root. Part of the `raw/refined/lab_notebooks` triad. |

The Obsidian one is where humans browse + edit. The lab-VM one is
the staging/aggregation tier for cross-user notebook collation
(future work).

## Personal vs lab Oracle storage

| Tier | Path | Writable by |
|---|---|---|
| Personal | `<personal-vault>/oracle/<YYYY-MM-DD>_<slug>.md` | `oracle` agent (your machine) |
| Lab | `~/repos/murmurent_lab_mgmt_<lab>/oracle/<YYYY-MM-DD>_<slug>.md` | `murmurent oracle publish` (gated) |

Both tiers use the same frontmatter schema
([`rules/oracle_schema.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/oracle_schema.md)) and are
searched together by the `murmurent-oracle` MCP server.

## `maps-legends/` (vault-side)

`maps-legends/` is your own convention for organizing the vault
(categories, conventions, where things go) — Murmurent doesn't read or
write it. See [obsidian-usage.md §4](obsidian-usage.md) for the full
picture of what Murmurent does and doesn't touch. Oracle entries may
still reference it via `[[wikilinks]]` so Obsidian's graph view threads
them in.

If your vault's `CLAUDE.md` exists at the vault root, CC will
pick it up automatically the next time it opens a file in the
vault (per the standard CC CLAUDE.md discovery walk).

## Why we didn't add a third-party Obsidian MCP

Community Obsidian MCP servers (e.g. `obsidian-mcp-server`,
`mcp-obsidian`) exist and would give CC `search_notes` / `get_note`
tools. We decided against pulling one in because:

- The `murmurent-oracle` MCP already exposes search + get + list
  over the vault's `oracle/` subfolder (and the lab tier), with
  filters for our specific frontmatter schema.
- Adding a generic Obsidian MCP would search the whole vault
  including notebooks + your personal notes — broader than
  Oracle's intent.
- One less dependency to maintain.

If you ever want generic vault search (not just Oracle), the path
is to add a third-party Obsidian MCP alongside `murmurent-oracle`.
The two won't collide — they expose differently-named tools.
