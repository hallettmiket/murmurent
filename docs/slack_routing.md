# Where a Slack message goes

Every message murmurent sends has one of five destinations. This page says
which, and what decides it. It was written after issue #243, when the notes of
a dozen projects were found in one channel: an always-loaded rule named a
single channel for every push, while the push skill and the push command each
resolved the project channel their own way. There is now one resolver,
`core/slack_routing.py`, and one command, `murmurent project note`, and the
rule tells sessions to use it.

## The five destinations

| Message | Goes to | Decided by |
|---|---|---|
| A note about a **repository** (a release note after a push, a job notice, a status update) | the project's channel, else the lab's channel, else nowhere | `slack_routing.resolve_route`: the repository's marker override, then the one project whose record lists the repository, then the lab in the registry |
| A **project event** (a SEA changing state, a project request, a member added to a project) | the project's channel; nowhere if the project has none | the project record's `slack_channel_id` |
| A **lab event** (server etiquette lines, a member leaving the group) | the lab's channel | the registry entry's `slack_channel_id` |
| A **centre notice** (a join request, a decision, a core booking) | the private mayor channel, else the deployment's configured default | `centre_init` profile `mayor_channel_id`, else `MURMURENT_SLACK_DEFAULT_CHANNEL` / `~/.config/murmurent/slack-default-channel` |
| A **broadcast** | the audience's channel (everyone, pis, leaders, admin) | `broadcast_channels` in the registrar profile |

A message with no destination is **not sent**. Nothing falls back to another
project's channel or to a development channel; the sender reports why.

## How a repository is routed

`murmurent project note "<text>"` from inside a repository, or
`murmurent project note --dry-run ""` to see the destination only:

1. **`slack_channel:` in the repository's `.murmurent.yaml`.** A deliberate
   per-repository override, recorded in the repository. Use it for a repository
   whose traffic should stay out of the project's channel, for example a
   development repository of a project whose channel the whole lab reads.
   It must be a channel id (`C…`), not a name.
2. **The project whose record lists the repository.** A repository listed by two
   active projects is ambiguous and gets no channel; `murmurent project
   channels` lists every such case. Fix the records rather than guessing:
   remove the repository from one project's record in the lab records
   repository (`cert_projects/<name>.md`, its `repos:` list).
3. **The project's channel**, `slack_channel_id` on its record, created by
   `murmurent project provision-slack <name>` (named `proj-<name>`).
4. **The lab's channel**, from the registry, when the repository is
   murmurent-ready but belongs to no project with a channel.
5. **Nowhere.** The command prints the reason and exits 1.

The bot is the one for that channel's workspace: the project's workspace for a
project channel (`cert_provision.resolve_project_slack`), else the lab's bot
(`group_reconcile.resolve_group_slack_token`). Sessions never post these notes
through the Slack MCP tools, which use other bot identities and let the session
choose the channel.

## Channels: creating, naming, archiving

| Action | Command | What it does |
|---|---|---|
| Create a project channel | `murmurent project provision-slack <name>` (PI) | Creates private `#proj-<name>`, reuses it if the name exists, stamps the id on the record, invites certified members |
| Rename | `murmurent project rename-slack <name> [--to <channel>]` (PI) | Renames to the convention or a chosen name |
| Archive | `murmurent project end <name>` → `cert_provision.teardown` | Archives the channel, drops GitHub collaborators; the record keeps the id |
| Audit | `murmurent project channels` | Every project: id, name, archived, bot membership; duplicate repository claims; projects with no channel |
| Lab channel | `murmurent group-reconcile <lab>` | Ensures `#lab-<group>` exists and its members are in it |

The channel name convention is `proj-<project>`, underscores kept
(`cert_provision.slack_channel_name`); the dashboard derives its links from the
same function.

## Membership

`murmurent project reconcile <name>` compares the channel's members with the
project's certified members and reports the drift; `--apply` invites the
missing and removes the extras. Three safeguards:

- A member is matched to a Slack account by the **roster's `slack:` member id
  first**, then by the roster email. Slack accounts are often registered under
  a different email from the institutional one, so an email-only match fails for
  most people.
- **Nobody is removed while any certified member is unresolved**: the unmatched
  member might be one of the "extras". The drift is still reported, with the
  handles to fix (add their Slack member id to `members/<handle>.md`).
- The **bot is never removed** from the channel it posts to (its id comes from
  `auth.test`).
- **An invite counts only when the member arrives.** After Slack accepts an
  invite, the channel is read again and each handle is reported as invited or
  as not in the channel, with the reason. The usual reason is a
  **single-channel guest**: Slack answers `ok` for one and adds nobody, because
  a single-channel guest can be in exactly one channel. A workspace admin has
  to make them a multi-channel guest, or a member, before the reconcile can add
  them. The same check runs in `murmurent project provision-slack`.

The lab channel's membership is kept by `murmurent group-reconcile`, and a
member leaving the group is removed from it by `murmurent group-remove-member`.
