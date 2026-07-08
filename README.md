# wigamig

Shared agentic-AI infrastructure for a bioconvergence centre. It lets research
groups work independently, pool agents and data when collaboration helps, and
accumulate institutional knowledge across every project. See
[`CLAUDE.md`](CLAUDE.md) for the architectural overview and
[`docs/`](docs/) for the full design.

Wigamig is **institution-agnostic** — it is not tied to any one university. A
new institution stands it up by having one person (the **mayor**) bootstrap a
*centre*; everyone else joins afterward.

> **Just want to join a wigamig that already runs at your institution?**
> You don't install anything — jump to [Join an existing wigamig](#join-an-existing-wigamig).

---

## Join an existing wigamig

**Most people start here.** Membership in wigamig is a **signed certificate**,
not just a name in a list — so joining means getting a card cryptographically
issued to your key. Which path you take depends on whether you're starting a
group or joining one.

**Starting a lab or core (you're the PI):**

1. Open the public directory:
   **[github.com/hallettmiket/wigamig_public](https://github.com/hallettmiket/wigamig_public)**
2. Find your institution and note its **registrar email**.
3. **Email the registrar** an encrypted join request (the one-line
   `wigamig-join.sh` script in the hub does this for you). Nothing about you is
   posted publicly — the request is encrypted to the registrar's key.

Once approved, the mayor issues you a signed **PI card**; you `wigamig
import-card` it and you're set.

**Joining an existing group (member):** you clone wigamig, mint your key on first
run, prove you hold it (`wigamig enroll`), and your **PI** issues you a signed
member card. The full step-by-step for every role — member, PI, mayor — is in
**[`docs/identity.md`](docs/identity.md)**.

Everything below is only for people **setting up** wigamig at a new institution
(administrators) or **building** wigamig itself (developers).

---

## Install wigamig at your institution (administrator / mayor)

If you are setting up wigamig at a new institution, you are the **mayor** — the
human who bootstraps the centre and becomes its first registrar. You do this on
your **laptop** (personal workstation); the centre is later synced to an
always-online server.

### Prerequisites

- **git** — required.
- **[uv](https://docs.astral.sh/uv/)** — the installer adds it for you if missing.
- **[Claude Code](https://claude.com/claude-code)** — install it and run it once
  to log in (OAuth). The installer can't do this for you.
- **[GitHub CLI `gh`](https://cli.github.com/)**, authenticated (`gh auth login`)
  — needed when the centre creates its GitHub org/repos.

### One command

The repo is public, so you can bootstrap from nothing:

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/wigamig/main/scripts/bootstrap.sh | bash
```

Prefer to read the script before running it (recommended)? Clone first, then run
the same script locally:

```bash
git clone https://github.com/hallettmiket/wigamig ~/repos/wigamig
cd ~/repos/wigamig
./scripts/bootstrap.sh
```

Either way, [`scripts/bootstrap.sh`](scripts/bootstrap.sh) is **idempotent** —
safe to re-run — and does the following:

1. Checks prerequisites (installs `uv` if missing; warns if Claude Code / `gh`
   aren't logged in — those need a human).
2. Clones or updates `~/repos/wigamig`.
3. Installs the `wigamig` CLI.
4. Wires the commons (agents, rules, skills) into `~/.claude/`.
5. Registers the data-governance hooks + MCP servers.
6. Prints the next step and offers to launch the dashboard.

### Become the founding registrar

The installer leaves you one step from a live centre — the **centre-setup form**:

```bash
wigamig dashboard --hifi --port 8771
# open http://localhost:8771/registrar and fill in the one-time setup form
```

...or bootstrap headlessly from the CLI:

```bash
wigamig centre-init --mayor @<your-handle> \
  --name "<Centre name>" --institution "<Institution>" \
  --unique-name <short-id> --server-host <wigamig-server-host>

wigamig centre-status      # confirms you are the founding registrar
```

### After bootstrap: make your centre joinable

`centre-init` creates the centre but does **not** publish anything or wire
Slack — those stay deliberate, opt-in steps. The `/registrar` page shows a
**Slack** card and a **Public hub listing** card walking you through them; in
short:

1. **Encryption key for join requests.** `centre-init` generates an `age`
   keypair automatically (so members can send you encrypted join requests). If
   you ever need to (re)create it: `wigamig centre-age-keygen`. The public key
   is stamped on your centre profile.

2. **Root signing key (the identity CA).** Run **`wigamig centre-root-keygen`** —
   this creates the key that signs PI cards and the revocation list, and pins it
   as your trust anchor. **Back it up offline** (losing it or leaking it is a
   centre-level event): see [`docs/centre_root_key.md`](docs/centre_root_key.md).
   How membership cards work end-to-end: [`docs/identity.md`](docs/identity.md).

3. **Get listed on the public hub** so members can find you. Nothing is posted
   to GitHub automatically. Run **`wigamig centre-hub-publish`** — it clones the
   [`wigamig_public`](https://github.com/hallettmiket/wigamig_public) hub (if you
   don't already have it), writes your directory row + README table entry, and
   (once the root key exists) publishes your **signing key + revocation list** as
   machine-readable files so members can verify identity cards. It then prints a
   `git push` for you to run — you commit and push yourself, so publishing stays a
   deliberate act. (Manual alternative: [`docs/connect_to_hub.md`](docs/connect_to_hub.md).)

4. **Set up Slack** (the centre's communication fabric). You create a Slack
   workspace named `wigamig-<unique-name>`, add a bot token, and smoke-test it
   with `wigamig centre-slack-smoke`. Full guide:
   [`docs/slack_setup.md`](docs/slack_setup.md).

Once the centre exists on your laptop, move it to the always-online **wigamig
server** by following [`docs/setup.md`](docs/setup.md) → *"Deploying a centre on
a dedicated Ubuntu server"*. Onboarding of other labs, cores, and members comes
after that — each person self-onboards; you approve from `/registrar`.

---

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

Mike Hallett &mdash; hallett.mike.t@gmail.com
