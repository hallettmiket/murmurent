# wigamig

Shared agentic-AI infrastructure for a bioconvergence centre. It lets research
groups work independently, pool agents and data when collaboration helps, and
accumulate institutional knowledge across every project. See
[`CLAUDE.md`](CLAUDE.md) for the architectural overview and
[`docs/`](docs/) for the full design.

Wigamig is **institution-agnostic** — it is not tied to any one university. A
new institution stands it up by having one person (the **mayor**) bootstrap a
*centre*; everyone else joins afterward.

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
