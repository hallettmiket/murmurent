# Slack integration design

> Status: design (2026-05-08), **partially implemented** (Phase 11):
> `murmurent slack mirror` / `slack distil` and the
> `oracle drafts / approve / decline` review loop are live
> (`core/slack_mirror.py`, `core/slack_distill.py`). Bulk fetch
> (`--all/--since`), cron, redaction, and the weekly digest are not yet
> built. PRs against this doc are how we change the remaining design.

## Goal

Surface lab Slack conversations in two complementary ways:

1. **Provenance** — every project channel mirrored verbatim into the
   lab-mgmt repo as a daily markdown log, so we don't lose context if
   Slack data retention rolls over.
2. **Distillation** — the Oracle agent reads each day's mirror, picks
   out new knowledge / decisions / open questions, and writes oracle
   entries that surface in the dashboard's "Group oracle · recent"
   panel.

Today the dashboard shows oracle entries that came from manual
`murmurent publish`. After this phase, oracle entries also come from
nightly Slack distillation, with the raw mirror as their citation
trail.

## Channel convention

- One channel per project, named `#proj_<project_slug>` (e.g.
  `#proj_dcis_sc_tutorial`). The convention matches the project repo's
  directory name so a glance at the sidebar is unambiguous.
- Lab-wide channels (`#general`, `#random`, journal clubs, etc.) are
  not auto-monitored.
- A channel becomes monitored when its **topic line contains the
  marker** `[oracle:on]`. This is the opt-in (per the resolved decision
  in HANDOFF.md / Phase-7 conversation): channels say so explicitly,
  members can see it in the topic, anyone can flip it off by editing
  the topic.

## The bot account

A new Slack user account in the existing Hallett Lab workspace:

- Display name: **Murmurent Oracle Bot**
- Handle: `@murmurent-oracle`
- Profile bio: "Auto-summarises monitored channels into the lab oracle.
  Read-only. See `docs/slack_integration.md`."
- Member of every monitored channel (the channel's topic flag is what
  the bot uses to decide whether to read; channel membership is just
  to receive history).
- App-level OAuth scopes (no user-OAuth):
  - `channels:history` — read public-channel messages
  - `groups:history` — read private-channel messages (only on channels
    the bot is invited to)
  - `users:read` — resolve user IDs → handles for citations
  - `team:read` — workspace metadata (one-time, for `lab.md`)
  - `chat:write` — **only used to post the daily summary back into
    the channel** (see "Two-way?" below); not used for one-way phase

The bot owner is the PI's Slack admin role; rotation is via the
Slack admin UI.

## Storage layout in lab-mgmt

```
~/repos/murmurent_lab_mgmt_<lab>/
├── slack/
│   ├── proj_dcis_sc_tutorial/
│   │   ├── 2026-05-08.md           ← raw mirror (one file per day)
│   │   └── 2026-05-07.md
│   └── proj_bbb_drug_screen/
│       └── 2026-05-08.md
└── oracle/
    ├── 2026-05-08_dcis_chrm_p14.md          ← manual publish (current)
    └── 2026-05-09_proj_dcis_summary.md      ← bot-distilled
```

Each raw mirror file is markdown with frontmatter:

```yaml
---
channel: proj_dcis_sc_tutorial
date: 2026-05-08
message_count: 47
participants: ['@allie', '@bob', '@cassie']
slack_workspace: hallett-lab.slack.com
---

## 09:14 · @allie
Q30 above 92% across the lane on run 17. Re-checking the chrM
contig issue.

## 09:18 · @bob
Confirmed — same chrM artefact as before. Patched in p14.

## 09:24 · @allie  (thread reply to 09:18)
Switching reference build for run 17. Documenting in CHANGELOG.
```

Each distilled oracle entry is markdown with frontmatter:

```yaml
---
title: 'GRCh38.p14 fixes the chrM contig issue for run 17'
author: '@murmurent-oracle'
date: 2026-05-09
project: dcis_sc_tutorial
source_channel: proj_dcis_sc_tutorial
source_date: 2026-05-08
source_messages: ['09:14', '09:18', '09:24']
participants: ['@allie', '@bob']
tags: [reference-genome, chrm, dcis]
---

# GRCh38.p14 fixes the chrM contig issue

The chrM artefact we hit in February with GRCh38.p13 is patched in
p14. For run 17 we are aligning against p14, not p13.

## Provenance

[[slack/proj_dcis_sc_tutorial/2026-05-08]] — messages at 09:14, 09:18, 09:24.
```

Linking the raw mirror as `[[slack/...]]` means the dashboard can
surface citations and the Obsidian vault can navigate to them.

## Cadence (nightly cron)

