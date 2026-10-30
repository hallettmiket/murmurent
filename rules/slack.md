# Slack posting rules

## After every `git push`

Post a short note about the push: repository name, branch, commit hash, commit
message, and a one-line summary of what changed. **One command decides where
it goes and posts it:**

```bash
murmurent project note "<repo> · <branch> · <hash>: <commit title>. <one line on what changed>"
```

Run it from inside the repository you pushed. It resolves the channel the way
murmurent does everywhere (see `docs/slack_routing.md`):

1. a `slack_channel` set in the repository's `.murmurent.yaml`, if any;
2. else the channel of the **project** whose record lists this repository;
3. else the **lab's** channel from the registry;
4. else nothing: it prints why, and the note is not posted anywhere.

It uses the right bot for that channel (the project's workspace, else the
lab's). Read what it prints and report it, for example
"Slack: posted to the channel of project 'param_complexity'" or
"Slack: not posted: project 'bioinfo' has no Slack channel yet".

Check first with `murmurent project note --dry-run ""` if you want to see the
destination without posting.

## What never to do

- **Never pick a channel yourself.** Do not post to a channel id from memory,
  from another rule, from a search of the workspace, or from a previous
  session. A note that cannot be routed is not posted; say so instead.
- **Never fall back to a shared or development channel** because the project
  has none. Tell the user: the PI runs
  `murmurent project provision-slack <project>`.
- **Never use the `mcp__claude_ai_Slack__*` or `mcp__slack__*` tools** for these
  notes. They post as other bots that are not members of the project channels,
  and they let a session choose the channel, which is the mistake this rule
  exists to prevent.
- If the command says the repository is **listed by two projects**, post
  nothing and tell the user which two; the records need fixing
  (`murmurent project channels` shows every such case).

**Which workspace and which bot are deployment facts, not murmurent facts.** A
centre records its own in `rules/local/`, which is not part of the public
release. Never hardcode a channel ID, workspace slug or bot user into a shared
rule: the next centre to install murmurent inherits it.
