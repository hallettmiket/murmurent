# Colony phenotypes of a synthetic isolate compendium: a queryable thesis package

This repository is a **thesis package**: chapters that are paper packages
(each with its own `paper.yaml` mapping claims to code and data) or plain
chapters carrying their own claims, plus the candidate's introduction,
bridging text, conclusion and front matter (`thesis.yaml`).
`murmurent thesis build` writes `build/main.tex`, the thesis of record, and
`build/claim_map.md`, the map of every claim in every chapter.
`murmurent thesis talk` drafts the defence talk; `murmurent thesis paperwork`
writes the Western submission checklist.

Open it in Claude Code and ask the `docent`. It walks a candidate through
building and checking the package, and walks an examiner through reading it:
where a claim is made, what sits behind it, how to re-run it, and what the
thesis does not address.

## Rules for an examiner

- **Read, do not change.** Nothing outside `build/` and `queries/` is written
  by an examiner's session.
- **Every answer carries a location.** An answer with no location is labelled
  a guess.
- **Questions are logged** to `queries/<your-handle>/<date>.md`, append-only.
  The log is part of the record of the examination.
- **The PDF is the thesis of record.** This package supplements it; a
  disagreement between the two is a finding, and the PDF wins until fixed.
- **Data stays in its tier.** Protected data is reached on the server that
  holds it, never copied here.

## Where things are

| What | Where |
|---|---|
| Chapters and front matter | `thesis.yaml`, `chapters/`, `front/` |
| Paper packages | listed under `chapters:` with `kind: paper` |
| The assembled thesis | `build/main.tex` (and `build/main.pdf` after `--pdf`) |
| Every claim with its evidence | `build/claim_map.md` |
| The defence talk | `build/talk_plan.md`, `build/talk.tex` |
| Submission checklist | `build/paperwork.md` |
| Query log | `queries/` |

Start with: `murmurent thesis check` then `murmurent thesis build`.
