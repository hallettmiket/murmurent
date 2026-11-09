# The lab notebook

Your lab notebook lives in your personal Obsidian vault, and the oracle reads
it. This page says how it is laid out, how to put things into it from Claude
Code (text, a photo, a handwritten page, a sound note, a video, a result
file), where large files go, and how to build a report or an exposition from
it for one audience without sharing anything else.

The older page, [Lab notebook guide](lab_notebook_guide.md), covers the
dashboard's daily-journal panel and the per-experiment `notebook.md` inside a
project repository. This page is about the daily notebook in the vault.

## Two streams, written by two hands

| Stream | Where | Who writes it | What it holds |
|---|---|---|---|
| Notes | `<vault>/lab-notebook/<date>.md` | you | the day's own notes: short, headed, with frontmatter |
| Sessions | `<vault>/sessions/<date>/<session>.md` | a hook, automatically | every prompt you gave Claude Code, with the time, project, repository and commit |

You write your prompts in Obsidian, because a long prompt is easier to
write in a Markdown file than in a terminal, and you send them to Claude Code.
There is nothing to create per day:

- **From any note, with one key.** Write the prompt wherever you are, in the
  day's entry if you like, select it, and press the hotkey (set up once,
  below). It goes into Claude Code and is recorded under
  `sessions/<date>/sent.md` with the time.
- **A prompts file, only if you want prompts out of your notes.** Say "open
  today's prompts" to Claude Code (`murmurent prompt new`): it creates
  `prompts/<date>.md` with a heading and opens it. One prompt per block, a
  line `---` between blocks; `murmurent prompt send` with no arguments sends
  the latest block. You never type the path.

The hook then records every prompt that reached Claude Code, however it got
there (typed, pasted, or sent), in `sessions/<date>/<session>.md`. So prompts
that used to scroll off the screen and vanish when the session closed are
kept, with the time, project, repository and commit, and the oracle can
search them (`kind=sessions`).

### Sending a prompt from Obsidian with a hotkey

1. Install the community plugin **Shell commands** in Obsidian (Settings,
   Community plugins, Browse).
2. Add a shell command: `murmurent prompt send --text {{selection}}` (or
   `murmurent prompt send --file {{file_path:absolute}}` to send the latest
   block of the open file).
3. Give it a hotkey (Settings, Hotkeys, search for the command).

Select the prompt in any note, press the key: it lands in Claude Code and in
your sessions stream. `murmurent prompt send --to Terminal` or `--tmux <pane>`
chooses where it is pasted; `--no-paste` only copies and records.

Three things about the sessions stream:

- It stays in your personal vault. It is never published to the lab oracle,
  and inside a protected project the session file is marked `protected`, so
  the vault sync keeps it on the machine.
- A prompt that matches a PHI pattern (a health-card, medical-record or
  social-insurance number) or a secret pattern (an API key, a private key) is
  not written. The hook tells the session that the record has a gap there.
- `MURMURENT_NO_SESSION_LOG=1` turns it off.

The notebook is not a form. An entry needs frontmatter and one heading per
topic, nothing more. Obsidian's daily-note template can supply the
frontmatter:

```yaml
---
title: 2026-11-07
date: 2026-11-07
project: dcis
sensitivity: standard
audience: me
tags: []
---
```

Named entries (`meeting_with_x.md`) are fine; the oracle reads them too.

### Moving old pasted prompts out: `murmurent notebook split`

If your existing entries hold prompts you pasted by hand, run it once:

```bash
murmurent notebook split --dry-run   # shows what would move
murmurent notebook split             # moves it
```

It walks every entry, finds the prompt-shaped blocks (long paragraphs in the
second person, addressed to Claude), appends them to
`sessions/<date>/pasted.md`, and leaves the rest as the day's notes with a link
to where the prompts went. It prints each move for you to read. It deletes
nothing: a copy of each original goes under `<vault>/obsolete/lab-notebook/`
first. Fenced code is never cut in two.

