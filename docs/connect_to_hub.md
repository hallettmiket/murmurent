# Connecting to the public directory

A short runbook for a **mayor** whose centre is bootstrapped and who
wants prospective members to be able to find and contact them. Joining
is by **email**: the public directory just points people at your
address. Example University is the worked example; swap in your own
values.

## 1. Update the Murmurent CLI

```bash
cd ~/repos/murmurent && git pull && uv tool install --reinstall .
```

## 2. Set your centre's join email

The address prospective members write to. Set it on the centre
(hand-edit `~/.murmurent/lab_info/centre.md` frontmatter, or the
`/registrar` profile editor):

```yaml
join_email: murmurent-join@example.edu      # a shared/role address is ideal
```

```bash
git -C ~/.murmurent/lab_info commit -am "set centre join_email"
murmurent centre-status
```

## 3. Generate your age key (for encrypted join requests)

Prospective members encrypt their join form to your **public** key so
nothing about them is ever readable in transit or on GitHub. Generate
the key once:

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

It clones [`murmurent_public`](https://github.com/hallettmiket/murmurent_public)
if you don't have it, writes your row (institution, centre name, join
email, and your `age1...` public key) into both `join/directory.tsv`
and the README table, and (with `--submit`) publishes it the right way
for **you specifically**:

- **You maintain the public directory** (own or have write access): it
  commits and **pushes**.
- **You're at any other institution** (the normal case): it **forks**
  the public directory, pushes a branch to your fork, and **opens a
  pull request** against it. The public directory's maintainer reviews
  and merges it: that merge is what lists you. (`--submit` needs the
  GitHub CLI: `gh` + `gh auth login`.)

Either way, only the directory row gets published: institution,
registrar email, and age public key, with member data staying local to
your own machine.

## 5. Handle requests as they arrive

A prospective member emails you an encrypted `join-request.age`.
Decrypt and file it in one step, then approve:

```bash
murmurent join-request decrypt join-request.age   # decrypts + files a pending request
murmurent join-request list
murmurent join-request approve 1                   # provisions Slack + GitHub + FS
```

(You can also file a plaintext request by hand with `murmurent
join-request submit …` if someone emails you unencrypted.)

Everything about the requester stays on your machine and the centre's
private `lab_info`, kept local to your own infrastructure. See
[`docs/hub_setup.md`](hub_setup.md) for the wider model and
[`docs/slack_setup.md`](slack_setup.md) for the Slack fabric.
