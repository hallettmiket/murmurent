# The reference agents

The **commons** is a shared set of reference agents, hard rules, and
baseline workflows every member of the centre draws on, regardless of
lab: a common operating system for research, while each lab keeps its
own research direction. The reference agents ship in
[`agents/*.md`](https://github.com/hallettmiket/murmurent/tree/main/agents)
and are symlinked into `~/.claude/agents/` by `scripts/setup.sh`. They
fall into three categories:

- **Member** — the per-member/per-lab science toolkit (Oracle, Lab
  Oracle, Bookworm, Blacksmith, Adversary, Artist, Conscience, Lawyer,
  Cable Guy, Security Guard).
- **Administrative** — centre-level singletons that act above any single
  lab (`registrar`, `centre_cable_guy`; a centre security guard will
  join them).
- **Choreography-support** — agents that specifically support building
  compositional choreographies (`judge`, plus data-shaping / filtering /
  chaining agents to come).

Alongside the commons, a member can create **personal agents** for their
own work — for a bespoke step in a choreography, or just for day-to-day
computing. Create one with `murmurent agent new <name>` (or the dashboard
Agents panel's **+ new**); it is written to your personal vault under
`agents/`, so `murmurent vault sync` backs it up to your GitHub, and it is
symlinked into `~/.claude/agents/` so Claude Code loads it. A personal agent
lives in your village only — it is never part of the commons and never
appears in another member's environment. (Making your own copy of a *commons*
agent instead is a **fork**: `murmurent agent fork <name>`, kept in
`~/.murmurent/agent_forks/`.)

You invoke these by addressing an agent by name in plain English (for
example, *"Bookworm, find all manuscripts related to MMP11 in breast
cancer,"* or *"Adversary, review the findings of the Bookworm's
literature review for overlooked or contradictory studies"*) in any
Claude Code session on a Murmurent-enabled machine, and CC routes to it.
Every agent ships pre-configured with sensible defaults and is usable
immediately; you can override those defaults without editing the agent
itself, per member via `~/.claude/murmurent-preferences.yaml`
(`murmurent preference set <field> <value>`), or per lab through the
lab's own toolkit. The sections below call out which defaults are worth
knowing about for each agent. Every agent's final reply leads with a
single ≤200-character verdict line in a fixed vocabulary (see
[`rules/headline_first.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/headline_first.md)),
so the Murmurent VSCode dashboard's live activity pane always shows a
scannable verdict.

Group and core toolkits are built on top of the commons: a lab adds
discipline-specific agents (a medchem specialist, an image segmenter, a
cohort curator, …) that compose against this same reference set, the
same hard rules, and the same verdict protocol. This corresponds to the
so-called "commons-plus-toolkit" pattern described in the manuscript.

---

## Oracle

Personal, per-member knowledge keeper. One Oracle per user (not per
project) living in the member's own Obsidian vault under `oracle/`.
It remembers genes, findings, hypotheses, and experimental context
across every project the member works on, cross-referencing entries
via `project:` frontmatter rather than separate stores per project. It
refuses to write an entry missing required schema fields. See
[`memory.md`](memory.md) for how it fits the three-tier model.

**Verdict vocabulary:** `Found / Not found / Unsure — <one-line what>`

> **You:** Oracle, what did I decide about reference genomes for breast
> cancer sequencing?
>
> **Oracle:** Found: you standardised on GRCh38.p14 for run 17 (patches
> the chrM artefact from p13); switching references mid-cohort was
> explicitly ruled out.

## Lab Oracle

The lab-wide counterpart to the personal Oracle: curated, reviewed,
group-readable institutional memory backed by the
`murmurent_lab_mgmt_<lab>` repo. It is read-only from the agent side
(its toolset deliberately
excludes `Write`) because new lab knowledge only arrives through the
`murmurent oracle publish` review flow, never by the agent writing
directly. Useful for "what has the whole lab agreed to remember,"
distinct from any one member's working notes.

**Verdict vocabulary:** `Found / Not found / Unsure — <one-line what>`

> **You:** Lab Oracle, what does the lab know about chrM artefacts?
>
> **Lab Oracle:** Found 2 lab entries: both point to GRCh38.p14 as the
> fix; contributed by @allie and @bob, see `2026-05-08_chrm_p14.md`.

## Bookworm

The team's connection to the outside world of published science and
databases, tailored for biomedical research. It maintains a reading
list, queries biomedical databases and preprint servers (PubMed,
bioRxiv/medRxiv, ClinicalTrials.gov) to annotate data with published
knowledge, retrieves and summarises literature, and cross-references
computational predictions against known validated results. It always
cites a source (database name + accession or PubMed ID) and
distinguishes validated results from predictions rather than blending
them. When Zotero API credentials are configured
(`$ZOTERO_USER_ID`/`$ZOTERO_API_KEY`), it can add papers straight to a
member's Zotero library. Which databases it favours and which starter
reading list it emphasizes are tunable per lab, so a PI can bring a new
trainee up to speed on the relevant literature quickly.

**Verdict vocabulary:** `Found N sources — <one-line summary>`

> **You:** Bookworm, find the three most-cited papers on MMP11 in breast
> cancer and add them to my reading list.
>
> **Bookworm:** Found 3 sources: added to `./outputs/bookworm/`; two are
> validated knockout studies, one is a computational prediction only.

## Blacksmith

The primary computational agent. It loads and preprocesses data, engineers
features, trains and evaluates classifiers, and builds interactive
interfaces (Streamlit or Dash) for exploration, always verifying code
actually runs before reporting completion. It ships with defaults (for
example `package_manager: uv`), and its tool and library preferences are
configurable: a lab can standardize on, say, Streamlit over Dash, or a
particular statistics stack, by changing the agent's defaults rather
than re-instructing it every session.

**Verdict vocabulary:** `Done / Failed / Partial — <one-line what>`

> **You:** Blacksmith, load `append_only/brca_wgs/3_qc/counts.parquet`, train
> an XGBoost classifier on subtype, and report AUC with a train/test split.
>
> **Blacksmith:** Done: AUC 0.87 on held-out test set (20% split);
> outputs in `./outputs/blacksmith/`.

## Adversary

The internal methodological reviewer. It checks for data leakage and verifies that
the train/test split respects structure in the data rather than
splitting individual rows at random. Concretely: when a dataset has
grouped structure (for example several cells or samples drawn from the
same patient), splitting rows at random can place data from the same
patient in both the training and test sets. That leaks information
between the two sets and makes reported performance look better than it
really is; the correct approach is to split by the grouping unit (by
patient), not by row. The Adversary also demands proper cross-validation
and challenges any result that looks too good. It distinguishes
`OBSERVED:` claims (verified by
running code or reading files) from `SPECULATED:` ones, and never
presents the latter as fact. Adversarial critique between agents reduces
hallucinations, improves factual validity, and increases the depth of
answers. The Adversary is Murmurent's implementation of that idea, and
it is expected to evolve with use.

**Verdict vocabulary:** `Pass / Questions / Reject — <one-line why>`

> **You:** Adversary, review the classifier the Blacksmith just built.
>
> **Adversary:** Questions: your train/test split leaks: samples from
> the same patient appear in both folds, so the AUC is optimistic.

## Artist

Transforms data and findings into figures, plots, and presentation
materials that communicate science clearly. It maintains a rolling
project HTML report, produces ROC curves, confusion matrices, SHAP
plots and more, and insists every figure is legible, labelled, and
versioned. The Artist is shared across a group by design, giving a lab
a common look and feel across outputs even as different HQP extend it
with new plotting techniques over time. Its visual defaults (colour
schemes, fonts, and figure/presentation conventions) are configurable,
the same way every agent's defaults are (see the intro above): a lab can
point the Artist at, say, a university's brand palette and fonts and its
presentation best-practice guidelines, so every output the group
produces carries a consistent look.

**Verdict vocabulary:** `Rendered / Skipped / Failed — <one-line what>`

> **You:** Artist, make a publication-quality ROC curve from the
> Blacksmith's last run.
>
> **Artist:** Rendered: `roc_curve_xgboost.png` (300dpi) + `.pdf` saved
> to `./outputs/artist/figures/`.

## Conscience

The Conscience is both an equity, diversity, inclusion, and
decolonization (EDID) reviewer and a sex- and gender-based analysis
(SGBA) agent. It reviews experimental designs, text, and literature for
both concerns, and flags colonial framing, exclusionary language, and
narrow sampling, recommending concrete revisions. Its Indigenization
and decolonization guidance is grounded specifically in *Pulling
Together: A Guide for Curriculum Developers* (BCcampus, 2018), a
Canadian-context open resource, and it can draw on Tier-II oracle
knowledge the lab has recorded about EDID and sex/gender-based-analysis
practices. This review runs during workflow execution (for example,
flagging genes on sex chromosomes) rather than only after the fact.

**Verdict vocabulary:** `OK / Flagged — <one-line concern>`

> **You:** Conscience, review this cohort description for the grant.
>
> **Conscience:** Flagged: the cohort text implies a universal
> phenotype from a single-ancestry sample; let's name the population
> explicitly and note the generalisability limit.

> **You:** Conscience, check the abstract before I submit the grant.
>
> **Conscience:** Flagged: "suffers from" and "confined to a
> wheelchair" are exclusionary/ableist phrasing; use "has" and "uses a
> wheelchair" instead.

> **You:** Conscience, read the background section of this methods
> paper.
>
> **Conscience:** Flagged: the background frames the sampled community
> as a passive source of specimens rather than a partner; name the
> community, credit their contribution, and note any data-sharing
> agreement in place.

> **You:** Conscience, does this analysis need SGBA?
>
> **Conscience:** Flagged: the differential-expression list includes
> several X-linked genes but the model doesn't stratify or adjust by
> sex; re-run stratified by sex or add sex as a covariate before
> interpreting those hits.

> **You:** Conscience, review this cohort table for the manuscript.
>
> **Conscience:** Flagged: the cohort table never reports a sex/gender
> breakdown; add it so readers can judge whether the sample supports
> sex-stratified conclusions.

## Lawyer

Patent and IP counsel for the centre. Searches global patent databases
(Google Patents, Espacenet, USPTO, PatentScope, CIPO, DEPATISnet) for
genes, proteins, molecules, and devices, determines patent status, flags
freedom-to-operate concerns, and routes real FTO decisions through the
Research & Innovation Office rather than deciding them itself. Alongside
the Conscience, this brings regulatory and IP concerns into
decision-making during the work, not after.

**Verdict vocabulary:** `Clear / Conflict / Unknown — <one-line on patent landscape>`

> **You:** Lawyer, is MMP11 wide open for a biotherapeutic angle?
>
> **Lawyer:** Clear: no active composition-of-matter patents on MMP11
> inhibition found across USPTO/EPO/WIPO; nearest filing expired 2019.

## Cable Guy

Infrastructure provisioner and environment wrangler for a single lab.
It onboards new members (SSH keys, repo clone, CC config, Obsidian
vault), scaffolds new projects (GitHub repo, Slack channel, `immutable/` +
`append_only/` dirs), maintains the installations registry, and
health-checks existing environments, always requesting PI sign-off
before touching shared infrastructure. By default it first previews the
actions it would take (creating a channel, cloning a repo, setting up
directories) and waits for explicit confirmation before making any
change, so nothing happens to shared infrastructure without a human
approving it first. It is dedicated to the installation and
verification of all administrative protocols, periodically auditing
that channels, repos, disk space, and membership stay correctly wired.

**Verdict vocabulary:** `Provisioned / Skipped / Failed — <one-line on what>`

> **You:** Cable Guy, provision @didi for brca_imaging_genomics on
> lab-server.
>
> **Cable Guy:** "Wired. @didi is ready to connect on lab-server for
> brca_imaging_genomics."

## Centre Cable Guy

The centre-wide analogue of Cable Guy. Every lab runs its own copy of
Cable Guy, but there is exactly one Centre Cable Guy for the whole
centre (a **singleton**) running on the registrar's machine rather
than any PI's. It reconciles cross-lab infrastructure: per-project
filesystem ACLs on shared servers and cross-lab Slack/GitHub
membership. It does this through a drift-detection loop: **drift** is
the gap between a project's declared, intended membership and
configuration and the actual state of Slack, GitHub, and the
filesystem: for example a member who was removed from a project's
roster but never removed from its Slack channel. The reconcile loop
diffs declared state against actual state and applies the corrections
needed to close that gap. It always requests registrar sign-off before
writing to shared infra. This is the thirteenth reference agent, the
one that operates at centre scope rather than individual/group/lab
scope.

**Verdict vocabulary:** `Provisioned / Skipped / Failed — <one-line on what>`
(shares Cable Guy's vocabulary; also emits `Reconciled — N deltas
applied.` after a reconcile pass)

> **You:** Centre Cable Guy, reconcile example_core × brca-imaging.
>
> **Centre Cable Guy:** "Reconciled example_core × brca-imaging: 2 ACL
> grants, 1 Slack invite. 0 unresolved."

## Registrar

The administrative agent above any single lab. It tracks every lab,
core, and collaboration in the centre's registry, enforces invariants
(one PI leads at most one lab/core; collaboration member subsets must
resolve against real lab rosters), and surfaces an institution-level
view (including cross-group certification status) to the centre's
administrative head. It never looks inside a lab's own projects,
notebooks, SEAs, or personal Oracles: labs are opaque units from its
vantage point. It also acts as the centre's certificate authority,
issuing PI cards signed with the centre root key and publishing the CRL.
Beyond the live registry, the Registrar also maintains centre-level
institutional memory over time, for example, remembering which
institutional datasets of lasting value the centre holds, who curates
each one, and their provenance, so that knowledge persists across
personnel changes rather than leaving with whoever originally set it up.

**Verdict vocabulary:** `Recorded / Conflict / Skipped — <one-line on what>`

> **You:** Registrar, register a new core for the proteomics facility.
>
> **Registrar:** Recorded: `proteomics_core` added to `_registry.yaml`,
> pointer to its `murmurent_lab_mgmt_<lab>` repo unresolved pending
> first push.

## Security Guard

Scans diffs and outgoing artefacts for secrets, restricted paths, and
PHI patterns before they leave the lab. It checks for credentials, API
tokens, and key material; for clinical-sensitivity projects, scans for
PHI-shaped patterns (OHIP/MRN/SIN-like strings, DOB-near-name
proximity); and treats `~/.murmurent/keys/**` as never-commit
territory. Under Murmurent's default data layout (see
[`memory.md`](memory.md)), `immutable/` holds a project's original inputs and
is read-only: nothing may modify or delete files there. The Security
Guard helps enforce that rule at the data-folder level by refusing any
PR that would modify `immutable/`, complementing the `raw_guard` hook that
blocks the same kind of change at the tool layer (before a write even
reaches disk). Always invoked on PRs that touch shared code or data, and
jointly maintains identity-key hygiene alongside the Cable Guy.

**Verdict vocabulary:** `Clear / Concerns / Blocked — <one-line why>`

> **You:** Security Guard, check this PR before I merge.
>
> **Security Guard:** Blocked: hardcoded API key at `src/foo.py:12`;
> load from env instead.

---

## Judge

Combines and presents the phrases contributed to a compositional
choreography (see [Choreographies](choreography.md) and
[Phrases](phrases.md)). Given a run package, it joins the phrases' outputs on
the choreography's candidate-identity key, applies the criteria the
question-poser supplied, and presents the candidates with full provenance. It
surfaces disagreement between phrases rather than hiding it, and computes a
single consensus only when the phrase outputs share a metric; otherwise it
presents the alternatives side by side. It never silently discards a phrase's
output, hands the combined presentation to the [Artist](#artist) for
expression, and its combination is reviewed by the [Adversary](#adversary).
Its ranking and decision strategy evolves in its own definition over time and
can be forked per lab like any reference agent.

**Verdict vocabulary:** `Presented / Split / Insufficient — <one-line on the combined result>`

> **You:** Judge, combine the phrases for the sulfopin choreography.
>
> **Judge:** Split: the docking and ML phrases agree on the top two
> candidates, but the wet-lab affinities rank them in the opposite order;
> presenting both rankings side by side with the measured values flagged.

---

## Where to go next

| You want to… | Read |
|---|---|
| Understand the memory each agent draws on | [`memory.md`](memory.md) |
| See the personal ↔ lab Oracle publish flow in detail | [`oracle-workflow.md`](oracle-workflow.md) |
| See the full commons roster in context | [`CLAUDE.md`](https://github.com/hallettmiket/murmurent/blob/main/CLAUDE.md#reference-agents-the-commons) |
| Read the manuscript's framing of agents and choreography | the Murmurent manuscript (private; Results § "Each user inherits a robust agentic AI operating system", Methods § "Reference agents and verdict vocabulary") |
