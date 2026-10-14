---
name: murmurent-update-me
description: Post a plain-English status update for the current project to its Slack channel, saying what is running now, what finished since the last update, what is blocked and on whom, and the next steps. It gathers facts read-only (running analyses on every lab account, the agent log, output times, quality-gate results, git, GitHub progress issues), checks them against the project's state document if it has one, and trusts the facts where the two disagree. Use when a member types /murmurent-update-me, or asks for an update to post.
disable-model-invocation: true
argument-hint: "[dry-run]"
allowed-tools: Bash(nice -n 19 "$MPY" ${CLAUDE_SKILL_DIR}/gather_facts.py*), Bash(nice -n 19 python3 ${CLAUDE_SKILL_DIR}/gather_facts.py*)
---

# /murmurent-update-me: a status update for the project's channel

Mike Hallett asked for this on 2026-09-30, for the survival project: "a simple to
understand explanation of the current state of all builds and computation in the
project. It should post this summary to the slack channel. It should point out if there
are issues that are blocking progress and what needs to be done to resolve them." It was
built and used there, then made available to every project (issue #152).

It exists because status reports went wrong three ways on 2026-09-30: a process check
missed an R job launched through `conda run` and a duplicate run was started; the state
document said a build was running when nothing had run for two and a half hours; and clock
times were estimated instead of read. So the facts come from a script, and **where the
state document and the facts disagree, the facts win and the summary says so.**

Run it from inside the project's repository: the project is the one the session is open
in. If the arguments (`$ARGUMENTS`) say `dry-run`, do steps 1 to 5 and stop: show the
text, post nothing.

## Project settings

Everything has a default, so a project with no settings still gets an update. To change
one, add an `update_me:` block to the repository's `.murmurent.yaml`. Every key is
optional:

```yaml
update_me:
  channel: C0123ABCDEF          # Slack channel ID. Default: the project's own channel in its record
  channel_name: "#proj-x"       # for messages only
  outputs: /data/lab_vm/append_only/x   # Default: <data root>/append_only/<project>
  github: owner/x               # Default: the GitHub repository behind `origin`
  progress_label: progress      # GitHub label of the issues that track progress
  other_repos: [x_manuscript]   # Default: <project>_manuscript, if it sits beside this one
  state_document: state_of_the_project.md   # Optional. Default: that file, if it exists
  lab_group: my-unix-group      # whose accounts' jobs count. Default: your main Unix group
  process_markers: ["/envs/x/"] # extra text that marks a running job as this project's
  people: {jsmith: Jane Smith}  # names for accounts and GitHub logins
  gates:                        # quality-gate result files to report, newest first
    - {label: "phase 1, Gate D", folder: 01_models/gate_d, prefix: gate_d_result_, experiment: exp/01_models}
  allow_small_counts: true      # ONLY for a project with no data about people (see below)
```

The project's name comes from `update_me.project`, else the choreography's `name`, else
the folder's name. The lab whose Slack bot posts comes from the marker's `lab`.

## What this skill never does

- It does not edit any project file (including the state document), commit, push, or
  start or stop any job or agent.
- It reads no file contents from the data tree, apart from the verdict line and the
  assertion-count line of each quality gate's newest result, and never enters a
  `publication/` folder.

## Governance: binding on every line posted

Slack text is easy to copy and quote, so the summary carries **paths and times only**:

- no participant-level data, no cohort tables, and **no count under six** of people,
  events or anything else about a cohort (write "fewer than six", or leave it out);
- no model coefficients, hazard ratios, C-indices or other results;
- nothing from any `publication/` folder, and no file contents from the data tree;
- no token or credential, ever.

Counts of files, assertions, workers or comments are not cohort data and may be given.
The posting script refuses a message with a token-shaped string, a `publication/` path, a
number from 0 to 5 followed by people, patients, events and similar words, or an em dash.
It cannot catch everything, so these rules bind you, not only the script. The small-count
check is on for every project unless `allow_small_counts: true` is set, which is only for
a project that holds no data about people. It is on by default because a folder's
`sensitivity` field is not always filled in, even for governed data.

## Steps

### 1. Gather the facts

Use murmurent's own Python, which can read `.murmurent.yaml`:

```bash
MPY="$HOME/.local/share/uv/tools/murmurent/bin/python3"
[ -x "$MPY" ] || MPY="$(head -1 "$(command -v murmurent)" | sed 's/^#!//')"
nice -n 19 "$MPY" ${CLAUDE_SKILL_DIR}/gather_facts.py
```

If the output starts with a NOTE that the settings were ignored, the wrong Python ran it:
fix that before going on, or the update describes the wrong folders.

It takes a few seconds (it runs `git fetch` in the project's repositories first; add
`--no-fetch` to skip that). Read all of it. Add `--json` for every unreadable path, or
`--since "YYYY-MM-DD HH:MM"` to set where "since the last update" starts. By default that
is this account's last update for **this project**, or midnight if there has been none.

What each section is, and its limits:

- **Clock**: from `date`. Use this time in the summary. Never estimate a time.
- **Running now**: this project's R and Python scripts, tests and web apps, on every
  account in the lab group, on this server only. Forked workers are folded into their main
  job. A WARNING line means the same script is running twice at once: say so first, since
  that is how a duplicate run looks. A note about a web app means an open app is showing
  old code until it is restarted.
- **Agents**: from this account's `~/.murmurent/agents.log`. "Stopped" is certain; "may
  still be running" is not, and only its report file proves it finished. A background
  agent stops, without notice, when the session that started it closes. Agents started
  from another member's account are not visible, and the output says whose.
  The log has no task number, and several agents of one type often run at once. So a
  finish line is paired with a start only when its text uses words of exactly one open
  task of that type, and only with a start from the 24 hours before it. Otherwise the
  output says **"finish line not matched"** and lists the candidates, each shown as "It
  may have finished". Do not pick one yourself: say in the summary that it may have
  finished, or check its report file in the output tree. "Resumed" means a finish line
  that names a task whose finish was already logged.
- **Newest outputs**: per folder of the project's outputs folder, the newest file, its
  time and owner, and how many files changed in the window. A NOTE means the project has
  no outputs folder there.
- **Gates**: the newest result of each quality gate set in `update_me.gates`. None if
  none are set.
- **Git**: each of the project's repositories, after a fetch: ahead or behind GitHub,
  uncommitted files, and today's commits with their authors.
- **Issues**: open issues with the progress label on the project's GitHub repository,
  with the time and author of each one's last comment, and any closed in the window.
- **Cannot open**: items in the output tree this account cannot open.

A line starting NOTE is information about the project's setup, not a failure. Do not
report it in the summary unless it explains something missing.

### 2. Compare with the state document, if there is one

If the facts show a state document, read the sections the facts point to (they give line
numbers and the command). When this clone is behind GitHub, they point at GitHub's copy,
which is newer. Check, item by item:

- everything the document calls running or in flight: is it in **Running now**, or does
  an agent show "may still be running"? If not, it is not running.
- every gate result, commit and "uncommitted" claim against the facts;
- every "waiting on" item: has that person commented on the issue since the document's
  "Last updated" time? If so, write "may be answered; see #n", not "waiting".

The document is the source for **who** a blocked item waits on and **why**. The facts are
the source for what is running, what finished, times, and git state. Where they disagree,
use the facts and add one short clause, for example: "(The state document says the
phase 2 rerun is in flight; nothing from phase 2 is running.)"

