# Phrases (work in progress)

!!! warning "Work in progress"
    Phrases are a design under active development. This page describes the
    intended model; the tooling is not yet implemented.

A **phrase** is a unit of contribution that an individual or a group offers
to everyone else. It is the building block of a **compositional
choreography** (see [Choreographies](choreography.md)): a lab or centre
poses a question, and each contributor offers a phrase that tackles it from
their own angle.

A phrase is deliberately general. Contributors' approaches span the whole
spectrum from classic low-throughput human biology to a fully AI-driven
algorithm, and no single phrase need answer the whole question; each may add
insight.

## Steps and transitions

A phrase is built from two kinds of component, which are themselves
offerable and reusable across groups:

- A **step** applies an analysis to data, transforming an input `X'` into a
  new output `X''` (a docking calculation, a binding assay, a generative
  model run).
- A **transition** inspects a step's output and makes a decision: rank,
  filter, or select (given a set of generated analogues, keep the plausible
  binders and rank the top 100).

Steps and transitions chain into a small graph. A phrase eventually produces
an output that is **expressed** for people to read (a figure, a spreadsheet,
an HTML report), by the [Artist](agents.md#artist).

## What a phrase declares: the output contract

For phrases to be combined, each phrase declares a typed **output contract**
describing the shape and meaning of what it produces:

- a **candidate-identity key**: the shared identifier that lets two phrases
  refer to the same thing (for a small-molecule problem, an InChIKey or
  SMILES);
- the **metric** it reports, its **units**, and its **direction** (is higher
  better?);
- an **uncertainty** estimate.

The contract is recorded as [Tier-2 memory](memory.md), a schema-validated
entry carrying frontmatter the same way Oracle entries do, so it is durable
and human-readable. The phrase's output is served at runtime through an MCP
server, and any bulk data it references lives in Tier-3 `append_only/`
storage. The candidate-identity key is the join column that makes "where do
these phrases agree or disagree?" a well-defined question.

## Offering a phrase: methods and services

A phrase is **offered** to everyone. There are two cases, with different
governance:

- A **method phrase** is a shared recipe that anyone can run on their own
  data. Offering it requires nothing beyond publishing it to the phrase
  catalog.
- A **service phrase** requires the offering party to act on their own
  resource (run their instrument, use their private data). Using a service
  phrase across a group boundary keeps a governance gate: the offering
  group's PI approves the request, and a data-access grant scopes what the
  requester may see. This is the cross-group governance that the earlier
  "SEA" concept carried; SEA is retired, and the gate is re-homed onto
  service-phrase use.

## Example

A lab decides that optimizing a Pin1 inhibitor (say, sulfopin) matters.
Three members offer phrases from different points on the spectrum:

- a **wet-lab biochemist** offers a phrase whose step is a binding assay and
  whose transition ranks measured affinities;
- a **computational chemist** offers a phrase that docks candidate analogues
  and filters by predicted binding energy;
- an **ML researcher** offers a phrase whose step generates analogues with a
  model and whose transition scores and shortlists them.

Each phrase declares the same candidate-identity key (the molecule), so their
outputs can be aligned even though their metrics differ (a measured K_D in
nM, a docking score in kcal/mol, a model score). How these phrases combine
into one answer is the job of the choreography's judge; see
[Choreographies](choreography.md).

## In the dashboard

A member authors phrases privately in their vault
(`<vault>/phrases/`, via `murmurent phrase spec new`). The dashboard's **My
phrases** panel lists them, each showing the question it answers, its output
contract as a compact signature (`candidate_key → metric (units) direction`),
and its step/transition counts.

To make a phrase known to the group as an offered method or service, the member
**states** it: the panel's *state to group* action publishes the phrase — its
spec and its contract — into the group's governance repo under `phrases/` (a
sibling of `choreographies/`). Two things then work that could not before:
other members see the offered phrase, and a choreography (which lives in the
same repo) can resolve it to check joinability. Authoring stays private; stating
is the deliberate step that shares. A choreography assembles stated phrases —
see [Choreographies](choreography.md).
