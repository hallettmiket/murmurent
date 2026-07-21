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
| `bookworm` | `Found N sources — <one-line summary>` |
| `blacksmith` | `Done / Failed / Partial — <one-line what>` |
| `artist` | `Rendered / Skipped / Failed — <one-line what>` |
| `conscience` | `OK / Flagged — <one-line concern>` |
| `lawyer` | `Clear / Conflict / Unknown — <one-line on patent landscape>` |
| `cable_guy` | `Provisioned / Skipped / Failed — <one-line on what>` |
| `receptionist` | `Routed / Held / Bounced — <one-line on who/why>` |
| `registrar` | `Recorded / Conflict / Skipped — <one-line on what>` |
| `judge` | `Presented / Split / Insufficient — <one-line on the combined result>` |

Then a blank line. Then the detail. Example:

```
Clear — no world-writable or sensitive-readable files in scope.

**Security Guard Audit — /Users/mth/repos/murmurent**
1. World-writable files: none found.
2. World-readable sensitive matches: none found.
3. World-executable shell scripts in scripts/: 7 (all intentional).

Verdict: CLEAR
```

## When in doubt

If your output is a single short sentence anyway (e.g. answering a
trivial factual question), that sentence IS the headline — no extra
formatting needed. The rule only kicks in when you have structured
output to deliver.
