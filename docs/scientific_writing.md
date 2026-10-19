# Writing a scientific manuscript

This is the house style for manuscripts, grant text and other scientific
writing. The Scribe agent follows it, and so should any Claude Code session
writing a paper. It is stricter than, and different from,
[`output_styles/plain_english.md`](../output_styles/plain_english.md), which is
for documentation. A paper is formal, cited, understated and built on
convention. Where a manuscript's own `CLAUDE.md` says more, follow that too.

Every example below is invented, written to show the rule. A lab that keeps
real before-and-after pairs from its own PI's edits puts them in
`docs/scientific_writing_examples.md`, which the Scribe also reads, and which
should stay private while the papers it quotes are unpublished.

## Where these rules come from

They were taken from one PI's own hand edits to text Claude Code had drafted,
not from general advice: several hundred rewrites and deletions across two
manuscripts, read in full, plus a profile of the finished papers section by
section. A lab can build its own version the same way (see the last section).

Three findings shape everything below:

1. **Most edits change voice, not facts.** The content was usually right. The
   register was wrong.
2. **The main move is to cut.** Even when a fact is corrected, the sentence
   usually gets shorter.
3. **What gets cut is the writer explaining itself:** why a sentence is there,
   how candid it is being, what the alternative was, and what a reviewer might
   object to.

---

## The rules

### 1. Cut what explains yourself

The most common edit. State the fact and stop.

- **No justification tails.** Cut ", which is the failure it was designed to
  catch", ", so that no result can be reported without its control",
  "because ...", "which is why ...".
- **No "rather than" foils.** The reader did not ask what the alternative was.
  "Samples were processed in a single batch rather than over several weeks"
  becomes "Samples were processed in a single batch."
- **No comments on your own candour or purpose.** Cut "We state this plainly
  because", "The limitations are stated openly rather than hidden", "This is
  deliberately not ...", "the distinction matters", "which is the point".
- **No pre-empting the reviewer.** Delete caveats whose only job is to answer
  an objection nobody has raised yet, and do not repeat a point already made.
