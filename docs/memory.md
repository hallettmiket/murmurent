# How Murmurent remembers: the three tiers

Most agentic AI systems treat memory as undifferentiated: the model's
prompt window holds the live conversation, and anything else is fetched
on demand, typically via retrieval-augmented generation (RAG) over a
vector index. Murmurent instead separates memory into three explicit
tiers, each with its own representation, access pattern, and
governance.

Those three tiers, **conversation context**, **the oracle**, and
**bulk data**, map onto three different places on disk, three different
audiences, and three different sets of rules about who can write what. This page walks
through each tier, how information moves between them, and the
governance boundary that stops the wrong thing from moving.

---

## Tier 1: conversation context

**What it is.** The live, in-session working memory of an agent: the
user's prompt, the agent's reasoning, and the immediate tool-call
traces. Murmurent doesn't reimplement Claude Code's context window;
this tier is fully delegated to the underlying agentic command-line
interface. Murmurent adds two things on top of it:

1. **Deterministic project-context injection at session start.** The
   relevant `CLAUDE.md`, project charter, and active rules are loaded
   automatically, so an agent doesn't have to rediscover a project's
   conventions (data-storage invariants, naming rules, headline-first
   protocol) every session.
2. **Session-level audit logging** via the subagent-stop hook
   ([`scripts/murmurent_log_agent_event.sh`](https://github.com/hallettmiket/murmurent/blob/main/scripts/murmurent_log_agent_event.sh)),
   which captures each subagent's final message and feeds the
   Murmurent VSCode dashboard's live activity pane (see
   [`vscode-workflow.md`](vscode-workflow.md)).

**Where it lives.** Nowhere durable. It's the CC session's own context
window, plus a line in `~/.murmurent/agents.log` for the audit trail.

**Lifetime and audience.** Single session, single user. It evaporates
when the session ends; nothing here survives to the next conversation
unless it is deliberately promoted to Tier 2.

**Promotion out.** A user (or an agent, acting on the user's
instruction) tells the Oracle to remember something. That's the only
path out of Tier 1.

---

## Tier 2: the oracle, durable and human-readable memory

**What it is.** Durable, qualitative knowledge (observations,
decisions, near-miss results, literature summaries, methodological
choices) recorded as Markdown entries with mandatory frontmatter
(`title`, `date`, `project`, `sensitivity`, `tags`, `sources`; full
schema at
[`rules/oracle_schema.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/oracle_schema.md)).

This is a deliberate contrast with RAG. RAG is a stateless lookup over
an opaque vector index, rebuilt rather than accumulated, with limited
visibility into provenance. The oracle instead returns schema-validated
entries with explicit provenance, sensitivity, and an audit trail, and
accumulates across personnel turnover by design. Entries are
git-tracked and human-readable, so the recorded knowledge can be
audited by reading files rather than an opaque index.

**Two tiers within Tier 2.** The oracle is itself two-tier: a per-user
*personal* oracle in each researcher's Obsidian vault, and a per-lab
*group* oracle that ingests curated entries through a reviewed
publication step.

| | Personal Oracle | Lab Oracle |
|---|---|---|
| Where it lives | `<vault>/oracle/` (the member's own Obsidian vault) | `~/repos/murmurent_lab_mgmt_<lab>/oracle/` (the lab-mgmt git repo) |
| Agent | [`oracle`](https://github.com/hallettmiket/murmurent/blob/main/agents/oracle.md), reads and writes | [`lab_oracle`](https://github.com/hallettmiket/murmurent/blob/main/agents/lab_oracle.md), **read-only** (`Write` excluded from its toolset) |
| Audience | The member alone | Every lab member, across personnel turnover |
| Lifetime | As long as the member keeps the vault | Indefinite; version-controlled, reviewed |
| How new entries arrive | Directly: the member tells the Oracle to remember something | Members of the group submit entries to the lab oracle through the publish flow; it is never written directly |

**Querying across tiers.** The `murmurent-oracle` MCP server exposes
`oracle_search`/`oracle_get`/`oracle_list` with a `kind` parameter that
reaches both curated tiers and a third, more permissive **notebook**
tier: `kind` ∈ {`personal`, `lab`, `notebook`, `both` (`personal+lab`,
default), `all` (all three)}.

The notebook tier reads the member's daily lab-notebook files (see
[`lab_notebook_guide.md`](lab_notebook_guide.md)) and does not require
the Oracle schema; missing fields are derived from filename and path
conventions instead. The daily journal functions as a less-curated
layer beneath the personal Oracle, queryable through the same MCP
surface but never mandatorily promoted. Treat the personal and lab
oracle as the curated core, both schema-checked, and the notebook
`kind` as a practical extension for surfacing raw context alongside
distilled findings. Full detail:
[`oracle-workflow.md`](oracle-workflow.md).

**Promotion: personal → lab.** Deliberate and reviewed, never
automatic; see the worked example below for the exact commands. The
intent, per `oracle-workflow.md`, is that findings from one
collaboration don't accidentally cross-contaminate another.

**Governance boundary.** `murmurent oracle publish` refuses any entry
with `sensitivity: clinical` or `sensitivity: restricted`. Those stay
in the personal vault, permanently. The personal Oracle agent enforces
the same refusal before it will even stage a draft. This matches the
schema rule in
[`rules/oracle_schema.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/oracle_schema.md),
which states that a clinical entry must stay in the personal vault and
is never published to the Lab Oracle, and it is enforced identically
in the agent definitions of both `oracle` and `lab_oracle`.

---

## Tier 3: bulk data

**What it is.** Sequencing reads, mass-spec runs, NMR FIDs, microscopy
stacks, patient-cohort tables: artefacts too large for the oracle and
too varied for a single index.

**Default layout.** Murmurent ships a default layout for this tier,
and it's how a lab organizes its own bulk data. A group is
free to organize differently; the part that generalizes is the core
idea the layout encodes: a hard distinction between immutable original
inputs and append-only derived outputs.

- **`raw/<project>/`**: read-only. Original inputs from instruments,
  collaborators, or public repositories.
- **`refined/<project>/<experiment>/`**: append-only. Outputs of
  analyses, mirroring the structure of `exp/` in the project's git
  repo so the relationship between code and the data it produced is
  one `cd` away.

**How the invariant is enforced.** Murmurent installs two Claude Code
hooks, registered by `murmurent install --hooks`, that make these
rules mechanical rather than a matter of convention:

- [`raw_guard`](https://github.com/hallettmiket/murmurent/blob/main/src/murmurent/hooks/raw_guard.py)
  blocks any write, edit, rename, truncate, chmod, or delete under
  `raw/`, whether attempted through Write, Edit, NotebookEdit, or a
  Bash command. This is what makes `raw/` immutable.
- [`protected_paths`](https://github.com/hallettmiket/murmurent/blob/main/src/murmurent/hooks/protected_paths.py)
  blocks delete or overwrite of any file that already exists under
  `refined/`, while still allowing brand-new files. This is what makes
  `refined/` append-only.

To supersede a refined file, write a new integer-suffixed version
(`file_2.csv`) instead of overwriting `file_1.csv`.

**Audience and access pattern.** Agents interact with bulk data
several ways: directly, with the standard Claude Code file tools
(grep, awk, sed, ordinary reads); through purpose-built helpers such as
Blacksmith for analysis or Artist for visualisation; or, where the
data has a natural query interface (a cohort's relational schema, a
chemical-structure database), through a dedicated MCP server rather
than by copying the data into a prompt.

**A related, project-scoped artefact: the experimental notebook.**
Alongside raw/refined data, each experiment carries a git-tracked
`notebook.md` at `<project_repo>/exp/<n>_<slug>/notebook.md`: protocol,
run dates, instrument, data-file paths, and conclusions, visible to
every project member on the next `git pull`. It sits structurally
closer to Tier 3 (it documents and is versioned alongside the
refined-data outputs it describes; `murmurent push --refined`
recomputes its checksums) than to the oracle's institutional-memory
role. See [`lab_notebook_guide.md`](lab_notebook_guide.md) for the
full distinction between this **experimental notebook** and the
**daily journal** (the personal, unpublished Tier-2-adjacent notebook
tier described above).

---

## Sensitivity levels

Sensitivity is a label carried by both individual oracle entries (the
frontmatter `sensitivity:` field) and whole projects (the project
record's `sensitivity:` field, shown in the Murmurent dashboard as a
coloured badge). There are three levels:

| Level | Meaning | `murmurent oracle publish` |
|---|---|---|
| `standard` | Shareable with the lab. | Promotes it to the Lab Oracle. |
| `restricted` | Stays in the personal vault. | Refuses to publish it. |
| `clinical` | Stays in the personal vault. The underlying clinical records stay in Tier-3 storage with access logging (see below). | Refuses to publish it. |

For `clinical` data, the records themselves live in Tier-3 storage
(for example under `raw/<project>/clinical/`) with access logging.
Agents reach them only through a de-identifying MCP boundary that
returns structured summary slices, never the raw pathology reports or
radiology notes. The records are never copied into an oracle entry, a
prompt, or a vector index. Only a de-identified provenance or summary
entry (cohort size, inclusion criteria, REB/IRB approval) may live in
the oracle, and even that entry is tagged `sensitivity: clinical` so
it never gets promoted to the Lab Oracle.

---

## The governance boundary, summarised

| Rule | Enforced by |
|---|---|
| `sensitivity: clinical` / `restricted` entries never leave the personal vault | `oracle` agent (refuses to stage a draft) and `murmurent oracle publish` CLI (refuses to commit) |
| New Lab Oracle entries arrive only via reviewed `murmurent oracle publish` | `lab_oracle` agent has no `Write` tool; the CLI is the only write path |
| `raw/` is immutable | `raw_guard` hook, blocks Write/Edit/NotebookEdit/Bash on `raw/` |
| `refined/` is append-only | `protected_paths` hook, blocks delete/overwrite of existing files |
| Clinical-cohort records never enter the oracle or a vector index | Tier-3 storage plus a de-identifying MCP boundary; only provenance/summary metadata reaches Tier 2 |

---

## Worked example: one finding, three tiers

A member is investigating a chrM (mitochondrial contig) alignment
artefact on a breast cancer DNA sequencing project.

**Tier 1: the finding surfaces mid-session.** During a live CC session
running the alignment QC pipeline, the member and the Blacksmith agent
notice GRCh38.p13 mis-maps chrM reads, and that GRCh38.p14 fixes it.
This is still just conversation context: real, but ephemeral, and gone
once the session ends unless someone acts on it.

**Tier 2, personal: the member commits it to memory.** Before closing
the session:

```text
You: Oracle, remember this: GRCh38.p14 fixes the chrM contig artefact we
hit with p13 on the breast cancer cohort. We're standardising on p14 for
run 17, so don't switch references mid-cohort.
```

The Oracle agent writes `<vault>/oracle/2026-05-16_chrm_p14.md` with
required frontmatter:

```yaml
---
title: GRCh38.p14 fixes the chrM contig issue for run 17
date: 2026-05-16
project: brca_wgs
sensitivity: standard
tags: [reference-genome, chrm, breast-cancer]
sources: ['@allie']
source_exp: 3_alignment_qc
---
```

and updates `MEMORY.md` with an `[[wikilink]]` pointer. This is now
durable, personal, cross-session memory: findable weeks later from a
completely different project via `oracle_search(kind=personal)`.

**Tier 2, lab: the member decides it's worth the whole lab knowing.**
This isn't automatic; it's a deliberate two-step promotion:

```text
You: Oracle, stage 2026-05-16_chrm_p14 as a publish draft.
```

which writes `<vault>/oracle/drafts/2026-05-16_chrm_p14.md` (the
original is untouched), then from a terminal:

```bash
murmurent oracle vault-drafts                       # confirm it's staged
murmurent oracle publish 2026-05-16_chrm_p14 --push # validate + commit + push
```

`murmurent oracle publish` checks `sensitivity` (here `standard`, so
it proceeds; had it been `clinical` or `restricted` it would refuse),
checks the lab doesn't already have an entry at that path, and commits
the file into
`~/repos/murmurent_lab_mgmt_mh/oracle/2026-05-16_chrm_p14.md` under
the member's handle. From this point on, `lab_oracle` can answer "what
does the lab know about chrM artefacts?" for any member, including one
who joins the lab after @allie has moved on.

**Tier 3: the data underneath the finding.** The oracle entry's
`source_exp: 3_alignment_qc` points at the actual evidence: the
aligned BAMs and QC report live at
`$MURMURENT_LAB_VM_ROOT/refined/brca_wgs/3_alignment_qc/qc_report.html`,
produced from immutable inputs at
`$MURMURENT_LAB_VM_ROOT/raw/brca_wgs/3_alignment_qc/`, with provenance
also recorded in the git-tracked `exp/3_alignment_qc/notebook.md`. The
oracle entry is the durable, searchable pointer and summary. The
multi-gigabyte alignment outputs themselves stay in Tier 3, which is
where Murmurent keeps bulk data by design, and are never copied into
the oracle or a prompt.

---

## See also

- [`oracle-workflow.md`](oracle-workflow.md): the personal to lab
  publish flow in full, including the MCP search surface and its
  `kind` parameter.
- [`rules/oracle_schema.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/oracle_schema.md):
  required frontmatter for every Tier-2 entry.
- [`lab_notebook_guide.md`](lab_notebook_guide.md): daily journal vs.
  experimental notebook, and how each relates to the tiers above.
- [`agents.md`](agents.md): the `oracle` and `lab_oracle` agents in
  the context of the full reference-agent roster.
- [`../rules/data-storage.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/data-storage.md):
  the Tier-3 raw/refined invariants and the hooks that enforce them.
