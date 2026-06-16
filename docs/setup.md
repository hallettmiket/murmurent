# Setup

First-time wigamig installation on a new machine.

## Per-machine wiring

```bash
# 1. Clone the commons.
git clone git@github.com:hallettmiket/wigamig.git ~/repos/wigamig
cd ~/repos/wigamig

# 2. Install the CLI + venv.
uv tool install -e .

# 3. Symlink agents + rules into ~/.claude/.
bash scripts/setup.sh

# 4. Register hooks + MCP servers in ~/.claude/settings.json.
wigamig install --hooks
```

What each step does:

- `setup.sh` symlinks every `agents/*.md` and `rules/*.md` into
  `~/.claude/agents/` and `~/.claude/rules/`. Preserves any
  user-authored files at the same paths.
- `wigamig install --hooks` merges the wigamig hooks (raw_guard,
  protected_paths, phi_check, audit, agent reporter) and the MCP
  servers (`wigamig-inventory`, `wigamig-oracle`) into
  `~/.claude/settings.json`. Idempotent; preserves existing
  hooks/servers.

## Per-project wiring

Use the dashboard's *adopt* button (for existing clones) or
*install* button (for fresh ones). Both call
[`core.projectize`](../src/wigamig/core/projectize.py) under the
hood, which writes:

1. `CHARTER.md` at the clone root (if missing).
2. `lab_mgmt/projects/<name>.md` (the lab registry entry, if missing).
3. `~/.wigamig/installations/<name>.yaml` (this-machine manifest).
4. `.claude/agents/` symlinks for the agents you picked.
5. `.vscode/settings.json` (wigamig chrome — title, activity bar
   right, terminals in editor area).
6. `.gitignore` line for `.claude/settings.json` (machine-local
   permissions/grants don't escape to git).

Existing files are preserved on re-run.

## Remote host setup

If you also run wigamig on a remote (e.g. lab-server):

```bash
# Add the host to the local registry (dashboard Machines panel,
# or ~/.wigamig/hosts.yaml directly).
wigamig host add lab-server --ssh-host lab-server ...

# Clone wigamig on the remote so the commons agents resolve there.
scripts/install_remote.sh lab-server
```

After that, `↑ adopt` works for `• clone` rows on lab-server in the
Repos panel (writes CHARTER + bootstrap + chrome on the remote
over a single batched SSH session).

## Verify

```bash
ls -la ~/.claude/agents/   # should be symlinks into ~/repos/wigamig/agents/
ls -la ~/.claude/rules/    # should be symlinks into ~/repos/wigamig/rules/
grep wigamig-oracle ~/.claude/settings.json  # MCP registered
wigamig --version
```

## Deploying a centre on a dedicated Ubuntu server

For a brand-new centre, the **mayor** typically runs `wigamig
centre-init` on their laptop (the GUI wizard at `/registrar` collects
the centre profile). Once bootstrap succeeds, the centre data lives
under `~/.wigamig/lab_info/`. To move that centre to a permanent
Ubuntu server so it can accept join requests around the clock:

### 1. On the laptop — push lab_info to a private git remote

```bash
cd ~/.wigamig/lab_info
git remote add origin git@<your-git-host>:<your-org>/lab_info.git
git push -u origin main
```

### 2. On the Ubuntu server — clone + install

Run as root (or via sudo). Replace placeholders to match your install.

```bash
# System user + install location.
sudo adduser --system --group --home /var/lib/wigamig wigamig
sudo mkdir -p /var/lib/wigamig
sudo -u wigamig git clone git@<your-git-host>:<your-org>/lab_info.git \
  /var/lib/wigamig/lab_info

# wigamig itself — via pipx / uv tool (whichever you use in production).
sudo -u wigamig pipx install wigamig

# Project ACL script (item 0c) + sudoers fragment.
sudo install -m 0755 \
  ~wigamig/.../scripts/wigamig_project_acl.sh \
  /opt/wigamig/wigamig_project_acl.sh
echo 'wigamig ALL=(root) NOPASSWD: /opt/wigamig/wigamig_project_acl.sh' \
  | sudo tee /etc/sudoers.d/wigamig_project_acl
sudo chmod 0440 /etc/sudoers.d/wigamig_project_acl

# Systemd unit (template at scripts/wigamig-dashboard.service).
sudo install -m 0644 \
  ~wigamig/.../scripts/wigamig-dashboard.service \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wigamig-dashboard
sudo systemctl status wigamig-dashboard
```

The unit binds to `0.0.0.0:8771`. **Do not expose 8771 directly to
the internet** — front it with TLS via Caddy or nginx. Minimal
Caddyfile:

```
wigamig.<your-domain>.edu {
  reverse_proxy 127.0.0.1:8771
}
```

### 3. Pulling lab_info updates

The centre data is a normal git repo. To sync edits made on the
laptop (e.g. profile updates the registrar makes from `/registrar`):

```bash
# On the laptop:
cd ~/.wigamig/lab_info && git push

# On the server:
sudo -u wigamig git -C /var/lib/wigamig/lab_info pull
sudo systemctl reload wigamig-dashboard
```

For larger centres a webhook → systemd-path-triggered pull avoids
the manual step. For our small-scale deployment, a daily pull via
cron is sufficient.

### 4. Member onboarding

Once the centre is live, anyone at the institution visits
`https://wigamig.<your-domain>.edu/join` and submits a request. The
registrar reviews from `/registrar`'s "Pending join requests" panel
and approves; `centre_cable_guy` auto-provisions Slack + GitHub +
filesystem ACLs. Per-member onboarding inside an approved lab
remains the per-lab `cable_guy` agent's job.
