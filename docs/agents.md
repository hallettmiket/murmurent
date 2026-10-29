# The reference agents

The **commons** is a shared set of reference agents, hard rules, and
baseline workflows every member of the centre draws on, regardless of
lab: a common operating system for research, while each lab keeps its
own research direction. The reference agents ship in
[`agents/*.md`](https://github.com/hallettmiket/murmurent/tree/main/agents)
and are symlinked into `~/.claude/agents/` by `scripts/setup.sh`. They
fall into three categories:

- **Member** — the per-member/per-lab science toolkit (Oracle, Lab
  Oracle, Bookworm, Blacksmith, Adversary, Artist, Teacher, Scribe,
  Conscience, Lawyer, Millwright, Security Guard).
- **Administrative** — centre-level singletons that act above any single
  lab (`registrar`, `centre_millwright`; a centre security guard will
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
agent instead is a **fork**: `murmurent agent fork <name>`, kept in your
vault under `agent_forks/`.) Because both folders live in the vault, your
personal agents and forks follow you to every machine: after a vault pull,
run `murmurent agent relink` (`scripts/setup.sh` also runs it) to load them
into that machine's `~/.claude/agents/`.

**Which version am I using?** Each agent card on the dashboard says which
definition Claude Code will actually use on this machine: the centre version,
your own version, a hand-written file, a broken link, or nothing installed.
Hover over the label for the reason. In a terminal,
`murmurent agent which` shows the same for every agent, and
`murmurent agent which --repo <folder>` shows it for a session started in
that repo, where the repo's own agent files take priority. A **broken link**
usually means the repo contains links into another member's home folder;
`murmurent repo status <folder>` explains how to fix it.

A version can also be kept for one project only, shared with a project team
or the whole lab, or an agent switched off in one project: see
[Choosing an agent's version](agent_versions.md). The **disable** button on
the dashboard's agent cards only labels the agent; to stop Claude Code using
it in a project, use `murmurent agent off <name> --project <project>`.

You invoke these by addressing an agent by name in plain English (for
example, *"Bookworm, find all manuscripts related to MMP11 in breast
cancer,"* or *"Adversary, review the findings of the Bookworm's
literature review for overlooked or contradictory studies"*) in any
Claude Code session on a Murmurent-enabled machine, and CC routes to it.
Every agent ships pre-configured with sensible defaults and is usable
immediately; you can override those defaults without editing the agent
itself, per member via `~/.claude/murmurent-preferences.yaml`
(`murmurent preference set <field> <value>`). The sections below call out
which defaults are worth
knowing about for each agent. Every agent's final reply leads with a
single ≤200-character verdict line in a fixed vocabulary (see
[`rules/headline_first.md`](https://github.com/hallettmiket/murmurent/blob/main/rules/headline_first.md)),
so the Murmurent VSCode dashboard's live activity pane always shows a
scannable verdict.

Group and core toolkits are meant to build on top of the commons: a lab adds
discipline-specific agents (a medchem specialist, an image segmenter, a
cohort curator, …) that compose against this same reference set, the
same hard rules, and the same verdict protocol. This corresponds to the
so-called "commons-plus-toolkit" pattern described in the manuscript.

**A lab's own versions** live in the `agents/` folder of the lab-management
repository. The PI puts one there with
`murmurent agent share <name> --lab`, and every member's machine uses it
unless they have their own. See
[Choosing an agent's version](agent_versions.md).

## All of them at a glance

**Scope** names the social unit whose state the agent reads and writes.
**Verdict** is the fixed set of words that agent's conclusion is drawn from,
and with which it must open its reply.

| Agent | What it does | Scope | Verdict |
|---|---|---|---|
| *Research and production* | | | |
| Blacksmith | Data handling, feature engineering, statistical modelling and evaluation; tailored per group to local tools and protocols | member | Done / Partial / Failed |
| Bookworm | Literature search and biomedical-database queries; annotates results with published knowledge | member | Found *n* sources |
| Artist | Figures, plots and presentation material for publication and communication | member | Rendered / Skipped / Failed |
| Teacher | Explains methods, papers and decisions for a technically competent, adjacent-field audience | member | Explained / Gap |
| Scribe | Writes and revises manuscript text in the PI's own scientific register, from a guide built on the PI's edits | member | Revised / Drafted / Gap |
| *Memory* | | | |
| Oracle | Personal research memory: findings, hypotheses and experimental context across a member's projects | member | Found / Not found / Unsure |
| Lab Oracle | Group memory of reviewed findings | group | Found / Not found / Unsure |
| *Review and adjudication* | | | |
| Adversary | Methodological audit: validates design, checks for data leakage, demands cross-validation; checks written-up prediction models and marker studies against TRIPOD+AI, PROBAST+AI and REMARK | member | Pass / Questions / Reject |
| Conscience | EDID and SGBA+ review of design, language, literature selection and presentation | member | OK / Flagged |
| Lawyer | Patent landscape and freedom-to-operate assessment | member | Clear / Conflict / Unknown |
| Security Guard | Scans diffs and outgoing data objects for credentials, protected health information and permission errors | member | Clear / Concerns / Blocked |
| Judge | Combines contributions to one choreography on a shared key, shows disagreement, and computes a consensus only where the contributions share a metric | project | Presented / Split / Insufficient |
| *Infrastructure and administration* | | | |
| Millwright | Provisions and health-checks member environments, repositories, storage and communication channels for one group | group | Provisioned / Skipped / Failed |
| Centre Millwright | Centre-wide reconciler: cross-group permissions, membership drift and shared-infrastructure differences | centre | Reconciled / Drift / BLOCKED |
| Registrar | Registry of groups, cores and collaborations; the centre-level administrative view | centre | Recorded / Conflict / Skipped |

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

### Checking sources before they enter a project

Every outside number and paper reaches a project through the Bookworm, so it
is the main guard against two documented problems. The first is invented
statistics: a web page with a precise number and a year in its title gets
picked up by AI research tools whether or not the number is true, and each
new citation makes it look more trustworthy. The second is wrong references
written by an AI agent, which can look exactly like real ones.

Before it reports a source, the Bookworm runs `murmurent cite check` (below),
traces each outside number to the study that measured it, and labels what it
found:

| Label | Meaning |
|---|---|
| `VERIFIED` | The reference is real and the Bookworm saw the claim in the original study |
| `MISMATCH` | The reference is a different paper, or the number is not in it |
| `RETRACTED` | Retracted, or under an expression of concern |
| `SECONDARY ONLY` | Found only in a summary or round-up page; the original study was not found |
| `UNRESOLVED` | Could not be checked, with the reason (for example a paywall) |

A paper it could not open is `UNRESOLVED`, never `MISMATCH`. Nothing
unverified goes into the Oracle as a fact.

**`murmurent cite check <file>`** works on its own too. Give it a `.bib`,
`.tex` or `.md` file and it looks up every DOI, PubMed ID (PMID) and arXiv ID.
For each it says whether the identifier exists, whether it is the paper the
bibliography entry claims, and whether it has been retracted, using Crossref
(which includes the Retraction Watch database), PubMed and DataCite. It uses
no AI, so it gives the same answer every time. For a `.tex` file it follows
the bibliography files the manuscript names and checks only the entries it
cites.

```bash
murmurent cite check main-article.tex   # exits with an error if any reference fails
```

It cannot tell whether a real paper supports the sentence that cites it. For a
`.md` file it prints each paper's real title beside the line that cites it, so
you can compare them.

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

When the work names something a project intends to act on (a compound going
to synthesis, a result heading for publication or disclosure) or moves
governed data, the Adversary refers it to the [Lawyer](#lawyer) itself and
folds the Lawyer's verdict into its own. Every audit ends with a `COUNSEL:`
line saying what the Lawyer found, or why no referral was needed.

### Checking the sources in a write-up

When it audits a manuscript, grant section, abstract, slides or report, the
Adversary checks the sources again, because an agent should not be the only
check on its own work. It runs `murmurent cite check` on the write-up, reads
each cited paper's real title against the sentence citing it, and fetches the
sources of the numbers that the main argument rests on. A reference that does
not exist, names a different paper, or has been retracted fails the audit. So
does a central number that traces only to a summary page. A source it could
not open is reported as not checked, with the reason, and never counts against
the work. It does not check sources in code or analyses with nothing written
up.

### Reporting checklists for prediction models

A paper can describe a sound method and still be returned by a journal because
it does not report what reviewers check for. For clinical prediction models
and prognostic markers those items are published as checklists, and the
Adversary checks against them whenever the work calls for it, not only when
asked.

**When it checks.** Both must hold: the work develops, validates or updates a
model that predicts an individual's diagnosis or outcome (by regression or
machine learning), or studies whether a single marker is prognostic; **and**
something presents it (a manuscript, abstract, report, poster, grant section
or slides). For a model still in progress with nothing written up, it adds one
line saying which checklist will apply. For work that predicts nothing about a
person (a normalisation step, a compound shortlist, a segmentation tool) it
says nothing about checklists at all, so groups that do not build clinical
models see no extra noise.

**Which checklist.**

| The work | Reporting | Risk of bias |
|---|---|---|
| A model predicting an individual's diagnosis or outcome | **TRIPOD+AI** (Collins et al., *BMJ* 2024; 27 items) | **PROBAST+AI** (Moons et al., *BMJ* 2025; 4 domains) |
| A single marker's prognostic value, including marker-by-marker screens | **REMARK** (McShane et al., 2005; Altman et al., 2012; 20 items) | reviewed as methods |
| A model built from markers first screened one at a time | TRIPOD+AI, and REMARK for the screen | PROBAST+AI |

CONSORT (randomised trials), STROBE (observational studies) and STARD
(diagnostic accuracy studies) are named when they apply, but not checked.

**How the result reads.** Reporting gaps get a section of their own, item by
item (`OBSERVED: TRIPOD+AI 10 missing`), with items it could not check marked
`NOT CHECKED` and the reason. Missing reporting items alone never produce
MAJOR CONCERNS: they are things to fix before submission, not a failed method.
A high PROBAST+AI risk of bias is a methods finding, labelled with its domain
(participants, predictors, outcome or analysis), and counts like any other.
Passing these checklists says the work is reported fully and is not obviously
biased; it does not say the model adds anything over the clinical factors,
which stays part of the methods review.

**Where the items come from.** The Adversary may not browse, so it checks
against a local copy of each checklist, [Reporting checklists](reporting_guidelines.md), which
the Bookworm sourced from the published papers on 14 October 2026 and keeps
current. It never recites a checklist from memory: an item number it reports is
one you can look up in that file. TRIPOD+AI and REMARK are reproduced word for
word under their CC BY licences; PROBAST+AI is paraphrased, because its licence
is non-commercial.

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

## Teacher

The Teacher turns reasoning into understanding a learner can carry somewhere
else. You reach it by typing one verb — `teacher debrief`, `teacher explain
<thing>`, or `teacher course <subject>` — and it works in three modes:

- **DEBRIEF** is the "wait, what?" reflex. You fire it at the sentence Claude
  Code *just* wrote that didn't land — jargon where plain words existed, a small
  mechanism it just built described as though it were intricate, or a decision
  handed to you that it never explained — and it re-pitches that in plain words
  and says what follows. It is not a catch-up for a session you looked away
  from. It reads the tail of the actual session transcript rather than offering
  a plausible reconstruction, under rails that keep it to its own session and
  stop it reproducing the data it read.
- **EXPLAIN** covers any method, paper, statistical idea, codebase, or decision
  on request.
- **COURSE** is checked *first*, before either of the others: it recognises a
  subject that needs weeks rather than one sitting and hands it to the
  [`murmurent-course`](https://github.com/hallettmiket/murmurent/blob/main/skills/murmurent-course/SKILL.md) skill without writing
  anything. The failure it exists to prevent is a compelling one-shot page that
  substitutes for the learning — someone reads it, feels they understand, and
  never starts. The Teacher cannot invoke a skill (it is a subagent; a skill
  loads into its caller's context), so it returns a `Gap` naming the skill and
  the main session picks it up.

**It answers in chat** — one dispatch, no file. For a debrief that is a hard
budget of **60 seconds**, because it is read mid-task by someone who wants to
keep working: a debrief that arrives after they've moved on has failed however
good it is, so it reads the tail of the transcript rather than its history and
never writes a page. When you want an artifact to annotate or return to, that is
`teacher explain <thing>` with `--page`; it costs minutes and tens of thousands
of tokens and earns them. A page is self-contained HTML reviewed in
`lavish-axi`, where a "wait, what?" annotation carries the exact text range, so
the re-pitch targets the sentence that failed rather than the whole page — the
same move DEBRIEF performs against Claude Code's output. EXPLAIN pages also
carry a self-grading quiz.

It writes for a smart colleague from an adjacent field: bullet-led and
jargon-light, succinct and literal rather than folksy, scaling detail inversely
to the reader's expertise, with at most three technical terms each defined on
first use. Its discipline is refusing to fake understanding — it emits a `Gap`
(never a soft middle) whenever it cannot honestly reduce something to plain
language, on the conviction that the honest signal "the understanding isn't there
yet" is more useful than a fluent wrong explanation. A keeper can be written to
`./outputs/teacher/` and handed to the Oracle. The Teacher is prose-anchored —
figures go to the Artist, durable records to the Oracle, and planning questions
to the separately-installed `grilling` skill, which runs in your session and can
hold the back-and-forth a subagent cannot.

**Verdict vocabulary:** `Explained / Gap — <one-line on what was/wasn't understood>`

> **You:** Teacher, debrief — wait, what? It just said it "hoisted the seeding
> out of the per-call path into fixture scope to make the harness deterministic".
>
> **Teacher:** Explained: that means the test was picking new random numbers
> every run, so it passed or failed by luck; it now picks them once, at setup.
> "Deterministic" is the whole mechanism — same input every time, nothing more
> intricate under it.

> **You:** Teacher, explain why we can't just overwrite the append_only file.
>
> **Teacher:** Explained: a hook enforces append-only, so writing `file_2.csv`
> is the only path — here's the mechanism, and where it would differ if the file
> lived under `data/` instead.

## Scribe

The Scribe writes scientific prose: manuscript sections, grant text, figure
legends. It exists because Claude Code, after a session of code and commit
messages, tends to write science like a software engineer: justifying itself,
reaching for metaphors, adding "rather than" contrasts and dramatic one-line
sentences. A subagent starts with a clean context, so that register is not
carried in.

It has two jobs, inferred from what you give it:

- **Revise.** Give it a passage. It returns the passage rewritten, a list of
  each change with the rule it follows, and the sentences it removed, quoted so
  you can restore any of them. It never changes a fact, a number, a citation
  key, a `\label` or a `\ref`; a fact it doubts is flagged, not fixed.
- **Draft.** Give it results, figures and notes as files, and name the
  section. It writes it, leaving `[CITE: ...]`, `[N=?]` or `[CHECK: ...]`
  wherever a citation, a number or an interpretation is missing, rather than
  inventing one.

Its rules come from a PI's own writing, not from general advice. The writing
guide ([`scientific_writing.md`](scientific_writing.md)) was built from several
hundred rewrites and deletions a PI made by hand to text Claude Code had
written for two manuscripts, plus a profile of the finished papers. Most of
those edits change voice rather than facts, and the main move is cutting. Its
examples are invented. A lab can add real pairs from its own PI's edits in
`docs/scientific_writing_examples.md`, kept private while the papers are
unpublished, and the Scribe reads them too. If the guide is not on the
machine, the Scribe returns `Gap` rather than fall back on generic advice.

Two blind tests on 18 passages the PI later rewrote showed where it can be
trusted. Word-level fixes (intensifiers, metaphors, dashes, emphasis, sentence
length) matched his edits well. Deciding which whole sentences a paper does not
need takes knowledge of the whole manuscript, so the Scribe deletes only clear
cases (roadmaps, restatements, comments on the writing) and lists the rest
under **Consider cutting** for the author to decide.

**It returns text and never edits the manuscript itself.** The main session
applies it, because manuscripts synced with Overleaf have their own rules
(pull first, never rewrap a paragraph, commit promptly). It does not browse:
citations come from the project's `.bib` files or through the Bookworm, and it
hands reporting questions to the Adversary and wording about people to the
Conscience. It replies once, so for "try this paragraph three ways" use the
main session with the same guide.

A member can fork it (`murmurent agent fork scribe`) to build a version in their
own voice from their own edits.

**Verdict vocabulary:** `Revised / Drafted / Gap — <one-line on what was written or what is missing>`

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

## Millwright

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

> **You:** Millwright, provision @didi for brca_imaging_genomics on
> lab-server.
>
> **Millwright:** "Wired. @didi is ready to connect on lab-server for
> brca_imaging_genomics."

## Centre Millwright

The centre-wide analogue of the Millwright. Every lab runs its own copy of
the Millwright, but there is exactly one Centre Millwright for the whole
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
writing to shared infra. It is the reference agent that operates at
centre scope rather than individual/group/lab scope.

**Verdict vocabulary:** `Provisioned / Skipped / Failed — <one-line on what>`
(shares the Millwright's vocabulary; also emits `Reconciled — N deltas
applied.` after a reconcile pass)

> **You:** Centre Millwright, reconcile example_core × brca-imaging.
>
> **Centre Millwright:** "Reconciled example_core × brca-imaging: 2 ACL
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
tokens, and key material; for protected-sensitivity projects, scans for
PHI-shaped patterns (OHIP/MRN/SIN-like strings, DOB-near-name
proximity); and treats `~/.murmurent/keys/**` as never-commit
territory. Under Murmurent's default data layout (see
[`memory.md`](memory.md)), `immutable/` holds a project's original inputs and
is read-only: nothing may modify or delete files there. The Security
Guard helps enforce that rule at the data-folder level by refusing any
PR that would modify `immutable/`, complementing the `raw_guard` hook that
blocks the same kind of change at the tool layer (before a write even
reaches disk). Always invoked on PRs that touch shared code or data, and
jointly maintains identity-key hygiene alongside the Millwright.

**Verdict vocabulary:** `Clear / Concerns / Blocked — <one-line why>`

> **You:** Security Guard, check this PR before I merge.
>
> **Security Guard:** Blocked: hardcoded API key at `src/foo.py:12`;
> load from env instead.

---

## Judge

Combines and presents the contributions contributed to a compositional
choreography (see [Choreographies](choreography.md) and
[Contributions](contributions.md)). Given a run package, it joins the contributions' outputs on
the choreography's candidate-identity key, applies the criteria the
question-poser supplied, and presents the candidates with full provenance. It
surfaces disagreement between contributions rather than hiding it, and computes a
single consensus only when the contribution outputs share a metric; otherwise it
presents the alternatives side by side. It never silently discards a contribution's
output, hands the combined presentation to the [Artist](#artist) for
expression, and its combination is reviewed by the [Adversary](#adversary).
Its ranking and decision strategy evolves in its own definition over time and
can be forked like any reference agent.

**Verdict vocabulary:** `Presented / Split / Insufficient — <one-line on the combined result>`

> **You:** Judge, combine the contributions for the sulfopin choreography.
>
> **Judge:** Split: the docking and ML contributions agree on the top two
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
