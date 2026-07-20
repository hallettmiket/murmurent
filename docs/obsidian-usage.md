# Your Obsidian vault: layout and what Murmurent touches

A plain answer to two related questions: how your vault is organized on
the Murmurent side, and exactly what Murmurent reads and writes there.
Everything below is checked against the code that ships today
(`src/murmurent/core/obsidian.py`, `src/murmurent/core/oracle_publish.py`,
`src/murmurent/mcp/oracle_server.py`, `rules/oracle_schema.md`,
`agents/oracle.md`).

For vault-side organization, meaning how you personally organize your
notes overall (including the `maps-legends/` folder), see the
`CLAUDE.md` at the root of your vault.

## Two vaults: personal and lab (issue #25)

Murmurent distinguishes two kinds of Obsidian vault. Each has a
machine-independent identity (a GitHub repo) and a per-machine location
(where the clone lives on this laptop or server):

| Vault | GitHub repo (identity) | Owned by | Set the clone path in | Everyone can clone? |
|---|---|---|---|---|
| **Personal** | `murmurent_vault` (private, on the person's own GitHub) | the individual (including the PI) | Machine window, Personal vault | private to the person |
| **Lab (group)** | `murmurent_lab_mgmt_<lab>` (private, on the lab's GitHub) | the lab or core | Machine window, Lab vault | yes, every member gets read access |

The lab vault is the existing lab-management repo. Per the PI's decision
on issue #25, the group Oracle, lab notebook, and `maps-legends/` for
the group all live under `murmurent_lab_mgmt_<lab>`, which members
already clone read-only (via `group_reconcile.grant_lab_mgmt_read`) and
which `roster_sync` keeps fresh with a fast-forward-only pull. This repo
supersedes the issue's originally proposed `murmurent_vault_lab` name.

Identity vs. location:

- **Identity** (the GitHub repo) is machine-independent: the personal
  repo appears in the Profile window, the lab repo in Lab Settings.
- **Location** (the clone path plus the Oracle/lab-notebook subfolders)
  is per-machine, set in the Machine window. The personal vault path is
  editable there; the lab vault path is the resolved lab-mgmt clone,
  read-only in the Machine window and managed at install time or via
  the `lab_mgmt` pin, giving a single source of truth for where the lab
  vault clone lives.

Naming helpers live in `core/repo.py`: `personal_vault_repo_name()`
(`murmurent_vault`), `lab_vault_repo_name(<lab>)`
(`murmurent_lab_mgmt_<lab>`), plus `personal_vault_path()` and
`lab_vault_path(<lab>)` for the canonical clone locations.

## Where the vault lives

The vault path resolves fresh on every call, in this order (shown for
the personal Oracle dir; the notebook dir uses the same chain):

1. **Env override**: `$MURMURENT_PERSONAL_ORACLE_DIR` (personal tier) or
   `$MURMURENT_NOTEBOOK_DIR` (notebook tier). Points straight at the
   directory; mainly useful for tests and power users.
2. **`~/.murmurent/machine.yaml`**: `obsidian_vault_path` (plus
   `oracle_subfolder`, default `oracle`, and `notebook_subfolder`,
   default `lab-notebook`). This is the normal per-machine
   configuration, written by the dashboard's Machine Settings modal. It
   lives here rather than in the git-synced lab-mgmt repo, since where
   Obsidian lives on your laptop is specific to this machine.
3. **`obsidian.json` discovery**: when neither of the above resolves,
   Murmurent reads Obsidian's own vault registry
   (`~/Library/Application Support/obsidian/obsidian.json` on macOS,
   `~/.config/obsidian/obsidian.json` on Linux) and picks the
   most-recently-opened vault. Pin a specific vault by name with
   `$MURMURENT_OBSIDIAN_VAULT` when more than one vault is registered
   and the most recent one isn't the right one.

Tools that need the personal tier raise a clear error when none of
these resolve; the notebook tier resolves via the same chain and comes
back empty when nothing resolves.

**To point Murmurent at your vault:** open the vault at least once in
the Obsidian app so it lands in `obsidian.json` and discovery can pick
it up, or set `obsidian_vault_path` explicitly via the dashboard's
Machine Settings (or by hand-editing `~/.murmurent/machine.yaml`).

Two commands help confirm the resolution worked:

- `murmurent oracle path`: prints your personal Oracle dir
  (`<vault>/oracle`); the vault root is its parent directory.
- `murmurent oracle doctor`: attempts an actual read and reports
  whether Murmurent can access the vault on this machine. See "The
  Full Disk Access gotcha" below for what its statuses mean and the
  common macOS permission fix.

## What Murmurent touches

Murmurent's reach into your vault is limited to a few named subfolders,
each configurable per machine (`~/.murmurent/machine.yaml`):

| Subfolder (default name) | What lives there | Read by | Written by |
|---|---|---|---|
| `oracle/` | Personal Oracle entries: one markdown file per finding, schema-checked, plus the `MEMORY.md` index | `murmurent-oracle` MCP server, the `oracle` agent | the `oracle` agent |
| `oracle/drafts/` | Entries staged for `murmurent oracle publish`, promotion to the lab tier | same | the `oracle` agent |
| `lab-notebook/` (the `notebook_subfolder` setting, default name) | Daily, free-form lab-notebook entries | `murmurent-oracle` MCP server, as the `notebook` tier | you, by hand, via the dashboard's "Lab notebook, today" edit button, which creates the day's file from a template on first use |

Every other folder in the vault, including `maps-legends/`, project
notes, and attachments, is entirely yours to organize (see
"`maps-legends/`" below).

**Path naming.** Two superficially similar directories sit at
different layers; keep them straight:

| Path | Purpose |
|---|---|
| `<vault>/lab-notebook/` (hyphen, singular) | Obsidian-side daily notebook entries. Configured per machine via `~/.murmurent/machine.yaml: notebook_subfolder`. |
| `$MURMURENT_LAB_VM_ROOT/lab_notebooks/` (underscore, plural) | Murmurent's data-storage layer notebook directory under the lab-VM root, part of the `raw/refined/lab_notebooks` triad. |

The Obsidian one is where humans browse and edit. The lab-VM one is the
staging and aggregation tier for cross-user notebook collation (future
work).

## The three Oracle tiers

The `murmurent-oracle` MCP server (`src/murmurent/mcp/oracle_server.py`)
exposes three tiers, queryable separately or together:

| Tier | Path | Writable by |
|---|---|---|
| **`personal`** | `<personal-vault>/oracle/<YYYY-MM-DD>_<slug>.md` | the `oracle` agent, on your machine. Yours alone until you explicitly publish (see below). |
| **`lab`** | `~/repos/murmurent_lab_mgmt_<lab>/oracle/<YYYY-MM-DD>_<slug>.md` | `murmurent oracle publish` only, gated by PI review |
| **`notebook`** | `<vault>/<notebook_subfolder>/`, default `lab-notebook/` | you, by hand |

Notebook entries skip the Oracle frontmatter (see "The entry schema"
below): they're free-form daily notes, parsed permissively, with
date/project inferred from the filename and folder when frontmatter is
missing.

Both structured tiers share the same frontmatter schema
([`rules/oracle_schema.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/oracle_schema.md))
and are searched together by the `murmurent-oracle` MCP server.

### Searching and browsing

These are MCP tools any Claude Code session with the `murmurent-oracle`
server registered can call (they're what the `oracle` agent uses
internally, and you can ask any session to invoke them on your behalf):

- `oracle_search(query, kind=..., project=..., tags=..., sensitivity=..., source=...)`:
  keyword and frontmatter-filtered search. `kind` defaults to `"both"`
  (personal plus lab); pass `kind="all"` to include the notebook tier
  too, or a single tier name (`"personal"`, `"lab"`, `"notebook"`) to
  search just one. An empty query with filters returns everything
  matching those filters (for example, every `brca_*` entry).
- `oracle_get(path)`: read one entry in full, with body, by its
  absolute path. Notebooks tolerate missing frontmatter; personal and
  lab entries must parse as valid frontmatter to be returned.
- `oracle_list(kind=...)`: a one-line summary of every entry in the
  requested tier(s), newest first.

Search today works by keyword plus explicit frontmatter filters; the
schema itself is the index, rather than semantic embeddings.

### Command-line equivalents

- `murmurent oracle path`: print the personal Oracle dir Murmurent has
  resolved on this machine (confirms it found the right vault).
- `murmurent oracle doctor`: attempts to read a file in that dir and
  reports OK, BLOCKED, MISSING, NO VAULT, or empty. Use this whenever
  search turns up thinner than expected (see "The Full Disk Access
  gotcha").
- `murmurent oracle vault-drafts`: list drafts waiting in
  `<vault>/oracle/drafts/`.
- `murmurent oracle publish <slug> [--push] [--dry-run]`: promote a
  draft (see "Publishing personal to lab" below).

### What writes to the personal tier

The `oracle` agent is the intended writer of `oracle/`: it creates one
file per entry and maintains the `MEMORY.md` index. Daily notebook
entries under `lab-notebook/` come from the dashboard's "Lab notebook,
today" edit button: the first click of the day writes the file from a
small template and opens it in your editor, and the content from there
is yours to write. A dedicated `murmurent notebook` CLI is on the
roadmap (see "What's in progress" below).

### Publishing personal to lab

Promotion is a two-step, explicit action:

1. The `oracle` agent copies the entry to
   `<vault>/oracle/drafts/<slug>.md` (the original stays untouched).
2. You run `murmurent oracle publish <slug>` (or call the MCP tool
   `oracle_publish_draft(slug, push=...)`, which wraps the same code
   path and resolves your identity so publishing always attributes to
   you).

Publish enforces, mechanically, in `core/oracle_publish.py`:

- The draft must have complete frontmatter: `title`, `date`, `project`,
  `sensitivity`, non-empty `tags`, non-empty `sources`.
- Entries with `sensitivity: clinical` or `sensitivity: restricted` are
  refused and stay in your personal vault. (`rules/oracle_schema.md`
  calls out `clinical` explicitly; the code also blocks `restricted`,
  so treat both as personal-vault-only.)
- The target filename (`<lab-mgmt>/oracle/<YYYY-MM-DD>_<slug>.md`) must
  be new: publish refuses to overwrite an existing lab entry.
- On success, the draft commits to the lab-mgmt repo (and pushes, if
  you asked for `--push`), and the source draft is removed from your
  vault so the entry lives in exactly one place.

Publish handles the mechanics only; whether the lab *should* accept the
entry is a PI-review question handled separately.

## The entry schema

Personal and lab entries (not notebook entries) must start with YAML
frontmatter conforming to `rules/oracle_schema.md` for the Oracle tools
to parse them:

```yaml
---
title:        <one-line human-readable headline>
date:         <YYYY-MM-DD>
project:      <project_name | "general">
sensitivity:  standard | restricted | clinical
tags:         [comma-sep, list, of, tags]
sources:      ['@handle']
---
```

Optional fields: `related` (a list of `[[wikilink]]`s to other
entries), `source_sea`, `source_exp`, `url`.

Conventions:

- **One entry per file**, named `<YYYY-MM-DD>_<slug>.md`. Older
  "topic file with `### Heading` anchors" style files remain readable
  by the tools; the per-entry shape is the recommended one for new
  writes.
- **`MEMORY.md`** at the root of `oracle/` is the master index the
  `oracle` agent reads first and updates with a one-line, wikilinked
  pointer to every new entry
  (`- [[<YYYY-MM-DD>_<slug>]]: one-line description`). `oracle_search`
  and `oracle_list` treat `MEMORY.md` (and `README.md`) as the index,
  skipping them when returning entries.
- **`[[wikilinks]]`**, not markdown links, for cross-references: that's
  what lets Obsidian's own graph view resolve them.

## `maps-legends/`

`maps-legends/` is your own convention for organizing the vault
(categories, conventions, where things go), documented in your vault's
own `CLAUDE.md` rather than in this repo. It sits outside the folders
listed in "What Murmurent touches" above, so Murmurent's code treats it
like any other part of the vault: entirely yours to read, write, and
organize. Treat it as the authoritative human-readable guide to where
things live in your vault; Murmurent's Oracle tiers are a narrower,
structured slice (`oracle/`, `oracle/drafts/`, the notebook folder)
that sits alongside whatever else `maps-legends/` organizes. Oracle
entries may still reference it via `[[wikilinks]]` so Obsidian's graph
view threads them together.

If your vault's `CLAUDE.md` exists at the vault root, Claude Code picks
it up automatically the next time it opens a file in the vault, per the
standard CLAUDE.md discovery walk.

## Why we didn't add a third-party Obsidian MCP

Community Obsidian MCP servers (for example `obsidian-mcp-server`,
`mcp-obsidian`) exist and would give Claude Code `search_notes` /
`get_note` tools. We did not adopt one because:

- The `murmurent-oracle` MCP already exposes search, get, and list over
  the vault's `oracle/` subfolder (and the lab tier), with filters for
  our specific frontmatter schema.
- A generic Obsidian MCP would search the whole vault, including
  notebooks and personal notes, a broader scope than the Oracle's own
  intent.
- Keeping the dependency list smaller stays easier to maintain.

Adding generic vault search alongside `murmurent-oracle` stays
straightforward for later: the two tool sets use differently named
tools, so they coexist cleanly.

## The Full Disk Access gotcha (read this before assuming something is empty)

This is the single most common cause of "my Oracle looks empty"
reports.

If your vault lives under iCloud Drive (`~/Library/Mobile
Documents/...`, where Obsidian puts vaults by default on macOS when you
use iCloud sync), that path is protected by macOS's Full Disk Access
(FDA) permission (TCC, the framework macOS uses to gate access to
protected user data). Obsidian itself can read it because it's been
granted access; your terminal and the `claude` process typically
haven't been granted the same.

The tricky part: when access is denied, the personal and notebook tiers
degrade silently to empty, rather than raising an error. `oracle_search`
and `oracle_list` come back with nothing, which looks identical to "no
entries yet" instead of "can't read the vault." This is a deliberate
design choice (a sandbox denial shouldn't crash the MCP server), and it
means search results alone leave "empty" and "blocked" indistinguishable.

**Confirm with `murmurent oracle doctor`** whenever search results look
thinner than expected. It attempts an actual read, unlike `murmurent
oracle path`, which only resolves a path, and reports one of:

- `OK`: read succeeded, the vault is genuinely accessible.
- `OK (empty)`: readable, but no `.md` entries yet.
- `MISSING`: the resolved path doesn't exist yet.
- `NO VAULT`: no Obsidian vault registered on this machine.
- `BLOCKED`: the dir resolved but a read was denied, the FDA case.

**Fix for `BLOCKED`:** System Settings, Privacy & Security, Full Disk
Access, add your terminal app (Terminal.app, iTerm, whichever you use)
and the `claude` binary itself, then retry. Both need access since
macOS checks the terminal running the process and the process's own
binary separately.

**iCloud placeholder caveat:** files under iCloud Drive can exist as
`.icloud` placeholder stubs that haven't downloaded to disk yet (the
cloud-only "optimize storage" state). A placeholder can list in a
directory enumeration while failing an actual read, surfacing as
`BLOCKED` too (or as an unreadable individual file even when the
directory itself is accessible). If `doctor` reports blocked access
even after granting FDA, check whether the relevant files show the
iCloud download icon in Finder and force a download by opening them
there first.

## What's in progress

Two capabilities are still being built:

- **A CLI for writing daily notebook entries.** Today, notebook entries
  under `<vault>/<notebook_subfolder>/` are plain files you create and
  edit yourself, in Obsidian, an editor, or whatever you like. A
  `murmurent notebook ...`-style command that writes one for you is
  planned.
- **A vault-map command.** `maps-legends/` (see above) stays a manual,
  human-maintained convention for now; a `murmurent vault map` command
  that inspects or reports on your vault's structure is planned but not
  yet built.

Treat this document, checked directly against the code referenced
above, as the current answer if you see either capability described as
available elsewhere.
