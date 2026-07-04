# Setup

First-time wigamig installation on a new machine.

## Per-machine wiring

```bash
# 1. Clone the commons.
git clone git@github.com:hallettmiket/wigamig.git ~/repos/wigamig
cd ~/repos/wigamig

# 2. Install the CLI (editable, pinned to Python 3.12).
#    -e (editable): keeps the package in this clone so the dashboard's static
#    assets (docs/designer_dashboard/) resolve — a non-editable install
#    relocates it into site-packages and the hi-fi dashboard 500s.
#    --python 3.12: wigamig needs >=3.12; avoids inheriting an older
#    system/conda default (uv fetches a managed 3.12 if needed).
#    The dashboard (fastapi/uvicorn), Slack, and MCP deps are HARD deps in
#    pyproject, so they come along automatically — no extras to drop. (Only the
#    low-fi streamlit dashboard is optional: `uv tool install ... -e '.[dashboard]'`.)
uv tool install --python 3.12 -e .

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
   See [`lab_mgmt.md`](lab_mgmt.md) for what this repo is, who needs
   it, and how it differs from `~/.wigamig/lab_info/`.
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

**Require a dashboard login (do this before exposing it).** By default the
dashboard trusts `?user=<handle>` — fine on a localhost laptop, but a hole
once it's reachable off-machine. Set a **dashboard secret** and every
mutating action (approve/decline, profile edits, provisioning, …) then
requires a signed session cookie; the public join form and first-run
bootstrap stay open. It's opt-in — with no secret set, behaviour is
unchanged.

```bash
# one secret, known to the registrar(s):
sudo -u wigamig sh -c 'umask 077; openssl rand -hex 32 > ~wigamig/.wigamig/dashboard_secret'
#   ...or set WIGAMIG_DASHBOARD_SECRET in the systemd unit's Environment=.
```

Operators then log in once per session: `POST /api/login/authenticate`
with `{handle, secret}` sets the cookie (the dashboard shows a prompt).
`wigamig dashboard` warns loudly if it's bound to a non-loopback address
with no secret configured. Shared-secret model: the secret proves you're a
trusted operator; per-user accountability is via the audit log. (Per-user
credentials / GitHub OAuth are future upgrades.)

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

### 4. Smoke-test the Slack token BEFORE accepting real join requests

The auto-provisioning path calls `conversations.create` against the
centre's Slack workspace. If the bot token is misconfigured, the
first real lab approval will fail mid-flight — the lab record is
written, but the Slack channel + GitHub repo + FS ACLs all warn,
and the registrar has to remediate by hand.

Run this once before the first real approval:

```bash
export SLACK_BOT_TOKEN=xoxb-...           # the centre workspace bot
wigamig centre-slack-smoke
```

Expected output:

```
channel name:  wigamig-smoke-20260616-093014
private:       True
keep:          False

✓ created channel C09ABC123 (wigamig-smoke-20260616-093014)
  detail: created (HTTP 200)
✓ probe channel archived

Bot token is healthy. Real join-approve provisioning will work.
```

If the smoke fails it prints an actionable hint for the specific
Slack error code (most commonly `missing_scope` — add
`groups:write` to the bot's OAuth scopes and reinstall the app to
the workspace). Re-run until it passes.

### 5. Member onboarding

Once the centre is live, anyone at the institution visits
`https://wigamig.<your-domain>.edu/join` and submits a request. The
registrar reviews from `/registrar`'s "Pending join requests" panel
and approves; `centre_cable_guy` auto-provisions Slack + GitHub +
filesystem ACLs. Per-member onboarding inside an approved lab
remains the per-lab `cable_guy` agent's job.
