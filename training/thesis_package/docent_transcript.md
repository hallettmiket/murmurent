# Docent exchanges shown in the movie

Real replies of the docent, run on 2026-11-07 against a copy of
`examples/thesis_example` (Murmurent 2026.11.0), shortened to fit a frame.
The verdict lines are verbatim; the detail keeps the locations and the numbers
and drops nothing that changes the answer. `make_movie.py` reads this file:
each `## <key>` section starts with `<who>: <question>`, then the reply lines.

## 1
External examiner: Where does the thesis show that serum enlarges colonies, and does that result hold? Re-run it.
Located — Chapter 2, Results, first paragraph (claim c1, fig:signal). Re-run: serum 5.12 mm
vs control 4.17 mm, difference 0.95 mm, permutation p = 0.0004. The result holds.

Where: build/claim_map.md, chapter 2, row c1; thesis of record build/main.pdf, chapter 2,
Results, Figure 2.1: "Colonies grown in serum were larger than controls ... the difference
held under permutation." The PDF and the package agree.
Re-run: cd paper_example && python3 exp/1_signal/run_all.py   (data/signal.csv, 40 isolates)
  mean_control_mm 4.17   mean_serum_mm 5.12   difference_mm 0.95   permutation_p 0.0004
  5000 permutations, seed 0. Identical to the results.tsv already in the package.
Not said in the text: no significance threshold; main.tex line 13 says the data are made up.
Onward: whether a permutation test on 40 simulated values is the right evidence is for
the adversary, citing claim c1. Logged in queries/examiner/2026-11-07.md.

## 2
External examiner: Does the thesis address incubation temperature?
Absent — no chapter, claim, script or data column mentions incubation temperature; the only
growth condition the thesis varies is the medium (serum versus control).

Searched, no match for "temperature", "incubat" or a degree value: thesis.yaml (c3.1),
paper_example/paper.yaml (c1), build/claim_map.md; every chapter and front-matter file;
paper_example/main.tex; the text of build/main.pdf. data/signal.csv has columns isolate,
medium, colony_mm, country: no temperature. Neither run_all.py reads or sets one.
Nearest thing the thesis does address: growth medium (main.tex, Methods and Results,
claim c1) and country of origin (chapters/03_metadata.tex, claim c3.1). Methods say the
diameters were drawn from two normal distributions, so no incubation took place.
Logged in queries/examiner/2026-11-07.md, append-only.

## 3
Candidate: Is my defence talk plan going to fit in 20 minutes, and what paperwork is still open?
Located — build/talk_plan.md budgets 10 slides at exactly 20.0 minutes with no slack;
build/paperwork.md has 17 boxes unticked, 3 of them before the preliminary submission.

The talk: slides 6 and 7 (one per claim) 6.2 min each; the other eight share 7.6 min.
build/paperwork.md, "The defence": 10 to 15 minutes unless the program sets another
length. The plan is 20: confirm the length with the Graduate Program Coordinator.
Neither figure has an image in the package yet: a figure for the screen is the artist's job.
Paperwork open: supervisor confirms the thesis is ready; date and format agreed with the
examiners; Thesis Examination Request Form, all by 2027-03-12. Then the six Veritas
steps, and five final-submission boxes after the defence.
Already ticked: the board, abstract, lay summary, GenAI and co-authorship statements,
the PDF, the talk draft. Logged in queries/candidate/2026-11-07.md.

## log
examiner: the examiner's log for the day
## 07:19

**Question (as asked):** Where does the thesis show that
serum enlarges colonies, and does that result hold? Re-run it.

**Verdict:** Located — Chapter 2 Results, first paragraph
(claim c1, fig:signal); re-run of exp/1_signal/run_all.py
gives serum 5.12 mm vs control 4.17 mm, permutation p = 0.0004.

**Locations:** build/claim_map.md row c1; build/main.pdf
chapter 2, Figure 2.1; paper_example/main.tex lines 16-22;
exp/1_signal/run_all.py; data/signal.csv; build/results.tsv.

## 07:19

**Question (as asked):** Does the thesis address incubation
temperature?

**Verdict:** Absent — no chapter, claim, script or data
column mentions incubation temperature ...
