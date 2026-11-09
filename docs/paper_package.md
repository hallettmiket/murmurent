# Paper packages and the thesis built from them

A **paper package** is a manuscript repository that a reader can question. It
holds the manuscript, the code and data behind each of its central claims, and
a manifest, `paper.yaml`, that maps one to the other. Opened in Claude Code, it
answers "where does the paper show this", "what is behind figure 2", "re-run
it", and "what does it not address", each answer with a location. A **thesis
package** is a thesis composed of paper packages, or of chapters that carry
their own claims, plus the candidate's introduction, bridging text, conclusion
and front matter, in `thesis.yaml`. The [`docent`](https://github.com/hallettmiket/murmurent/blob/main/agents/docent.md) is the
agent that walks a reader or an examiner through either, and walks the author
or candidate through getting it ready. Issue #284 holds the discussion that led
here.

Who wrote the prose is deliberately not part of this. A package is about how a
paper is read, not how it was written.

## Why the paper is the unit

Everything an examiner wants from a queryable thesis is a property of one
paper: claims attached to their evidence, a check that refuses a package whose
figures have no code, a guide that answers with a location, a read-only
harness, and a log of the questions asked. Build it per paper and every paper
gains reviewers and readers, not only the one thesis its examiners. The thesis
is then a composition, and the examination is where the package first gets
used in anger: an examiner is an obliged reader with time and authority, and
Western's rules already allow a supplementary file of any format beside the
PDF.

People have tried "executable papers" before (notebook-backed supplements,
Code Ocean capsules, eLife's Executable Research Articles). They let a reader
re-run the authors' figures and little else, and uptake stayed small because
the packaging cost fell on the author and the reader rarely pressed the
button. Two things are different now: a reader asks in plain language instead
of editing a notebook, and the packaging can be checked and partly done by
agents. That is the bet, and the pilot is what tests it.

## A paper package

```
<paper>/
  paper.yaml        the manifest (below)
  main.tex          the manuscript source
  exp/<n>_<slug>/   the code behind each claim, run_all.* as the entry point
  data/             small data; anything large stays under the lab data root
  queries/          the docent's log, one file per reader per day, append only
  CLAUDE.md         the reader's primer: rules, and where things are
  build/            claim_map.md, the PDF; not committed
  .murmurent.yaml   the readiness marker
```

`murmurent paper init <dir> --title "..." --author "..."` writes all of it and
never overwrites a file that exists.

### `paper.yaml`

```yaml
paper: 1
title: Serum enlarges colonies of a synthetic isolate compendium
authors:
  - name: A. Candidate
  - name: M. Supervisor
status: in-prep          # in-prep | submitted | published
doi: ''
sensitivity: standard    # standard | restricted | protected
source: main.tex
claims:
  - id: c1
    text: Colonies grown in serum are larger than controls, and the difference holds under permutation.
    where: Results, first paragraph
    figure: fig:signal                   # a \label in the source
    code: exp/1_signal/run_all.py        # the script or folder that produces the evidence
    data: [data/signal.csv]              # in the package, or under the data root
```

A claim is one sentence the paper rests on. `code` is what makes the evidence;
`data` is what it reads, either a file in the package or a path under the lab
data root (`immutable/...`, `append_only/...`), which is reached on the machine
that holds it and never copied in. Write the current folder names; a server
whose data root still says `raw/` and `refined/` is read under those names.
A claim with no `code` is allowed and shows
in the claim map as not re-runnable.

### `murmurent paper check`

Reads the manifest and refuses what the docent could not stand behind:

| It refuses (error) | It warns |
|---|---|
| a missing source, code path or in-package data file | no claims at all (readable, not re-runnable) |
| a `figure:` label the source does not define | a claim with no `code:` |
| a duplicate claim id, a claim with no `text:` | a data-root path when no data root is set here, or the file is missing there |
| `sensitivity: protected` with any data bundled in the package | `published` with no DOI; no `CLAUDE.md`, `queries/` or marker |

Exit status 1 on any error, or on any warning with `--strict`, so an agent can
stop on it.

### `murmurent paper build [--pdf]`

Writes `build/claim_map.md`, the table the docent reads first: every claim,
where it is made, which figure shows it, which script makes it, from which
data. With `--pdf`, runs `latexmk` on the source when it is installed, and says
so when it is not.

## A thesis package

```
<thesis>/
  thesis.yaml
  front/           abstract, lay summary, GenAI statement, co-authorship, acknowledgements
  chapters/        introduction, bridges, monograph chapters, conclusion (LaTeX)
  permissions/     publishers' copyright releases, one per published article
  figures/         figures redrawn for the talk
  exp/             code behind the claims of monograph chapters
  queries/         the examiners' log
  CLAUDE.md        the examiner's primer
  build/           main.tex, main.pdf, claim_map.md, talk.tex, talk_plan.md, paperwork.md
```

`murmurent thesis init <dir> --title "..." --candidate "..."` writes it.

### `thesis.yaml`

```yaml
thesis: 1
title: Colony phenotypes of a synthetic isolate compendium
candidate: {name: A. Candidate}
supervisor: M. Supervisor
degree: Doctor of Philosophy
program: Biochemistry
university: Western University
format: integrated-article
sensitivity: standard            # the highest tier of any chapter
defence: {date: '2027-04-16', format: hybrid}
examiners:
  - {role: external, name: E. Xaminer, affiliation: Another University}
  - {role: university, name: U. Examiner, affiliation: "Western, another department"}
  - {role: program, name: P. One, affiliation: "Western, Biochemistry"}
  - {role: program, name: P. Two, affiliation: "Western, Biochemistry"}
front:
  abstract: front/abstract.tex
  lay_summary: front/lay_summary.tex
  genai_statement: front/genai_statement.tex
  coauthorship: front/coauthorship.tex
chapters:
  - {kind: introduction, title: Introduction, source: chapters/01_introduction.tex}
  - kind: paper                   # an article: a paper package, usually its own repository
    package: ../paper_example
    bridge: chapters/02_bridge.tex
    permission: permissions/paper_example.pdf    # required once the paper is published
  - kind: chapter                 # a monograph chapter with its own claims
    title: Colony size and country of origin
    source: chapters/03_metadata.tex
    claims:
      - {id: c3.1, text: ..., figure: fig:country, code: exp/3_metadata/run_all.py, data: [...]}
  - {kind: conclusion, title: Conclusion, source: chapters/99_conclusion.tex}
appendices: []
bibliography: ''
```

Four kinds of chapter: exactly one `introduction` and one `conclusion`, and
between them any number of `paper` chapters (a paper package, reached by path)
and `chapter` chapters (a monograph chapter whose claims are listed inline and
checked the same way). A thesis of only `chapter` chapters is a monograph; a
thesis of `paper` chapters is Western's integrated-article format; a mix is
allowed.

### `murmurent thesis adopt <thesis.tex> <dir>`

Most theses already exist as one LaTeX file. `adopt` turns it into a package
without changing the original: the preamble is kept as `preamble.tex` (so the
build uses the candidate's own class and packages, and `\printbibliography`
when the preamble loads biblatex); each `\chapter*` the SGPS template names
(Abstract, Summary for Lay Audience, Co-Authorship Statement, Acknowledgements,
the GenAI statement) goes to `front/`; each numbered `\chapter` goes to
`chapters/NN_slug.tex`, the first as the introduction, the first titled
Discussion or Conclusion as the conclusion, the rest as chapters; an unnamed
`\chapter*` becomes an appendix. Every figure label in a results chapter
becomes a **draft claim** with the caption's first sentence as its text and no
code, so the check warns on each until the candidate names the script. Chapters
titled Background, Introduction or Methods get no drafts, since their figures
are usually not the candidate's claims. Figures and `.bib` files the text
refers to are copied in. The title and author are read from `\title` and
`\author` when present and can be overridden.

### `murmurent thesis check`

Runs every paper package's own check and reports its findings under the
chapter, then checks what only a thesis has:

| It refuses (error) | It warns |
|---|---|
| not exactly one introduction and one conclusion, or nothing between them | an introduction that is not first, a conclusion that is not last |
| a missing abstract, lay summary or GenAI statement (SGPS requires all three) | a paper chapter with no bridge (SGPS asks for connecting text) |
| a lay summary or abstract over 350 words | an empty front-matter file |
| a published paper with no `permission:` file | |
| a co-authored article with no co-authorship statement | |
| a `protected` paper in a thesis that is not `protected` | |
| a monograph chapter whose claims fail the paper checks | |

### `murmurent thesis build [--pdf]`

Assembles `build/main.tex` in the SGPS order: title page, abstract, lay
summary, co-authorship statement, GenAI statement, acknowledgements, contents
and lists, the chapters, the bibliography, the appendices. A paper chapter is
included as the body of its manuscript with the title block, the abstract
(SGPS presents articles without one) and the paper's own bibliography call
removed, after its bridge. The preamble is a plain `book` class; drop the SGPS
LaTeX template from the SGPS formatting page over it when the thesis goes in.
Also writes `build/claim_map.md` for every chapter. With `--pdf`, runs
`latexmk`.

The PDF stays the thesis of record. The package is the supplementary file
beside it, which Western's procedure allows in any format that examiners can
open.

### `murmurent thesis talk [--minutes 20] [--pdf]`

Drafts the defence talk as a timed skeleton, one slide per claim.
`build/talk_plan.md` is the plan: fixed slots for the title, outline,
introduction (three slides), conclusion (two) and acknowledgements, and the
rest of the minutes shared among the result chapters in proportion to their
claims. `build/talk.tex` is the Beamer file, each slide titled with its claim,
a comment naming its figure label and evidence, and a `\note` with its time
budget. When the claims outnumber the minutes, the plan says how many result
slides fall under 45 seconds and that the rest belong in backup slides. The
sentences on the slides are the [`scribe`](https://github.com/hallettmiket/murmurent/blob/main/agents/scribe.md)'s job and a
figure made for a page is the [`artist`](https://github.com/hallettmiket/murmurent/blob/main/agents/artist.md)'s; the command
gives the order and the time.

### `murmurent thesis paperwork`

Writes `build/paperwork.md`, the Western submission checklist pre-filled from
the manifest: the thesis fields; the deadlines computed from `defence.date`
(the examination request and the preliminary submission five working weeks
before a doctoral defence, examiners' reports five working days before, final
submission by the end of the term); the examination board against SGPS's
composition; the Proposed Examiner Form and the Thesis Examination Request
Form, both to the Graduate Program Coordinator; the front-matter limits; the
copyright releases; a scan for email addresses and phone numbers, which must be
removed; the 100 MB limit on each supplementary file; the Veritas steps for
the preliminary submission; and the Open Repository steps for the final one.
Each line is a box, ticked when the manifest can tell. The steps, limits and
deadline rules come from the institution pack's
`procedures/thesis_examination.yaml` when a pack is found (see
[`institution_pack.md`](institution_pack.md)): the deadlines then skip the
pack's holidays. With no pack, the seed built into murmurent is used, and
weekends alone are skipped. The requirements were read from the SGPS pages on
the date the file names; a deadline or a form that matters is confirmed with
the Graduate Program Coordinator, who is the only person who can open an
examination in Veritas. The docent asks the clerk for this part.

## The docent

The [`docent`](https://github.com/hallettmiket/murmurent/blob/main/agents/docent.md) is the one new agent. It reads the claim
map first, runs the check, and answers every question with a location or says
`Absent` when the work does not address it. It re-runs a claim's code before
reporting a number, logs each question and answer to
`queries/<handle>/<date>.md` append-only, writes nothing else outside `build/`,
and is offline, because a thesis under examination is not public. It infers
which side it is on: a question about the work is the reader's; a question
about the package, the talk or the paperwork is the author's. It does not
grade: the adversary audits, the examiner decides. The candidate should run it
on their own thesis before anyone else does.

## What is known to be hard

These are the objections raised when this was designed, kept here so each can
be ticked off as it is met.

- **Protected data.** A clinical thesis cannot ship its data to an external
  examiner. The check refuses a protected package that bundles data; the data
  is reached on the server that holds it, which means provisioning an examiner
  there, or giving them derived data. The tiers handle the mechanics; the
  data-use agreement and the ethics board decide, and neither has yet thought
  about examiners as users.
- **Confident wrong answers.** An examiner who gets a fluent wrong answer is
  worse off than one reading the PDF. Hence the location on every answer, the
  re-run before a number, and `Absent` as a full answer.
- **Who is examining whom.** A preliminary report drafted mostly by an agent is
  possible. The tool lets the examiner verify more, not judge less, the query
  log makes the difference visible, and a GenAI statement from the examiner
  would match the one SGPS now requires from the candidate.
- **The burden on the candidate.** Mapping every claim to code is work in the
  last months. A claim with no code is allowed and marked, so the package
  degrades to "readable" rather than failing.
- **The wrong harness for most of campus.** Claude Code is right for a
  computational examiner and wrong for most of SGPS. A web front end on the
  same package comes later; the pilot uses Claude Code.
- **Preservation.** The archive of record stays the PDF plus the raw data and
  code; the agent layer is a convenience that will be replaced.

## Sources for the Western requirements

Read on 2026-11-06: the SGPS [thesis](https://grad.uwo.ca/academics/thesis/index.html),
[formatting](https://grad.uwo.ca/academics/thesis/formatting.html),
[examination](https://grad.uwo.ca/academics/thesis/examination.html) and
[timelines](https://grad.uwo.ca/academics/thesis/timelines.html) pages; the
Senate [Procedure for Thesis Formats and Content](https://www.uwo.ca/univsec/pdf/academic_policies/grad_postdoc/thesis_procedures_format.pdf);
and the Veritas student instructions (Schulich's copy). They live in the
institution pack as `procedures/thesis_examination.yaml`, each source with the
date it was read; the constants at the top of
`src/murmurent/core/paper_package.py` are only the seed that
`murmurent institution init --seed-thesis` writes into a new pack.
