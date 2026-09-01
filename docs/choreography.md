# Choreographies (work in progress)

!!! warning "Work in progress"
    Choreographies are an area of active development. This page describes the
    intended model; several parts are not yet implemented.

A **choreography** is a documented multi-actor pattern: a recipe for how
several people, and the agents they run, work together, in what order,
producing what artefacts. A choreography runs in one of two modes.

## Two modes

- **Coordination mode**: an administrative pattern that sequences people,
  agents, and approvals. Examples: bringing a project into being, onboarding
  a new member, and the finalisation (deliberation) ritual that decides what
  a completed result means. These are largely prose-plus-command recipes,
  run with a human in the loop.
- **Compositional mode**: a scientific pattern in which a lab or centre poses
  a question, contributors offer [contributions](contributions.md) that tackle it from
  different angles, and a **judge** combines and presents their outputs. This
  mode is the focus below.

## Compositional choreographies

A compositional choreography answers a posed question by composing
independently authored contributions. Because the contributors' approaches
are heterogeneous and their routes differ, it is a composition, not a linear
pipeline.

**1. Pose the question.** A member (the *poser*) states the question, for
example: optimize compound X (a Pin1 inhibitor such as sulfopin) for purpose
Y. The poser also states the **candidate-identity space** (here, chemical
structures) and the **criteria** the judge should use to rank and present
results.

**2. Contributors offer contributions.** Members and groups each offer a
[contribution](contributions.md), a small graph of steps and transitions, from anywhere
on the spectrum between low-throughput human biology and fully AI-driven
optimization. Each contribution declares a typed output contract (candidate key,
metric, units, direction, uncertainty), so the contributions can later be aligned.

**3. The judge combines them.** The **judge** is a markdown-defined agent.
Its ranking and decision strategy is supplied by the poser and evolves in
its definition over time, as the lab learns which presentations are
effective; it is not a learned black box, and it can be forked and adapted
per lab like any reference agent (see
[Customizing an agent](group_level.md#customizing-an-agent-and-keeping-your-changes)).
The judge:

- aligns contribution outputs on the shared candidate-identity key;
- presents them with full provenance and **surfaces where they disagree**;
- computes a single consensus only when the outputs share a metric, and
  otherwise reports the alternatives side by side with their evidence;
- is reviewed by the [Adversary](agents.md#adversary), which checks the
  combination for laundered or incommensurable evidence.

**4. Express and gate.** The [Artist](agents.md#artist) expresses the result
(a ranked table, a figure, an HTML report). "Done" is a **human gate**: the
poser or PI decides when the choreography has converged and what to conclude.
Non-linearity is allowed; unbounded iteration is not.

### Reproducibility

Every run freezes, as append-only artefacts, the judge's definition version,
the poser's criteria, and each contribution's declared output, so the same
choreography can be re-run and its headline result reconstructed. This
follows the same immutable / append-only discipline as the rest of
Murmurent's data governance.

### Worked example: optimizing a Pin1 inhibitor

A lab poses: optimize sulfopin, a Pin1 inhibitor. Three members offer contributions
(a wet-lab binding assay; a structure-based docking-and-filter; an ML
generate-and-score), each declaring the molecule as its candidate-identity
key. The judge, using the poser's criteria, aligns the three candidate
rankings, shows where the measured affinities and the computed scores agree
and disagree, flags candidates that only one contribution favours, and presents a
combined shortlist with the provenance of every number. The PI reviews and
decides which candidates to pursue. The contributing units are described in
[Contributions](contributions.md).

## Coordination choreographies

Coordination-mode choreographies sequence administrative work. The principal
ones are project birth, member onboarding, and the finalisation ritual.

### The finalisation choreography

After a piece of work (an experiment, or a whole project) is complete, the
group takes the result through a **deliberation** that produces a permanent
record of what it means, rather than moving on without interpreting it. The
deliberation runs at experiment and project scope with the same shape, and
always produces a **deliberation document** with a fixed structure:

- agent contributions (each relevant agent's read on the result),
- member reflections,
- group-Oracle context (what the lab already knows that bears on it),
- an attempted consensus statement,
- caveats and dissent (recorded, not smoothed over), and
- an approval log.

The dashboard makes an outstanding finalisation visible, so "what does this
mean?" becomes a default step rather than an optional one. Curated
conclusions are then promoted to the group Oracle (see
[The Oracle](oracle-workflow.md)).

## In the dashboard

The **Choreographies** panel is where a group assembles compositional
choreographies. Each choreography advertises its target — the question, the
title, the `candidate_key` it joins on, and the criteria the judge applies.
*Pose* opens a form to advertise a new one.

For each choreography the panel shows its **contributed** contributions (with a tick
or cross for whether each joins on the shared candidate key) and, below them, a
**joinable** pool: the group's stated contributions (see [Contributions](contributions.md)) whose
contract shares that candidate key but which are not attached yet. *Attach*
adds one; a contribution that does not join is refused, because a mismatched key
means the outputs cannot be combined. When every contributed contribution joins, the
choreography is ready to compose — the judge aligns the outputs on the shared
key and presents the result (see the `judge` agent in
[the reference agents](agents.md)).
