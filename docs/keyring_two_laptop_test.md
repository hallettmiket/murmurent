---
output:
  html_document: default
  pdf_document: default
---
# Tier 2 — validate the keyring across two Macs (full install)

End-to-end test of the keyring across **Laptop A (this Mac — mayor, already live)**
and **Laptop B (a second MacBook Pro, Apple Silicon / M-series)**. Same test as
`docs/keyring_server_test.md`, but both machines are macOS, which is easier to set
up: because Laptop B is *your own* machine with *your own* GitHub account, it
authenticates with `gh` (one login covers both private repos) instead of the
per-repo deploy keys a shared server needs.

> **Pre-merge note.** The keyring lives on the private fork branch
> `your-fork/murmurent @ feat/keyring-mvp`, so Laptop B installs from there
> (not upstream). Once the feature merges into public `hallettmiket/murmurent`,
> Laptop B installs from the public repo and needs no auth for the code.

> **Role choice.** This runbook makes Laptop B a **`server`-role** machine, so it
> can obtain `slack-token` but is *refused* the `mayor`-only box (Part 9 — the
> security proof). If you instead want B to be a full second mayor, use
> `--role mayor` in Part 7; then Part 9's box would open on B (a mayor can read
> everything), so skip Part 9 in that case.

Run **A** blocks on this Mac, **B** blocks on the second MacBook. Replace `<...>`.

---

## Part 1 — LAPTOP B: prerequisites (Homebrew)

```bash
# If you don't already have the Xcode command-line tools (for git):
xcode-select --install

# If Homebrew isn't installed, install it (official installer):
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# Apple Silicon puts brew in /opt/homebrew — make sure it's on PATH:
eval "$(/opt/homebrew/bin/brew shellenv)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile

brew install age uv gh
age --version && git --version && uv --version && gh --version
```

**Does:** installs `age` (encryption), `uv` (installs + runs murmurent), and `gh`
(GitHub auth). `git` comes with the Xcode CLT.
**Errors:**
- `brew: command not found` after install → Apple Silicon keeps brew in `/opt/homebrew`; run the `eval "$(/opt/homebrew/bin/brew shellenv)"` line and reopen the terminal.
- `xcode-select: note: install requested` dialog → click Install and wait; re-run the block after.

## Part 2 — LAPTOP B: authenticate GitHub

```bash
gh auth login          # GitHub.com → HTTPS → login with a browser, as your-fork
gh auth status         # confirms you're logged in
```

**Does:** logs Laptop B into your GitHub account, granting read access to both
private repos in one step — no per-repo deploy keys needed on your own machine.
**Errors:**
- Browser device-code flow stalls → re-run `gh auth login` and choose "Paste an authentication token" with a PAT that has the `repo` scope.
- Already logged in as a different account → `gh auth switch` or `gh auth login` again.

## Part 3 — LAPTOP B: the FULL murmurent install

