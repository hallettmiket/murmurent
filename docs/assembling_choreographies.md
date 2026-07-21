# Assembling a choreography 🚧

!!! warning "Work in progress"
    This page documents Phase 1 (the phrase output contract), Phase 2a
    (the phrase spec and the choreography object), and Phase 2b (the
    phrase-output table format, `prepare-run`, the `judge` commons agent,
    and `freeze-run`) exactly as shipped in `src/murmurent/core/` and
    `src/murmurent/commands/`. Compositional choreography remains under
    active development, and two steps in the workflow below stay manual
    by design rather than by omission: producing the phrase-output table
    (step 3) and invoking the judge (step 8) both happen outside any
    murmurent CLI, as described in those steps.

This page is a technical how-to and glossary for assembling a
**compositional choreography**: a posed question that several
contributors answer with independently authored phrases, joined and
compared by a judge. For the conceptual overview, read
[Choreographies](choreography.md) and [Phrases](phrases.md) first; this
page assumes that context and goes one level deeper, into the exact
artefacts, fields, and commands.

## Glossary

Each term below is anchored to the concrete artefact or field that
defines it, avoiding loose description. Where a term names a Python
class or a CLI subcommand, that mapping is given explicitly.

### output contract

Implemented by `murmurent.core.phrase_contract.PhraseContract`
(`src/murmurent/core/phrase_contract.py`). The typed declaration of what a
phrase produces, authored once per phrase, independent of how the phrase
computes its answer. A contract is a schema-validated markdown entry
(`kind: phrase_contract` in its frontmatter) with these required fields:

| Field | Meaning |
|---|---|
| `phrase` | Name/slug of the phrase this contract belongs to. |
| `author` | Offering member's handle, of the form `@name`. |
| `question` | The posed question / choreography this phrase answers. |
| `candidate_key` | The candidate-identity key (see below) this phrase's output is keyed on. |
| `metric` | What the phrase reports, e.g. `binding_affinity`. |
| `units` | Units of that metric, e.g. `nM`, `kcal/mol`, `dimensionless`. |
| `direction` | `higher_better` or `lower_better`: whether a larger value of the metric is the better outcome. |
| `uncertainty` | How uncertainty is expressed, e.g. `stderr`, `ci95`, or `none`. |

Optional fields: `tags` (list) and a free-text `notes` body. A contract
declares the *shape and meaning* of an output; the actual result table
conforming to that shape is the **phrase output**, defined below.

`PhraseContract.validate()` checks the mechanical properties only
(required fields present, `author` starts with `@`, `direction` is one
of the two allowed values, `candidate_key` is in the controlled
vocabulary or an `other:` escape). It does not, and cannot, judge
whether the metric is scientifically meaningful.

### candidate-identity key

The field `candidate_key` on both a `PhraseContract` and a
`Choreography`. It names the identity space that lets two different
phrases refer to *the same candidate* despite reporting different
metrics. The controlled vocabulary
(`phrase_contract.CANDIDATE_KEY_VOCAB`) is:

```
inchikey | smiles | gene_symbol | uniprot
```

with an escape hatch `other:<free-text>` for identity spaces outside
that set (checked by `candidate_key_ok()`). A wet-lab binding assay, a
docking simulation, and a generative-model score can all report on the
same `inchikey` even though their `metric` and `units` differ entirely;
that shared key is what makes their outputs combinable.

### joinability

The property, checked mechanically by
`Choreography.validate()` → `_validate_joinability()`, that every phrase
attached to a choreography resolves to a spec whose output contract's
`candidate_key` **equals** the choreography's own `candidate_key`. A
phrase whose contract key differs is reported as a validation problem
(`... does not join the choreography's ... phrases are not
combinable`) and a phrase whose spec or contract cannot be resolved on
disk is reported separately. Joinability is a necessary condition for
phrases to be combinable; it is insufficient on its own, since the
judge (below) still has to decide what to do when the joined outputs
disagree.

### phrase spec

