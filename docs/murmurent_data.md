# Reference files (`murmurent_data/`)

`murmurent_data/` is a recognized folder in your Obsidian vault, alongside
`oracle/` and `lab-notebook/`. Where the Oracle holds short, curated
*facts* and the lab notebook holds *daily entries*, `murmurent_data/` holds
**reference documents**: the underlying files you want the agents to be able
to read, such as PDFs of papers, spreadsheets of metadata, protocols, or
images. Unlike the Oracle, it is not schema-validated and holds any file
type.

Like the other vault folders, it is scaffolded by `murmurent vault init`,
git-tracked, pushed to your private `murmurent_vault` repository, and pinned
per machine (its location is resolvable with `murmurent vault paths`).

## What goes in it

- Reference-sized documents: a paper PDF, a small metadata spreadsheet, a
  protocol, a figure.
- Anything you want available to an agent as source material to condition
  its work.

Two boundaries:

- **Size.** `murmurent_data/` is git-tracked and pushed to GitHub, so keep
  it to reference-sized files. Large or bulk data (cohort tables, imaging
  stacks, sequencing outputs) belong in Tier 3 (`raw/` and `refined/` on the
  lab VM), not the vault.
- **Sensitivity.** Because the vault is pushed to GitHub, genuinely
  sensitive clinical data files should not go here; keep them in Tier 3 on
  the lab VM, under filesystem ACLs.

## How agents reach it

Agents access `murmurent_data/` two ways:

- **Directly.** An agent can `Glob` and `Read` the files (Claude Code reads
  PDFs, spreadsheets, and images).
- **Through the `murmurent-data` MCP server.** It exposes `data_list` (list
  the files, with size and type) and `data_read` (return the text of a
  text file, or the absolute path of a binary file to open directly).

## How Murmurent decides: Oracle or `murmurent_data`?

A natural question is how an agent knows whether to look in the Oracle
(recorded facts) or in `murmurent_data/` (reference documents). There is no
separate router; the choice follows from your request and from the
documented purpose of each store, which the agents are told about in the
vault's `CLAUDE.md` and in their own instructions.

- Ask about a **recorded fact or decision** ("what did I conclude about
  ESR1?"), and the agent searches the **Oracle** with the `murmurent-oracle`
  MCP, which does structured search over short entries by project, tag,
  date, and sensitivity.
- Ask it to **read or use a document** ("read the ESR1 paper in my data
  folder", "summarise this metadata spreadsheet"), and the agent lists and
  reads **`murmurent_data/`** with the `murmurent-data` MCP or a direct file
  read.

Most often you do not choose at all, because the two are linked. The
recommended pattern is to keep the short *fact* in the Oracle and the
*source document* in `murmurent_data/`, with the Oracle entry referencing
the file (by path, or by `url:`/DOI for a paper). A search of the Oracle
then finds the fact and points at the underlying document, which the agent
reads on demand. The Oracle is the searchable index; `murmurent_data/` is
where the full sources live.

A practical consequence: the Oracle and the lab notebook are full-text
searched by the `murmurent-oracle` MCP, but the *contents* of a PDF or
spreadsheet in `murmurent_data/` are not indexed. They are reached when an
entry references them, or when you ask an agent to read them directly. If
you want a fact from a document to be searchable, record it as a short
Oracle note.

## Worked example

See [vignette 4](vault_vignettes/4_add_a_manuscript.md) for a step-by-step
example: dropping a paper PDF into `murmurent_data/`, having the Bookworm
read it, and saving a one-line Oracle note that references it.
