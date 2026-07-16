# Vignette 3 — frontmatter, and the "me" file

## The situation

Sam has been saving notes for a few weeks and starts wondering: how
does the oracle know which notes belong to which project, and why
does Claude sometimes explain things Sam already knows? Two small
files answer both questions.

## What you type

First, Sam looks at the top of a saved note — the frontmatter — and
notices `project`, `tags`, and `sensitivity` are already filled in.
These let the oracle find the right notes later, and decide what may
ever be shared. A note marked `sensitivity: standard` can eventually
be shared with the lab; a note marked `sensitivity: clinical` stays
private and can never be published — more on that in vignette 5 and 6.

Second, Sam writes a short "me" file describing how they like to
work, at `maps-legends/me.md`:

```markdown
I'm a first-year student — please explain any acronyms.
My project is brca_er.
```

## What murmurent does

Murmurent doesn't parse `maps-legends/` itself. Instead, when Sam's
vault was created, murmurent seeded a `CLAUDE.md` file at the vault
root that tells Claude to read `maps-legends/` for context. Claude
Code automatically loads that `CLAUDE.md` whenever Sam opens a file
in the vault — so the "me" file shapes how Claude talks to Sam
indirectly, as context Claude reads, not a setting murmurent enforces.

```mermaid
flowchart LR
    A[You open a file in your vault] --> B[Claude loads your vault's CLAUDE.md]
    B --> C[CLAUDE.md points to maps-legends/me.md]
    C --> D[Claude tailors how it talks to you]
```

## What you get

Before the "me" file, Claude might say "ESR1 is a strong prognostic
marker in ER+ BC." After Sam adds `maps-legends/me.md`, Claude says
something like: "ESR1 (the estrogen-receptor gene) is a strong sign
of outcome in ER-positive (ER+) breast cancer (BC) — I'll spell out
acronyms like that going forward."

??? note "Under the hood"
    The frontmatter fields are defined by the
    [oracle entry schema](https://github.com/hallettmiket/murmurent/blob/main/rules/oracle_schema.md).
    `maps-legends/` is yours to write — murmurent never writes there
    itself; see [the vault layout](../obsidian-layout.md) and
    [what murmurent touches in your vault](../obsidian-usage.md) for
    the full picture of which folders murmurent reads and writes.
