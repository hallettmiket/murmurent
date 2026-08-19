---
output:
  html_document: default
  pdf_document: default
---
# Tier 2 — validate the keyring on a real server (full install)

End-to-end test of the keyring across **this laptop (mayor, already live)** and a
**second machine (a server, role `server`)**. Unlike `docs/keyring_deploy.md`
(the condensed production runbook), this walks the **complete murmurent install**
on the server — CLI, commons symlinks, hooks/MCP — then runs the keyring's own
test suite there before wiring the two machines together.

> **Pre-merge note.** The keyring lives on the private fork branch
> `your-fork/murmurent @ feat/keyring-mvp`, so the server installs from
> there (not upstream). Once the feature merges into public `hallettmiket/murmurent`,
> the server installs from the public repo and the code deploy key goes away.

Run **LAPTOP** blocks on the Mac, **SERVER** blocks over SSH. Commands are
Ubuntu/Debian. Replace `<...>` placeholders.

---

## Part 1 — SERVER: prerequisites

```bash
sudo apt-get update && sudo apt-get install -y age git curl
curl -LsSf https://astral.sh/uv/install.sh | sh
exec $SHELL                      # reload PATH so `uv` is found
age --version && git --version && uv --version
```

**Does:** installs `age` (encryption), `git` (transport), `uv` (installs + runs murmurent).
**Errors:**
- `age: command not found` after install → older distros may name it `age-encryption`, or fetch the binary from https://age-encryption.org onto `PATH`.
- `uv: command not found` → you skipped `exec $SHELL`; open a new shell or `source ~/.bashrc`.

## Part 2 — SERVER: scoped deploy keys for the two private repos

The server needs read access to the **code** (`your-fork/murmurent`) and the
**secrets** (`your-org/lab_info`). A deploy key grants access to one repo only.

```bash
ssh-keygen -t ed25519 -f ~/.ssh/code_deploy    -N "" -C "server: murmurent code"
ssh-keygen -t ed25519 -f ~/.ssh/labinfo_deploy -N "" -C "server: lab_info"
echo "=== CODE key ==="    ; cat ~/.ssh/code_deploy.pub
echo "=== LABINFO key ===" ; cat ~/.ssh/labinfo_deploy.pub

cat >> ~/.ssh/config <<'EOF'
Host gh-code
  HostName github.com
  User git
  IdentityFile ~/.ssh/code_deploy
  IdentitiesOnly yes
Host gh-labinfo
  HostName github.com
  User git
  IdentityFile ~/.ssh/labinfo_deploy
  IdentitiesOnly yes
EOF
```

In the browser, add each printed **public** key as a **read-only Deploy key**:
- `your-fork/murmurent` → Settings → Deploy keys → paste the **CODE** key.
- `your-org/lab_info` → Settings → Deploy keys → paste the **LABINFO** key.

**Does:** two SSH keys, each mapped to one repo via a `Host` alias.
**Errors:**
- Later `Permission denied (publickey)` → key not added to that repo, you pasted the private half instead of `.pub`, or the clone URL's `Host` alias doesn't match this config.
- Read-only suffices (the server only pulls). Tick "Allow write access" only if this server will also run the registrar dashboard.

## Part 3 — SERVER: the FULL murmurent install

This is the complete install (the four steps the bootstrap one-liner runs), from
the fork branch.

```bash
# 3a. Clone the code (fork branch) via the code deploy key
git clone gh-code:your-fork/murmurent.git ~/murmurent
cd ~/murmurent && git checkout feat/keyring-mvp

# 3b. Install the CLI (editable, pinned to Python 3.12)
uv tool install --python 3.12 -e .

# 3c. Symlink the commons (agents, rules, skills) into ~/.claude/
bash scripts/setup.sh

# 3d. Register murmurent hooks + MCP servers into ~/.claude/settings.json
murmurent install --hooks

# 3e. Verify the install
murmurent --version
ls -la ~/.claude/agents/ | head
grep -c 'murmurent.hooks' ~/.claude/settings.json      # > 0
grep -c 'murmurent-oracle' ~/.claude/settings.json     # 1
```

