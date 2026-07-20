# Slack setup for a Murmurent centre (mayor guide)

Murmurent treats messaging as a pluggable layer. This deployment plugs in
Slack because the lab and centre already communicate there day to day; a
different messaging system could fill the same role with an equivalent
integration. Slack is today's chosen fabric, kept in place because it works
and is already where people are.

Murmurent uses Slack as its communication fabric in this deployment: a
private **mayor↔CC channel** (`#murmurent-ops`) where the code posts events,
a private **channel per lab/core** (named after the group, members-only),
and **`#general`** for broadcasts. This guide is the one-time setup a
**mayor** does so those channels get created and populated automatically.

> Looking for a **lab/core's own** Slack workspace instead (the PI-level
> setup)? See [`docs/group_slack_setup.md`](group_slack_setup.md) and
> `murmurent group-slack-setup <group>`. This page is centre-wide only.

## Slack terms used in this guide

Two Slack concepts come up throughout this guide, worth defining plainly
since Slack experience varies across readers:

- **Workspace**: an organization's whole Slack instance, with its own
  members, apps, and billing. Murmurent involves two kinds of workspace: a
  **centre-level workspace** that the mayor runs (the subject of this
  guide), and each **lab/core's own, separate workspace** (see
  [`docs/group_slack_setup.md`](group_slack_setup.md)).
- **Channel**: a single conversation stream inside a workspace. Murmurent
  creates channels inside whichever workspace is relevant: generally one
  per lab/core, one per project, plus shared channels like `#general` and
  `#murmurent-ops`.

Slack workspaces are created through the Slack UI rather than an API, so a
few of the following steps are manual. They're marked **[manual]**.

## 1. Create the workspace  [manual]

In Slack, create a workspace named **`murmurent-<unique_name>`** (e.g.
`murmurent-bioconvergence`). Then:

- **Create a channel named exactly `#general`.** Newer Slack workspaces start
  with a different default channel, such as `#social` or a welcome channel,
  in place of `#general`, so plan on creating it yourself: *+ → Create a
  channel → name it `general` → Create*. Murmurent broadcasts to *everyone*
  through this channel, and `centre-slack-setup` looks it up by that exact
  name; if it's missing, `centre-slack-setup` reports `#general not found;
  create it in Slack`, and broadcasts to `everyone` have nowhere to land
  until the channel exists.
- Grab the **workspace invite link**: *Invite people → Copy invite link*. You'll
  give this to new members during onboarding.

## 2. Create a bot token  [manual]

Murmurent talks to Slack through a **bot user** on a Slack **app** you own. Create
it once, click by click:

1. Go to <https://api.slack.com/apps> and sign in as the account that owns your
   `murmurent-<name>` workspace.
2. **Create New App → From scratch.** Name it **`mayor`**, pick your
   `murmurent-<name>` workspace, **Create App**. Then open **App Home** (left
   sidebar) and set the bot's **Display Name** and **Default username** to
   `mayor`. This name is what PIs + members see as the *sender* of every DM
   Murmurent sends (onboarding steps, approvals), so messages consistently
   read as coming **from the mayor**. (Already have an app? Rename it here.)
3. In the app's left sidebar, open **OAuth & Permissions**.
4. Scroll to **Scopes → Bot Token Scopes** (the *Bot* section; the separate
   "User Token Scopes" section stays empty here). Click **Add an OAuth
   Scope** and add each of these:

   | Scope | Why |
   |---|---|
   | `groups:write` | create private channels (lab/core + `#murmurent-ops`) |
   | `channels:manage` | create public channels (if you use any) |
   | `chat:write` | post events + broadcasts |
   | `im:write` | opens a real DM to a member (onboarding + decision DMs) so it lands in the member's Direct Messages rather than the bot's *App messages* tab |
   | `files:write` | attaches signed bundles (e.g. `bundle.json`) to DMs as **downloadable files** rather than plain inline text |
   | `im:history` | reads back the bot's **own** DM threads so Murmurent can verify a delivery actually landed |
   | `users:read.email` | resolve a member's email → their Slack account |
   | `groups:read`, `channels:read` | look up channel ids by name (e.g. `#general`) |
   | `channels:join` | lets Murmurent **auto-join a public channel** it needs to post to (e.g. `#claude-test`) rather than requiring a manual `/invite` of the bot. Applies to public channels; private channels still use a one-time manual invite. |

