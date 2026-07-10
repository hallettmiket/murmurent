# murmurent

Shared agentic-AI infrastructure for academic researchers, labs cores and research centers. 
It lets research groups work independently, pool agents and data when collaboration helps, and
accumulate institutional knowledge across every project. See
[`CLAUDE.md`](CLAUDE.md) for the architectural overview and [`docs/`](docs/) for
the full design.

Murmurent is **institution-agnostic** — not tied to any one university. A new
institution stands it up by having one person (the **mayor**) bootstrap a
*centre*; everyone else joins afterward.

## Download Murmurent

**Everyone — member, PI, or mayor — starts by installing murmurent.** The code is
public; one command does it (you only need `git`):

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/murmurent/main/scripts/bootstrap.sh | bash
```

Prefer to read the script first (recommended)? Clone it **wherever you like**,
then run it — it installs whatever clone you run it from:

```bash
git clone https://github.com/hallettmiket/murmurent
cd murmurent && ./scripts/bootstrap.sh
```

[`scripts/bootstrap.sh`](scripts/bootstrap.sh) is idempotent: it installs the
`murmurent` command, wires the shared agents/rules/skills into `~/.claude/`, and
registers the data-governance hooks. On your first run it mints your **identity
key** (your unique ID). Then set your personal info — `murmurent whoami` shows your
handle + key, and the dashboard (`murmurent dashboard --hifi`) has the rest.

Then find your situation below.

## I'm a member of a lab that already uses murmurent

You need a **membership ID** (a signed identity certificate) from your **PI**
before your dashboard recognises your role. There are two steps — you prove
you hold your key, your PI signs it — and Slack is how they travel between
you if your lab's Slack is connected:

1. **Request your ID.** Run this on your own machine (it proves you hold your
   local key — your PI can't skip this even if they already know who you are):
   ```bash
   murmurent enroll --group <your-lab> --out enroll.json
   ```
   This prints exactly what to do next: **send `enroll.json` to your PI —
   DM it to them directly on Slack** (you're already in their lab's
   workspace) if you can, otherwise email/paste it works too.
2. **Wait for your card.** Your PI runs `murmurent issue-member-card` against
   your request. If their lab's Slack is connected
   (`murmurent group-slack-setup`), murmurent **DMs the signed bundle straight
   back to you** — no action needed from your PI beyond running the one
   command. Otherwise they'll send you the bundle file by hand.
3. **Import it.** Save whatever you received as a file (e.g. `bundle.json`)
   and run the one `murmurent import-card` command it came with — your
   dashboard now recognises your role. That's it; you never touch the mayor
   or the public directory.

## I'm a PI of a lab or core

**You don't need a mayor to run a lab.** You are your own lab's certificate
authority.

1. Install murmurent (above), then **self-issue your PI ID** — this makes you your
   lab's root and prints a **trust root** to give your members:
   ```bash
   murmurent pi-init <your-lab>          # (or answer "PI" in `murmurent init`)
   ```
2. **Optional but recommended — connect your lab's Slack.** This is what lets
   member IDs travel by DM instead of by hand:
   ```bash
   murmurent group-slack-setup <your-lab>
   ```
   Full walkthrough (creating the Slack app, scopes, etc.):
   [`docs/group_slack_setup.md`](docs/group_slack_setup.md).
3. **Accept members by issuing them IDs.** A member runs `murmurent enroll
   --group <your-lab>` and gets instructions to send you the resulting
   request — typically a Slack DM, since they're already in your lab's
   workspace. Once you have it:
   ```bash
   murmurent issue-member-card <their-request> --group <your-lab>
   ```
   If your lab's Slack is connected (step 2), this **automatically DMs the
   signed bundle back to the member** — resolved from the email they carried
   in their request, or pass `--dm <slack_user_id>` if you already know it.
   No Slack, or the lookup fails? It prints the bundle for you to send
   yourself, and tells you exactly what to say (`murmurent import-card
   <bundle> --trust-root <your-trust-root>`). Add `--no-dm` to always skip
   Slack and just print/write the bundle.
4. **Optional — join a centre.** If your institution runs a murmurent centre,
   register with its mayor (the [implementations directory](https://github.com/hallettmiket/murmurent_public)
   → `murmurent-join.sh`). The mayor issues you a **separate** centre PI ID that
   attests your *same key* to the centre — your members' cards keep working
   unchanged; only the trust anchor gains a higher root.

Full identity flow (enroll → issue → import → revoke): [`docs/identity.md`](docs/identity.md).

## I want to run murmurent at my institution (become the mayor)

You bootstrap a new **centre** and become its founding registrar — see the
detailed setup just below. You then register PIs and send each one their ID.

---

## Setting up a centre (mayor)

You do this on your **laptop**; the centre is later synced to an always-online
server. Beyond `git`, you'll want:

- **[Claude Code](https://claude.com/claude-code)** — installed and logged in once (OAuth).
- **[GitHub CLI `gh`](https://cli.github.com/)**, authenticated (`gh auth login`) —
  for the centre's GitHub org/repos.
- **[uv](https://docs.astral.sh/uv/)** — the installer adds it if missing.

After running `bootstrap.sh` (above), bootstrap the centre:

```bash
murmurent dashboard --hifi --port 8771
# open http://localhost:8771/registrar and fill in the one-time setup form
```

...or headlessly:

```bash
murmurent centre-init --mayor @<your-handle> \
  --name "<Centre name>" --institution "<Institution>" \
  --unique-name <short-id> --server-host <wigamig-server-host>
murmurent centre-status      # confirms you are the founding registrar
```

### Make your centre joinable

`centre-init` creates the centre but publishes nothing and wires no Slack — those
stay deliberate, opt-in steps:

1. **Encryption key for join requests.** `centre-init` generates an `age` keypair
   automatically (PIs encrypt their join requests to it); recreate with
   `murmurent centre-age-keygen`.
2. **Root signing key (the identity CA).** `murmurent centre-root-keygen` — signs PI
   IDs + the revocation list. **Back it up offline** (see
   [`docs/centre_root_key.md`](docs/centre_root_key.md)).
3. **List your centre** in the implementations directory: `murmurent centre-hub-publish`
   clones [`murmurent_public`](https://github.com/hallettmiket/murmurent_public),
   writes your directory row, and publishes your **signing key + revocation list**
   so members can verify IDs. It prints a `git push` for you to run.
4. **Set up Slack.** Create a `wigamig-<unique-name>` workspace + bot token and
   smoke-test with `murmurent centre-slack-smoke`. Guide:
   [`docs/slack_setup.md`](docs/slack_setup.md).

Then move the centre to the always-online **murmurent server** —
[`docs/setup.md`](docs/setup.md) → *"Deploying a centre on a dedicated Ubuntu
server"*. Labs, cores, and members onboard after that; you approve from
`/registrar`.

## Install (developer)

Working on murmurent itself (not deploying a centre):

```bash
git clone https://github.com/hallettmiket/murmurent
cd murmurent
uv sync --extra dev
uv run murmurent --help
```

## Running tests

```bash
uv run pytest
```

## Authors

Mike Hallett &mdash; michael.hallett@example.edu