- **Cut whole sentences, not only words.** Trimming inside sentences is not
  enough. Ask of each sentence whether a reader of the paper needs it, and
  delete it when it does not. The kinds deleted most often:
  - the reasoning behind a design choice ("because the opposite order would
    let contamination pass unnoticed"), when the paper only needs the choice;
  - the motivation for an analysis step ("which motivates pooling the two
    cohorts below"), when the next paragraph simply does it;
  - analysis settings outside Methods (fold counts, bootstraps, permutation
    nulls in the Introduction);
  - a second sentence that restates or elaborates the first.

  Cutting is not changing the facts: a deleted sentence leaves every remaining
  claim as true as it was. In a data paper, though, the PI often *adds* a
  plain "That is," sentence, so a rewrite there can be as long as the
  original. Cut what serves the writer; keep and add what serves the reader.

  For an editor that is not the author (the Scribe, or any session), the line
  is drawn in two places. Delete what plainly serves the writer: roadmaps,
  restatements, comments on the writing. Propose, but leave in place, cuts of
  detail the paper may not need: deciding those takes the whole manuscript and
  the author's intent.

### 2. Say it literally

- **No metaphors, aphorisms or epigrams.** "the signal is drowned out" becomes
  "the signal falls below the detection limit"; "a moving target" becomes "a
  quantity that changes between visits"; "the pipeline is the bottleneck"
  becomes "processing takes longer than sequencing".
- **No "not X but Y", "neither X nor Y but Z", or cleft sentences** ("What X
  does is ..."). State the positive claim, with a person or the system as the
  actor.
- **No punchline fragments.** "It does not." becomes "We show that this is not
  the case." "It is." becomes "Indeed, ...".
- **No coined names for things.** "the Rapid Rescue screen" becomes "the
  second compound screen".

### 3. Turn the volume down

- **No intensifiers:** decisively, critically, crucially, serious, far more,
  genuinely, actually, precisely, inevitably, easily, notably, importantly
  (rare, and never as a paragraph opener), "to us, the strongest".
- **No italic or bold on ordinary words** for emphasis ("in \emph{both}
  cohorts"). Italics are for a term at its definition, species, gene names and
  *in situ*.
- **Hedge to match the evidence.** Weak results are named as weak ("at best
  exploratory", "suggestive at most"). Mechanistic explanations are hypotheses
  ("perhaps", "may explain", "There are several overlapping hypotheses").
  Candidates are "putative". A strong claim is earned by agreement between
  independent lines of evidence, and then said once.
- **No absolutes about settings or people.** "Hospital laboratories also face
  constraints" becomes "Hospital laboratories may also face some constraints".
  Never imply that people are replaced: "may decrease the load placed upon
  them".

### 4. Shape sentences for a reader

- **One result per sentence.** Split semicolon chains and ", which" chains into
  separate sentences.
- **Do not go choppy.** The finished papers run at a median of 23 to 27 words
  a sentence. The rhythm is a long sentence carrying the evidence, then a short
  one carrying the verdict: "No model improved on the baseline in either
  cohort."
- **Use "of" rather than stacked possessives:** "the expression profile of the
  primary tumour", not "the primary tumour's expression profile".
- **In the `.tex`, one clause per line.** Never rewrap a paragraph: Overleaf
  reads it as a change to every line.

### 5. Lead with the science and the person

- **Context first, then the claim; purpose first, then the mechanism.** "Two
  checks run on every upload" becomes "To reduce the chance that a mislabelled
  sample enters the analysis, every upload is checked twice."
- **Make a person the actor.** A PI, a student, "we", or the system named as
  doing something. "less configuration is needed" becomes "This frees the
  researcher from re-entering the same settings for each experiment".
- **Say what it buys the researcher.** When describing a feature, state the
  benefit to the person using it.
- **Frame the biology, not the pipeline.** "we systematically computed, for
  every tissue × time point × treatment cell, differential expression, ..."
  becomes "we asked whether gene expression predicts response to treatment
  beyond standard clinical features".

### 6. Leave the engineering out of the story

- **No implementation detail in the Introduction, Results or Discussion:** file
  paths, environment variables, configuration keys, tags, URLs, internal code
  labels (`batch.07`), counts nobody needs ("43 such records" becomes "many
  such records"), and the history of renames.
- **Report the outcome, not the process.** No step-by-step narrative of what
  was tried first and then, and no debugging stories. "on the first run the
  reference was missing, so it failed ... After adding it ..." becomes "The
  pipeline aligned all 120 samples to the reference".
- **Methods is the exception.** There, give what someone needs to reproduce
  the work: software and versions, random seeds, hyperparameters, permutation
  counts, thresholds ("Python 3.11 with scikit-learn 1.5", "random\_state =
  42", "1,000 permutations"). Not the reasoning that chose them, unless a
  reviewer would ask.

### 7. No signposting

Cut roadmaps and throat-clearing: "The three results subsections below
correspond to the three questions posed in the Introduction", "The subsections
that follow describe ...", "Where it is useful we name ...", "is taken up next".
Keep cross-references (`\S\ref`) to the ones a reader will actually follow. Get
to the scientific question: "We asked whether the mutation changes growth rate
in three media."

### 8. Structure

- **Number parallel points.** Use "First, ... Second, ... Third," or inline
  "(i) ... (ii) ... (iii)". Prefer these to bullet lists, which are rare in
  finished papers (one or two `itemize` each).
- **Run-in headings** (`\paragraph{}` or underlined labels) only when each one
  states a claim ("Resistance appears before exposure.") or names a fixed
  component ("Scoped.", "Attributed."). Never as decoration.
- **Short plain headings and captions.** "Study design: cohorts, sampling and
  follow-up" becomes "Study design".
- **Move dense statistics into a table** and keep the prose to the claim.

### 9. Words

- **Field terms over formal or house terms:** lab, not laboratory; PI, not
  principal investigator (after defining it once); members, not HQP; "chat
  (Slack here)", not "Slack".
- **Define every term and abbreviation at first use, then use the short
  form:** "clinical features (CFs)"; "a \emph{sample registry}; that is, the
  list of ...". Software and industry terms most of all.
- **Give examples with "e.g."**: "core facilities (e.g. genomics,
  proteomics)".
- **Spelling: Canadian.** tumour, colour, centre, behaviour, analysed,
  modelled, program; but -ize (organized, normalized). Match the surrounding
  text. A lab elsewhere sets its own.
- **Dashes:** no em dashes, and no `---` or ` -- ` used as a pause. LaTeX en
  dashes (`--`) only in ranges (`$7$--$17$-fold`) and compound names
  (Benjamini--Hochberg). Use a comma, brackets, a colon or a new sentence.
- **Words that do not appear:** leverage, crucial, cutting-edge, delve,
  state-of-the-art, seamless, empower, unlock, revolutionary, powerful,
  comprehensive (except in a precise sense), novel (rarely, and only of a
  finding), robust (only in its statistical sense), "it is important to note",
  "In recent years", "Additionally", "Furthermore", "In summary".

### 10. Numbers

- **Always give the number, the test, the threshold and the multiple-testing
  context:** "A moderated-$t$ contrast did not identify any differentially
  expressed genes at a Benjamini--Hochberg false-discovery rate of $q<0.1$".
- **Put statistics in brackets after the claim, then say what they mean in one
  plain sentence,** often beginning "That is," or "For example,": "That is,
  treated samples resemble untreated ones, and not the resistant line."
- **Qualify a result by its weakness straight away:** "however $\approx25$
  false positives are expected by chance among the $500$ genes tested."
- Numbers in LaTeX math (`$412$`, `$p=0.01$`); confidence intervals as
  `[0.12\text{--}0.58]`.

---

## Section by section

**Abstract.** One block, four movements: what is established; what is not
(the gap, stated as a fact); what we did, with the cohort or system in
brackets; what we found, with statistics inline, and one sentence on what it
means. Present tense for the field and conclusions, past for what was done.
Lead with the biology or the clinical stakes, never the pipeline.

**Introduction.** Field, then gap, then contribution, in prose. Define the
central term first. Survey prior work as "First, ... Second, ... Third," with
named examples and citations at clause ends. State the gap plainly
("Nevertheless, most studies of this disease pool its two subtypes").
Questions may be listed. Close by weighing what each possible answer would
mean. Present tense; sentences of 20 to 35 words.

**Methods.** Short, factual, procedural, reproducible: versions, seeds,
thresholds, exclusions with the reason ("Four genes were excluded due to low
expression"). Past tense for a study; present tense is acceptable for
describing a system. Inline lists use (i) to (v).

**Results.** Subsection titles state the finding as a sentence ("Expression
adds little to clinical features in predicting relapse."). A paragraph opens
on the test and its result together, qualifies the result at once, and closes
on a summary sentence that names the table or figure. Past tense for what was
done and seen, present for interpretation ("We cannot conclude"). Point to
Methods with `\S\ref` rather than repeating them.

**Discussion.** Open by restating the questions and the answer in brief ("We
asked three questions ... In brief, we do not find any evidence ..."). Then
run-in paragraphs titled with claims, each raising the natural objection and
answering it ("A natural concern is that ... We show that this is not the
case."). Then limitations, frankly. End on a measured recommendation, not a
flourish.

**Figure and table legends.** A bold title that states the finding; then how
to read the figure; a one-sentence definition of any unfamiliar method; the key
numbers; footnotes marked a, b, c. Description only: no interpretation, no
caveats, no defence of the analysis.

---

## Before and after

Invented pairs, each showing one rule. A lab's real pairs go in
`docs/scientific_writing_examples.md`.

1. *Cut the justification.*
   - Before: "The assay therefore reports only two outcomes, \emph{growth} and
     \emph{no growth}, with no intermediate category, on the reasoning that
     an intermediate category would absorb every ambiguous plate."
   - After: "The assay has two outcomes: \emph{growth} and \emph{no growth}."

2. *No commentary on your own candour.*
   - Before: "The limits of this design are worth stating plainly, because it
     is a screen and not a validation."
   - After: "This design has limits."

3. *No cleft sentence, no restating tail.*
   - Before: "What the filter reliably removes is low-quality reads, which is
     the problem it was built for."
   - After: "The filter removes low-quality reads."

4. *Literal, not figurative.*
   - Before: "the effect of the inhibitor melts away by the third day."
   - After: "the effect of the inhibitor is no longer significant by the third
     day."

5. *Name the action, not an abstraction; two sentences, not an epigram.*
   - Before: "The design is a bargain and we present it as one: pooling buys
     power and spends independence."
   - After: "Pooling the cohorts increases statistical power. The price is
     that their samples are no longer independent."

6. *No antithesis; state the aim in the first person.*
   - Before: "The real question is not whether the score predicts relapse but
     whether it adds anything \emph{beyond} --- and independently of ---
     tumour grade"
   - After: "Our focus is on whether the score adds information to the
     prediction of relapse beyond tumour grade"

7. *No punchline; numbers, then one plain sentence.*
   - Before: "asked whether the marker distinguishes the two groups. It does.
     Levels are raised in responders (median $2.1$) but stay near baseline in
     non-responders ..."
   - After: "asked whether the marker distinguishes the two groups. Indeed,
     responders carry raised levels (median $2.1$) compared to non-responders,
     who sit near baseline ($0.9$ vs $0.8$ for controls). That is,
     non-responders look like controls, and not like responders."

8. *The person as actor, and the benefit to them.*
   - Before: "For a lab with little technical support, the gain is that sample
     naming rules can be written once and then checked automatically rather
     than by reminding people, which matters most for new students"
   - After: "Now a PI can write down how samples should be named, and the
     system checks every new sample against it. This is more efficient than
     repeatedly reminding people, especially new students"

9. *Purpose first, plain heading.*
   - Before: "\paragraph{Two checks no upload can skip.} Two checks are run
     on each file before it is stored."
   - After: "\paragraph{Upload checks.} To reduce the chance that a corrupted
     or mislabelled file enters the analysis, every file is checked twice
     before it is stored."

10. *Methods: the order, not the debugging history.*
    - Before: "Databases are queried in a fixed order, chosen by how reliable
      each proved during testing rather than by convenience. The first is
      queried first because it never timed out in a week of trials. ..."
    - After: "Databases are queried in a fixed order: first the primary
      archive, then two mirrors."

11. *Hedge speculation; drop emphasis and slang.*
    - Before: "resistance is a \emph{gradual} property of the population,
      whereas spread is a \emph{sudden} transition. The second outbreak is,
      mechanistically, a rebound ... the strain is already firing on all
      cylinders"
    - After: "resistance is a gradual property of the population, whereas
      spread is a more sudden transition. The second outbreak is perhaps,
      mechanistically, a rebound ... the strain is already growing
      rapidly"

12. *No signposting; get to the question.*
    - Before: "The subsections that follow describe each feature in turn, and
      each is illustrated with the same experiment, which we introduce here so
      that the illustrations are concrete."
    - After: "We illustrate each feature using one experiment: measuring the
      growth of a mutant strain in three media."

---

## Integrity

- **Never invent a citation, a number or a behaviour of the system.** Where one
  is missing, leave a visible gap (`[CITE: ...]`, `[N=?]`) and say so.
- **Cite only bibliography keys that already exist.** Ask for a missing
  reference to be added; do not edit exported `.bib` files.
- **Flag a clinical or empirical claim you cannot source** rather than soften
  it into vagueness.
- Citations go through the bookworm; reporting checklists (TRIPOD+AI,
  PROBAST+AI, REMARK) through the adversary; wording about people and
  communities through the conscience.

## Keeping this guide current

When the PI rewrites a passage the Scribe produced, the pair is evidence. Add
the clearest ones to `docs/scientific_writing_examples.md`, and change a rule
here when the pairs contradict it. The extraction is repeatable: pair each
commit in which the PI edited a manuscript by hand (on Overleaf, these arrive
as "Updates from Overleaf") with the lines it replaced, and keep those whose
earlier version came from a commit co-authored by Claude.

A lab that wants its Scribe in its own PI's voice builds its examples file the
same way, from its own manuscripts.