Without a state document, take blocked items and who they wait on from the open progress
issues only, and say nothing you cannot back with a fact.

### 3. Write the summary

Follow the voice of murmurent's `output_styles/plain_english.md`. In short:

- **No em dashes.** Use a comma, a colon, brackets or two sentences.
- **Answer first.** The headline line says the most useful thing, such as the one blocker
  that matters most.
- **Every technical term defined or removed.** Say "phase 2's automatic checks (Gate D2)"
  rather than "Gate D2", "saved to GitHub" rather than "pushed", "an AI helper (the
  adversary)" on first mention of an agent, "the project's web app" rather than
  "Streamlit".
- One idea per sentence; ordinary words; people by name; issue numbers as #n.
- No personification of software, no enthusiasm, no apology.

Fixed shape, **about 25 lines at most**, in Slack formatting (`*bold*`, `-` bullets):

```
*<Project> update, <weekday> <date>, <HH:MM>*: <one-line headline>

*Running now*
- <what, whose, since when, and when it should finish if a known duration exists>
*Finished since the last update* (since <time>)
- <what finished, where to find it, issue #n>
*Blocked*
- <what is blocked>: waits on <person or body>. To unblock: <the one thing that would do it>. (#n)
*Next steps*
1. <in order, each with who does it>
```

Put nothing in a section you cannot back with a fact or the document. If a section is
empty, write "Nothing." Items waiting on outside bodies (an ethics board, a data
custodian) go under **Blocked** only when they block something being attempted now.

### 4. Save the text

Write it to a new file in your scratchpad folder, or `mktemp --suffix=_update_me.txt` if
you have none. Never inside the repository or the data tree.

### 5. Dry run

```bash
"$MPY" ${CLAUDE_SKILL_DIR}/post_summary.py <summary file> --dry-run
```

Run it from inside the repository. It prints the message exactly as it would be posted,
the channel it would go to, and whether every rule passed and whether a token was found
(never showing it). If a rule is broken, fix the text and run the dry run again. If no
channel is known, say so and show where to set it (`update_me.channel`). If the arguments
said `dry-run`, show the text and stop.

### 6. Post

```bash
"$MPY" ${CLAUDE_SKILL_DIR}/post_summary.py <summary file>
```

This posts to the project's channel with the lab's own bot, as murmurent's
`rules/slack.md` says. If it fails it prints why in one sentence and exits non-zero
(1: no channel known; 3: murmurent missing; 4: no usable token, or no lab set; 5: Slack
refused). On a member's account other than the PI's the token may be missing or a
placeholder: say so, and show the text so they can paste it into the channel or ask the
PI. Never type, search for or print a token.

### 7. Show it in chat

Show the posted text in chat exactly as the script printed it. Below it, in two or three
lines: each place the state document disagreed with the facts, and an offer to correct
the state document as a separate step (this skill does not edit it).

## Checking the skill itself

After changing `gather_facts.py`, run its tests (standard library only, under a second):

```bash
python3 -B ${CLAUDE_SKILL_DIR}/test_gather_facts.py
```

They cover how agent start and finish lines are paired, including several agents of one
type running at once.
