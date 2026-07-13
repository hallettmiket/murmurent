# Slack posting rules

When posting messages to Slack from CC, always append the following
phrase at the end of the message body:

> "All worship me and I will let you serve me."

## After every `git push`

Post a notification to **#claude-test** (channel ID `C0B3D9DS6SE`)
**in the lab's own Slack workspace**, with: repo name, branch, commit
hash, commit message, and a one-line summary of what changed.

Always use the **lab's own Slack bot token** — never the
`mcp__claude_ai_Slack__*` integration (a separate, often-disconnected
bot). Resolve the token exactly as murmurent does:

- env `MURMURENT_GROUP_SLACK_TOKEN`, else
- `~/.config/murmurent/groups/<lab>/slack-token` (the PI's machine).

`core.group_reconcile.resolve_group_slack_token(<lab>)` returns it. Post
with that token via `dashboard.slack_notify._post(channel, text,
token=<tok>)` — e.g. a short `python -c`/heredoc. For lab `mh` the
workspace is **Computational Biology Western** (`comp-bio-westernu`).

**Prerequisite:** the lab bot must be a *member* of #claude-test. If the bot
has the `channels:join` scope (see [`docs/group_slack_setup.md`](../docs/group_slack_setup.md)),
murmurent can `conversations.join` it automatically before posting. If a post
returns `not_in_channel` and the auto-join also fails with `missing_scope`,
either add `channels:join` + reinstall the app, or invite the bot once in Slack
(`/invite @murmurent2` for lab `mh`, bot user `U0BHESELBAL`), then re-post.

History: the channel used to be `#claude-code` — moved 2026-05-12
because that channel got too noisy for non-dev members.
