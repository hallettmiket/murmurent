# wigamig

Shared agentic-AI infrastructure for academic researchers, labs cores and research centers. 
It lets research groups work independently, pool agents and data when collaboration helps, and
accumulate institutional knowledge across every project. See
[`CLAUDE.md`](CLAUDE.md) for the architectural overview and [`docs/`](docs/) for
the full design.

Wigamig is **institution-agnostic** — not tied to any one university. A new
institution stands it up by having one person (the **mayor**) bootstrap a
*centre*; everyone else joins afterward.

## Download Wigamig

**Everyone — member, PI, or mayor — starts by installing wigamig.** The code is
public; one command does it (you only need `git`):

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/wigamig/main/scripts/bootstrap.sh | bash
```

Prefer to read the script first (recommended)? Clone it **wherever you like**,
then run it — it installs whatever clone you run it from:

```bash
git clone https://github.com/hallettmiket/wigamig
cd wigamig && ./scripts/bootstrap.sh
```

(`~/repos/wigamig` is a common spot but not required. The `curl` one-liner above
clones there by default; override it with `WIGAMIG_REPO_DIR=/your/path`.)

[`scripts/bootstrap.sh`](scripts/bootstrap.sh) is idempotent: it installs the
`wigamig` command, wires the shared agents/rules/skills into `~/.claude/`, and
registers the data-governance hooks. On your first run it mints your **identity
key** (your unique ID). Then set your personal info — `wigamig whoami` shows your
handle + key, and the dashboard (`wigamig dashboard --hifi`) has the rest.

Then find your situation below.

## I'm a member of a lab that already uses wigamig

Set your info, then ask your **PI** for a **membership ID** (a signed identity
certificate). Run the one `wigamig import-card` command they give you, and your
dashboard recognises your role. That's it — you never touch the mayor or the
public directory.

## I'm a PI of a lab or core

1. Install wigamig (above) and set your lab's parameters.
2. **Register your lab with your institution's mayor.** Find your institution in
   the [wigamig implementations directory](https://github.com/hallettmiket/wigamig_public)
   and send the encrypted request its `wigamig-join.sh` generates. The mayor
   approves and sends you back your **PI ID**.
3. **Accept members by issuing them IDs.** When a member sends a `wigamig enroll`
   request, sign and return it:
   ```bash
   wigamig issue-member-card <their-request> --group <your-lab>
   ```

Full identity flow (enroll → issue → import → revoke): [`docs/identity.md`](docs/identity.md).

## I want to run wigamig at my institution (become the mayor)

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
wigamig dashboard --hifi --port 8771
# open http://localhost:8771/registrar and fill in the one-time setup form
```

...or headlessly:

```bash
wigamig centre-init --mayor @<your-handle> \
  --name "<Centre name>" --institution "<Institution>" \
  --unique-name <short-id> --server-host <wigamig-server-host>
wigamig centre-status      # confirms you are the founding registrar
```

### Make your centre joinable

`centre-init` creates the centre but publishes nothing and wires no Slack — those
stay deliberate, opt-in steps:

1. **Encryption key for join requests.** `centre-init` generates an `age` keypair
   automatically (PIs encrypt their join requests to it); recreate with
   `wigamig centre-age-keygen`.
2. **Root signing key (the identity CA).** `wigamig centre-root-keygen` — signs PI
   IDs + the revocation list. **Back it up offline** (see
   [`docs/centre_root_key.md`](docs/centre_root_key.md)).
3. **List your centre** in the implementations directory: `wigamig centre-hub-publish`
   clones [`wigamig_public`](https://github.com/hallettmiket/wigamig_public),
   writes your directory row, and publishes your **signing key + revocation list**
   so members can verify IDs. It prints a `git push` for you to run.
4. **Set up Slack.** Create a `wigamig-<unique-name>` workspace + bot token and
   smoke-test with `wigamig centre-slack-smoke`. Guide:
   [`docs/slack_setup.md`](docs/slack_setup.md).

Then move the centre to the always-online **wigamig server** —
[`docs/setup.md`](docs/setup.md) → *"Deploying a centre on a dedicated Ubuntu
server"*. Labs, cores, and members onboard after that; you approve from
`/registrar`.

## Install (developer)

Working on wigamig itself (not deploying a centre):

```bash
git clone https://github.com/hallettmiket/wigamig
cd wigamig
uv sync --extra dev
uv run wigamig --help
```

## Running tests

```bash
uv run pytest
```

## Authors

Mike Hallett &mdash; michael.hallett@example.edu