### How the oracle reads it

`kind=notebook` searches the notes; `kind=sessions` searches the prompts;
`kind=all` returns both with the notes first. See
[The Oracle](oracle-workflow.md).

## Putting things in: `murmurent notebook add`

From a project folder (or with `--project <name>`):

```bash
murmurent notebook add "Gel of sample 27 ran clean; band at 40 kDa."
murmurent notebook add ~/Desktop/gel_27.jpg --note "lane 3 is the control"
murmurent notebook add ~/Desktop/bench_page.jpg --handwritten
murmurent notebook add ~/Desktop/voice_note.m4a
murmurent notebook add ~/Desktop/clip.mov
murmurent notebook add results/counts.csv
```

Or say it to Claude Code: "add this photo to today's notebook". Each call
adds one block to today's entry under a time heading.

| Given | What happens |
|---|---|
| text | appended under a `## HH:MM` heading |
| an image | sent to the server; a thumbnail in the vault's `attachments/<date>/`; the entry gets the thumbnail, the link, and a marked placeholder for Claude Code to describe what is in it, in one line, in the session |
| a handwritten page (`--handwritten`) | as an image, plus a marked placeholder for a transcription; the image stays the record |
| sound | sent to the server; transcribed if an ElevenLabs key is in the Keychain (see below), the transcript in the entry, marked; otherwise the entry says transcription was skipped |
| video | sent to the server; a poster frame in the vault; a transcript if there is speech, marked |
| a result file (CSV, figure, PDF) | at or under 2 MB: into the vault's `attachments/<date>/`; larger: to the server, linked |

**Every machine-made text is a reading, not the record.** A transcription or
an image description is marked as such in the entry, beside the original's
link, so a handwritten "20 µg" read as "20 ug" can be checked against the
page. A transcription that matches a PHI pattern is withheld; the entry says
so and the recording stays on the server. A corrected transcript is a new
line in the entry, never a change to the file on the server.

**Where large files go.** `$MURMURENT_DATA_ROOT/append_only/<project>/notebook/<date>/`
on the project's data host, over SSH, using the host murmurent already knows:
the lab's `data_host` (set with `murmurent group-setup`), else the host of the
project's main repository, else this machine. The host's data root is read
from `MURMURENT_DATA_ROOT` in its login shell. Nothing there is ever
overwritten: a second file of the same name becomes `name_2.ext`. The vault
keeps only text, thumbnails and poster frames, so the vault's sync to GitHub
stays fast and the original of a photo never sits in a synced folder. The
entry's link is `<host>:<path>`; a copy to look at comes with

```bash
murmurent notebook open lab-server:/data/lab_vm/append_only/dcis/notebook/2026-11-07/gel_27.jpg
```

which fetches it into `~/.murmurent/notebook_cache/` and opens it.

`--dry-run` shows what would happen and sends nothing. When no host is known
for the project, the command says so and names `murmurent host add`; `--host
<name>` chooses one.

**A protected project's images never get a thumbnail in the vault.** The
entry holds only the link. The project's tier comes from its record;
`--sensitivity` overrides it for one call.

**Transcription.** `murmurent notebook add` calls ElevenLabs speech-to-text
when the macOS Keychain holds an item named `elevenlabs-api-key` (or
`ELEVENLABS_API_KEY` is set). Store one with:

```bash
security add-generic-password -U -a "$USER" -s elevenlabs-api-key -w
```

Without a key the entry says transcription was skipped, and the recording is
still on the server. Image descriptions are not made by the command: it leaves
a marked line for Claude Code to fill in during the session, so you can see
and correct the reading at once.

The first version works from a laptop: drag the file into Claude Code or name
its path. A route from a phone is a later issue.

## Sharing some of it: `audience` and `murmurent notebook report`

Nothing leaves the notebook without an explicit audience. Each entry's
frontmatter may say:

