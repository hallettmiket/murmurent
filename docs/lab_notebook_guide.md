# Lab Notebook Guide

> A concrete, opinionated guide for keeping a wigamig-compatible lab notebook
> as a Hallett Lab member. Read this once. Bookmark it. Don't reinvent.

There are **two distinct things** in wigamig that the word "notebook" can
mean. Knowing which is which prevents 90 % of confusion:

| Term | Where it lives | Who can read it | What goes there |
|---|---|---|---|
| **Daily journal** | `~/lab-notebook/YYYY-MM-DD.md` (your laptop) | You only | Today's plan, decisions, scratch reasoning, links to SEAs you're touching. |
| **Experimental notebook** | `<project_repo>/exp/<n>_<slug>/notebook.md` | Every project member (via git) | The lab notebook *for that experiment*: protocol, run dates, instrument, data file paths, raw results, conclusion. |

The dashboard's "Lab notebook · today" panel shows the **daily journal**.
The PI sees your **experimental notebooks** the moment you `wigamig push`.

## The daily journal — `~/lab-notebook/`

### Set up once

```bash
mkdir -p ~/lab-notebook
# (optional but recommended) open ~/lab-notebook as an Obsidian vault
```

If you use Obsidian: `Open folder as vault…` → pick `~/lab-notebook`.
The dashboard's `obsidian://` URL will then jump to the right file.

### Daily flow

1. Open the dashboard (`Open Dashboard.command`).
2. Click **edit** in the "Lab notebook · today" panel header.
   - First click of the day creates `~/lab-notebook/2026-05-08.md` from
     a small template.
   - Subsequent clicks just open it.
3. Write whatever helps you think. Use markdown. The dashboard renders
   these blocks: `#### heading`, paragraph (with `[[wikilinks]]`),
   `- [ ] task`, `- [x] done`, bulleted list, `> blockquote`, fenced
   code.
4. Save and switch back to the dashboard. The panel auto-refreshes the
   word count and content.

### Picking a different editor

Default order: `$WIGAMIG_NOTEBOOK_EDITOR` → `$EDITOR` → `obsidian://` → `code` → platform default.

```bash
# Force Obsidian (assumes lab-notebook is registered as a vault)
export WIGAMIG_NOTEBOOK_EDITOR=obsidian

# Force VS Code
export WIGAMIG_NOTEBOOK_EDITOR="code -g {path}"

# Force a specific binary with arguments
export WIGAMIG_NOTEBOOK_EDITOR="vim {path}"
```

### Sharing daily journals

The daily journal is **personal by default** — it never leaves your
laptop unless you explicitly publish from it. When you have a finding,
decision, or note that the lab should see, copy that section into:

- A **finding** in the project repo: `<project>/findings/YYYY-MM-DD_topic.md`,
  then `wigamig push <project>` — visible to project members on next pull.
- An **oracle entry** for lab-wide knowledge:
  `wigamig publish <path> --to oracle` — surfaces in the dashboard's
  "Group oracle · recent" panel for everyone.

Don't push your raw daily journal. It has half-formed thoughts.

---

## The experimental notebook — `<project>/exp/<n>_<slug>/notebook.md`

This is your **lab notebook for one experiment**, in the lab's classic
sense (paper notebook → digital). One experiment = one folder under
`<project_repo>/exp/`.

### Create a new experiment

```bash
wigamig experiment new --project dcis_sc_tutorial --name titration_v3
```

This scaffolds:

```
~/repos/dcis_sc_tutorial/exp/3_titration_v3/
  ├── README.md                ← purpose + parameters
  ├── run_all.py               ← entry point for the analysis
  ├── notebook.md              ← THE NOTEBOOK
  ├── pages/                   ← downsampled photos of paper notebook pages
  ├── sketches/                ← drawings (PNG/PDF)
  └── data/                    ← very small data files (< 1 MB)
```

…and the corresponding lab-VM directories:

```
/data/lab_vm/wigamig/raw/dcis_sc_tutorial/3_titration_v3/      (read-only after ingest)
/data/lab_vm/wigamig/refined/dcis_sc_tutorial/3_titration_v3/  (analysis outputs)
```

### `notebook.md` — what to write

Required frontmatter:

```yaml
---
experiment: 3_titration_v3
date: 2026-05-08
performer: ['@allie']
project: '[[dcis_sc_tutorial]]'
protocol: '[[src/protocols/qpcr_v2]]'
equipment: ['BioRad CFX96', 'Eppendorf 5810R']
reagents:
  - anti_cd31
  - 4_oht
status: running
analysis_status: not_started
---
```

Body: free-form. Markdown. Embed photos, link to data files, capture
your reasoning. The body always ends up in the project repo so write
it for your future self **and** for someone catching up next week.

### Adding pictures

**Phone snap (paper notebook page, instrument display, gel image):**

