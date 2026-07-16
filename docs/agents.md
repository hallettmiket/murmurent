# The reference agents

The **commons** is the set of reference agents, hard rules, and baseline
workflows every member of the centre draws on, regardless of lab. The
manuscript frames it this way: *"Murmurent guarantees for each user a
common set of reference agents, a robust computing environment and
interfaces which are aware of available resources and tools"* — a
shared operating system for research, not a shared research direction.
Thirteen reference agents ship in [`agents/*.md`](https://github.com/hallettmiket/murmurent/tree/main/agents)
and are symlinked into `~/.claude/agents/` by `scripts/setup.sh`: twelve
operate at the individual, group, or lab level, and a thirteenth,
`centre_cable_guy`, is a centre-level singleton.

You don't configure or invoke these specially — in any Claude Code
session on a Murmurent-enabled machine, you address an agent by name in
plain English (`Bookworm, find...`, `Adversary, review...`) and CC
routes to it. Every agent's final reply leads with a single ≤200-character
verdict line in a fixed vocabulary (see
[`rules/headline_first.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/headline_first.md)),
so the Murmurent VSCode dashboard's live activity pane always shows a
scannable punchline instead of buried prose.

Group and core toolkits are built **on top of** the commons, not instead
of it: a lab adds discipline-specific agents (a medchem specialist, an
image segmenter, a cohort curator, …) that compose against this same
reference set, the same hard rules, and the same verdict protocol —
what the manuscript calls the "commons-plus-toolkit" pattern.

---

## Oracle

Personal, per-member knowledge keeper. One Oracle per user — not per
project — living in the member's own Obsidian vault under `oracle/`.
It remembers genes, findings, hypotheses, and experimental context
across *every* project the member works on, cross-referencing entries
via `project:` frontmatter rather than separate stores per project. It
refuses to write an entry missing required schema fields. See
[`memory.md`](memory.md) for how it fits the three-tier model.

**Verdict vocabulary:** `Found / Not found / Unsure — <one-line what>`

> **You:** Oracle, what did I decide about reference genomes for DCIS?
>
> **Oracle:** Found — you standardised on GRCh38.p14 for run 17 (patches
> the chrM artefact from p13); switching references mid-cohort was
> explicitly ruled out.

## Lab Oracle

The lab-wide counterpart to the personal Oracle: curated, reviewed,
group-readable institutional memory backed by the `lab_mgmt` repo.
It is **read-only from the agent side** — its toolset deliberately
excludes `Write` — because new lab knowledge only arrives through the
`murmurent oracle publish` review flow, never by the agent writing
directly. Useful for "what has the whole lab agreed to remember,"
distinct from any one member's working notes.

**Verdict vocabulary:** `Found / Not found / Unsure — <one-line what>`

> **You:** Lab Oracle, what does the lab know about chrM artefacts?
>
> **Lab Oracle:** Found 2 lab entries — both point to GRCh38.p14 as the
> fix; contributed by @allie and @bob, see `2026-05-08_chrm_p14.md`.

## Bookworm

The team's connection to the outside world of published science and
databases. It maintains a reading list, queries scientific databases
to annotate data with published knowledge, retrieves and summarises
literature, cross-references computational predictions against known
validated results, and always cites a source (database name + accession
or PubMed ID) — distinguishing validated results from predictions. The
manuscript notes it "focuses on literature survey and harvesting of
external, publicly available data" and is easily tailored per lab so a
PI can onboard new HQP with relevant literature fast.

**Verdict vocabulary:** `Found N sources — <one-line summary>`

> **You:** Bookworm, find the three most-cited papers on MMP11 in breast
> cancer and add them to my reading list.
>
> **Bookworm:** Found 3 sources — added to `./outputs/bookworm/`; two are
> validated knockout studies, one is a computational prediction only.

## Blacksmith

The computational workhorse. It loads and preprocesses data, engineers
features, trains and evaluates classifiers, and builds
Streamlit/Dash dashboards for exploration — always verifying code
actually runs before reporting completion. The manuscript describes it
as the agent that "focuses on the management of data, development of
software and statistical analyses," tailored per lab to domain-specific
tools and protocols.

**Verdict vocabulary:** `Done / Failed / Partial — <one-line what>`

> **You:** Blacksmith, load `refined/dcis/3_qc/counts.parquet`, train an
> XGBoost classifier on subtype, and report AUC with a train/test split.
>
> **Blacksmith:** Done — AUC 0.87 on held-out test set (20% split);
> outputs in `./outputs/blacksmith/`.

## Adversary

The team's internal critic. It checks for data leakage, verifies
splitting strategy respects structure in the data (not naive random
splitting), demands proper cross-validation, and challenges any result
that looks too good. It distinguishes `OBSERVED:` claims (verified by
running code or reading files) from `SPECULATED:` ones, and never
presents the latter as fact. Per the manuscript, adversarial critique
between agents is intended to "reduce LLM hallucinations, improve
factual validity and increase the depth of answers" — the Adversary is
Murmurent's implementation of that idea, expected to evolve with use.

**Verdict vocabulary:** `Pass / Questions / Reject — <one-line why>`

> **You:** Adversary, review the classifier the Blacksmith just built.
>
> **Adversary:** Questions — your train/test split leaks: samples from
> the same patient appear in both folds, so the AUC is optimistic.

## Artist

Transforms data and findings into figures, plots, and presentation
materials that communicate science clearly. It maintains a rolling
project HTML report, produces ROC curves, confusion matrices, SHAP
plots and more, and insists every figure is legible, labelled, and
versioned. The manuscript frames the Artist as group-shared by design,
giving a lab "a common look and feel" across outputs even as different
HQP extend it with new plotting techniques over time.

**Verdict vocabulary:** `Rendered / Skipped / Failed — <one-line what>`

> **You:** Artist, make a publication-quality ROC curve from the
> Blacksmith's last run.
>
> **Artist:** Rendered — `roc_curve_xgboost.png` (300dpi) + `.pdf` saved
> to `./outputs/artist/figures/`.

## Conscience

An equity, diversity, inclusion, and decolonization watchdog. It
reviews experimental designs, text, and literature for sex/gender bias,
colonial framing, exclusionary language, and narrow sampling, and
recommends concrete revisions — grounded, for Indigenization/
decolonization guidance specifically, in *Pulling Together: A Guide for
Curriculum Developers* (BCcampus, 2018). The manuscript positions this
as a first-class review step, not an afterthought: catching bias "on
the fly" during workflow execution (e.g. flagging genes on sex
chromosomes) rather than only after the fact.

**Verdict vocabulary:** `OK / Flagged — <one-line concern>`

> **You:** Conscience, review this cohort description for the grant.
>
> **Conscience:** Flagged — the cohort text implies a universal
> phenotype from a single-ancestry sample; let's name the population
> explicitly and note the generalisability limit.

## Lawyer

Patent and IP counsel for the centre (agent body still speaks in the
voice of its former name, Saul Goodman; the canonical agent name is
now `lawyer`). Searches global patent databases (Google Patents,
Espacenet, USPTO, PatentScope, CIPO, DEPATISnet) for genes, proteins,
molecules, and devices, determines patent status, flags freedom-to-operate
concerns, and routes real FTO decisions through the Research &
Innovation Office rather than deciding them itself. The manuscript
frames this alongside the Conscience as bringing regulatory and IP
concerns into decision-making during the work, not after.

**Verdict vocabulary:** `Clear / Conflict / Unknown — <one-line on patent landscape>`

> **You:** Lawyer, is MMP11 wide open for a biotherapeutic angle?
>
> **Lawyer:** Clear — no active composition-of-matter patents on MMP11
> inhibition found across USPTO/EPO/WIPO; nearest filing expired 2019.

## Cable Guy

Infrastructure provisioner and environment wrangler for a single lab.
It onboards new members (SSH keys, repo clone, CC config, Obsidian
vault), scaffolds new projects (GitHub repo, Slack channel, `raw/` +
`refined/` dirs), maintains the installations registry, and
health-checks existing environments — always requesting PI sign-off
before touching shared infrastructure, and defaulting to `dry_run`. The
manuscript calls it the agent "dedicated to the installation and
verification of all administrative protocols," periodically auditing
that channels, repos, disk space, and membership stay correctly wired.

**Verdict vocabulary:** `Provisioned / Skipped / Failed — <one-line on what>`

> **You:** Cable Guy, provision @didi for dcis_imaging_genomics on
> lab-server.
>
> **Cable Guy:** "Wired. @didi is ready to connect on lab-server for
> dcis_imaging_genomics."

## Centre Cable Guy

The centre-wide analogue of Cable Guy: a singleton that reconciles
cross-lab infrastructure — per-project filesystem ACLs on shared
servers, cross-lab Slack/GitHub membership, and the drift-detection loop
that diffs each project's declared membership against actual state and
applies the deltas. It runs on the registrar's machine, not any PI's,
and always requests registrar sign-off before writing to shared infra.
Per the manuscript, this is the thirteenth reference agent — the one
that operates at centre scope rather than individual/group/lab scope.

**Verdict vocabulary:** `Provisioned / Skipped / Failed — <one-line on what>`
(shares Cable Guy's vocabulary; also emits `Reconciled — N deltas
applied.` after a reconcile pass)

> **You:** Centre Cable Guy, reconcile biocore × dcis-imaging.
>
> **Centre Cable Guy:** "Reconciled biocore × dcis-imaging: 2 ACL
> grants, 1 Slack invite. 0 unresolved."

## Receptionist

Routes inbound cross-group SEA (shareable experiments/assays) requests
to the right member. It watches the lab's inbound queue, matches each
request against the SEA catalog to confirm the offering still stands
and pull the contact handle, and notifies that person on Slack — and
re-notifies gently if a request sits pending more than 24 hours. It
explicitly does **not** decide: approval or decline stays with the PI
on the dashboard's Receptionist panel.

**Verdict vocabulary:** `Routed / Held / Bounced — <one-line on who/why>`

> **You:** Receptionist, anything new in the inbound queue?
>
> **Receptionist:** Routed — SEA request #14 from @foreign_lab matched
> to `qpcr_protocol_v2`; DM sent to @allie, PI review pending.

## Registrar

The administrative agent above any single lab. It tracks every lab,
core, and collaboration in the centre's registry, enforces invariants
(one PI leads at most one lab/core; collaboration member subsets must
resolve against real lab rosters), and surfaces an institution-level
view — including cross-group certification status — to the centre's
administrative head. It never looks inside a lab's own projects,
notebooks, SEAs, or personal Oracles: labs are opaque units from its
vantage point. It also acts as the centre's certificate authority,
issuing PI cards signed with the centre root key and publishing the CRL.

**Verdict vocabulary:** `Recorded / Conflict / Skipped — <one-line on what>`

> **You:** Registrar, register a new core for the proteomics facility.
>
> **Registrar:** Recorded — `proteomics_core` added to `_registry.yaml`,
> pointer to its `lab-mgmt` repo unresolved pending first push.

## Security Guard

Scans diffs and outgoing artefacts for secrets, restricted paths, and
PHI patterns before they leave the lab. It checks for credentials, API
tokens, and key material; refuses any PR that touches `raw/`; for
clinical-sensitivity projects, scans for PHI-shaped patterns (OHIP/MRN/
SIN-like strings, DOB-near-name proximity); and treats
`~/.murmurent/keys/**` as never-commit territory. Always invoked on PRs
that touch shared code or data — and, per the manuscript, jointly
maintains identity-key hygiene alongside the Cable Guy.

**Verdict vocabulary:** `Clear / Concerns / Blocked — <one-line why>`

> **You:** Security Guard, check this PR before I merge.
>
> **Security Guard:** Blocked — hardcoded API key at `src/foo.py:12`;
> load from env instead.

---

## Where to go next

| You want to… | Read |
|---|---|
| Understand the memory each agent draws on | [`memory.md`](memory.md) |
| See the personal ↔ lab Oracle publish flow in detail | [`oracle-workflow.md`](oracle-workflow.md) |
| See the full commons roster in context | [`CLAUDE.md`](https://github.com/hallettmiket/murmurent/blob/main/CLAUDE.md#reference-agents-the-commons) |
| Read the manuscript's framing of agents and choreography | the Murmurent manuscript (private; Results § "Each user inherits a robust agentic AI operating system", Methods § "Reference agents and verdict vocabulary") |
