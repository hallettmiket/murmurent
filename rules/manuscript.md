# Manuscript pull-first rule

The wigamig manuscript lives in its own repo, synchronised with
**Overleaf via GitHub**:

- Working clone: `~/repos/wigamig_manuscript`
- Remote: `git@github.com:hallettmiket/wigamig_manuscript.git`
- Single source file: `main-article.tex` (Springer Nature class);
  bibliography in `wigamig_bib.bib`.

Mike edits the manuscript **both** locally (through Claude Code) and on
Overleaf (in a browser). Overleaf pushes to GitHub, so the GitHub `main`
can be ahead of your local clone at any moment.

## The rule

**Before modifying the manuscript, `git -C ~/repos/wigamig_manuscript
pull` first.** Skipping this risks clobbering edits Mike made in
Overleaf, and produces merge conflicts that are painful to resolve
(Overleaf has no branches — everything is on `main`).

After a coherent block of edits: **commit and push promptly** so
Overleaf can fetch them. Do not sit on uncommitted manuscript changes.

## Guardrails (from the manuscript's own `CLAUDE.md`)

- **Overleaf edits are authoritative** on conflict — if a `git pull`
  produces conflict markers in a `.tex` file, stop and ask before
  resolving.
- **No feature branches** — Overleaf only tracks `main`.
- **No bulk reformatting** (rewrapping, reordering preamble) — Overleaf
  reads whitespace churn as content changes and it buries real edits.
- **Do not edit auto-generated artefacts** (`*.aux`, `*.bbl`, `*.blg`,
  `*.log`, `*.out`, `*.synctex.gz`) — Overleaf regenerates them on
  compile. **Do not compile locally**; Overleaf compiles.

The manuscript is the authoritative description of wigamig's purpose and
architecture. When doing admin-level or design work, read it (and the
code) before acting — see the `/wigamig-admin` skill.