1. Take the photo on your phone.
2. AirDrop / iCloud / Files → drop into `exp/3_titration_v3/pages/`.
   - Downsample first if it's bigger than ~2 MB. Scanbot or Genius Scan
     for paper pages (they detect edges and produce clean JPGs).
3. Reference in the notebook body:
   ```markdown
   ![](pages/p3_run_setup.jpg)
   ```

**Drawings (Apple Pencil, iPad, tablet):**

Export PNG/PDF to `sketches/`. Same embed syntax:
`![](sketches/circuit.png)`.

**Screenshots (FACS plot, software output):**

`sketches/` is fine. If it's instrument-derived, prefer `wigamig
experiment ingest` — the file lands in `/data/lab_vm/wigamig/refined/<project>/<exp>/instrument_outputs/`
with checksums and the notebook's `instrument_outputs:` list updates
automatically.

**Don't** commit anything bigger than ~2 MB to the repo. Big images
go in `/data/lab_vm/wigamig/refined/<project>/<exp>/` and you reference them
by path in the notebook body.

### Linking to data files on the lab VM

Files on `/data/lab_vm/` are not in the repo (the lab-VM is the
canonical store). Reference them by absolute path:

```markdown
## Raw data

- Sequencing run: `/data/lab_vm/wigamig/raw/dcis_sc_tutorial/3_titration_v3/run_001.fastq.gz`
- Clinical metadata: `/data/lab_vm/wigamig/raw/dcis_sc_tutorial/3_titration_v3/clin.csv`

## Refined outputs

- Count matrix: `/data/lab_vm/wigamig/refined/dcis_sc_tutorial/3_titration_v3/counts.parquet`
- QC report: `/data/lab_vm/wigamig/refined/dcis_sc_tutorial/3_titration_v3/qc_report.html`
```

`wigamig push <project> --refined 3_titration_v3` walks the refined
dir, recomputes SHA-256 for every file, and updates the notebook's
`refined_data:` and `checksums:` frontmatter automatically. Run this
when you've produced new outputs.

### Pushing the experimental notebook so the PI can see it

The experimental notebook is **already in the project repo**, so it
travels with normal git push:

```bash
cd ~/repos/dcis_sc_tutorial
git add exp/3_titration_v3/
wigamig push dcis_sc_tutorial   # writes a personal branch + PR-friendly commit
```

Or, if you've also produced refined data on the lab VM:

```bash
wigamig push dcis_sc_tutorial --refined 3_titration_v3
```

The PI (and every project member) sees the new notebook on next pull.
The dashboard's "SEAs" + "Projects" panels update automatically once
their next refresh hits the API.

### When an experiment is finished

```bash
wigamig experiment status dcis_sc_tutorial titration_v3 --set complete
wigamig finalize experiment 3_titration_v3 --project dcis_sc_tutorial
```

`finalize` walks: examine → conclude. Examine creates a deliberation
document with one section per common agent (Adversary, Bookworm,
Oracle, Conscience). You paste each agent's contribution into the
right section in your CC session. Conclude validates that all
sections are present and writes a final summary into the project's
`findings/` directory.

---

## Quick reference

| I want to… | Do this |
|---|---|
| Capture a quick today-thought | Click **edit** in the dashboard's notebook panel |
| Open yesterday's daily journal | Click yesterday's date in the 7-day strip |
| Start a new experiment | `wigamig experiment new --project <p> --name <slug>` |
| Add a phone photo to an experiment | Drop into `<project>/exp/<n>/pages/`, embed with `![](pages/<file>)` |
| Add a screenshot of an instrument | `wigamig experiment ingest <project> <slug> <source-dir>` |
| Update refined-data checksums | `wigamig push <project> --refined <slug>` |
| Make my notebook visible to the PI | `wigamig push <project>` (or `--finalize` for a PR) |
| Promote a finding lab-wide | `wigamig publish <path> --to oracle` |

---

## What goes where (recap)

```
~/lab-notebook/                                  ← daily journal (private)
└── 2026-05-08.md

~/repos/dcis_sc_tutorial/                        ← project repo (shared via git)
└── exp/3_titration_v3/
    ├── notebook.md                              ← experimental notebook
    ├── pages/                                   ← photos
    └── sketches/                                ← drawings

/data/lab_vm/wigamig/raw/dcis_sc_tutorial/3_titration_v3/      ← raw data (read-only)
/data/lab_vm/wigamig/refined/dcis_sc_tutorial/3_titration_v3/  ← analysis outputs

~/repos/lab_mgmt/                        ← lab-mgmt repo (shared via git)
└── oracle/
    └── 2026-05-08_dcis_chrm_p14.md              ← curated findings (lab-wide)
```

If you find yourself wanting to put something in a place not in this
table, ask. The structure is intentional: data location determines who
can read it and how it gets backed up.
