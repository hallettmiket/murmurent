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

(`~/repos/wigamig` is a common spot but not required. The `curl` one-liner above
clones there by default; override it with `MURMURENT_REPO_DIR=/your/path`.)

[`scripts/bootstrap.sh`](scripts/bootstrap.sh) is idempotent: it installs the
`murmurent` command, wires the shared agents/rules/skills into `~/.claude/`, and
registers the data-governance hooks. On your first run it mints your **identity
key** (your unique ID). Then set your personal info — `murmurent whoami` shows your
handle + key, and the dashboard (`murmurent dashboard --hifi`) has the rest.

Then find your situation below.

## I'm a member of a lab that already uses murmurent

Set your info, then ask your **PI** for a **membership ID** (a signed identity
certificate). Run the one `murmurent import-card` command they give you, and your
dashboard recognises your role. That's it — you never touch the mayor or the
public directory.

## I'm a PI of a lab or core

**You don't need a mayor to run a lab.** You are your own lab's certificate
authority.

1. Install murmurent (above), then **self-issue your PI ID** — this makes you your
   lab's root and prints a **trust root** to give your members:
   ```bash
   murmurent pi-init <your-lab>          # (or answer "PI" in `murmurent init`)
   ```
2. **Accept members by issuing them IDs.** When a member sends a `murmurent enroll`
   request, sign and return it:
   ```bash
   murmurent issue-member-card <their-request> --group <your-lab>
   ```
   They import it with `murmurent import-card <bundle> --trust-root <your-trust-root>`.
3. **Optional — join a centre.** If your institution runs a murmurent centre,
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