**Does:** 3a gets the source; 3b puts `murmurent` on `PATH`; 3c wires the commons
agents/rules/skills into `~/.claude/`; 3d registers the hooks + MCP servers. 3e
confirms each landed.
**Errors:**
- `Permission denied (publickey)` / `Repository not found` on 3a → deploy key not added, wrong alias, or wrong repo (Part 2).
- `murmurent: command not found` after 3b → uv's tool bin isn't on `PATH`: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc && exec $SHELL`.
- `uv tool install` can't find Python 3.12 → it normally downloads it; on an offline box `sudo apt-get install -y python3.12` first.
- 3c/3d write under `~/.claude/` (Claude Code config). On a headless server they still create the files harmlessly; they only matter if you run Claude Code on the server. If `~/.claude` doesn't exist, `setup.sh` creates it.

## Part 4 — SERVER: run the keyring test suite (prove the code works here)

```bash
cd ~/murmurent
uv run --with pytest pytest tests/test_keyring.py -q          # expect: 30 passed
uv run --with pytest pytest tests/test_age_join.py -q         # age wrapper: 6 passed
```

**Does:** runs the keyring's own tests inside the server's environment, so you know
the crypto + git + age behave here before trusting it with a real secret.
**Errors:**
- `No such file or directory: pytest` → `uv run --with pytest ...` fetches pytest on the fly; on an offline box use `uv run --group dev pytest ...` instead.
- Tests skipped with "age not installed" → redo Part 1; the suite skips (does not fail) when `age` is absent.

## Part 5 — SERVER: clone the registry + structural check

```bash
git clone gh-labinfo:your-org/lab_info.git ~/.murmurent/lab_info
murmurent keyring verify         # structural integrity of the .keyring store (no key needed)
```

**Does:** clones the registry (with the `.keyring/` boxes) to the default path
`~/.murmurent/lab_info`; `verify` confirms the store is internally consistent.
**Errors:**
- `Permission denied` → the lab_info deploy key (Part 2).
- `verify` prints `fail` → the store is inconsistent upstream; fix on the laptop and push before continuing.

## Part 6 — SERVER: create the server's keyring identity

```bash
murmurent keyring init
```

**Does:** generates the server's own `age` keypair (private half never leaves the
server) and prints its **public recipient** (`age1...`). Copy that whole line.
**Errors:**
- `age is not installed` → redo Part 1.
- Copy the recipient exactly — a broken paste causes "not a valid age recipient" next.

## Part 7 — LAPTOP: authorize the server and push

```bash
murmurent keyring authorize <PASTE_SERVER_RECIPIENT> --label server-prod --role server --push
```

**Does:** adds the server to the roster, re-locks the `slack-token` box so the
server's key fits it, and (`--push`) commits + pushes `lab_info` (pull-first).
**Errors:**
- `not a valid age recipient` → re-copy the recipient from Part 6.
- `! could not fast-forward lab_info (diverged)` → `git -C ~/.murmurent/lab_info pull --rebase`, then re-run.
- `! push failed` → check `gh auth status` (the laptop pushes over HTTPS with your gh token).

## Part 8 — SERVER: sync and verify (the proof)

```bash
murmurent keyring sync --apply   # pulls, decrypts with the server's key, writes the token
murmurent keyring check          # end-to-end health → HEALTHY
murmurent centre-slack-smoke     # the server USES the synced token: creates + archives a channel
```

**Does:** the server pulls the re-locked box, decrypts with **its own** key, writes
`~/.config/murmurent/slack-token`, and proves it can actually use the token.
**Errors:**
- `this machine is not authorised yet` → Part 7 didn't push, or this pull is stale; wait a moment and re-run `keyring sync --apply` (it pulls first).
- `centre-slack-smoke` → `invalid_auth` means the box holds a stale token (rotate it on the laptop with `keyring rotate-secret slack-token --file ... --push`); `missing_scope` is a Slack app scope issue, not a keyring problem.

## Part 9 — SERVER: confirm the crown-jewel refusal (recommended)

On the **LAPTOP**:
```bash
murmurent keyring set-secret test-ca --value "PRETEND-CA" --target ~/.murmurent/keys/test-ca --consumers mayor --push
```
On the **SERVER**:
```bash
murmurent keyring sync --apply   # test-ca → skip-not-entitled
ls ~/.murmurent/keys/test-ca     # "No such file" — server holds the box but cannot open it
murmurent keyring check          # test-ca shows "correctly refused"
```

**Does:** demonstrates the core promise on real hardware — the server has the file
but no keyhole for a `mayor`-only box.

## Part 10 — Cleanup / rollback (if this was only a test)

```bash
# on the LAPTOP:
murmurent keyring revoke server-prod --push     # drop the server; re-lock boxes without it
```
Then destroy the server VM, or on it: `rm -rf ~/.murmurent ~/murmurent && uv tool uninstall murmurent`.

**Does:** `revoke` removes the server from the roster and re-locks the boxes.
**Rotation note:** `revoke` will tell you to rotate the token because git history is
permanent — essential if a machine was *untrusted/compromised*. For **your own
trusted test server that you are destroying**, dropping it is enough; rotate the
real Slack token only if you're concerned the server's disk outlives the test.

---

## Quick reference — the whole flow

| Where | Command | Purpose |
|---|---|---|
| SERVER | `apt install age git curl` + uv installer | prerequisites |
| SERVER | 2× `ssh-keygen` + add Deploy keys | scoped git access |
| SERVER | clone fork · `uv tool install -e .` · `setup.sh` · `install --hooks` | full install |
| SERVER | `pytest tests/test_keyring.py` | prove the code runs here |
| SERVER | clone lab_info · `keyring verify` | get + check the store |
| SERVER | `keyring init` | server identity |
| LAPTOP | `keyring authorize <rec> --role server --push` | admit the server |
| SERVER | `keyring sync --apply` · `check` · `centre-slack-smoke` | obtain + use the secret |
| SERVER | (mayor-only box) `sync` → refused | crown-jewel proof |
| LAPTOP | `keyring revoke server-prod --push` | rollback |

**Most likely snag:** the deploy-key/SSH wiring in Parts 2–3 (`Permission denied
(publickey)` / `Repository not found`). If a clone fails, look there first.
