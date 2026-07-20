# Getting started: what Murmurent gives you on top of Claude Code

You've installed Murmurent and it runs locally on your machine. So what
does it actually *do* that plain [Claude Code](https://claude.com/claude-code)
(CC) doesn't?

Short version: Murmurent is an agentic AI operating system that provides:

- a set of **reference agents**: specialists (a literature scout, a computational
  workhorse, an adversarial reviewer, a security auditor, …) you delegate to by name;
- an **Oracle**: persistent, structured memory of what you've learned, that
  survives across sessions *and* projects;
- **hard rules + hooks**: data-governance guardrails that stop you (or the
  model) from doing something you'll regret, like overwriting raw data;
- and, when your lab or centre opts in, **shared infrastructure** so a whole
  group or collaboration accumulates knowledge together, not one laptop at a time.

Murmurent is built on Claude Code today, but nothing in its design is
specific to it: the same tiers, agents, and governance rules could sit on
another agentic AI system.

Everything below is something you can try today, on your own machine, with no PI
and no centre. The agents are already wired into `~/.claude/agents/`, so in any CC
session you invoke one just by asking for it in plain English.

---

## Where Murmurent lives on your machine

For the curious, or for auditing what Murmurent touches, here is what it
creates or modifies locally:

- `~/.claude/agents/`, `~/.claude/rules/`, `~/.claude/skills/`: the
  commons agents, rules, and skills, symlinked in by `scripts/setup.sh`.
- `~/.claude/settings.json`: where Murmurent registers its hooks and MCP
  servers.
- `~/.claude/agent-memory/`: per-agent working memory.
- `~/.claude/murmurent-preferences.yaml`: your personal preference
  profile (see Vignette 2 below).
- `~/.murmurent/`, this machine's Murmurent state: `machine.yaml`, your
  identity + membership cards, `lab_info/` (the centre registry, on a
  registrar's machine), `agents.log` (the activity log the dashboard
  tails), `keys/`, and host/registry files.
- `~/repos/murmurent` (the commons clone) and
  `~/repos/murmurent_lab_mgmt_<lab>` (your lab's governance clone).
- your Obsidian personal vault (the `murmurent_vault` clone) and, on the
  lab server, the bulk-data root `$MURMURENT_LAB_VM_ROOT/{raw,refined}/`.

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

The failure mode of an eager AI assistant is confident, plausible, *wrong*.
Murmurent ships an agent whose job is to check the other agents' work:

> **You:** Adversary, review the classifier the Blacksmith just built.
>
> **Adversary:** Questions: your train/test split leaks: samples from the same
> patient appear in both folds, so the AUC is optimistic. Re-split by patient,
> not by cell, and re-run before trusting this number.

The Adversary performs adversarial methodological review of other agents'
outputs. It checks for data leakage, inappropriate train/test splitting
(e.g. splitting by cell rather than by patient), missing or inadequate
cross-validation, and results that are implausibly strong. It separates
claims it verified itself (by running code or reading files) from claims
it could not verify, and reports the two differently. It reviews other
agents' work directly, for instance the Blacksmith's analyses or the
Bookworm's literature claims, functioning as an internal check that runs
before a result is relied on, rather than after a reviewer catches it
later.

---

## Vignette 4: Guardrails that stop mistakes before they happen (rules + hooks)

Some rules you don't want to rely on remembering. Murmurent enforces them at the
hook layer, so they hold even when you (or the model) get careless:

> **You:** Delete the old raw FASTQs in `raw/brca_wgs/` to free space.
>
> **Murmurent (raw_guard hook):** Blocked: `raw/` is immutable. No code may
> modify or delete files under `raw/`. If a refined output is superseded, write
> `file_2.csv` alongside it instead of overwriting `file_1.csv`.

Raw data stays immutable; refined data stays append-only; secrets and PHI get
caught before they reach a commit (that's the **Security Guard**'s job). These
guardrails are what make it safe to let an agent loose on real lab data. See
[`../rules/data-storage.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/data-storage.md).

---

## Vignette 5: From one laptop to a lab (the shared layer)

Everything above works standalone. The payoff compounds when a lab or centre opts
in:

- Your PI issues you a **membership ID** so agents know which lab/core you're in
  (see the README sections for members and PIs).
- The **Lab Oracle** becomes shared, curated memory: what the *whole lab* has
  agreed to remember, distinct from your personal notes, so a new student inherits
  years of institutional knowledge on day one instead of re-discovering it.
- **Cores** (e.g. a proteomics facility) expose deliverables to member labs
  through a controlled interface, and **collaborations** let groups pool agents and
  data on shared projects without a central controller dictating every move.

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