| `audience` | Who may read the entry in a report |
|---|---|
| `me` (the default, also when the field is missing) | nobody; it stays in the vault |
| `supervisor` | your supervisor |
| `lab` | the whole lab (which includes your supervisor) |
| `project:<name>` | members of that project |

**Audience is per entry, and a report takes whole entries.** To share one
sentence, move it into its own entry. There is no partial sharing by
paragraph, because a paragraph that mixes audiences is where leaks happen.
Marking an entry `supervisor` is your choice each time; nothing lets a
supervisor read your `me` entries.

A `restricted` or `protected` entry is refused whatever its audience, exactly
as `murmurent oracle publish` refuses it.

```bash
murmurent notebook report --for supervisor --since 2026-11-01
murmurent notebook report --for lab --since 2026-10-01 --until 2026-10-31   # the PI's exposition
murmurent notebook report --for project:dcis --since 2026-11-01 --out ~/Desktop/dcis_week
```

The command:

1. collects the whole entries whose audience admits the reader, in the range;
2. writes `material.md` (the entries, as written) and `sources.md` (every
   entry and file drawn on, and every entry refused) to the output folder,
   `<vault>/reports/<until>_<audience>/` unless `--out` says otherwise;
3. renders `report.html`, one self-contained page: the entries, thumbnails
   embedded, machine-made text still marked, server files linked;
4. prints the list of every entry and file it drew on;
5. sends nothing.

The same page serves a student's weekly report and a PI's exposition; the
difference is the audience and the voice, not the layout.

**The scribe's narrative.** The page has a marked section for a narrative.
Ask the [scribe](https://github.com/hallettmiket/murmurent/blob/main/agents/scribe.md)
to draft it from `material.md` into `narrative.md` in the same folder (it
leaves `[CITE]` and `[N=?]` gaps rather than inventing), then run the command
again: the narrative goes into the page. The
[artist](https://github.com/hallettmiket/murmurent/blob/main/agents/artist.md)
renders any figure that needs real data.

**Large shared files stay on the server.** The page links to
`append_only/<project>/notebook/...`; a reader with an account opens the file
there (`murmurent notebook open <link>`), and a reader without one sees the
thumbnail and a sentence saying where the original is. A movie is never
embedded in the page.

**Delivery, after you have read the page and the source list.** One of:

- a private Claude artifact: ask Claude Code to publish `report.html` as an
  artifact and share the link;
- the channel: `murmurent project note "<one line>"`, with the page attached
  or linked, which goes where the repository's notes belong;
- a file: send `report.html` yourself.

The artifact or the file is a carrier, not the archive. The record stays in
the vault and on the server.

## Reference

| Command | Effect |
|---|---|
| `murmurent notebook add <text or file> [--project P] [--host H] [--handwritten] [--kind K] [--note T] [--sensitivity S] [--date D] [--dry-run]` | Put text or a file into today's entry; large files to the host's `append_only/<P>/notebook/<date>/` |
| `murmurent notebook open <host>:<path> [--no-open]` | Fetch a copy of a linked file into `~/.murmurent/notebook_cache/` and open it |
| `murmurent prompt new` | Open today's `prompts/<date>.md` (created with a heading if missing). |
| `murmurent prompt send [--text ...] [--file ...] [--to <app>] [--tmux <pane>] [--no-paste]` | Send a prompt from Obsidian to Claude Code: clipboard, paste, and a record under `sessions/<date>/sent.md`. |
| `murmurent notebook split [--dry-run]` | Move pasted prompts out of old entries into `sessions/<date>/pasted.md`; originals kept under `obsolete/` |
| `murmurent notebook report --for <audience> --since <date> [--until <date>] [--out DIR] [--title T]` | Collect, write material and sources, render the page, list what was used; send nothing |

Folders in the vault: `lab-notebook/` (notes), `prompts/` (what you write to send), `sessions/` (what reached Claude Code),
`attachments/<date>/` (thumbnails, poster frames, small result files),
`reports/` (built reports), `obsolete/` (originals kept by `split`).
