# List your centre in the public directory (mayor runbook)

A short runbook for a **mayor** whose centre is bootstrapped and who wants
prospective members to be able to find and contact them. Joining is by **email**
— the public directory just points people at your address. Western is the worked
example; swap in your own values.

## 1. Update the murmurent CLI

```bash
cd ~/repos/murmurent && git pull && uv tool install --reinstall .
```

## 2. Set your centre's join email

The address prospective members write to. Set it on the centre (hand-edit
`~/.murmurent/lab_info/centre.md` frontmatter, or the `/registrar` profile editor):

```yaml
join_email: murmurent-western@example.edu      # a shared/role address is ideal
```

```bash
git -C ~/.murmurent/lab_info commit -am "set centre join_email"
murmurent centre-status
```

## 3. Generate your age key (for encrypted join requests)

Prospective members encrypt their join form to your **public** key so nothing
about them is ever readable in transit or on GitHub. Generate the key once:

```bash
murmurent centre-age-keygen
#  → private key: ~/.murmurent/age/mayor.key   (0600, keep secret)
#  → public recipient: age1...               (safe to publish)
```

## 4. Add your row to the public directory

Run:

```bash
murmurent centre-hub-publish            # writes your row + prints next steps
murmurent centre-hub-publish --submit   # …and publishes it for you
```

It clones the [`murmurent_public`](https://github.com/hallettmiket/murmurent_public)
hub if you don't have it, writes your row (institution, centre name, join email,
and your `age1...` public key) into both `join/directory.tsv` and the README
table, and — with `--submit` — publishes it the right way for **you specifically**:

- **You maintain the hub** (own/have write access): it commits and **pushes**.
- **You're at any other institution** (the normal case): it **forks** the hub,
  pushes a branch to your fork, and **opens a pull request** against the hub. The
  hub maintainer reviews and merges it — that merge is what lists you. (`--submit`
  needs the GitHub CLI: `gh` + `gh auth login`.)

Either way, the directory row is the **only** thing published — institution,
registrar email, age public key. **No member data, ever.**

## 5. Handle requests as they arrive

A prospective member emails you an encrypted `join-request.age`. Decrypt + file
it in one step, then approve:

```bash
murmurent join-request decrypt join-request.age   # decrypts + files a pending request
murmurent join-request list
murmurent join-request approve 1                   # provisions Slack + GitHub + FS
```

(You can also file a plaintext request by hand with `murmurent join-request submit
…` if someone emails you unencrypted.)

Everything about the requester stays on your machine and the centre's private
`lab_info` — nothing touches GitHub. See [`docs/hub_setup.md`](hub_setup.md) for
the wider model and [`docs/slack_setup.md`](slack_setup.md) for the Slack fabric.
