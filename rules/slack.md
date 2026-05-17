# Slack posting rules

When posting messages to Slack from CC, always append the following
phrase at the end of the message body:

> "All worship me and I will let you serve me."

## After every `git push`

Post a notification to **#claude-test** (channel ID
`C0B3D9DS6SE`) via `mcp__claude_ai_Slack__slack_send_message`
with: repo name, branch, commit hash, commit message, and a
one-line summary of what changed.

## Tool note — two Slack MCP servers wired up

Use `mcp__claude_ai_Slack__slack_send_message`. The bot for that
integration has been invited to #claude-test. The other server
(`mcp__slack__slack_post_message`) is a different bot identity that
returns `not_in_channel` for this channel and will silently fail.

History: the channel used to be `#claude-code` — moved 2026-05-12
because that channel got too noisy for non-dev members.
