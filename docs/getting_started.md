# Getting started: what Murmurent adds to Claude Code

Murmurent is an agentic AI operating system for biomedical and basic
life-science research, built on top of
[Claude Code](https://claude.com/claude-code) (CC). The [home page](index.md)
summarizes what it provides; this page shows, through five short vignettes,
what Murmurent gives you over plain Claude Code.

Each vignette works on a single machine, with no PI and no centre required.
The reference agents are already wired into `~/.claude/agents/`, so any CC
session can invoke one by name. For the full list of what Murmurent installs
or modifies on your machine, see [Install & setup](setup.md).

---

## Vignette 1: Memory that outlives the session (the Oracle)

Plain CC starts every session as a blank slate. You re-explain your project, your
gene list, and last week's dead end every single time.

With Murmurent, you tell the **Oracle** once:

> **You:** Oracle, remember this: GRCh38.p14 fixes the chrM contig artefact we
> hit with p13 on the `brca_wgs` breast cancer cohort. We're standardising on
> p14 for run 17. Don't switch references mid-cohort.

The Oracle writes a structured entry into your Obsidian vault (`oracle/`), with
frontmatter (`title`, `date`, `project`, `tags`, …) so it's findable later. Weeks
later, in a *different* session on a *different* project:

> **You:** Oracle, what did I decide about reference genomes for breast
> cancer sequencing?
>
> **Oracle:** Found: you standardised on GRCh38.p14 for run 17 (p14 patches the
> chrM artefact from p13); switching references mid-cohort was explicitly ruled out.

That memory is **yours**, per-user, and spans every project you work on. Nothing
leaks between projects unless you deliberately promote it. See
[`oracle-workflow.md`](oracle-workflow.md) for the personal → lab publish flow.

---

## Vignette 2: Delegating to specialists (the agents)

Instead of one general assistant, you have a bench of specialists. Each one
ships with sensible defaults and is usable right away. You just address
the right one by name:

- **Bookworm**: literature + databases:
  > *Bookworm, find the three most-cited papers on MMP11 in breast cancer and
  > add them to my reading list.*
  It queries PubMed/bioRxiv, summarises, and curates a list you keep.

- **Blacksmith**: the computational workhorse:
  > *Blacksmith, load `refined/brca_wgs/3_qc/counts.parquet`, train an
  > XGBoost classifier on subtype, and report AUC with a train/test split.*
  It writes clean, runnable Python, verifies it executes, and reports metrics.

- **Artist**: figures + communication:
  > *Artist, make a publication-quality ROC curve and a SHAP beeswarm from the
  > Blacksmith's last run.*
  It produces labelled, legible figures and keeps a rolling HTML report.

Each agent leads its reply with a one-line verdict (so you see the punchline at a
glance) and stays in its lane. If a default doesn't suit you, you can change
it without editing the agent itself, per member, via
`~/.claude/murmurent-preferences.yaml` (`murmurent preference set <field>
<value>`), or per lab, through the lab's own toolkit. Full roster (Oracle,
Bookworm, Blacksmith, Adversary, Artist, Conscience, Lawyer, Security Guard,
and more) in
[`CLAUDE.md`](https://github.com/hallettmiket/murmurent/blob/main/CLAUDE.md#reference-agents-the-commons).

---

## Vignette 3: Adversarial methodological review (the Adversary)

An AI agent can make mistakes. To address this, Murmurent employs an
adversarial agent, the **Adversary**, which performs methodological
review of other agents' outputs:

> **You:** Adversary, review the classifier the Blacksmith just built.
>
> **Adversary:** Questions: your train/test split leaks: samples from the same
> patient appear in both folds, so the AUC is optimistic. Re-split by patient,
> not by cell, and re-run before trusting this number.

The Adversary checks for data leakage, inappropriate train/test
splitting (for example, splitting by cell rather than by patient),
missing or inadequate cross-validation, and results that are
implausibly strong. It distinguishes claims it verified itself, by
running code or reading files, from claims it could not verify, and
reports the two separately. It reviews other agents' work directly, for
instance the Blacksmith's analyses or the Bookworm's literature claims,
providing an internal check applied before a result is relied upon.

---

## Vignette 4: Data-governance rules enforced in software (rules + hooks)

Certain data-governance rules are enforced in software rather than left
to convention. Murmurent implements them as Claude Code hooks, which
intercept an operation before it executes and reject it if it violates a
rule:

> **You:** Delete the old raw FASTQs in `raw/brca_wgs/` to free space.
>
> **Murmurent (raw_guard hook):** Blocked: `raw/` is immutable. No code may
> modify or delete files under `raw/`. If a refined output is superseded, write
> `file_2.csv` alongside it instead of overwriting `file_1.csv`.

Raw data is immutable and refined data is append-only; candidate commits
are screened for secrets and personal health information (PHI) before
they are recorded, which is the role of the **Security Guard**. Enforcing
these constraints at the hook layer is what makes it safe to grant an
agent access to real laboratory data. See
[`../rules/data-storage.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/data-storage.md).

---

## Vignette 5: From one laptop to a lab (the shared layer)

Everything above works standalone. The payoff compounds when a lab or centre opts
in:

- Your PI issues you a **membership ID** so agents know which lab or core
  you belong to (see the README sections for members and PIs).
- Murmurent provides a second, lab-level Oracle, distinct from your
  personal one. The **Lab Oracle** is shared, curated memory: what the
  whole lab has agreed to record. A new member inherits the lab's
  accumulated knowledge on their first day rather than rediscovering it.
- **Cores** (a shared facility such as a proteomics or imaging centre) are
  themselves groups, each led by a PI, that expose deliverables to member labs
  through a controlled interface. **Projects** bring individual members
  together around shared repositories and data, with members drawn from a
  single group or from several groups at once.

Independent groups share a common set of agents, rules, and infrastructure
(the commons), so knowledge accumulates across every project and every
person who works on it, instead of being trapped on one machine. The full
vision is in
[`CLAUDE.md`](https://github.com/hallettmiket/murmurent/blob/main/CLAUDE.md) and the design docs under [`docs/`](https://github.com/hallettmiket/murmurent/tree/main/docs).

---

## Where to go next

| You want to… | Read |
|---|---|
| See every CLI command | [`cli_manual.md`](cli_manual.md) |
| Create a project (intra- or inter-group) | [`project_intra.md`](project_intra.md) |
| Understand the Oracle (personal vs lab) | [`oracle-workflow.md`](oracle-workflow.md) |
| Set up the 4-quadrant VSCode workflow | [`vscode-workflow.md`](vscode-workflow.md) |
| Understand membership IDs & trust | [`identity.md`](identity.md) |
| Learn the data-storage rules | [`../rules/data-storage.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/data-storage.md) |
| Read the full architecture | [`../CLAUDE.md`](https://github.com/hallettmiket/murmurent/blob/main/CLAUDE.md) |
