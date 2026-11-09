# Serum enlarges colonies of a synthetic isolate compendium: a queryable paper package

This repository is a **paper package**: the manuscript, the code and data
behind each of its central claims, and a map between them (`paper.yaml`,
rendered to `build/claim_map.md` by `murmurent paper build`). Open it in
Claude Code and ask the `docent` to walk you through it: where a claim is
made, what evidence sits behind it, how to re-run it, and what the paper does
not address.

## Rules for a reader, reviewer or examiner

- **Read, do not change.** Nothing outside `build/` and `queries/` is written
  by a reader's session. If an analysis is re-run, its outputs go in `build/`.
- **Every answer carries a location**: a section or figure in the source, a
  file under `exp/`, or a data path. An answer with no location is a guess
  and is labelled one.
- **Questions are logged.** The docent appends each question and its answer to
  `queries/<your-handle>/<date>.md`. The log is append-only and is part of the
  record of the review.
- **Data stays where its tier puts it.** Paths under `immutable/`,
  `append_only/` and the other data-root folders are reached on the machine
  that holds them, never copied into this package.

## Where things are

| What | Where |
|---|---|
| Manuscript source | `main.tex` |
| Claims and their evidence | `paper.yaml`, `build/claim_map.md` |
| Code that made each figure | `exp/<n>_<slug>/` |
| Small data | `data/` |
| Query log | `queries/` |

Start with: `murmurent paper check` then `murmurent paper build`.
