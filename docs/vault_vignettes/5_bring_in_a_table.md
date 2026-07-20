# Vignette 5: bring in a table

## The situation

Sam wants Claude to be able to look at the 4-row sample table from
the index page and answer questions about it, not just about notes
written in prose.

## What you type

Sam writes a small oracle note whose body is just the table, and
asks:

> "Which of my tumour samples are ER-positive?"

This uses the **Oracle**, not `murmurent_data/`. The table is small and
*is* the fact Sam wants to keep and search, so it belongs inside an Oracle
note, where Claude reads it during an ordinary recall. A full spreadsheet
file that you would not paste inline goes in `murmurent_data/` instead (see
vignette 4), where an agent reads it on demand.

## What Murmurent does

1. A small table can live inside an Oracle note as a plain
   markdown table, with no special format required.
2. Claude reads the table directly from the note and can answer
   questions about it.
3. This illustrative table is fabricated, so `sensitivity: standard`
   is appropriate. Real clinicopathological or patient data must be
   marked `sensitivity: clinical`: that keeps it in Sam's personal
   vault only, and it can never be published to the lab (see vignette 6).
   Only small tables belong inside a note; a full spreadsheet file goes
   in `murmurent_data/` (see vignette 4), and large data files live in the
   lab's `refined/` storage.

```mermaid
flowchart LR
    A[Put a small table in a vault note] --> B[Claude reads it]
    B --> C[Ask questions about your samples]
```

Clinical data stays personal: it never leaves Sam's vault.

## What you get

```markdown
---
title: brca_er sample table
date: 2026-07-30
project: brca_er
sensitivity: standard
tags: [esr1, samples, breast-cancer]
sources: ['@sam']
---

# brca_er sample table

| sample | type   | ER status | grade |
|--------|--------|-----------|-------|
| s1     | tumour | pos       | 2     |
| s2     | tumour | pos       | 3     |
| s3     | tumour | neg       | 2     |
| s4     | normal | neg       | 1     |
```

Claude can now answer "which tumour samples are ER-positive?" with
"s1 and s2" directly from this note.

??? note "Under the hood"
    Sensitivity governs what can later be published: see the
    [data storage rule](https://github.com/hallettmiket/murmurent/blob/main/rules/data-storage.md)
    and the [oracle entry schema](https://github.com/hallettmiket/murmurent/blob/main/rules/oracle_schema.md).
    For the difference between small notes like this one and bulk
    data files, see [memory tiers](../memory.md): tier-2 notes
    versus tier-3 bulk data.
