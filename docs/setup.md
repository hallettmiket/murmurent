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

If you also run wigamig on a remote (e.g. biodatsci):

```bash
# Add the host to the local registry (dashboard Machines panel,
# or ~/.wigamig/hosts.yaml directly).
wigamig host add biodatsci --ssh-host biodatsci ...

# Clone wigamig on the remote so the commons agents resolve there.
scripts/install_remote.sh biodatsci
```

After that, `↑ adopt` works for `• clone` rows on biodatsci in the
Repos panel (writes CHARTER + bootstrap + chrome on the remote
over a single batched SSH session).

## Verify

```bash
ls -la ~/.claude/agents/   # should be symlinks into ~/repos/wigamig/agents/
ls -la ~/.claude/rules/    # should be symlinks into ~/repos/wigamig/rules/
grep wigamig-oracle ~/.claude/settings.json  # MCP registered
wigamig --version
```
