# Getting started — what Murmurent gives you on top of Claude Code

You've installed Murmurent and it runs locally on your machine. So what
does it actually *do* that plain [Claude Code](https://claude.com/claude-code)
(CC) doesn't?

Short version: CC is a brilliant generalist that **forgets everything between
sessions** and knows nothing about your lab. Murmurent turns it into a
**research team with a memory and house rules**:

- a set of **reference agents** — specialists (a literature scout, a computational
  workhorse, a skeptical reviewer, a security auditor, …) you delegate to by name;
- an **Oracle** — persistent, structured memory of what you've learned, that
  survives across sessions *and* projects;
- **hard rules + hooks** — data-governance guardrails that stop you (or the
  model) from doing something you'll regret, like overwriting raw data;
- and, when your lab or centre opts in, **shared infrastructure** so a whole
  group or collaboration accumulates knowledge together, not one laptop at a time.

Everything below is something you can try today, on your own machine, with no PI
and no centre. The agents are already wired into `~/.claude/agents/`, so in any CC
session you invoke one just by asking for it in plain English.

---

## Vignette 1 — Memory that outlives the session (the Oracle)

Plain CC starts every session as a blank slate. You re-explain your project, your
gene list, and last week's dead end every single time.

With Murmurent, you tell the **Oracle** once:

> **You:** Oracle, remember this: GRCh38.p14 fixes the chrM contig artefact we
> hit with p13 on the DCIS cohort. We're standardising on p14 for run 17 — don't
> switch references mid-cohort.

The Oracle writes a structured entry into your Obsidian vault (`oracle/`), with
frontmatter (`title`, `date`, `project`, `tags`, …) so it's findable later. Weeks
later, in a *different* session on a *different* project:

> **You:** Oracle, what did I decide about reference genomes for DCIS?
>
> **Oracle:** Found — you standardised on GRCh38.p14 for run 17 (p14 patches the
> chrM artefact from p13); switching references mid-cohort was explicitly ruled out.

That memory is **yours**, per-user, and spans every project you work on. Nothing
leaks between projects unless you deliberately promote it. See
[`oracle-workflow.md`](oracle-workflow.md) for the personal → lab publish flow.

---

## Vignette 2 — Delegating to specialists (the agents)

Instead of one general assistant, you have a bench of specialists. You don't
configure them — you just address the right one:

- **Bookworm** — literature + databases:
  > *Bookworm, find the three most-cited papers on MMP11 in breast cancer and
  > add them to my reading list.*
  It queries PubMed/bioRxiv, summarises, and curates a list you keep.

- **Blacksmith** — the computational workhorse:
  > *Blacksmith, load `refined/dcis/3_qc/counts.parquet`, train an XGBoost
  > classifier on subtype, and report AUC with a train/test split.*
  It writes clean, runnable Python, verifies it executes, and reports metrics.

- **Artist** — figures + communication:
  > *Artist, make a publication-quality ROC curve and a SHAP beeswarm from the
  > Blacksmith's last run.*
  It produces labelled, legible figures and keeps a rolling HTML report.

Each agent leads its reply with a one-line verdict (so you see the punchline at a
glance) and stays in its lane. Full roster (Oracle, Bookworm, Blacksmith,
Adversary, Artist, Conscience, Lawyer, Security Guard, and more) in
[`CLAUDE.md`](../CLAUDE.md#reference-agents-the-commons).

---

## Vignette 3 — A skeptic who reads your work before your reviewers do (the Adversary)

The failure mode of an eager AI assistant is confident, plausible, *wrong*.
Murmurent ships a built-in critic:

> **You:** Adversary, review the classifier the Blacksmith just built.
>
> **Adversary:** Questions — your train/test split leaks: samples from the same
> patient appear in both folds, so the AUC is optimistic. Re-split by patient,
> not by cell, and re-run before trusting this number.

The Adversary hunts for data leakage, unstated assumptions, and results too good
to be true. It's the cheapest peer review you'll ever get, and it happens *before*
you write the paper, not after a reviewer catches it.

---

## Vignette 4 — Guardrails that stop mistakes before they happen (rules + hooks)

Some rules you don't want to rely on remembering. Murmurent enforces them at the
hook layer, so they hold even when you (or the model) get careless:

> **You:** Delete the old raw FASTQs in `raw/dcis/` to free space.
>
> **Murmurent (raw_guard hook):** Blocked — `raw/` is immutable. No code may
> modify or delete files under `raw/`. If a refined output is superseded, write
> `file_2.csv` alongside it instead of overwriting `file_1.csv`.

Raw data stays immutable; refined data stays append-only; secrets and PHI get
caught before they reach a commit (that's the **Security Guard**'s job). These
guardrails are what make it safe to let an agent loose on real lab data. See
[`../rules/data-storage.md`](../rules/data-storage.md).

---

## Vignette 5 — From one laptop to a lab (the shared layer)

Everything above works standalone. The payoff compounds when a lab or centre opts
in:

- Your PI issues you a **membership ID** so agents know which lab/core you're in
  (see the README sections for members and PIs).
- The **Lab Oracle** becomes shared, curated memory: what the *whole lab* has
  agreed to remember, distinct from your personal notes — so a new student inherits
  years of institutional knowledge on day one instead of re-discovering it.
- **Cores** (e.g. a proteomics facility) expose deliverables to member labs
  through a controlled interface, and **collaborations** let groups pool agents and
  data on shared projects without a central controller dictating every move.

That's the "village" idea: independent groups, shared commons, accumulating
knowledge across every project. The full vision is in
[`CLAUDE.md`](../CLAUDE.md) and the design docs under [`.`](.).

---

## Where to go next

| You want to… | Read |
|---|---|
| See every CLI command | [`cli_manual.md`](cli_manual.md) |
| Create a project (intra- or inter-group) | [`project_creation.md`](project_creation.md) |
| Understand the Oracle (personal vs lab) | [`oracle-workflow.md`](oracle-workflow.md) |
| Set up the 4-quadrant VSCode workflow | [`vscode-workflow.md`](vscode-workflow.md) |
| Understand membership IDs & trust | [`identity.md`](identity.md) |
| Learn the data-storage rules | [`../rules/data-storage.md`](../rules/data-storage.md) |
| Read the full architecture | [`../CLAUDE.md`](../CLAUDE.md) |
