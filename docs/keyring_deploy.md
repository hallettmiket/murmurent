# Deploying the keyring: sync `~/.murmurent` secrets across your machines

The **keyring** distributes a centre's shared secrets (Slack token, and later the
onboarding age key) across all of one principal's installs — a laptop, an
always-online server, a second laptop months later — without ever hand-copying a
private key. Each machine holds its own `age` identity (private half never
leaves it); each secret is one `age`-encrypted "box" in the `lab_info` git repo,
locked **per role** so a `server` machine can hold every box yet be unable to
open a `mayor`-only one (e.g. the root CA).

See `docs/keyring.md` (design) for the mechanism. This page is the deployment
runbook. Commands assume the mayor's laptop plus one Linux server.

> **Phase 1 scope.** `init / authorize / set-secret / sync / status / check`.
> There is **no `revoke`/`rotate` command yet** — decommissioning a machine is
> manual (see "Operations"). Adding machines and rotating-by-reseeding both work.

## Prerequisites

- `age`, `git`, `uv`, and murmurent installed on each machine.
- `lab_info` pushed to a **private** git remote (`your-org/lab_info` here). All
  machines pull from it.
- Until the keyring is merged upstream, the server installs murmurent from the
  private fork branch, so it needs read access to that repo too.

## Part A — On the mayor's laptop: seed the secret

```bash
murmurent keyring init                                   # this machine's identity (one-time)
LAP=$(murmurent keyring status --no-pull | awk '/recipient:/{print $2}')
murmurent keyring authorize "$LAP" --label laptop --role mayor
murmurent keyring set-secret slack-token \
  --file  ~/.config/murmurent/slack-token \
  --target ~/.config/murmurent/slack-token \
  --consumers mayor,server

git -C ~/.murmurent/lab_info add .keyring
git -C ~/.murmurent/lab_info commit -m "keyring: seed slack-token + authorize laptop"
git -C ~/.murmurent/lab_info push
murmurent keyring check                                  # expect: HEALTHY
```

## Part B — Provision the server (scoped deploy keys, no full account)

A **deploy key** is an SSH key scoped to a single repo — the right way to give a
server git access without handing it your whole account.

```bash
# Prerequisites
sudo apt-get update && sudo apt-get install -y age git curl
curl -LsSf https://astral.sh/uv/install.sh | sh && exec $SHELL

# READ deploy key for the CODE repo (private fork; until keyring merges upstream)
ssh-keygen -t ed25519 -f ~/.ssh/code_deploy -N "" -C "server: murmurent code (read)"
cat ~/.ssh/code_deploy.pub          # → GitHub: <fork> → Settings → Deploy keys → Add (read-only)

# READ/WRITE deploy key for lab_info
ssh-keygen -t ed25519 -f ~/.ssh/labinfo_deploy -N "" -C "server: lab_info (write)"
cat ~/.ssh/labinfo_deploy.pub       # → GitHub: <lab_info> → Deploy keys → Add, TICK "Allow write access"

# Map each key to its repo
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

# Install murmurent (with keyring) from the fork, and clone lab_info
git clone gh-code:your-fork/murmurent.git ~/murmurent
cd ~/murmurent && git checkout feat/keyring-mvp && uv tool install --python 3.12 -e .
git clone gh-labinfo:your-org/lab_info.git ~/.murmurent/lab_info

murmurent keyring init              # COPY the printed age1... recipient
```

## Part C — On the laptop: authorize the server

```bash
murmurent keyring authorize <SERVER_RECIPIENT> --label server-prod --role server
git -C ~/.murmurent/lab_info add .keyring
git -C ~/.murmurent/lab_info commit -m "keyring: authorize server-prod"
git -C ~/.murmurent/lab_info push
```

## Part D — On the server: sync and verify

```bash
murmurent keyring sync --apply      # pulls, decrypts with the server's own key, writes the token
murmurent keyring check             # expect: HEALTHY (a mayor-only box would read "correctly refused")
murmurent centre-slack-smoke        # the server USES the synced token → creates + archives a channel
```

## Operations

| Task | How |
|---|---|
| **Rotate a secret** | On any authorised machine: `keyring set-secret <name> --file … --target … --consumers …` → commit + push. Peers converge on next `keyring sync`. |
| **Add a machine** | Repeat Parts B–D. |
| **Health monitoring** | Cron on each machine: `@hourly cd ~/repos/murmurent && scripts/keyring_check.sh || <alert>`. |
| **Decommission a machine** (manual, Phase 1) | Remove it from `.keyring/recipients.yaml`, **rotate the value of every secret it could read** (new values), re-lock, push. Rotation is mandatory because **git history is permanent** — the old box stays decryptable by the removed key forever. |

## What the keyring never carries

Per-machine keys (`keys/id_ed25519`), logs, and anything not declared in
`manifest.yaml`. The root CA is only ever in a `mayor`-consumer box — it is never
encrypted to a `server` recipient, so it cannot land on an internet-facing box.
The keyring is online *distribution*, not disaster recovery: keep an **offline
backup of the root CA** regardless.
