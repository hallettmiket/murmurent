# Slack posting rules

## After every `git push`

Post a notification to **the group's own Slack channel**, with: repo name,
branch, commit hash, commit message, and a one-line summary of what changed.

Always use the **group's own Slack bot token** — never the
`mcp__claude_ai_Slack__*` integration (a separate, often-disconnected bot).
Resolve the token exactly as murmurent does:

- env `MURMURENT_GROUP_SLACK_TOKEN`, else
- `~/.config/murmurent/groups/<group>/slack-token` (the PI's machine).

`core.group_reconcile.resolve_group_slack_token(<group>)` returns it. Post with
that token via `dashboard.slack_notify._post(channel, text, token=<tok>)` — a
short `python -c` or heredoc is enough.

**Prerequisite:** the group's bot must be a *member* of the channel. If the bot
has the `channels:join` scope (see
[`docs/group_slack_setup.md`](../docs/group_slack_setup.md)), murmurent can
`conversations.join` before posting. If a post returns `not_in_channel` and the
auto-join fails with `missing_scope`, either add `channels:join` and reinstall
the app, or invite the bot once in Slack, then re-post.

**Which channel, which workspace, and which bot are deployment facts, not
murmurent facts.** A centre records its own in `rules/local/`, which is not
part of the public release. Never hardcode a channel ID, workspace slug or bot
user into a shared rule: the next centre to install murmurent inherits it.