Implemented by `murmurent.core.phrase_spec.PhraseSpec`
(`src/murmurent/core/phrase_spec.py`). The authored phrase itself: a
schema-validated markdown entry (`kind: phrase_spec`) with required
fields `phrase`, `author`, `question`, and `contract` (a reference, given
as a relative path or bare slug, to the phrase's output contract), plus an
ordered `steps` list and an optional `transitions` list. `PhraseSpec.validate()`
resolves the referenced contract and validates it too, so an authored
phrase and the declared shape of what it produces cannot silently
drift apart.

A spec also carries an optional `output` field: a path, relative to the
spec file, to the produced phrase-output table (see below).
`PhraseSpec.validate()` validates that table against the referenced
contract only when `output` is set; a spec authored before the table
exists is still a valid spec.

### step

A `phrase_spec.Step`: one analysis in a phrase's graph, transforming an
input into an output. Fields: `name`, `kind` (`agent` or `script`, per
`phrase_spec.STEP_KIND_VOCAB`), `run` (the agent name or the command to
execute), and an optional `description`. A phrase spec must declare at
least one step (`steps must be a non-empty, ordered list`); each step
must have a non-empty `name` and `run`, and a `kind` in the controlled
vocabulary.

### transition

A `phrase_spec.Transition`: a decision applied to a step's output.
Fields: `name`, `kind` (`rank`, `filter`, or `select`, per
`phrase_spec.TRANSITION_KIND_VOCAB`), and a free `params` dict (e.g.
`{"top": 100}`). Transitions are optional at the spec level, but any
transition present must have a valid `name` and `kind`.

### phrase output

The contract-conforming result table a phrase actually produces once its
steps and transitions run, validated by
`core.phrase_output.validate_output(contract, path)`. One row per
candidate, with a column named after the contract's `candidate_key` and
a column named after its `metric`; an uncertainty column (named
`uncertainty`, or after the estimate kind, e.g. `stderr`) is required
only when the contract's `uncertainty` is not `none`. CSV is the
baseline format; `.tsv`/`.tab` (tab-delimited) and `.parquet`/`.pq` are
recognised by extension. There is no CLI to produce this table: the
contributor writes it with their own pipeline and points the phrase
spec's `output` field at it (see **phrase spec**, above). Once written
under Tier-3 `append_only/<project>/...` (see [How Murmurent
remembers](memory.md)), the table is itself append-only and immutable
inputs stay untouched. The phrase output is what the judge reads and
aligns across phrases; the phrase *contract* is the promise the output
keeps.

### choreography

Implemented by `murmurent.core.choreography.Choreography`
(`src/murmurent/core/choreography.py`). The posed question itself: a
schema-validated markdown entry (`kind: choreography`) with required
fields:

| Field | Meaning |
|---|---|
| `question` | Question slug/id. |
| `poser` | Posing member's handle, `@name`. |
| `title` | The human question, in prose. |
| `candidate_key` | Identity space for the whole choreography (same vocabulary as a contract's `candidate_key`). |
| `criteria` | The poser's judging/presentation criteria: free text, or loaded from a file. |

Plus `phrases`, a list of references (path or slug) to attached phrase
specs, populated by `attach_phrase()` / `choreography offer`.
`Choreography.validate()` checks the required fields, that `poser`
starts with `@`, that `candidate_key` is in vocabulary, and joinability
across every attached phrase.

### run package / prepare-run

`murmurent choreography prepare-run <choreography-path> [--out <dir>]`
assembles a run package: a directory holding a `run.yaml` manifest
(the choreography's `question`, `title`, `poser`, `candidate_key`, and
`criteria`; a `judge: {agent: judge, version_sha256: <sha256 of
agents/judge.md>}` block; and, per attached phrase, the contract fields
plus a copied `contract.md` and a copied `output.<ext>`, each recorded
with its own sha256), a `choreography.md` copy, and a `phrases/<slug>/`
copy per phrase. The command refuses to run if the choreography fails
`validate()` (the joinability check) or if any attached phrase lacks a
conforming output table. By default the package is written to Tier-3
`append_only/` when the project's data tree exists, falling back to
`--out` or a temporary default otherwise. The run package is what the
judge agent reads; gathering these into one bundle up front means the
judge's session starts from a fixed, inspectable set of inputs rather
than re-resolving references live.

### judge

A markdown-defined commons agent, shipped as `agents/judge.md`
(alongside `bookworm`, `blacksmith`, `adversary`, etc.; see [The
reference agents](agents.md)), with a verdict vocabulary of `Presented /
Split / Insufficient`, following the headline-first convention every
reference agent uses. There is no CLI to run the judge: it is invoked
in a Claude Code session against a prepared run package. Once invoked,
it:

- aligns every phrase's output on the choreography's `candidate_key`;
- applies the poser's `criteria` to rank and present results;
- surfaces disagreement explicitly rather than silently averaging it
  away, flagging a candidate that only one phrase favours rather than
  dropping it;
- computes a single consensus figure only when the joined outputs share
  a `metric`; otherwise it reports the alternatives side by side with
  their provenance;
- hands its output to the [Artist](agents.md#artist) for expression (a
  ranked table, a figure, an HTML report);
- is itself reviewed by the [Adversary](agents.md#adversary), which
  checks the combination step for laundered or incommensurable
  evidence (e.g. quietly treating a docking score and a measured K_D as
  the same number).

Like other reference agents, the judge's ranking and presentation
strategy is expected to be forked and adapted per lab as the group
learns which presentations work (see [Customizing an
agent](group_level.md#customizing-an-agent-and-keeping-your-changes)).

### freeze-run / run record

`murmurent choreography freeze-run <choreography-path> --result <path>
[--run <run-package>] [--out <dir>]` writes an append-only run record
(`record.yaml`): a copy of the run package (frozen inputs, judge
version, criteria) plus the judge's `--result`. Only new files are
written, never overwrites. This is what makes a choreography's headline
result reconstructible later, following the same discipline as Tier-3
`immutable/`/`append_only/` storage described in [How Murmurent
remembers](memory.md), applied to a choreography run rather than a data
file.

## Step-by-step assembly workflow

The example below follows the sulfopin/Pin1-inhibitor case from
[Choreographies](choreography.md) and [Phrases](phrases.md): a lab
poses the question of optimizing a Pin1 inhibitor, and three
contributors, `@member_a` (wet-lab binding assay), `@member_b`
(structure-based docking), and `@member_c` (generative model), each
offer a phrase. All commands are shown as run from a shell with the
murmurent CLI on `PATH`; every `new` subcommand writes to the personal
vault's `phrases/`/`choreographies/` folder by default (or the lab-mgmt
repo's `choreographies/` for `choreography new` specifically), falls
back to `--out`, and falls back to stdout if neither resolves.

### 1. Author each phrase's output contract

Each contributor authors a contract before writing any code, so the
shape of what they will report is fixed and reviewable up front.

```bash
murmurent phrase contract new \
  --phrase pin1_binding_assay \
  --author @member_a \
  --question optimize_sulfopin_pin1 \
  --candidate-key inchikey \
  --metric binding_affinity \
  --units nM \
  --direction lower_better \
  --uncertainty stderr

murmurent phrase contract new \
  --phrase pin1_docking_filter \
  --author @member_b \
  --question optimize_sulfopin_pin1 \
  --candidate-key inchikey \
  --metric docking_score \
  --units kcal/mol \
  --direction lower_better \
  --uncertainty none

murmurent phrase contract new \
  --phrase pin1_generate_score \
  --author @member_c \
  --question optimize_sulfopin_pin1 \
  --candidate-key inchikey \
  --metric model_score \
  --units dimensionless \
  --direction higher_better \
  --uncertainty ci95
```

All three declare `--candidate-key inchikey`: that is the joinability
requirement, decided before anyone writes a step. `murmurent phrase
contract new` refuses to write an invalid contract; problems are printed
and the command exits non-zero. Validate an existing contract file with:

```bash
murmurent phrase contract validate <path>
```

### 2. Author each phrase spec

Each contributor then authors the phrase itself: the steps and
transitions that produce output conforming to the contract just
written. `--step` is repeatable, one `name:kind:run` per step
(`kind` is `agent` or `script`); `--transition` is repeatable,
`name:kind` (`kind` is `rank`, `filter`, or `select`).

```bash
murmurent phrase spec new \
  --phrase pin1_binding_assay \
  --author @member_a \
  --question optimize_sulfopin_pin1 \
  --contract pin1_binding_assay \
  --step "assay:script:run_binding_assay.sh" \
  --transition "rank_by_affinity:rank"

murmurent phrase spec new \
  --phrase pin1_docking_filter \
  --author @member_b \
  --question optimize_sulfopin_pin1 \
  --contract pin1_docking_filter \
  --step "dock:script:run_docking.py --target pin1" \
  --transition "filter_by_energy:filter"

murmurent phrase spec new \
  --phrase pin1_generate_score \
  --author @member_c \
  --question optimize_sulfopin_pin1 \
  --contract pin1_generate_score \
  --step "generate:agent:blacksmith" \
  --step "score:script:score_candidates.py" \
  --transition "shortlist:select"
```

The `--contract` value is a bare slug here (`pin1_binding_assay`),
which resolves to `<slug>_contract.md` in the same directory the spec
is being written to; `murmurent phrase spec new` roots that resolution
at the intended output directory before validating, so the stored
reference still resolves once the file is written. `murmurent phrase
spec new` validates both the spec's own fields (non-empty steps, valid
`kind` values) **and** the referenced contract, refusing to write if
either fails. Validate an existing spec (contract included) with:

```bash
murmurent phrase spec validate <path>
```

### 3. Produce each phrase output table

**Manual step: no CLI wrapper.** Each contributor runs their phrase's
steps and transitions (however `run` invokes them: a script, an agent
session) and writes the resulting table under
`append_only/<project>/<phrase>/`, one row per candidate, with a column
named after the choreography's `candidate_key`, a column named after
the contract's `metric`, and an uncertainty column when the contract's
`uncertainty` is not `none`. CSV is the baseline format; `.tsv`/`.tab`
and `.parquet`/`.pq` are also recognised, by extension. Producing this
table is the contributor's own pipeline; murmurent's part is only to
validate it against the contract (`phrase_output.validate_output`) once
written. The contributor then sets the phrase spec's `output` field to
a path pointing at the table, relative to the spec file, so
`prepare-run` (step 7) can find it.

### 4. Pose the choreography

The poser states the question, the shared candidate-identity space, and
the criteria the judge should apply. `--criteria` accepts either a
literal string or `@<file>` to load criteria text from a file.

```bash
murmurent choreography new \
  --question optimize_sulfopin_pin1 \
  --poser @the_pi \
  --title "Optimize sulfopin (a Pin1 inhibitor) for improved binding affinity" \
  --candidate-key inchikey \
  --criteria @sulfopin_judging_criteria.md
```

A freshly posed choreography has no phrases attached, so `validate()`
at this point only checks the poser-supplied fields; the joinability
check is a no-op until phrases are offered.

### 5. Offer phrases

Each contributor attaches their phrase spec to the posed choreography.
`offer` is idempotent: attaching the same reference twice is a no-op,
not an error.

```bash
murmurent choreography offer optimize_sulfopin_pin1.md --phrase pin1_binding_assay
murmurent choreography offer optimize_sulfopin_pin1.md --phrase pin1_docking_filter
murmurent choreography offer optimize_sulfopin_pin1.md --phrase pin1_generate_score
```

### 6. Validate the choreography (the joinability check)

```bash
murmurent choreography validate optimize_sulfopin_pin1.md
```

This resolves every attached phrase's spec, resolves each spec's
contract, and checks `contract.candidate_key == choreography.candidate_key`
for all three. On success:

```
OK — optimize_sulfopin_pin1.md is a valid choreography (3 phrase(s), all joinable on 'inchikey').
```

A phrase whose contract used, say, `--candidate-key smiles` instead of
`inchikey` would fail here with a problem of the form:

```
phrase '...': contract candidate_key 'smiles' does not join the
choreography's 'inchikey' -- phrases are not combinable
```

before any judge ever runs. `murmurent choreography show <path>` is the
read-only companion command: it prints the question, poser, candidate
key, criteria, and each attached phrase's metric/units/direction with a
`joins`/`DIFFERS` flag per phrase, useful for a quick human check
before running `validate`.

### 7. Prepare the run

```bash
murmurent choreography prepare-run optimize_sulfopin_pin1.md
```

Assembles the run package: a `run.yaml` manifest (question, title,
poser, candidate key, criteria, and the judge's agent name and
`agents/judge.md` sha256), each attached phrase's contract and output
table (from step 3, found via each spec's `output` field), and copies
of the choreography and phrase specs. The command refuses to proceed if
the choreography fails `validate` (the joinability check from step 6)
or if any attached phrase lacks a conforming output table. By default
the package is written to Tier-3 `append_only/` when the project's data
tree exists; pass `--out <dir>` to choose a destination explicitly.

### 8. Invoke the judge

**Manual step: no CLI to run the judge.** Open a Claude Code session and
invoke the `judge` commons agent against the prepared run package. The
judge aligns the three phrase outputs on `inchikey`, applies the
criteria from `sulfopin_judging_criteria.md`, and produces a ranked
result, flagging a candidate the docking phrase ranks highly but the
binding assay does not cover rather than silently omitting it, and
leads its reply with a `Presented / Split / Insufficient` verdict. The
judge's combination step is expected to go to the
[Adversary](agents.md#adversary) for review before the result is
treated as final.

### 9. Freeze the run

```bash
murmurent choreography freeze-run optimize_sulfopin_pin1.md --result <path-to-judge-output>
```

Writes the append-only run record (`record.yaml`): a copy of the run
package (frozen inputs, judge-definition sha256, criteria) plus the
judge's result, so the choreography's headline conclusion can be
reconstructed later even as phrases are added or re-run. Pass `--run
<run-package>` to freeze a specific previously-prepared package, or
`--out <dir>` to choose the run record's destination.

## See also

- [Choreographies](choreography.md): the conceptual model, coordination
  vs. compositional mode, the finalisation choreography.
- [Phrases](phrases.md): what a phrase is, method vs. service phrases,
  the sulfopin worked example this page follows.
- [How Murmurent remembers](memory.md): the three-tier memory model;
  Tier-3 `immutable/`/`append_only/` storage referenced by phrase
  outputs and run records.
- [The reference agents](agents.md): the Adversary and Artist roles the
  judge hands off to.
