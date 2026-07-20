# Getting started: what Murmurent adds to Claude Code

Murmurent is an agentic AI operating system for biomedical and basic
life-science research, built on top of
[Claude Code](https://claude.com/claude-code) (CC). The [home page](index.md)
summarizes what it provides; this page shows, through five short vignettes,
what Murmurent gives you over plain Claude Code. Each vignette works on a
single machine, with no PI and no centre required.

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

That memory is yours, per-user, and spans every project you work on.

---

## Vignette 2: Delegating to specialists (the agents)

Instead of a single general assistant, Murmurent gives you a set of
specialist agents, each addressed by name. The agents are designed for
biomedical and basic life-science research: they are initialized to be
aware of the resources, databases, and protocols common to these fields
(for example, PubMed and bioRxiv for the literature scout, and standard
reference genomes and quality-control conventions for the computational
agent).

- **Bookworm**: literature + databases:
  > *Bookworm, find the three most-cited papers on MMP11 in breast cancer and
  > add them to my reading list.*
  It queries PubMed/bioRxiv, summarises, and curates a list you keep.

- **Blacksmith**: the computational agent:
  > *Blacksmith, load `refined/brca_wgs/3_qc/counts.parquet`, train an
  > XGBoost classifier on subtype, and report AUC with a train/test split.*
  It writes clean, runnable Python, verifies it executes, and reports metrics.

- **Artist**: figures + communication:
  > *Artist, make a publication-quality ROC curve and a SHAP beeswarm from the
  > Blacksmith's last run.*
  It produces labelled, legible figures and keeps a rolling HTML report.

You can adapt these agents to your own research area. Each agent's
defaults (its preferred tools, libraries, databases, and conventions) can
be changed per member, without editing the shared agent definition, so
that the Bookworm searches the databases you use and the Artist follows
your plotting conventions. The full roster (Oracle, Bookworm, Blacksmith,
Adversary, Artist, Conscience, Lawyer, Security Guard, and others) is in
[`CLAUDE.md`](https://github.com/hallettmiket/murmurent/blob/main/CLAUDE.md#reference-agents-the-commons).

---

## Vignette 3: Adversarial methodological review (the Adversary)

Adversarial evaluation is a well-studied approach to improving the
reliability of AI systems. Murmurent includes an **Adversary** agent
whose role is to evaluate the outputs of the other agents and raise
questionable issues. The other reference agents are instructed to respond
to the Adversary's comments and to revise their work accordingly:

> **You:** Adversary, review the classifier the Blacksmith just built.
>
> **Adversary:** Questions: your train/test split leaks: samples from the same
> patient appear in both folds, so the AUC is optimistic. Re-split by patient,
> not by cell, and re-run before trusting this number.

The Adversary checks for problems such as data leakage, inappropriate
train/test splitting (for example, splitting by cell rather than by
patient), missing or inadequate cross-validation, and results that are
implausibly strong. It distinguishes claims it verified itself, by
running code or reading files, from claims it could not verify. When it
identifies a problem, the finding is returned to the originating agent,
which revises its output before the result is relied upon. This
adversarial loop reduces the rate at which plausible but incorrect
results (a hallucinated citation, an optimistic performance metric, an
unsupported literature claim) reach the researcher.

---

## Vignette 4: Data-governance rules enforced in software (rules + hooks)

Murmurent recognizes two special directories: **`raw/`**, whose contents
are immutable (they can be read but never modified or deleted), and
**`refined/`**, which is append-only (new analysis outputs can be added,
but existing ones are never overwritten). These rules are enforced
automatically by Claude Code hooks, which intercept an operation before
it executes and reject it if it would violate a rule:

> **You:** Delete the old raw FASTQs in `raw/brca_wgs/` to free space.
>
> **Murmurent (raw_guard hook):** Blocked: `raw/` is immutable. No code may
> modify or delete files under `raw/`. If a refined output is superseded, write
> `file_2.csv` alongside it instead of overwriting `file_1.csv`.

The same hook layer also screens candidate commits for sensitive data,
such as passwords, API keys, and clinical data, before they are recorded.
These hooks act automatically on every operation. In addition, Murmurent
provides a **Security Guard** agent that you can invoke to audit a change
or an outgoing artefact for the same problems: the hooks enforce the rules
without being asked, while the Security Guard agent performs a deeper,
on-demand review. Enforcing these constraints in software is what makes it
safe to grant an agent access to real laboratory data. See
[`../rules/data-storage.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/data-storage.md).

---

## Vignette 5: From one laptop to a lab (the shared layer)

Everything above works standalone. The payoff compounds when a lab or centre opts
in:

- Your PI issues you a **membership ID**, so agents know which lab or core
  you belong to.
- Murmurent adds a second, lab-level Oracle. In Vignette 1, the Oracle we
  used was your **personal** Oracle, private to you. The **Lab Oracle** is
  a separate, shared tier: curated memory that the whole lab has agreed to
  record. You continue to work in your personal Oracle as before, and when
  a finding is worth sharing, you deliberately push a selected entry to the
  Lab Oracle. Only what you choose to share leaves your personal vault. A
  new member then inherits the lab's accumulated knowledge from their first
  day rather than rediscovering it.

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
