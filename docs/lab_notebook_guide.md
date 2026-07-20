# Lab Notebook Guide

> A concrete guide for keeping a murmurent-compatible lab notebook
> as a lab member.

There are **two distinct things** in Murmurent that the word "notebook" can
mean. Distinguishing them prevents most of the common confusion:

| Term | Where it lives | Who can read it | What goes there |
|---|---|---|---|
| **Daily journal** | your Obsidian vault's `lab-notebook/YYYY-MM-DD.md` (or `~/lab-notebook/` if you have no vault registered) | You only | Today's plan, decisions, scratch reasoning, links to SEAs you're touching. |
| **Experimental notebook** | `<project_repo>/exp/<n>_<slug>/notebook.md` | Every project member (via git) | The lab notebook for that experiment: protocol, run dates, instrument, data file paths, raw results, conclusion. |

The dashboard's "Lab notebook · today" panel shows the **daily journal**.
The PI sees your **experimental notebooks** the moment you `murmurent push`.

## The daily journal: your vault's `lab-notebook/` folder

### Set up once

There's nothing to create by hand. The dashboard resolves where the daily
journal lives, in this order:

1. `$MURMURENT_NOTEBOOK_DIR` if you set it (power users / non-Obsidian setups).
2. **`<your-Obsidian-vault>/lab-notebook/`**: the normal case once you have a
   vault registered, so entries sit alongside the rest of your notes and the
   `obsidian://` link works.
3. `~/lab-notebook/`: a fallback only when no vault is registered.

The first time it resolves to the vault path, any pre-existing
`~/lab-notebook/*.md` files are migrated in for you (one-time, logged).

### Daily flow

1. Open the dashboard (`Open Dashboard.command`).
2. Click **edit** in the "Lab notebook · today" panel header.
   - First click of the day creates that day's file (e.g.
     `2026-05-08.md`) in the resolved `lab-notebook/` folder from a small
     template.
   - Subsequent clicks just open it.
3. Write whatever helps you think. Use markdown. The dashboard renders
   these blocks: `#### heading`, paragraph (with `[[wikilinks]]`),
   `- [ ] task`, `- [x] done`, bulleted list, `> blockquote`, fenced
   code.
4. Save and switch back to the dashboard. The panel auto-refreshes the
   word count and content.

### Picking a different editor

Default order: `$MURMURENT_NOTEBOOK_EDITOR` → `obsidian://` (when the note is in a registered vault) → `$EDITOR`/`$VISUAL` → `code` → platform default.

```bash
# Force Obsidian (assumes lab-notebook is registered as a vault)
export MURMURENT_NOTEBOOK_EDITOR=obsidian

# Force VS Code
export MURMURENT_NOTEBOOK_EDITOR="code -g {path}"

# Force a specific binary with arguments
export MURMURENT_NOTEBOOK_EDITOR="vim {path}"
```

### Sharing daily journals

The daily journal is **personal by default**: it never leaves your
laptop unless you explicitly publish from it. When you have a finding,
decision, or note that the lab should see, copy that section into:

- A **finding** in the project repo: `<project>/findings/YYYY-MM-DD_topic.md`,
  then `murmurent push <project>`, visible to project members on next pull.
- An **oracle entry** for lab-wide knowledge: stage a draft with the
  Oracle agent, then `murmurent oracle publish <slug>`, surfaces in the
  dashboard's "Group oracle · recent" panel for everyone (see
  [oracle-workflow.md](oracle-workflow.md)).

Do not push your raw daily journal; it contains half-formed thoughts.

---

## The experimental notebook: `<project>/exp/<n>_<slug>/notebook.md`

This is your **lab notebook for one experiment**, in the lab's classic
sense (paper notebook → digital). One experiment = one folder under
`<project_repo>/exp/`.

### Create a new experiment

```bash
murmurent experiment new --project brca_sc_tutorial --name titration_v3
```

This scaffolds:

```
~/repos/brca_sc_tutorial/exp/3_titration_v3/
  ├── README.md                ← purpose + parameters
  ├── run_all.py               ← entry point for the analysis
  ├── notebook.md              ← THE NOTEBOOK
  ├── pages/                   ← downsampled photos of paper notebook pages
  ├── sketches/                ← drawings (PNG/PDF)
  └── data/                    ← very small data files (< 1 MB)
```

…and the corresponding lab-VM directories:

