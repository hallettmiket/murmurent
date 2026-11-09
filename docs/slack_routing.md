# Where a Slack message goes

Every message murmurent sends has one of five destinations. This page says
which, and what decides it. It was written after issue #243, when the notes of
a dozen projects were found in one channel: an always-loaded rule named a
single channel for every push, while the push skill and the push command each
resolved the project channel their own way. There is now one resolver,
`core/slack_routing.py`, and one command, `murmurent project note`, and the
rule tells sessions to use it. `murmurent project push` posts its backup note
through the same resolver, by project name.

## The five destinations

| Message | Goes to | Decided by |
|---|---|---|
| A note about a **repository** (a release note after a push, a job notice, a status update) | the channel of every project that lists the repository, else the lab's channel, else nowhere | `slack_routing.resolve_route`: the repository's marker override, then each active project whose record lists the repository, then the lab in the registry |
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
2. **Every active project whose record lists the repository.** A repository
   may be in several projects (#253); the note is then posted once to each
   project's channel, and the command reports each post. A listing project with
   no channel yet is skipped, with its reason, and `murmurent project channels`
   lists every repository in more than one project. If a project should not
   list the repository, `murmurent project release-repo <project> <repo>` takes
   it off that record (the clone on disk is untouched).
   The repository's name is its main copy's folder: a note sent from a git
   worktree (a second working copy, such as the ones the Desktop app makes
   under `.claude/worktrees/`) is routed the same way as one sent from the
   main copy (#250).
3. **The project's channel**, `slack_channel_id` on its record, created by
   `murmurent project provision-slack <name>` (named `proj-<name>`).
4. **The lab's channel**, from the registry, when the repository is
   murmurent-ready but belongs to no project with a channel.
5. **Nowhere.** The command prints the reason and exits 1.

A channel can be found and the note still not sent: the bot token for that
workspace is kept per machine (`~/.config/murmurent/groups/<lab>/slack-token`).
From a machine that has none, `murmurent project note` prints "no Slack bot
token on this machine" with the one command to run there: on the PI's machine
`murmurent group-slack-setup <lab>`, on a member's machine
`murmurent group-slack-unlock <lab>` (next section).

## How a member's machine gets the bot token

The PI's machine is the only one that is handed the lab's bot token, by
`murmurent group-slack-setup`. A certified member pushing from their own
machine used to be stuck at "no Slack bot token on this machine", with no
supported way past it but the PI copying the token to them by hand.

**The choice: the PI seals the token to each member's own key and commits it
to the lab records.** Every certified member's roster entry
(`members/<handle>.md`) already carries the public key their machine attested
when their card was issued, and the private half is on that machine
(`~/.murmurent/keys/id_ed25519`). So nothing new has to be installed, generated
or sent:

1. The PI runs `murmurent group-slack-share <lab>`. It encrypts the token so
   that any one of the active members' keys can open it (one slot per member,
   the envelope scheme `age` uses, done with the library murmurent already
   signs cards with), writes `security/slack_bot_token.sealed.json` in the
   records repository, commits and pushes. Members without an attested key are
   listed, not included.
2. The member pulls the lab records, which they clone anyway, and runs
   `murmurent group-slack-unlock <lab>` once. It opens the box with the
   machine's key and stores the token at the per-machine path above, mode
   0600. `murmurent project note` tries the same thing on its own when the
   machine has no token yet, so in the usual case the member runs nothing.
3. After adding a member, or rotating the token, the PI shares again.

**Revocation means rotation.** The box stays in git history, and a key that
could open it then can open it forever. When a member leaves the lab, the PI
rotates the token in Slack, runs `group-slack-setup` with the new one, and
shares again; the old box opens to a dead token.

**The alternative, not taken: a relay.** A service on the lab server could hold
the only copy of the token and accept notes signed with a member's card,
posting each as that member (`docs/slack_cc_integration.md`, "Model C"). It
keeps the token off every member's machine and makes attribution verifiable,
but it is a service to host, keep up and reach from every machine, and today
no lab has one. The sealed box costs a file in a repository members already
pull. The relay remains the design to move to if non-repudiation of who posted
a note ever matters more than the hosting.

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
