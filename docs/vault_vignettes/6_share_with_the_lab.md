# Vignette 6: share a fact with the lab

## The situation

Sam's ESR1 finding from vignette 1 is now solid, checked against the
pathology data, and worth sharing with the whole lab.

## What you type

Sam asks the oracle, in plain English:

> "Can you stage my ESR1 finding to share with the lab?"

Then, in a terminal, Sam runs:

```
murmurent oracle publish esr1-high-in-tumour-samples --push
```

## What Murmurent does

1. The oracle writes a copy of the note into `oracle/drafts/` in
   Sam's vault. The oracle never pushes to the lab itself; it only
   stages the draft.
2. `murmurent oracle publish` validates the note, copies it into the
   lab vault (the lab-management repo,
   `murmurent_lab_mgmt_<lab>`), and commits it. Adding `--push`
   pushes it in one go.
3. Now every lab member can recall Sam's finding through their own
   oracle.
4. If the note were marked `sensitivity: clinical` or `restricted`,
   `murmurent oracle publish` would refuse it outright: those notes
   stay personal, tying back to vignettes 3 and 5.

```mermaid
flowchart LR
    A[Ask oracle to stage a draft] --> B[draft in oracle/drafts/]
    B --> C[murmurent oracle publish]
    C --> D[note in the lab vault, whole lab can see]
```

## What you get

```
murmurent oracle publish esr1-high-in-tumour-samples --push
```

```
published: esr1-high-in-tumour-samples -> lab vault · pushed: yes
```

If Sam had tried to publish a `sensitivity: clinical` note instead,
the command would refuse it and nothing would leave Sam's vault.

??? note "Under the hood"
    See [the oracle workflow](../oracle-workflow.md) for the full
    promote-personal-to-lab flow,
    [what Murmurent touches in your vault](../obsidian-usage.md) §2.4 for
    exactly what the publish command checks and what happens to the draft
    afterward, and [memory tiers](../memory.md) for where the
    personal/lab governance boundary sits. Sensitivity rules are defined
    in the
    [oracle entry schema](https://github.com/hallettmiket/murmurent/blob/main/rules/oracle_schema.md).