5. Scroll back **up** to **OAuth Tokens for Your Workspace** → **Install to
   Workspace** → **Allow**.
6. Copy the **Bot User OAuth Token**: it starts with `xoxb-`.

   > **Adding scopes later?** They do nothing until you **Reinstall to
   > Workspace**; the `xoxb-` token string usually stays the same, so
   > verify what's actually live via the `x-oauth-scopes` response header
   > (`curl -sI -X POST https://slack.com/api/auth.test -H "Authorization:
   > Bearer $TOKEN" | grep -i x-oauth-scopes`) rather than trusting the app
   > config page. Missing scopes degrade quietly: e.g. lacking
   > `channels:join` surfaces only as `not_in_channel` on public channels
   > the bot has yet to join. See docs/group_slack_setup.md → "Upgrading an
   > existing bot" for the symptom table.
7. Back in Slack, invite the bot to `#general` so it can post there: in the
   `#general` channel, type `/invite @mayor` (the bot's name). The bot is
   auto-added to any private channel it *creates*, but must be invited to
   pre-existing channels like `#general`.

## 3. Give Murmurent the token

Either export it, or store it in the token file (mode 0600):

```bash
export MURMURENT_SLACK_TOKEN=xoxb-...
#   ...or, to persist it for the dashboard/server:
umask 077; printf '%s\n' 'xoxb-...' > ~/.config/murmurent/slack-token
```

`MURMURENT_SLACK_TOKEN` and the legacy `SLACK_BOT_TOKEN` both work.

## 4. Point the centre at the workspace

Set the workspace id + invite link on the centre (via `murmurent centre-init
--slack-workspace T… --slack-invite-url https://join…`, or the `/registrar`
profile editor for an existing centre: `slack_workspace` and `slack_invite_url`
in `centre.md`).

## 5. Verify + provision the centre channels

```bash
murmurent centre-slack-smoke     # confirms the bot token can create a channel
murmurent centre-slack-setup     # creates #murmurent-ops, wires #general + admin broadcasts
```

`centre-slack-setup` creates the private **mayor↔CC channel** (`#murmurent-ops`,
stored as `mayor_channel_id`) and seeds the broadcast map (`admin` → the mayor
channel, `everyone` → `#general`). Re-running is safe (idempotent).

## What happens automatically after this

- **New lab/core** (created via a join approval or the registrar): a private
  channel **named after the group** is created, the PI/leader is invited, and the
  channel id is stored on the group, as long as the token + `slack_workspace`
  are set.
- **Broadcasts**: `murmurent broadcast --audience everyone …` lands in `#general`;
  `--audience admin` reaches the mayor channel.
- **Join requests**: the mayor is notified in the `admin` (mayor) channel; the
  requester is DM'd (or the source GitHub issue is commented) on a decision.

## New members

Give a new member the **workspace invite link** (step 1). Once they've joined the
workspace and their **email is on their member file** (`email:` frontmatter), the
next provision/reconcile of their lab adds them to that lab's channel, and only
that lab's channel. Members with an email recorded on their member file resolve
to a Slack account automatically; anyone missing that field is reported as
`unresolved` until it's added.

## Notes

- **Free/Pro Slack limits invites to the invite-link step above** (joining
  a *channel* is automatic once someone is already in the workspace). Full
  workspace-invite automation needs a paid admin token.
- Channel names follow the group's own name normalized to Slack rules
  (lowercase, `[a-z0-9_-]`, ≤80): `example_lab` → `#example_lab`.
