# Headline-first protocol

Every murmurent agent — main and subagent — must begin its final response
to the user with a **single line of ≤200 characters** that summarises
the outcome in the agent's own voice. Detail (tables, per-finding
breakdowns, code listings) follows after one blank line.

## Why

The murmurent VSCode workflow shows live subagent activity in the BR
(bottom-right) pane via `tail -F ~/.murmurent/agents.log`. The hook
handler ([scripts/murmurent_log_agent_event.sh](../scripts/murmurent_log_agent_event.sh))
captures each subagent's `last_assistant_message` on `SubagentStop`,
strips newlines, and truncates to 200 chars. Whatever sits in the
first 200 chars of your reply is the *only* thing the user sees in
the dashboard.

If you bury the verdict in paragraph three, the BR pane shows three
sentences of throat-clearing and the user has to re-read your full
reply to find the conclusion. If you lead with the verdict, the
dashboard becomes useful.

## Format

The headline should answer one question: **what's the punchline?**
Use the categorical verb that matches your agent's standard verdict
vocabulary:

| Agent | Lead with |
|---|---|
| `security_guard` | `Clear / Concerns / Blocked — <one-line why>` |
| `adversary` | `Pass / Questions / Reject — <one-line why>` |
| `oracle` | `Found / Not found / Unsure — <one-line what>` |
| `lab_oracle` | `Found / Not found / Unsure — <one-line what, naming the publisher>` |
| `bookworm` | `Found N sources — <one-line summary>` |
| `blacksmith` | `Done / Failed / Partial — <one-line what>` |
| `artist` | `Rendered / Skipped / Failed — <one-line what>` |
| `conscience` | `OK / Flagged — <one-line concern>` |
| `scribe` | `Revised / Drafted / Gap — <one-line on what was written or what is missing>` |
| `lawyer` | `Clear / Conflict / Unknown — <one-line on patent landscape>` |
| `millwright` | `Provisioned / Skipped / Failed — <one-line on what>` |
| `centre_millwright` | `Reconciled / Drift / BLOCKED — <one-line on what changed or what is blocking>` |
| `registrar` | `Recorded / Conflict / Skipped — <one-line on what>` |
| `judge` | `Presented / Split / Insufficient — <one-line on the combined result>` |
| `docent` | `Located / Absent / Incomplete — <one-line: where in the work, what it lacks, or what the package is missing>` |
| `clerk` | `Correct / Fix / Unknown — <one-line: what the pack confirms, what to change, or what it does not hold>` |
| `teacher` | `Explained / Gap — <one-line on what was/wasn't understood>` |

Then a blank line. Then the detail. Example:

```
Clear — no world-writable or sensitive-readable files in scope.

**Security Guard Audit — /Users/mth/repos/murmurent**
1. World-writable files: none found.
2. World-readable sensitive matches: none found.
3. World-executable shell scripts in scripts/: 7 (all intentional).

Verdict: CLEAR
```

## Adding an agent

**This table must list every agent in [`agents/`](../agents/).** It went two
agents out of date (`centre_millwright`, `lab_oracle`) because nothing tied the
two together: both agents declared their verdicts in their own files, so
nothing was broken and nothing complained. If you add an agent, add its row
here in the same commit, and take the vocabulary from the agent's own
`MANDATORY OUTPUT RULE` line rather than inventing one that looks plausible.

## The spoken line

When spoken verdicts are on (see `docs/vscode-workflow.md`), the hook reads a
verdict aloud. A headline is written for a pane and is full of names, numbers
and shorthand that make no sense to the ear, so every agent adds a **second
line beginning `Aloud:`**, right after the headline and before the blank line:

```
Pass — folds are clean; AUC 0.81 holds under leave-one-site-out.
Aloud: The model holds up. I re-ran it leaving each hospital out in turn and the accuracy barely moved, so the result is not carried by one site.

**Adversary audit — ...**
```

The spoken line is plain English a colleague from another field could follow,
at most 100 words, saying what was found and what it means. No web addresses,
file paths, identifiers, code or markdown: it is heard, not read. The hook
speaks that line when it is there and falls back to the headline when it is
not; the log pane still shows only the headline.

**Language.** The spoken line is in English unless the machine has chosen a
language (`murmurent config speak-language fr_FR`, say). Then a hook tells
each subagent, before its first prompt, to write the `Aloud:` line in that
language, and the hook reads it with a voice for that language; the headline
and the detail stay as they are. An agent with no such note in its context
writes English. The choices and how the voices are installed:
`docs/vscode-workflow.md`, "Spoken verdicts".

## When in doubt

If your output is a single short sentence anyway (e.g. answering a
trivial factual question), that sentence IS the headline — no extra
formatting needed. The rule only kicks in when you have structured
output to deliver.
