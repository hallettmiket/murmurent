# Setup

This page covers first-time Murmurent installation. It is organized by
role: every user installs the CLI and commons; a PI additionally sets up
a lab; a mayor additionally sets up a centre.

## Installing the CLI and commons (all users)

For most users, a single command performs the entire installation (see
the [README](https://github.com/hallettmiket/murmurent/blob/main/README.md)):

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/murmurent/main/scripts/bootstrap.sh | bash
```

This installs the `murmurent` command and symlinks the shared agents,
rules, and skills into `~/.claude/`. For most users it is the only
installation step required.

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
ls -la ~/.claude/agents/   # symlinks into ~/repos/murmurent/agents/
ls -la ~/.claude/rules/    # symlinks into ~/repos/murmurent/rules/
grep murmurent-oracle ~/.claude/settings.json   # MCP server registered
murmurent --version
```

## Making a repository Murmurent-aware

Installing Murmurent wires up one machine. Turning an individual
repository into something Murmurent-aware is a separate, repeatable step,
with two levels: making a repository **Murmurent-ready**, so that Claude
Code sessions opened in it can use the commons agents, and attaching a
ready repository to a **project**. Both are documented separately:

- [`ready_vs_projects.md`](ready_vs_projects.md): making a repository
  ready.
- [`project_intra.md`](project_intra.md): what a project is and how one
  is created.

## For PIs: setting up a lab

The steps above install Murmurent for one person on one machine. A PI
additionally stands up the lab's own governance and communication, which
is a one-time task:

- `murmurent pi-init <lab>` scaffolds the lab's governance repository,
  `murmurent_lab_mgmt_<lab>`, and pins it locally. The PI then creates a
  private GitHub repository of the same name and pushes it. See
  [`lab_mgmt.md`](lab_mgmt.md) for the repository's contents and access
  model.
- `murmurent group-slack-setup <lab>` creates the lab's Slack channel and
  configures the bot token. See
  [`group_slack_setup.md`](group_slack_setup.md) for the required OAuth
  scopes.
- To register the lab with an existing centre rather than running your
  own, submit a join request to the centre's mayor or registrar. See
  [`connect_to_hub.md`](connect_to_hub.md) and the README's section for
  PIs registering a lab or core with an existing centre.

## For mayors: setting up a centre

A **centre** is one institution's own Murmurent installation. A mayor
initializes it and, for a production deployment, moves it to a dedicated
server so that it can accept join requests continuously.

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
# Add the host to the local registry (dashboard Machines panel,
# or ~/.murmurent/hosts.yaml directly).
murmurent host add my-server --ssh-host <my_server> ...

# Clone murmurent on the remote so the commons agents resolve there.
scripts/install_remote.sh my-server
```

After that, the Repos panel's **↑ adopt** action works for `• clone`
rows on the remote host, over a single batched SSH session. See
[`ready_vs_projects.md`](ready_vs_projects.md) for what adoption does.

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
