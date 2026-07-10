# Using your Obsidian vault with murmurent — what you can and can't do

A plain answer to "what can and can't murmurent do with my vault?" Everything
below is checked against the code that ships today
(`src/wigamig/core/obsidian.py`, `src/wigamig/core/oracle_publish.py`,
`src/wigamig/mcp/oracle_server.py`, `rules/oracle_schema.md`,
`agents/oracle.md`). If a capability isn't demonstrable in that code, it's
called out explicitly as *not shipped* rather than implied.

## 1. What murmurent touches in your vault (and what it leaves alone)

Murmurent (Murmurent's reference implementation) does **not** read your whole
vault. It only ever touches two subfolders, both configurable per machine
(`~/.wigamig/machine.yaml`, see §6):

| Subfolder (default name) | What it's for | Read by | Written by |
|---|---|---|---|
| `oracle/` | Your personal Oracle — one markdown file per finding, schema-checked | `murmurent-oracle` MCP server, the `oracle` agent | the `oracle` agent, `murmurent oracle publish` |
| `oracle/drafts/` | Entries staged for promotion to the lab, not yet committed anywhere else | same | the `oracle` agent |
| `lab-notebook/` (the `notebook_subfolder` setting) | Daily, free-form notebook entries | `murmurent-oracle` MCP server (as the `notebook` tier) | you, by hand |

Everything else in the vault — `maps-legends/`, project notes, attachments,
whatever else you keep there — is yours. Nothing in the current codebase
walks the rest of the vault tree, and nothing writes there. If you keep
`maps-legends/` or other folders next to `oracle/`, murmurent simply never
looks at them (see §4).

## 2. The three Oracle tiers

The `murmurent-oracle` MCP server (`src/wigamig/mcp/oracle_server.py`) exposes
three tiers, queryable separately or together:

- **`personal`** — your vault's `oracle/` folder. Yours alone; nothing here
  is shared with the lab unless you explicitly publish it (§2.4).
- **`lab`** — the Lab Oracle, `<lab-mgmt>/oracle/` in the lab-mgmt repo.
  Read-only from the agent side; entries land there only via the publish
  flow, gated by PI review.
- **`notebook`** — your vault's daily notebook folder
  (`<vault>/<notebook_subfolder>/`, default `lab-notebook/`). Entries here
  don't need the Oracle frontmatter (§3) — they're free-form daily notes,
  parsed permissively (date/project inferred from filename and folder if
  missing).

### 2.1 Searching and browsing

These are MCP tools any Claude Code session with the `murmurent-oracle` server
registered can call (they're what the `oracle` agent uses internally, and
you can ask any session to invoke them on your behalf):

- `oracle_search(query, kind=..., project=..., tags=..., sensitivity=..., source=...)`
  — keyword + frontmatter-filtered search. `kind` defaults to `"both"`
  (personal + lab); pass `kind="all"` to also include the notebook tier, or
  a single tier name (`"personal"`, `"lab"`, `"notebook"`) to search just one.
  An empty query with filters returns everything matching those filters
  (e.g. "show me every `dcis_*` entry").
- `oracle_get(path)` — read one entry in full (with body) by its absolute
  path. Notebooks tolerate missing frontmatter; personal and lab entries
  are refused if they don't parse as valid frontmatter.
- `oracle_list(kind=...)` — a one-line summary of every entry in the
  requested tier(s), newest first.

Search today is keyword + explicit frontmatter filters, not semantic
embeddings — the schema itself is the index.

### 2.2 Command-line equivalents

- `murmurent oracle path` — print the personal Oracle dir murmurent has resolved
  on this machine (useful to confirm it found the right vault).
- `murmurent oracle doctor` — actually try to *read* a file in that dir and
  report OK / BLOCKED / MISSING / NO VAULT / empty. Use this whenever
  search looks emptier than it should (§5).
- `murmurent oracle vault-drafts` — list drafts waiting in
  `<vault>/oracle/drafts/`.
- `murmurent oracle publish <slug> [--push] [--dry-run]` — promote a draft
  (§2.4).

### 2.3 What writes to the personal tier

The `oracle` agent is the intended writer of `oracle/` — it creates one
file per entry and maintains a `MEMORY.md` index. Nothing currently in the
codebase writes daily notebook entries programmatically; those are
authored by hand (or by whatever editor you point at them) — see §7.

### 2.4 Publishing personal → lab

Promotion is a two-step, explicit action, never automatic:

1. The `oracle` agent copies the entry to `<vault>/oracle/drafts/<slug>.md`
   (the original stays untouched).
2. You run `murmurent oracle publish <slug>` (or call the MCP tool
   `oracle_publish_draft(slug, push=...)`, which wraps the same code path
   and resolves your identity so you can't publish as someone else).

Publish enforces, mechanically, in `core/oracle_publish.py`:

- The draft must have complete frontmatter — `title`, `date`, `project`,
  `sensitivity`, non-empty `tags`, non-empty `sources`.
- **Both `sensitivity: clinical` and `sensitivity: restricted` entries are
  refused outright** and must stay in your personal vault. (`rules/oracle_schema.md`
  only calls out `clinical` explicitly; the code also blocks `restricted`
  — treat both as non-publishable.)
- The target filename (`<lab-mgmt>/oracle/<YYYY-MM-DD>_<slug>.md`) must not
  already exist — publish never silently overwrites a lab entry.
- On success the draft commits to the lab-mgmt repo (and pushes, if you
  asked for `--push`) and the source draft is deleted from your vault so
  the same entry doesn't live in two places at once.

Publish does **not** decide whether the lab *should* accept the entry —
that's a PI-review question handled separately from these mechanics.

## 3. The entry schema

Personal and lab entries (not notebook entries) must start with YAML
frontmatter conforming to `rules/oracle_schema.md`, or the Oracle tools
will refuse to parse them:

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

Optional fields: `related` (a list of `[[wikilink]]`s to other entries),
`source_sea`, `source_exp`, `url`.

Conventions:

- **One entry per file**, named `<YYYY-MM-DD>_<slug>.md`. Older
  "topic file with `### Heading` anchors" style files are still readable
  by the tools but are no longer the recommended shape for new writes.
- **`MEMORY.md`** at the root of `oracle/` is the master index the `oracle`
  agent reads first and updates with a one-line, wikilinked pointer to
  every new entry (`- [[<YYYY-MM-DD>_<slug>]] — one-line description`).
  `oracle_search`/`oracle_list` skip `MEMORY.md` itself (and `README.md`)
  when returning entries — it's an index, not an entry.
- **`[[wikilinks]]`**, not markdown links, for cross-references — that's
  what lets Obsidian's own graph view resolve them.

Notebook-tier entries are exempt from this schema: frontmatter is optional,
and when it's missing, date/project are inferred from the filename
(`YYYY-MM-DD.md` or `YYYY-MM-DD_slug.md`) and the parent folder name.

## 4. `maps-legends/` — the vault's own map, not murmurent's

`maps-legends/` (or whatever navigation scheme you keep at the vault root)
is entirely your convention, documented in your vault's own `CLAUDE.md`,
not in this repo. Murmurent's code has no special handling for it: it isn't
one of the folders listed in §1, so nothing here reads, writes, or
schema-checks it. Treat it as the authoritative human-readable guide to
"where things live in my vault" — murmurent's Oracle tiers are a narrower,
structured slice (`oracle/`, `oracle/drafts/`, the notebook folder) that
sits alongside whatever else `maps-legends/` organizes.

## 5. The Full Disk Access gotcha (read this before assuming something is "empty")

**This is the single most common cause of "my Oracle looks empty" reports.**

If your vault lives under iCloud Drive (`~/Library/Mobile Documents/...`,
which is where Obsidian puts vaults by default on macOS when you use
iCloud sync), that path is protected by macOS's Full Disk Access (FDA)
permission (TCC). Obsidian itself can read it because it's been granted
access; your terminal and the `claude` process usually have **not**.

The dangerous part: when access is denied, the personal and notebook tiers
degrade **silently to empty** rather than erroring — `oracle_search` and
`oracle_list` will just return nothing, and it looks exactly like "no
entries yet" instead of "can't read the vault." This is a deliberate
design choice (a sandbox denial shouldn't crash the MCP server), but it
means you cannot tell the difference between "empty" and "blocked" from
search results alone.

**Always confirm with `murmurent oracle doctor`** if search results look
thinner than expected. It actually attempts a read (not just a path
resolution — `murmurent oracle path` only resolves a path, it never touches
the vault) and reports one of:

- `OK` — read succeeded, the vault is genuinely accessible.
- `OK (empty)` — readable, but no `.md` entries yet.
- `MISSING` — the resolved path doesn't exist yet.
- `NO VAULT` — no Obsidian vault registered on this machine at all.
- `BLOCKED` — the dir resolved but a read was denied. This is the FDA case.

**Fix for `BLOCKED`:** System Settings → Privacy & Security → Full Disk
Access → add your terminal app (Terminal.app, iTerm, whichever you use)
**and** the `claude` binary itself, then retry. Both need access — the
terminal running the process and the process's own binary are checked
separately by macOS.

**iCloud placeholder caveat:** files under iCloud Drive can exist as
`.icloud` placeholder stubs that haven't been downloaded to disk yet (the
cloud-only "optimize storage" state). A placeholder can list in a
directory enumeration but fail to actually read, which will also surface
as `BLOCKED` (or as an unreadable individual file even when the directory
itself is accessible) rather than as its own separate status. If `doctor`
reports blocked access even after granting FDA, check whether the
relevant files show the iCloud download icon in Finder and force a
download by opening them there first.

## 6. Per-machine setup — how murmurent finds your vault

The same vault path is **never** hardcoded — it's resolved fresh on every
call, in this order (personal Oracle dir; the notebook dir uses the same
chain):

1. **Env override** — `$WIGAMIG_PERSONAL_ORACLE_DIR` (personal tier) /
   `$WIGAMIG_NOTEBOOK_DIR` (notebook tier). Points straight at the
   directory; mainly for tests and power users.
2. **`~/.wigamig/machine.yaml`** — `obsidian_vault_path` (+ `oracle_subfolder`,
   default `oracle`; `notebook_subfolder`, default `lab-notebook`). This is
   the normal per-machine configuration, written by the dashboard's Machine
   Settings modal. It deliberately stays out of the git-synced lab-mgmt
   repo, because where Obsidian lives on *your* laptop has no reason to
   match anyone else's.
3. **`obsidian.json` discovery** — if neither of the above resolves, murmurent
   reads Obsidian's own vault registry
   (`~/Library/Application Support/obsidian/obsidian.json` on macOS,
   `~/.config/obsidian/obsidian.json` on Linux) and picks the
   most-recently-opened vault. You can pin a specific vault by name with
   `$WIGAMIG_OBSIDIAN_VAULT` if you have more than one registered and the
   most-recent isn't the right one.

If none of these resolve, tools that need the personal tier raise a clear
error rather than guessing; the notebook tier resolves via the same chain
and returns no entries if nothing resolves.

**To point murmurent at your vault:** either open the vault at least once in
the Obsidian app (so it lands in `obsidian.json`) and let discovery pick it
up, or set `obsidian_vault_path` explicitly via the dashboard's Machine
Settings (or hand-edit `~/.wigamig/machine.yaml`).

## 7. What you can't do yet

Two things are in progress but **not shipped** — don't expect them to
work, and don't let anything above be read as implying otherwise:

- **A CLI to write daily notebook entries.** Today, notebook entries under
  `<vault>/<notebook_subfolder>/` are plain files you create and edit
  yourself (in Obsidian, an editor, whatever you like); there is no
  `murmurent notebook ...`-style command that writes one for you.
- **A vault-map command.** There is no command that inspects or reports on
  your vault's structure (e.g. a `murmurent vault map`). `maps-legends/`
  (§4) is a manual, human-maintained convention, not something murmurent
  generates or checks.

If you see either described as available somewhere else, treat this
document — checked directly against the code above — as the more current
answer.