```
$MURMURENT_LAB_VM_ROOT/raw/brca_sc_tutorial/3_titration_v3/      (read-only after ingest)
$MURMURENT_LAB_VM_ROOT/refined/brca_sc_tutorial/3_titration_v3/  (analysis outputs)
```

### `notebook.md`: what to write

Required frontmatter:

```yaml
---
experiment: 3_titration_v3
date: 2026-05-08
performer: ['@allie']
project: '[[brca_sc_tutorial]]'
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
your reasoning. The body always ends up in the project repo, so write
it for your future self and for a colleague reviewing the work later.

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

`sketches/` is fine. If it's instrument-derived, prefer `murmurent
experiment ingest`: the file lands in `$MURMURENT_LAB_VM_ROOT/refined/<project>/<exp>/instrument_outputs/`
with checksums and the notebook's `instrument_outputs:` list updates
automatically.

Do not commit anything larger than ~2 MB to the repo. Large images
go in `$MURMURENT_LAB_VM_ROOT/refined/<project>/<exp>/` and you reference them
by path in the notebook body.

### Linking to data files on the lab VM

Files on `/data/lab_vm/` are not in the repo (the lab-VM is the
canonical store). Reference them by absolute path:

```markdown
## Raw data

- Sequencing run: `$MURMURENT_LAB_VM_ROOT/raw/brca_sc_tutorial/3_titration_v3/run_001.fastq.gz`
- Clinical metadata: `$MURMURENT_LAB_VM_ROOT/raw/brca_sc_tutorial/3_titration_v3/clin.csv`

## Refined outputs

- Count matrix: `$MURMURENT_LAB_VM_ROOT/refined/brca_sc_tutorial/3_titration_v3/counts.parquet`
- QC report: `$MURMURENT_LAB_VM_ROOT/refined/brca_sc_tutorial/3_titration_v3/qc_report.html`
```

`murmurent push <project> --refined 3_titration_v3` walks the refined
dir, recomputes SHA-256 for every file, and updates the notebook's
`refined_data:` and `checksums:` frontmatter automatically. Run this
when you've produced new outputs.

### Pushing the experimental notebook so the PI can see it

The experimental notebook is **already in the project repo**, so it
travels with normal git push:

```bash
cd ~/repos/brca_sc_tutorial
git add exp/3_titration_v3/
murmurent push brca_sc_tutorial   # writes a personal branch + PR-friendly commit
```

Or, if you've also produced refined data on the lab VM:

```bash
murmurent push brca_sc_tutorial --refined 3_titration_v3
```

The PI (and every project member) sees the new notebook on next pull.
The dashboard's "SEAs" + "Projects" panels update automatically once
their next refresh hits the API.

### When an experiment is finished

```bash
murmurent experiment status brca_sc_tutorial titration_v3 --set complete
murmurent finalize experiment 3_titration_v3 --project brca_sc_tutorial
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
| Start a new experiment | `murmurent experiment new --project <p> --name <slug>` |
| Add a phone photo to an experiment | Drop into `<project>/exp/<n>/pages/`, embed with `![](pages/<file>)` |
| Add a screenshot of an instrument | `murmurent experiment ingest <project> <slug> <source-dir>` |
| Update refined-data checksums | `murmurent push <project> --refined <slug>` |
| Make my notebook visible to the PI | `murmurent push <project>` (or `--finalize` for a PR) |
| Promote a finding lab-wide | `murmurent oracle publish <slug>` (stage the draft first, see [oracle-workflow.md](oracle-workflow.md)) |

---

## What goes where (recap)

```
~/lab-notebook/                                  ← daily journal (private)
└── 2026-05-08.md

~/repos/brca_sc_tutorial/                        ← project repo (shared via git)
└── exp/3_titration_v3/
    ├── notebook.md                              ← experimental notebook
    ├── pages/                                   ← photos
    └── sketches/                                ← drawings

$MURMURENT_LAB_VM_ROOT/raw/brca_sc_tutorial/3_titration_v3/      ← raw data (read-only)
$MURMURENT_LAB_VM_ROOT/refined/brca_sc_tutorial/3_titration_v3/  ← analysis outputs

~/repos/murmurent_lab_mgmt_<lab>/        ← lab-mgmt repo (shared via git)
└── oracle/
    └── 2026-05-08_brca_chrm_p14.md              ← curated findings (lab-wide)
```

If you find yourself wanting to put something in a place not in this
table, ask. The structure is intentional: data location determines who
can read it and how it gets backed up.
