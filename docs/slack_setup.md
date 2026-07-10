# Slack setup for a murmurent centre (mayor guide)

Murmurent uses Slack as its primary communication fabric: a private **mayor↔CC
channel** (`#wigamig-ops`) where the code posts events, a private **channel per
lab/core** (named after the group, members-only), and **`#general`** for
broadcasts. This guide is the one-time setup a **mayor** does so those channels
get created and populated automatically.

Slack workspaces can't be created by API, so a few steps are manual — they're
marked **[manual]**.

## 1. Create the workspace  [manual]

In Slack, create a workspace named **`wigamig-<unique_name>`** (e.g.
`wigamig-bioconvergence`). Then:

- **Create a channel named exactly `#general`.** Newer Slack workspaces **no
  longer ship with a `#general`** (you may see `#social` or a welcome channel
  instead) — so you almost certainly have to create it yourself: *+ → Create a
  channel → name it `general` → Create*. murmurent broadcasts to *everyone* through
  this channel, and `centre-slack-setup` looks it up by that exact name; if it's
  missing you'll get a `#general not found; create it in Slack` warning and
  broadcasts to `everyone` won't have a target.
- Grab the **workspace invite link**: *Invite people → Copy invite link*. You'll
  give this to new members during onboarding.

## 2. Create a bot token  [manual]

murmurent talks to Slack through a **bot user** on a Slack **app** you own. Create
it once — click by click:

1. Go to <https://api.slack.com/apps> and sign in as the account that owns your
   `wigamig-<name>` workspace.
2. **Create New App → From scratch.** Name it **`mayor`**, pick your
   `wigamig-<name>` workspace, **Create App**. Then open **App Home** (left
   sidebar) and set the bot's **Display Name** and **Default username** to
   `mayor`. This name is what PIs + members see as the *sender* of every DM
   murmurent sends (onboarding steps, approvals) — so messages read as coming
   **from the mayor**, not a generic bot. (Already have an app? Rename it here.)
3. In the app's left sidebar, open **OAuth & Permissions**.
4. Scroll to **Scopes → Bot Token Scopes** (the *Bot* section, **not** "User
   Token Scopes"). Click **Add an OAuth Scope** and add each of these:

   | Scope | Why |
   |---|---|
   | `groups:write` | create private channels (lab/core + `#wigamig-ops`) |
   | `channels:manage` | create public channels (if you use any) |
   | `chat:write` | post events + broadcasts |
   | `im:write` | open a real DM to a member (onboarding + decision DMs); without it, DMs land in the bot's *App messages* tab, not the member's Direct Messages |
   | `users:read.email` | resolve a member's email → their Slack account |
   | `groups:read`, `channels:read` | look up channel ids by name (e.g. `#general`) |

5. Scroll back **up** to **OAuth Tokens for Your Workspace** → **Install to
   Workspace** → **Allow**.
6. Copy the **Bot User OAuth Token** — it starts with `xoxb-`.
7. Back in Slack, invite the bot to `#general` so it can post there: in the
   `#general` channel, type `/invite @murmurent` (the bot's name). The bot is
   auto-added to any private channel it *creates*, but must be invited to
   pre-existing channels like `#general`.

## 3. Give murmurent the token

Either export it, or store it in the token file (mode 0600):

```bash
export WIGAMIG_SLACK_TOKEN=xoxb-...
#   ...or, to persist it for the dashboard/server:
umask 077; printf '%s\n' 'xoxb-...' > ~/.config/wigamig/slack-token
```

`WIGAMIG_SLACK_TOKEN` and the legacy `SLACK_BOT_TOKEN` both work.

## 4. Point the centre at the workspace

Set the workspace id + invite link on the centre (via `murmurent centre-init
--slack-workspace T… --slack-invite-url https://join…`, or the `/registrar`
profile editor for an existing centre — `slack_workspace` and `slack_invite_url`
in `centre.md`).

## 5. Verify + provision the centre channels

```bash
murmurent centre-slack-smoke     # confirms the bot token can create a channel
murmurent centre-slack-setup     # creates #wigamig-ops, wires #general + admin broadcasts
```

`centre-slack-setup` creates the private **mayor↔CC channel** (`#wigamig-ops`,
stored as `mayor_channel_id`) and seeds the broadcast map (`admin` → the mayor
channel, `everyone` → `#general`). Re-running is safe (idempotent).

## What happens automatically after this

- **New lab/core** (created via a join approval or the registrar): a private
  channel **named after the group** is created, the PI/leader is invited, and the
  channel id is stored on the group — as long as the token + `slack_workspace`
  are set.
- **Broadcasts**: `murmurent broadcast --audience everyone …` lands in `#general`;
  `--audience admin` reaches the mayor channel.
- **Join requests**: the mayor is notified in the `admin` (mayor) channel; the
  requester is DM'd (or the source GitHub issue is commented) on a decision.

## New members

Give a new member the **workspace invite link** (step 1). Once they've joined the
workspace and their **email is on their member file** (`email:` frontmatter), the
next provision/reconcile of their lab adds them to that lab's channel — and only
that lab's channel. Members without an email on file can't be resolved to a Slack
account and are reported as `unresolved` until one is recorded.

## Notes

- **Free/Pro Slack has no user-invite API**, so joining the workspace is the
  invite-link step above; murmurent auto-adds people to *channels* once they're in
  the workspace. Full workspace-invite automation needs a paid admin token.
- Channel names follow the group's own name normalized to Slack rules
  (lowercase, `[a-z0-9_-]`, ≤80): `lab_mh` → `#lab_mh`.
