# Murmurent

Shared agentic-AI infrastructure for academic researchers, labs cores and research centers. 
It lets research groups work independently, pool agents and data when collaboration helps, and
accumulate institutional knowledge across every project. See
[`CLAUDE.md`](CLAUDE.md) for the architectural overview and [`docs/`](docs/) for
the full design.

Murmurent can be used as a standalone agentic AI OS environment, as a means to integrate
members of the same lab, or as a means of intergrating labs and core facilities across
a centre or University.

## Step1. Download Murmurent

**Everyone — member, PI, or mayor — starts by installing murmurent.** The code is
public; one command does it (you only need `git`):

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/murmurent/main/scripts/bootstrap.sh | bash
```

This installs the `murmurent` command, wires the shared agents/rules/skills into `~/.claude/`, and
registers the data-governance hooks. On your first run it mints your **identity
key** (your unique ID). Then set your personal info — `murmurent whoami` shows your
handle + key, and the dashboard (`murmurent dashboard --hifi`) has the rest.

There are three ways a user interacts with Murmurent:
(i) through the `murmurent` CLI
(ii) through interactions (e.g. skills) defined in Claude Code
(iii) through a Dashboard (not discussed here).

After installation, find your situation below.

## I'm a member of a lab whose PI already uses murmurent

You need a **membership ID** (a signed identity certificate) from your **PI**
to include you in the lab or core. 

**Via Slack**

1. Request your ID:
   ```bash
   murmurent enroll --group <your-lab> --out enroll.json
   ```
   Send the output file `enroll.json` to your PI —
   DM it to them directly on Slack or via email.
2. The PI then runs `murmurent issue-member-card` against
   your request. Murmurent will DM the signed bundle
   back to you.
3. Save what you recevied as a file (e.g. `bundle.json`)
   and run the `murmurent import-card` command

## I'm a PI of a lab or core

You are your lab's certificate authority.

1. Install murmurent (above), then self-issue your PI ID — this makes you your
   lab's root and prints a **trust root** to give your members:
   ```bash
   murmurent pi-init <your-lab>          # (or answer "PI" in `murmurent init`)
   ```
2. Connect your lab's Slack. This lets member IDs travel by DM instead
   of by hand (it is possible to do this by email if preferred):
   ```bash
   murmurent group-slack-setup <your-lab>
   ```
   Full details regarding creating the Slack app with security scopes, etc.:
   [`docs/group_slack_setup.md`](docs/group_slack_setup.md).
4. Accept members by issuing them IDs. A member runs `murmurent enroll
   --group <your-lab>` and gets instructions to send you the resulting
   request (e.g. a Slack DM). Once you have it:
   ```bash
   murmurent issue-member-card <their-request> --group <your-lab>
   ```
   This automatically DMs the signed bundle back to the member — pass
   `--dm <slack_user_id>` if you already know their Slack id, or `--no-dm`
   to skip Slack and just print the bundle. If Slack isn't connected, or
   the member's Slack account can't be found, it falls back to printing
   the bundle for you to send yourself. Either way, the member finishes
   with `murmurent import-card <bundle> --trust-root <your-trust-root>`.

Full identity flow (enroll → issue → import → revoke): [`docs/identity.md`](docs/identity.md).

## I want to run murmurent at my institution (become the mayor)

You bootstrap a new **centre** and become its founding registrar — see the
details below. You then register PIs and send each one their ID.

---

## Setting up a centre (mayor)

You'll need:

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

`centre-init` creates the centre. In the following, we do not assume
that perspective members already belong to a Slack workspace.
The next steps are as follows:

1. Encryption key for join requests. `centre-init` generates an `age` keypair
   automatically so that PIs can encrypt their join requests to it; recreate with
   `murmurent centre-age-keygen`.
2. Root signing key (the identity CA). `murmurent centre-root-keygen` — signs PI
   IDs + the revocation list. Back it up offline (see
   [`docs/centre_root_key.md`](docs/centre_root_key.md)).
3. List your centre in the implementations directory: `murmurent centre-hub-publish`
   clones [`murmurent_public`](https://github.com/hallettmiket/murmurent_public),
   writes your directory row, and publishes your signing key + revocation list
   so members can verify IDs. It prints a `git push` for you to run.
4. Set up Slack. Create a `wigamig-<unique-name>` workspace + bot token and
   smoke-test with `murmurent centre-slack-smoke`. Guide:
   [`docs/slack_setup.md`](docs/slack_setup.md).


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

Mike Hallett &mdash; michael.hallett@uwo.ca