```bash
# 3a. Clone the code (fork branch) over HTTPS via gh
gh repo clone your-fork/murmurent ~/murmurent
cd ~/murmurent && git checkout feat/keyring-mvp

# 3b. Install the CLI (editable, pinned to Python 3.12 — uv fetches an arm64 build)
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
agents/rules/skills into `~/.claude/`; 3d registers hooks + MCP. 3e confirms each.
**Errors:**
- `murmurent: command not found` after 3b → uv's tool bin isn't on `PATH` (zsh): `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc && exec $SHELL`.
- `uv tool install` can't find Python 3.12 → it normally downloads an Apple-Silicon build automatically; if the network blocks it, `brew install python@3.12` first.
- 3c/3d write under `~/.claude/`. If you already run Claude Code on Laptop B, this wires murmurent's agents/hooks into it live — expected. If not, the files are created harmlessly.

## Part 4 — LAPTOP B: run the keyring test suite (prove the code works here)

```bash
cd ~/murmurent
uv run --with pytest pytest tests/test_keyring.py -q      # expect: 30 passed
uv run --with pytest pytest tests/test_age_join.py -q     # age wrapper: 6 passed
```

**Does:** runs the keyring's own tests in Laptop B's environment before trusting it
with a real secret.
**Errors:**
- `No such file or directory: pytest` → `uv run --with pytest ...` fetches pytest on the fly; offline, use `uv run --group dev pytest ...`.
- Tests skipped "age not installed" → redo Part 1 (`brew install age`).

## Part 5 — LAPTOP B: clone the registry + structural check

```bash
gh repo clone your-org/lab_info ~/.murmurent/lab_info
murmurent keyring verify         # structural integrity of the .keyring store (no key needed)
```

**Does:** clones the registry (with the `.keyring/` boxes) to the default path
`~/.murmurent/lab_info`; `verify` confirms the store is consistent.
**Errors:**
- `Repository not found` → `gh auth status` (Part 2); your account must be able to see `your-org/lab_info`.
- `verify` prints `fail` → the store is inconsistent upstream; fix on Laptop A and push first.

## Part 6 — LAPTOP B: create B's keyring identity

```bash
murmurent keyring init
```

**Does:** generates Laptop B's own `age` keypair (private half never leaves B) and
prints its **public recipient** (`age1...`). Copy that whole line.
**Errors:**
- `age is not installed` → redo Part 1.
- Copy the recipient exactly — a broken paste causes "not a valid age recipient" next.

## Part 7 — LAPTOP A: authorize Laptop B and push

```bash
murmurent keyring authorize <PASTE_B_RECIPIENT> --label macbook-b --role server --push
```

**Does:** adds B to the roster, re-locks the `slack-token` box so B's key fits it,
and (`--push`) commits + pushes `lab_info` (pull-first).
**Errors:**
- `not a valid age recipient` → re-copy the recipient from Part 6.
- `! could not fast-forward lab_info (diverged)` → `git -C ~/.murmurent/lab_info pull --rebase`, then re-run.
- `! push failed` → check `gh auth status` on Laptop A.

## Part 8 — LAPTOP B: sync and verify (the proof)

```bash
murmurent keyring sync --apply   # pulls, decrypts with B's key, writes the token
murmurent keyring check          # end-to-end health → HEALTHY
murmurent centre-slack-smoke     # B USES the synced token: creates + archives a channel
```

**Does:** B pulls the re-locked box, decrypts with **its own** key, writes
`~/.config/murmurent/slack-token`, and proves it can use the token.
**Errors:**
- `this machine is not authorised yet` → Part 7 didn't push, or this pull is stale; wait a moment and re-run `keyring sync --apply` (it pulls first).
- `centre-slack-smoke` → `invalid_auth` = the box holds a stale token (rotate on A with `keyring rotate-secret slack-token --file ... --push`); `missing_scope` = a Slack app scope issue, not a keyring problem.

## Part 9 — LAPTOP B: confirm the crown-jewel refusal (server role only)

On **LAPTOP A**:
```bash
murmurent keyring set-secret test-ca --value "PRETEND-CA" --target ~/.murmurent/keys/test-ca --consumers mayor --push
```
On **LAPTOP B**:
```bash
murmurent keyring sync --apply   # test-ca → skip-not-entitled
ls ~/.murmurent/keys/test-ca     # "No such file" — B holds the box but cannot open it
murmurent keyring check          # test-ca shows "correctly refused"
```

**Does:** demonstrates the core promise — B has the file but no keyhole for a
`mayor`-only box. (Skip this Part if you made B a mayor in Part 7.)

## Part 10 — Cleanup / rollback (if this was only a test)

```bash
# on LAPTOP A:
murmurent keyring revoke macbook-b --push     # drop B; re-lock boxes without it
```
Then on Laptop B: `rm -rf ~/.murmurent ~/murmurent && uv tool uninstall murmurent`
(and `bash ~/murmurent/scripts/... ` isn't needed — the ~/.claude symlinks can be
left or removed with `find ~/.claude/agents -type l -delete` etc.).

**Does:** `revoke` removes B from the roster and re-locks the boxes.
**Rotation note:** `revoke` will tell you to rotate the token because git history is
permanent — essential if a machine was *untrusted/compromised*. For **your own
second laptop that you control**, dropping it is enough; rotate the real Slack
token only if the laptop leaves your possession.

---

## Quick reference — the whole flow

| Where | Command | Purpose |
|---|---|---|
| B | `brew install age uv gh` | prerequisites |
| B | `gh auth login` | GitHub access (both repos, one login) |
| B | clone fork · `uv tool install -e .` · `setup.sh` · `install --hooks` | full install |
| B | `pytest tests/test_keyring.py` | prove the code runs here |
| B | clone lab_info · `keyring verify` | get + check the store |
| B | `keyring init` | B's identity |
| A | `keyring authorize <rec> --label macbook-b --role server --push` | admit B |
| B | `keyring sync --apply` · `check` · `centre-slack-smoke` | obtain + use the secret |
| B | (mayor-only box) `sync` → refused | crown-jewel proof (server role) |
| A | `keyring revoke macbook-b --push` | rollback |

**Two-Mac advantages:** no Linux server to provision, `gh auth login` instead of
deploy keys, and Homebrew handles the Apple-Silicon (`age`, Python 3.12) builds
automatically. The main thing to watch on a fresh Mac is Part 1 — Xcode CLT +
Homebrew on `PATH` (`/opt/homebrew` on Apple Silicon).
