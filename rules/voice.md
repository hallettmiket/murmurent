# Voice: read this before you write prose

**Read the voice guidelines at the start of every session, before writing
anything a person will read.** That includes replies in the terminal, commit
messages, pull request descriptions, README files, documentation, and any
document you are asked to produce. Code is exempt.

Reading them once at start up is the point. The guidelines are short, and the
cost of skipping them is a document written in the wrong register that someone
then has to rewrite.

## The two files

1. **The general voice**:
   [`output_styles/plain_english.md`](../output_styles/plain_english.md).
   Everything murmurent produces is read by working researchers, not by
   software engineers. Minimal jargon with every term defined where it first
   appears, no em dashes, plain and direct sentences, the answer before the
   detail.

   This file is also installed as a Claude Code output style, which a member
   selects per machine with `/config` then Output style. Selecting it applies
   it to the main conversation only. Subagents carry their own instructions,
   so an agent that writes prose must read this file itself.

2. **The voice of whatever you are writing in**. A repository may set its own
   register on top of the general voice, in its own `CLAUDE.md`. Read that
   file before writing in that repository, and follow it where it is stricter.

A centre with its own documents to write records them in `rules/local/`, not
here.

## The check before you send

1. No em dashes.
2. Every technical term either defined or removed.
3. A researcher who has not read the code could act on it.
