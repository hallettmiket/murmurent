# Setup

This page covers first-time Murmurent installation. It is organized by
role: every user installs the CLI and commons; a PI additionally sets up
a lab; a mayor additionally sets up a centre.

## Installing the CLI and commons (all users)

**For almost everyone, installation is a single command.** Copy and paste
this one line into your terminal and press Enter:

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/murmurent/main/scripts/bootstrap.sh | bash
```

That is the entire installation. It installs the `murmurent` command and
symlinks the shared agents, rules, and skills into `~/.claude/`.

!!! note "You are finished after the command above"
    You do **not** need to run any of the steps that follow. They are shown
    only for transparency, and for the rare case of installing by hand. If
    you ran the command above, skip ahead to
    [Verify the installation](#verify-the-installation).

The bootstrap script automates four steps, which can also be run by hand:

```bash
git clone git@github.com:hallettmiket/murmurent.git ~/repos/murmurent
cd ~/repos/murmurent
uv tool install --python 3.12 -e .
bash scripts/setup.sh
murmurent install --hooks
```

Each step, in order:

1. **Clone the commons** into `~/repos/murmurent`.
2. **Install the CLI** as an editable install pinned to Python 3.12. The
   editable install keeps the package in this clone so that the
   dashboard's static assets resolve correctly; the Python 3.12 pin
   prevents an older system or conda interpreter from being used
   (Murmurent requires Python 3.12 or later). The dashboard, Slack, and
   MCP dependencies are declared as hard dependencies and are installed
   automatically.
3. **Symlink the commons into Claude Code** with `scripts/setup.sh`,
   which links every `agents/*.md` and `rules/*.md` into
   `~/.claude/agents/` and `~/.claude/rules/`. User-authored files at the
   same paths are preserved.
4. **Register the hooks and MCP servers** with `murmurent install
   --hooks`, which merges the Murmurent hooks (`raw_guard`,
   `protected_paths`, `phi_check`, audit, and agent reporter) and the MCP
   servers (`murmurent-inventory`, `murmurent-oracle`) into
   `~/.claude/settings.json`. The command is idempotent and preserves
   existing entries.

### Verify the installation

```bash
murmurent doctor           # Python, PATH, links, hooks, clone remote; prints the fix for anything wrong
```

The doctor covers everything below. The manual checks remain for anyone who
wants to see the files themselves:

```bash
ls -la ~/.claude/agents/   # symlinks into ~/repos/murmurent/agents/
ls -la ~/.claude/rules/    # symlinks into ~/repos/murmurent/rules/
grep murmurent-oracle ~/.claude/settings.json   # MCP server registered
murmurent --version
```

### Members: clone your lab's governance repository

Installing Murmurent and importing your membership card establishes *who
you are*. It does not bring the lab's shared records onto your machine.
The roster of your fellow members, the lab's projects, its compliance
records, and the Lab Oracle all live in the lab's private governance
repository, which every member holds a read-only clone of. Ask your PI
for its name and clone it to the canonical path:

```bash
git clone git@github.com:<org>/murmurent_lab_mgmt_<lab>.git \
    ~/repos/murmurent_lab_mgmt_<lab>
murmurent member list   # the whole lab, not just you
```

Until you do, `murmurent member list` and the dashboard's members panel
have no roster to read; both will say so rather than showing an empty
lab. Keep the clone current with `git pull`, or the **update** button on
the dashboard's members panel — the PI pushes roster changes there. See
[`lab_mgmt.md`](lab_mgmt.md).

## What Murmurent installs on your machine

For reference, or for auditing what Murmurent touches, here is what it
creates or modifies locally:

- `~/.claude/agents/`, `~/.claude/rules/`, `~/.claude/skills/`: the commons
  agents, rules, and skills, symlinked in by `scripts/setup.sh`.
- `~/.claude/settings.json`: where Murmurent registers its hooks and MCP
  servers.
- `~/.claude/agent-memory/`: per-agent working memory.
- `~/.claude/murmurent-preferences.yaml`: your personal preference profile.
- `~/.murmurent/`, this machine's Murmurent state: `machine.yaml`, your
  identity and membership cards, `lab_info/` (the centre registry, on a
  registrar's machine), `agents.log` (the activity log the dashboard tails),
  `keys/`, and host/registry files.
- `~/repos/murmurent` (the commons clone) and
  `~/repos/murmurent_lab_mgmt_<lab>` (your lab's governance clone).
- your Obsidian personal vault (the `murmurent_vault` clone) and, on the lab
  server, the bulk-data root `$MURMURENT_DATA_ROOT/{immutable,append_only}/`.

## Initializing a directory for Murmurent

A **repository** (or "repo") is a folder of code and files tracked by git,
living under `~/repos/` on your machine (for example, `~/repos/brca_wgs`).
Your day-to-day research work happens inside repositories.

Installing Murmurent (above) prepares your machine. The next step is to make
each directory you want to use with Murmurent **ready**: this wires the
commons agents and rules into it, so Claude Code sessions opened there can use
them. The procedure is the same for a brand-new folder, a repository you have
worked in for years, and one that an older Murmurent release set up. Start
with the status check, because its verdict decides the step:

```bash
murmurent repo status ~/repos/<directory>
```

| Verdict | What it means | Do this |
|---|---|---|
| `not a git repo` | a plain folder | `git -C ~/repos/<directory> init`, then the next row |
| `plain clone` or `partial` | git, and Murmurent has never set it up | `murmurent repo adopt ~/repos/<directory>` |
| `ready`, bootstrapped by an older version | ready, and newer agents are missing | `murmurent repo upgrade ~/repos/<directory> --all-agents` |
| `ready`, current version | finished | open Claude Code in it |

Adopting writes a `.murmurent.yaml` marker and a `.claude/agents/` folder of
symlinks into the commons, and leaves every other file as it was. Commit
both, so each clone of the repository is ready as well. A ready repository
can then be attached to a **project**. Both topics have their own pages:

- [`ready_vs_projects.md`](ready_vs_projects.md): readiness in full, the
  verdicts, and upgrading after a release.
- [`project_intra.md`](project_intra.md): what a project is and how one is
  created.

## For PIs: setting up a lab

!!! info "The step-by-step commands are in the README"
    The
    [murmurent repo README](https://github.com/hallettmiket/murmurent/blob/main/README.md)
    gives the exact, copy-pasteable, step-by-step commands for a PI setting up
    a lab. The summary below explains what those steps do.

The steps above install Murmurent for one person on one machine. A PI
additionally stands up the lab's own governance and communication, which
is a one-time task:

- `murmurent pi-init <lab>` scaffolds the lab's governance repository,
  `murmurent_lab_mgmt_<lab>`, and pins it locally. The PI then creates a
  private GitHub repository of the same name and pushes it. See
  [`lab_mgmt.md`](lab_mgmt.md) for the repository's contents and access
  model.
- `murmurent group-setup <lab> --set github=<org>/<repo>` records the lab's
  GitHub. Setting `github` also fills the lab's **GitHub org** (the org that
  project repositories are created under), which clears the dashboard Repos
  panel's "no GitHub org configured" warning and lets Murmurent create a
  project's repository under your org. The same fields can be set from the
  dashboard's **Lab Settings** panel. `group-setup` also configures the lab
  notebook host and path, the lab's own Slack workspace, and the
  data-storage paths; run `murmurent group-setup <lab> --help` for the full
  list of settable fields.
- `murmurent group-slack-setup <lab>` creates the lab's Slack channel and
  configures the bot token. See
  [`group_slack_setup.md`](group_slack_setup.md) for the required OAuth
  scopes.
- To register the lab with an existing centre rather than running your
  own, submit a join request to the centre's mayor or registrar. See
  [`connect_to_hub.md`](connect_to_hub.md) and the README's section for
  PIs registering a lab or core with an existing centre.

## For mayors: setting up a centre

!!! info "The step-by-step commands are in the READMEs"
    The
    [murmurent repo README](https://github.com/hallettmiket/murmurent/blob/main/README.md)
    and the
    [murmurent_public README](https://github.com/hallettmiket/murmurent_public/blob/main/README.md)
    give the exact, step-by-step commands for a Mayor bootstrapping a centre
    and listing it in the public directory. The summary below explains what
    those steps do.

A **centre** is a collection of labs and cores (a research centre, a
department, or another federation of labs and units with shared scientific
goals). An institution can run more than one centre. A Mayor initializes a
centre and, for a production deployment, moves it to a dedicated server so
that it can accept join requests continuously.

To initialize a centre, the mayor runs `murmurent centre-init` on their
laptop; the wizard at `/registrar` collects the centre profile. After
bootstrap, the centre data lives under `~/.murmurent/lab_info/`. The
remaining steps move that centre to a permanent server.

The deployment below assumes a systemd-based Linux host. The commands are
shown for Ubuntu/Debian (`adduser`, `apt`, `pipx`) as a concrete,
copy-pasteable example; substitute the equivalent user-management and
package commands for another distribution.

### 1. On the laptop: push lab_info to a private git remote

```bash
cd ~/.murmurent/lab_info
git remote add origin git@<your-git-host>:<your-org>/lab_info.git
git push -u origin main
```

### 2. On the server: clone and install

Run as root (or via sudo). Replace placeholders to match your install.

```bash
# System user + install location.
sudo adduser --system --group --home /var/lib/murmurent murmurent
sudo mkdir -p /var/lib/murmurent
sudo -u murmurent git clone git@<your-git-host>:<your-org>/lab_info.git \
  /var/lib/murmurent/lab_info

# murmurent itself — via pipx / uv tool (whichever you use in production).
sudo -u murmurent pipx install murmurent

# Project ACL script + sudoers fragment.
sudo install -m 0755 \
  ~murmurent/.../scripts/murmurent_project_acl.sh \
  /opt/murmurent/murmurent_project_acl.sh
echo 'murmurent ALL=(root) NOPASSWD: /opt/murmurent/murmurent_project_acl.sh' \
  | sudo tee /etc/sudoers.d/murmurent_project_acl
sudo chmod 0440 /etc/sudoers.d/murmurent_project_acl

# Systemd unit (template at scripts/murmurent-dashboard.service).
sudo install -m 0644 \
  ~murmurent/.../scripts/murmurent-dashboard.service \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now murmurent-dashboard
sudo systemctl status murmurent-dashboard
```

The unit binds to `0.0.0.0:8771`. **Do not expose 8771 directly to the
internet**. Front it with TLS via Caddy or nginx. Minimal Caddyfile:

```
murmurent.<your-domain>.edu {
  reverse_proxy 127.0.0.1:8771
}
```

**Require a dashboard login before exposing it.** By default the
dashboard trusts `?user=<handle>`, which is acceptable on a localhost
laptop but is a security hole once the dashboard is reachable off-machine.
Set a **dashboard secret**, after which every mutating action
(approve/decline, profile edits, provisioning, and so on) requires a
signed session cookie; the public join form and first-run bootstrap
remain open. The feature is opt-in: with no secret set, behaviour is
unchanged.

```bash
# one secret, known to the registrar(s):
sudo -u murmurent sh -c 'umask 077; openssl rand -hex 32 > ~murmurent/.murmurent/dashboard_secret'
#   ...or set MURMURENT_DASHBOARD_SECRET in the systemd unit's Environment=.
```

Operators then log in once per session: `POST /api/login/authenticate`
with `{handle, secret}` sets the cookie (the dashboard shows a prompt).
`murmurent dashboard` warns if it is bound to a non-loopback address with
no secret configured. This is a shared-secret model: the secret proves
the operator is trusted, and per-user accountability is provided by the
audit log. (Per-user credentials and GitHub OAuth are future upgrades.)

### 3. Pulling lab_info updates

`~/.murmurent/lab_info/` is the centre registry (the same one
`centre-init` creates in step 1 above), and it is a normal git
repository. To sync edits made on the laptop (for example, profile
updates the registrar makes from `/registrar`):

```bash
# On the laptop:
cd ~/.murmurent/lab_info && git push

# On the server:
sudo -u murmurent git -C /var/lib/murmurent/lab_info pull
sudo systemctl reload murmurent-dashboard
```

For larger centres, a webhook that triggers a systemd-path pull avoids
the manual step. For a small-scale deployment, a daily pull via cron is
sufficient.

### 4. Smoke-test the Slack token before accepting join requests

The auto-provisioning path calls `conversations.create` against the
centre's Slack workspace. If the bot token is misconfigured, the first
real lab approval fails mid-flight: the lab record is written, but the
Slack channel, GitHub repository, and filesystem ACLs all warn, and the
registrar must remediate by hand.

Run this once before the first real approval:

```bash
export SLACK_BOT_TOKEN=xoxb-...           # the centre workspace bot
murmurent centre-slack-smoke
```

Expected output:

```
channel name:  murmurent-smoke-20260616-093014
private:       True
keep:          False

✓ created channel C09ABC123 (murmurent-smoke-20260616-093014)
  detail: created (HTTP 200)
✓ probe channel archived

Bot token is healthy. Real join-approve provisioning will work.
```

If the smoke test fails, it prints an actionable hint for the specific
Slack error code (most commonly `missing_scope`: add `groups:write` to
the bot's OAuth scopes and reinstall the app to the workspace). Re-run
until it passes.

### 5. Member onboarding

Once the centre is live, anyone at the institution visits
`https://murmurent.<your-domain>.edu/join` and submits a request. The
registrar reviews it from the "Pending join requests" panel at
`/registrar` and approves it; `centre_cable_guy` auto-provisions Slack,
GitHub, and filesystem ACLs. Per-member onboarding inside an approved lab
remains the responsibility of the per-lab `cable_guy` agent.

## Remote host setup

To run Murmurent on a remote host as well (for example, a shared lab
server):

```bash
# Register the host as a CONNECTION target (CLI-only; edit
# ~/.murmurent/hosts.yaml directly if you prefer). This is mainly a
# `--tunnel` alias + a remote-deploy target — see below.
murmurent host add my-server --ssh-host <my_server> --scan-dir repos

# Clone murmurent on the remote so the commons agents resolve there.
scripts/install_remote.sh my-server
```

`hosts.yaml` is a **connection-only registry** (issue #80): it records how to
reach a machine (`ssh_host`, `remote_user`) and where its git clones live
(`project_root` + `scan_dirs`). It does **not** hold a machine's data-root or
vault paths. Each machine configures its own data-root + personal/lab vault on
**its own dashboard** (This machine → edit → save, written to that machine's
`~/.murmurent/machine.yaml`); reach a remote machine's dashboard over the SSH
tunnel below. Every machine mirrors its own config to
`<vault>/machines/<machine_id>.yaml`, which syncs via the personal vault, so
each dashboard shows a read-only view of your other machines.

**The repo inventory is this-machine-only (issue #94).** The retired
"add an SSH host from the dashboard and scan it for repos" flow is gone:
the Repos panel lists **this** machine's clones cross-referenced against
GitHub, and adoption acts on this machine. To see or adopt repos on the
lab server, open **its own** dashboard over the tunnel below and use the
Repos panel there. See [`ready_vs_projects.md`](ready_vs_projects.md) for
what adoption does.

### Viewing a remote machine's dashboard

Each machine runs its own dashboard, bound to `127.0.0.1:8770` on that
machine only. Viewing a remote server's dashboard from your laptop
means opening an SSH tunnel to it (by hand, via the `--tunnel`
shortcut, or automatically through VS Code Remote-SSH). See
[Remote dashboard access](remote_dashboard.md) for the full
step-by-step recipe, including first-time server setup with
`ssh-copy-id`, viewing two dashboards at once, the identity badge that
tells tabs apart, and troubleshooting.

## Upgrading Murmurent

Installed from PyPI:

```bash
uv tool upgrade murmurent
murmurent install
```

Installed from a clone:

```bash
cd ~/repos/murmurent && git pull
uv tool install --python 3.12 --reinstall -e .
murmurent install
```

Then, either way:

```bash
murmurent doctor                 # confirms the upgrade landed
murmurent repo upgrade --all     # brings every ready repository up to the new release
```

Use `uv` for the reinstall. It installs into the interpreter Murmurent already
runs under. The `pip` on your PATH can belong to a different Python (a conda
`base` environment, for example), and then it either installs into the wrong
place or stops with `Package 'murmurent' requires a different Python`. The
doctor's `path` check reports exactly this situation.

Agent prompt edits reach every ready repository through the symlinks as soon
as the clone is pulled. `repo upgrade` is for the structural part of a
release: a new commons agent, or a change to the `.murmurent.yaml` marker. See
[`versioning.md`](versioning.md) for when a release is structural.

## Resetting a machine

The `/murmurent-reset` skill (run inside a Claude Code session) backs up
`~/.murmurent` first (always), then resets this machine's Murmurent state
to a fresh start, so that `murmurent centre-init` runs as first-run
again. Use it for a clean slate, or to start over from a fresh copy of
the repository.

It is tiered by how much it touches:

- **`centre`** (default, least destructive): resets only the centre
  registry.
- **`install`**: also reinstalls the `murmurent` tool and re-runs setup.
- **`full`**: also clears machine-local caches.
- **`data`**: clears all data you entered, while retaining key material.

Every tier supports `--dry-run` to preview what would change, and
credentials and other projects' installs are protected behind explicit
`--nuke`-style flags, so an ordinary reset cannot accidentally remove
them.