A scheduled job runs at **02:00 local time** on the lab VM (or
wherever the Murmurent server runs):

1. For each `[oracle:on]` channel:
   1. Pull yesterday's messages via the Slack web API.
   2. Write the raw mirror to `slack/<channel>/<yesterday>.md`.
2. For each new raw mirror file:
   1. Oracle agent reads it with the distillation prompt below.
   2. If the day produced nothing oracle-worthy, write an empty
      `oracle/<yesterday>_<channel>_no-summary.flag` (so we can tell
      "skipped" vs "missed") and continue.
   3. Otherwise, write `oracle/<yesterday>_<channel>_<topic-slug>.md`.
3. Commit + push lab-mgmt with message
   `"slack: distill <yesterday> for <N> channels"`.
4. Append one row per distilled entry to the audit chain
   (`<lab-mgmt>/audit/<today>.jsonl`).

Weekly job at **Sunday 03:00**: meta-summary across the week's
oracle entries → `oracle/<week>_weekly_digest.md`. PI gets pinged in
`#general` once weekly with a link to the digest (the only outbound
posting in the one-way phase).

### Distillation prompt (template)

```
You are summarising one day of Slack activity in the
[CHANNEL] channel for the [PROJECT] project.

Goal: extract NEW knowledge, decisions, open questions. Skip
chitchat, scheduling, code-paste-without-context.

For each oracle-worthy item:
  1. ONE-line title (under 80 chars)
  2. 2-4 paragraph summary in the lab's voice
  3. Cite the message timestamps you drew from
  4. Tag with relevant keywords from the lab vocabulary

If the day had nothing worth promoting, return exactly:
  NO_ORACLE_ENTRIES_TODAY

Otherwise return one frontmatter+body block per item, in the
oracle file schema described in slack_integration.md.
```

## Privacy + governance

- **Opt-in via channel topic flag** (resolved). New channels are
  monitored only after their topic includes `[oracle:on]`.
- **Visibility of mirrors:** lab-mgmt is private; only group members
  with read access to the repo see Slack mirrors. This matches Slack's
  own visibility (channel members ↔ workspace members).
- **DMs and private channels not invited to the bot:** never touched.
- **Edit/delete of raw mirrors** is allowed via PR (e.g. someone
  posts a personal anecdote and asks to redact). The git history
  remains; PR review is the audit trail.
- **Right to be forgotten:** if a member leaves the lab and asks for
  their messages to be redacted from mirrors, the lab admin runs
  `murmurent slack redact --member @<handle>` (not yet built; tracked).
- **Distillation review window:** for the first month, all oracle
  entries from the bot land with `status: draft` and only show in
  the dashboard once the PI confirms via `murmurent oracle approve`.
  After we trust the distillation, we drop the gate.

## Implementation order

The cron + raw mirror is the simpler half; the distillation is the
agentic half. Build in this order:

1. **`murmurent slack mirror --channel <name> --date <yyyy-mm-dd>`** —
   manual one-shot fetch of one channel/day. Validates the Slack
   adapter, the Markdown serialisation, and the lab-mgmt write path.
2. **`murmurent slack mirror --all --since <date>`** — bulk fetch.
   Hardens pagination and error handling.
3. **Cron entry** — nightly + weekly. Uses `cron` or `launchd` agent;
   `crontab -e` line plus a `launchd` plist for macOS.
4. **`murmurent slack distil --channel <name> --date <yyyy-mm-dd>`** —
   manual distillation of one mirror file. PI validates output by
   eye against the prompt.
5. **Distillation in the cron**, with the `status: draft` gate.
6. **Approval flow** + `murmurent oracle approve` command.
7. **Drop the gate** once the PI is happy with the distillations.
8. **Weekly digest** + the single outbound `chat:write` post.

Each step is independently shippable. Tests at every step assert
shape of the markdown output against fixture conversations.

## What's left to decide before I write code

These are the questions I'd want answered as a PR comment on this doc:

1. Which channels to monitor first? `#proj_dcis_sc_tutorial` only as
   a pilot, or all current project channels at once?
2. Where does the bot's OAuth token live? Slack app config has it; we
   need to store it locally for the cron to read. Default proposal:
   `~/.config/murmurent/slack-token` (mode 0600), with a fallback to
   `$MURMURENT_SLACK_TOKEN` env var for ephemeral use.
3. Distillation timing: 02:00 local seems right for North America.
   If the lab has trans-Atlantic collaborators (Barbados meetings?),
   should it be 06:00 UTC instead?
4. Approval flow UI: dashboard panel, CLI, or both? My instinct is
   both — `murmurent oracle approve` for terminals, plus an "Approve /
   Decline" pair on draft entries in the Group Oracle panel.
