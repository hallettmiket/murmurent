# List your centre in the public directory (mayor runbook)

A short runbook for a **mayor** whose centre is bootstrapped and who wants
prospective members to be able to find and contact them. Joining is by **email**
— the public directory just points people at your address. Western is the worked
example; swap in your own values.

## 1. Update the wigamig CLI

```bash
cd ~/repos/wigamig && git pull && uv tool install --reinstall .
```

## 2. Set your centre's join email

The address prospective members write to. Set it on the centre (hand-edit
`~/.wigamig/lab_info/centre.md` frontmatter, or the `/registrar` profile editor):

```yaml
join_email: wigamig-western@example.edu      # a shared/role address is ideal
```

```bash
git -C ~/.wigamig/lab_info commit -am "set centre join_email"
wigamig centre-status
```

## 3. Generate your age key (for encrypted join requests)

Prospective members encrypt their join form to your **public** key so nothing
about them is ever readable in transit or on GitHub. Generate the key once:

```bash
wigamig centre-age-keygen
#  → private key: ~/.wigamig/age/mayor.key   (0600, keep secret)
#  → public recipient: age1...               (safe to publish)
```

## 4. Add your row to the public directory

Add one line to the [`wigamig_public`](https://github.com/hallettmiket/wigamig_public)
README table — institution, a short description, the join email, and your
**age recipient** (the `age1...` public key):

```
| Western University | Bioconvergence Centre | wigamig-western@example.edu | age1... |
```

Open a PR (or push if you have access). That's the **only** thing published —
no member data, ever.

## 5. Handle requests as they arrive

A prospective member emails you an encrypted `join-request.age`. Decrypt + file
it in one step, then approve:

```bash
wigamig join-request decrypt join-request.age   # decrypts + files a pending request
wigamig join-request list
wigamig join-request approve 1                   # provisions Slack + GitHub + FS
```

(You can also file a plaintext request by hand with `wigamig join-request submit
…` if someone emails you unencrypted.)

Everything about the requester stays on your machine and the centre's private
`lab_info` — nothing touches GitHub. See [`docs/hub_setup.md`](hub_setup.md) for
the wider model and [`docs/slack_setup.md`](slack_setup.md) for the Slack fabric.
