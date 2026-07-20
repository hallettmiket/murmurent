# Preparing GitHub

Murmurent stores almost everything it manages in git repositories on GitHub:
the shared code, your own notes, and, for members of a lab, the lab's
governance repository. This page prepares a new member to work with all three
before joining a group.

## Why Murmurent uses GitHub

Three kinds of repo matter to you:

- **The commons**, `hallettmiket/murmurent`: the shared code every Murmurent
  install runs on, agents, rules, hooks, MCP servers, the CLI, the dashboard.
  Public, and cloned by everyone.
- **Your personal vault**, `<you>/murmurent_vault`: a private repo on your
  own GitHub account that backs your notes (your Oracle entries, your daily
  lab notebook, your maps-legends). Murmurent creates this repo for you.
- **Your lab's governance repo**, `<org>/murmurent_lab_mgmt_<lab>`: a
  private repo the PI owns, holding the lab's roster, project registry, and
  shared findings. Members get read access to it.

GitHub is also the mechanism by which you are granted read access to a
repository owned by someone else, which is how you read your lab's governance
repository without owning it. See [`what_mm_creates.md`](what_mm_creates.md)
for the complete, authoritative list of everything Murmurent creates, on
GitHub and on your machine.

## Authenticate the GitHub CLI

Murmurent acts as you on GitHub through the `gh` command-line tool (the
official GitHub CLI), so every repo it creates or clones on your behalf
needs you logged in first. Run:

```bash
gh auth login
```

and answer the prompts:

```text
? What account do you want to log into?  GitHub.com
? What is your preferred protocol for Git operations?  HTTPS
? Authenticate Git with your GitHub credentials?  Yes
? How would you like to authenticate GitHub CLI?  Login with a web browser
! First copy your one-time code: XXXX-XXXX
  Press Enter to open github.com in your browser...
```

Confirm it worked:

```bash
gh auth status   # should show: Logged in to github.com as <your-username>
```

Do this before running `murmurent vault init`, before asking your PI to add
you to a lab repo, and before any command that talks to GitHub on your
behalf.

## For a member

Once `gh auth status` shows you logged in, two things get you fully set up:

1. **Your personal vault.** Run `murmurent vault init` to create and clone
   `murmurent_vault` on your own GitHub account. Full walkthrough (including
   how to adopt an existing Obsidian vault instead of starting fresh):
   [`vault-setup.md`](vault-setup.md).
2. **Your lab's governance repo.** Your PI (say, `@the_pi`) grants you
   read access to `murmurent_lab_mgmt_<lab>` on GitHub. Accept the
   invitation email, then clone it:

   ```bash
   git clone git@github.com:example_org/murmurent_lab_mgmt_example_lab.git \
     ~/repos/murmurent_lab_mgmt_example_lab
   ```

   Murmurent auto-discovers this clone and pins it the next time you load
   the dashboard, so no further configuration is needed. Details on what
   this repo contains: [`lab_mgmt.md`](lab_mgmt.md).

In summary, `gh auth login` together with being added by your PI covers
everything a member needs from GitHub; Murmurent handles cloning, pinning, and
syncing thereafter.

## For a PI

Standing up your lab's presence on GitHub is a one-time job, done after your
own `gh auth login`:

1. Scaffold the governance repo locally:

   ```bash
   murmurent pi-init example_lab
   ```

2. Create the matching private GitHub repo and push it:

   ```bash
   gh repo create example_org/murmurent_lab_mgmt_example_lab --private \
     --source ~/repos/murmurent_lab_mgmt_example_lab --remote origin --push
   ```

3. Grant members read access as they join (or backfill access for the
   whole roster at once):

   ```bash
   murmurent group-reconcile example_lab --apply
   ```

For the full sequence, including Slack setup and issuing member IDs, see
[`setup.md`](setup.md)'s "Setting up a lab (for PIs)" section and
[`lab_mgmt.md`](lab_mgmt.md) for what the governance repo holds and who
needs access to it.
