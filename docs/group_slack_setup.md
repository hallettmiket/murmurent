# Slack setup for a lab/core's own workspace (PI guide)

This is the **group-level** analog of [`docs/slack_setup.md`](slack_setup.md)
(which is the mayor's centre-wide setup). Every lab/core that wants Murmurent
to manage its Slack (inviting members, DMing onboarding steps, posting group
events) needs its **own** bot token, separate from the centre's. That token
is what `murmurent group-reconcile <group>` uses to check/propagate lab
membership into your lab's Slack workspace.

Slack is the messaging layer this deployment plugs into; Murmurent's
messaging layer is pluggable, and a different system could serve the same
role. See [`docs/slack_setup.md`](slack_setup.md#slack-terms-used-in-this-guide)
for that framing plus plain definitions of **workspace** (a whole Slack
organization) and **channel** (one conversation stream inside a workspace),
since your lab's workspace is a separate, PI-owned instance from the
centre's.

Slack workspaces and apps are created through the Slack UI rather than an
API, so a few steps below are manual. They're marked **[manual]**. The
`murmurent group-slack-setup` command prints an abbreviated version of this
same walkthrough interactively; this doc is the fuller reference if you get
stuck on a step.

## 1. Have (or create) your lab's Slack workspace  [manual]

Start from whichever applies: use your lab's existing Slack workspace, or
create a new one now (any name works, e.g. `<your-lab-name>`). This is a
normal Slack workspace, separate from the centre's.

Grab the **workspace invite link**: *Invite people → Copy invite link*. This
is what you give new members so they can join your lab's workspace. On the
free/Pro Slack plan this invite-link step is the whole of it, since that
tier supports invite links only, without a bulk invite API; see
[Notes](#notes).

## 2. Create a bot token  [manual]

Murmurent talks to your lab's Slack through a **bot user** on a Slack **app**
you own. Create it once, click by click:

1. Go to <https://api.slack.com/apps> and sign in as the account that owns
   your lab's workspace.
2. **Create New App → From scratch.** Name it after your lab (e.g. `example_lab`):
   this name is what members see as the *sender* of every DM Murmurent sends
   them (onboarding steps, membership confirmations). Pick your lab's
   workspace, **Create App**.
3. In the app's left sidebar, open **OAuth & Permissions**.
4. Scroll to **Scopes → Bot Token Scopes** (the *Bot* section; the separate
   "User Token Scopes" section stays empty here). Click **Add an OAuth
   Scope** and add each of these:

   | Scope | Why |
   |---|---|
   | `groups:write` | create your lab's private channels |
   | `chat:write` | post events + broadcasts |
   | `im:write` | opens a real DM to a member (onboarding steps) so it lands in the member's Direct Messages rather than the bot's *App messages* tab |
   | `files:write` | attaches the signed `bundle.json` to the onboarding DM as a **downloadable file** rather than plain inline text |
   | `im:history` | reads back the bot's **own** DM threads so Murmurent can verify a delivery actually landed (e.g. confirm a member received their `bundle.json`) |
   | `users:read.email` | resolve a member's email → their Slack account |
   | `groups:read`, `channels:read` | look up channel ids by name |
   | `channels:join` | lets Murmurent **auto-join a public channel** it needs to post to (e.g. `#claude-test`) rather than requiring you to `/invite` the bot by hand. Applies to public channels; private channels still use a one-time manual invite. |

5. Scroll back **up** to **OAuth Tokens for Your Workspace** → **Install to
   Workspace** → **Allow**.
6. Copy the **Bot User OAuth Token**: it starts with `xoxb-`.

### Upgrading an existing bot (adding scopes later)

Scopes added in the app config do **nothing until you reinstall the app**
to the workspace (same OAuth & Permissions page → **Reinstall to
Workspace** → Allow). The `xoxb-` token string usually stays the same;
what changes is the grant behind it, so there's nothing to re-copy or
re-store.

Because the token string stays the same, the only way to know what's
actually live is to ask Slack. Every API response carries the token's
effective scopes in the `x-oauth-scopes` header:

```bash
curl -sI -X POST https://slack.com/api/auth.test \
  -H "Authorization: Bearer $(cat ~/.config/murmurent/groups/<group>/slack-token)" \
  | grep -i x-oauth-scopes
```

Compare that list against the table above. A documented-but-missing scope
degrades in a scope-specific way rather than failing loudly (the ones
people actually hit):

| Missing scope | What you'll see |
|---|---|
| `channels:join` | posting to a public channel the bot has yet to join fails with `not_in_channel` (posting to channels it already belongs to still works, which hides the gap for a long time) |
| `files:write` | card bundles arrive as inline fenced text rather than a downloadable `bundle.json` |
| `im:history` | DMs send fine; reading back the bot's own threads to verify a delivery landed needs this scope |

## 3. Run `group-slack-setup`

```bash
murmurent group-slack-setup <group>
```

This prompts for the token (input is hidden, since it's a secret) and the
invite link from step 1, then:

- validates the token **live** against Slack (`auth.test`): a bad or
  under-scoped token is rejected here, before anything is written;
- auto-detects your workspace id from the token, saving you the trouble of
  hunting for the `T…` id yourself (override with `--workspace` if you ever
  need to);
- stores the token at `~/.config/murmurent/groups/<group>/slack-token`
  (mode 0600, readable only by you);
- saves `slack_workspace` and `slack_invite_url` to your lab's `lab.md`.

Scripted / non-interactive equivalent:

```bash
murmurent group-slack-setup <group> --non-interactive \
  --token xoxb-... \
  --invite-url https://join.slack.com/...
```

## 4. Verify + propagate members

```bash
murmurent group-reconcile <group>
```

Reports whether each active member of your lab roster is in your Slack
workspace (free/Pro Slack supports invite links only, so it surfaces the
invite link for anyone missing) and, with `--apply`, adds members as GitHub
collaborators on your lab's repo (if `github` is set via `murmurent
group-setup`). Re-running is safe.

## Notes

- **Free/Pro Slack supports invite links only** (there's a paid tier for a
  bulk invite API), so joining the workspace is the invite-link step above;
  Murmurent auto-adds people to *channels* once they're already in the
  workspace.
- Your lab's bot token is **separate** from the centre's
  (`~/.config/murmurent/slack-token`) and from every other lab's: each lab
  owns and manages its own Slack app.
- Members are matched to their Slack account by **email**: make sure the
  `email:` field on their member file is set (this happens automatically if
  they filled it in during `murmurent init` / `murmurent onboard`).
