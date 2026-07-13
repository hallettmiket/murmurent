# Murmurent

Shared agentic-AI infrastructure for academic researchers, labs cores and research centers. 
It lets research groups work independently, pool agents and data when collaboration helps, and
accumulate institutional knowledge across every project. See
[`CLAUDE.md`](CLAUDE.md) for the architectural overview and [`docs/`](docs/) for
the full design.

Murmurent can be used as a standalone agentic AI OS environment, as a means to integrate
members of the same lab, or as a means of intergrating labs and core facilities across
a centre or University.

> **Stuck on any step below?** Once you've installed [Claude Code](https://claude.com/claude-code),
> you can just *ask it*. Murmurent wires its own docs and CLI into Claude Code, so
> "walk me through installing Murmurent", "did my install work?", or "how do I
> issue a member card?" all work — Claude Code can run many of these steps for you.

## Download Murmurent

**Everyone — member, PI, or mayor — starts by installing murmurent.** The code is
public; one command does it (you only need `git`):

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/murmurent/main/scripts/bootstrap.sh | bash
```

This installs the `murmurent` command, wires the shared agents/rules/skills into `~/.claude/`, and
registers the data-governance hooks. On your first run it mints your **identity
key** (your unique ID). Then set your personal info — `murmurent whoami` shows your
handle + key, and the dashboard (`murmurent dashboard --hifi`) has the rest.

There are three ways a user interacts with Murmurent:
(i) through the `murmurent` CLI
(ii) through interactions (e.g. skills) defined in Claude Code
(iii) through a Dashboard (not discussed here).

**Everyone runs this next — set up your identity:**

```bash
murmurent init          # sets your handle, name, email, GitHub (choose member / PI / mayor)
```

`init` mints your identity key and records your handle/name/email/GitHub; everything
else builds on it, whether or not you ever join a lab. (For a lab member, the next
step further down — `enroll` — packages exactly those details into your request: your
email + GitHub are how your PI adds you to the lab's Slack channel and GitHub repo.
Skip `init` and `enroll` has nothing to send.)

## You're ready to run Murmurent locally

That's it — Murmurent now runs on your machine, no PI or centre required. The
agents, the Oracle memory, and the data-governance guardrails all work standalone.

**New here? Start with the walkthrough:
[`docs/getting_started.md`](docs/getting_started.md).** It's a short set of worked
examples showing what Murmurent adds on top of Claude Code alone — delegating to
the specialist agents, giving the Oracle a memory that survives across sessions and
projects, and letting the guardrails catch mistakes before they happen. Read that
before the full architecture in [`CLAUDE.md`](CLAUDE.md).

To go further — joining or running a lab, a core, or a centre — find your situation
below.

## I'm a member of a lab whose PI already uses murmurent

You need a **membership ID** (a signed identity certificate) from your **PI**
to include you in the lab or core. You've already run `murmurent init` (see
[Download Murmurent](#download-murmurent) above) — that's the prerequisite; now:

1. Request your ID:
   ```bash
   murmurent enroll --group <your-lab> --out enroll.json
   ```
   Send the output file `enroll.json` to your PI —
   DM it to them directly on Slack.
2. The PI then runs `murmurent issue-member-card` against
   your request. Murmurent will DM the signed bundle
   back to you.
3. Save what you received as a file (e.g. `bundle.json`). It looks like this
   (trimmed):
   ```json
   {
     "member_card": {
       "payload": {"subject": {"handle": "@allie", "fingerprint": "SHA256:jo8Aqfe6In..."}, "group": "xia_lab"},
       "signature": "..."
     },
     "pi_card": {
       "payload": {"subject": {"handle": "@yxia266", "pubkey": "ed25519:Rgmuqeen5X3lW4pFV8GHVFafw0ozSxGk+uUeLC279Fw="}},
       "signature": "..."
     }
   }
   ```
   The **trust root** is that `pubkey` value inside `pi_card` —
   `ed25519:Rgmuqeen5X3lW4pFV8GHVFafw0ozSxGk+uUeLC279Fw=`. It's a short
   string, not a file, and murmurent deliberately won't just read it out of
   the bundle for you — a forged bundle could claim any key it likes, so you
   must be told the real one independently and pass it explicitly:
   ```bash
   murmurent import-card bundle.json --trust-root ed25519:Rgmuqeen5X3lW4pFV8GHVFafw0ozSxGk+uUeLC279Fw=
   ```
   The first time, confirm that trust-root value with your PI out-of-band
   (in person or by phone, not the same Slack message) before you rely on it.
4. Confirm it worked — you don't need to keep the output:
   ```bash
   murmurent whoami        # now lists your group and role
   ```
   `import-card` stores the verified card locally, so from now on murmurent
   knows you're a member of the lab. If your dashboard is open, restart it to
   pick up the new role.

## I'm a PI registering my lab or core with an existing centre

If your institution already runs a murmurent centre, you don't self-issue your
own ID — you send the centre's mayor an **encrypted join request**, and they send
you back a signed **PI ID**. You've already run `murmurent init` and chose **PI**
(see [Download Murmurent](#download-murmurent) above); now:

1. Find your centre in the public **implementations directory** —
   [`murmurent_public`](https://github.com/hallettmiket/murmurent_public) lists
   every institution running murmurent, the address to send join requests to, and
   the public key your request is encrypted to. If your institution isn't listed,
   it may not run murmurent yet — ask your lab manager or run it standalone (you're
   already set up above).
2. Run the join script. It asks a few questions, encrypts your request to your
   centre's key, and opens your email app ready to send:
   ```sh
   curl -fsSL -O https://raw.githubusercontent.com/hallettmiket/murmurent_public/main/join/murmurent-join.sh
   sh murmurent-join.sh
   ```
   The request is encrypted to your centre's registrar — only they can read it,
   and nothing about you is posted publicly. Press **Send**. *(Prefer to do it by
   hand? The plain form lives at [`join/join-form.txt`](https://github.com/hallettmiket/murmurent_public/blob/main/join/join-form.txt).)*
3. Once the mayor approves, they send your **PI ID** back to import — the same
   `murmurent import-card <bundle> --trust-root <centre-trust-root>` flow a member
   uses (see the member section above). Confirm the trust-root value with the mayor
   out-of-band before you rely on it. See [`docs/identity.md`](docs/identity.md)
   for the full flow.

Once you hold your PI ID, you are your lab's certificate authority — continue
with the next section to connect Slack and start issuing member IDs.

## I'm a PI of a lab or core

You are your lab's certificate authority.

1. You already ran `murmurent init` and chose **PI** (see
   [Download Murmurent](#download-murmurent) above). `init` asked for your lab's
   short name and then **offered to self-issue your PI ID on the spot** (the
   default) — that is what makes you your lab's root and prints a **trust root**
   (your public signing key, the anchor members pin so they can verify any card
   you sign). **If you accepted that prompt, this step is already done.** Only if
   you declined it (or want to redo it) do you run the standalone command — it does
   exactly the same self-issue:
   ```bash
   murmurent pi-init <your-lab>
   ```
2. Connect your lab's Slack. This lets member IDs travel by DM instead
   of by hand:
   ```bash
   murmurent group-slack-setup <your-lab>
   ```
   Full details regarding creating the Slack app with security scopes, etc.:
   [`docs/group_slack_setup.md`](docs/group_slack_setup.md).
3. Accept members by issuing them IDs. A member runs `murmurent enroll
   --group <your-lab>` and gets instructions to send you the resulting
   request (e.g. a Slack DM). Once you have it:
   ```bash
   murmurent issue-member-card <their-request> --group <your-lab>
   ```
   This automatically DMs the signed bundle back to the member — pass
   `--dm <slack_user_id>` if you already know their Slack id, or `--no-dm`
   to skip Slack and just print the bundle. If Slack isn't connected, or
   the member's Slack account can't be found, it falls back to printing
   the bundle for you to send yourself. Either way, the member finishes
   with `murmurent import-card <bundle> --trust-root <your-trust-root>`.

Full identity flow (enroll → issue → import → revoke): [`docs/identity.md`](docs/identity.md).

## I have a lab or core and want to join a centre

Your lab or core **already exists** — you created it when you ran `murmurent init`
(and self-issued your PI ID) above. Joining a centre simply *affiliates that
existing group* with an institution's murmurent centre. It does **not** create a
new group and it does **not** disturb your standalone setup: your roster, your
members' cards, and your day-to-day all keep working. You gain a **centre-signed
PI/leader ID** on top of your own key, and the centre's mayor gains cross-lab
coordination.

1. Send a join request to the centre's mayor. One script gathers the details,
   encrypts them to the mayor's key, and opens your email — nothing leaves your
   machine until you press Send:
   ```bash
   curl -fsSL -O https://raw.githubusercontent.com/hallettmiket/murmurent_public/main/join/murmurent-join.sh
   sh murmurent-join.sh
   ```
   Pick your institution, then answer **lab** or **core**, your group's short name
   (the one you used at `init`, e.g. `mh`), and your handle. (This script is for
   PIs/leaders only — members get their card from their PI via `import-card`, above.)
2. The mayor approves, registers your group with the centre, and sends you a
   **centre-signed PI card**. Import it, pinning the centre's trust root the first
   time (confirm that value with the mayor out-of-band):
   ```bash
   murmurent import-card <pi-bundle.json> --trust-root <centre-signing-key>
   ```
3. Done — your group is now part of the centre. Nothing about your existing lab
   changed except that your key now also chains to the centre's root; your
   members' cards keep verifying exactly as before.

## I want to run murmurent at my institution (become the mayor)

You already ran `murmurent init` and chose **mayor** (see
[Download Murmurent](#download-murmurent) above). That sets your identity but does
**not** create the centre — `init` deliberately just points you to the next step.
You then bootstrap a new **centre** with `murmurent centre-init` (or the dashboard's
registrar form) and become its founding registrar — see the details below — after
which you register PIs and send each one their ID.

---

## Setting up a centre (mayor)

You'll need:

- **[Claude Code](https://claude.com/claude-code)** — installed and logged in once (OAuth).
- **[GitHub CLI `gh`](https://cli.github.com/)**, authenticated (`gh auth login`) —
  for the centre's GitHub org/repos.
- **[uv](https://docs.astral.sh/uv/)** — the installer adds it if missing.

After running `bootstrap.sh` (above), bootstrap the centre:

```bash
murmurent dashboard --hifi --port 8771
# open http://localhost:8771/registrar and fill in the one-time setup form
```

...or headlessly. Only `--name` and `--institution` are required; everything else
is optional and can be filled in later from the dashboard or with
`murmurent centre-set`. A fully-worked example:

```bash
murmurent centre-init \
  --name "Western Bioconvergence Centre" \
  --institution "Western University" \
  --mayor @tbrowne \
  --unique-name western \
  --join-email murmurent-western@uwo.ca \
  --slack-workspace T0WESTERN \
  --github-org centre-westernu \
  --public-hub github.com/hallettmiket/murmurent_public#western \
  --server-host biodatsci.schulich.uwo.ca \
  --server-account murmurent \
  --cc-install-path /opt/claude \
  --mayor-root /mayor/western \
  --obsidian-vault /mayor/obsidian \
  --raw-root /data/western/raw \
  --refined-root /data/western/refined
murmurent centre-status      # confirms you are the founding registrar
```

Each parameter, with an example:

| Flag | What it is | Example |
|---|---|---|
| `--name` *(required)* | Display name of the centre | `"Western Bioconvergence Centre"` |
| `--institution` *(required)* | Hosting institution | `"Western University"` |
| `--mayor` | Your `@handle` (defaults to `$MURMURENT_USER`, then the OS user) | `@tbrowne` |
| `--unique-name` | Short, institution-agnostic id — drives repo / Slack / group names | `western` |
| `--join-email` | Public address PIs send join requests to (listed in the directory) | `murmurent-western@uwo.ca` |
| `--slack-workspace` | Your Slack workspace / team id (the `T…` id) | `T0WESTERN` |
| `--github-org` | The centre's GitHub org / dedicated account | `centre-westernu` |
| `--public-hub` | Global onboarding hub + this centre's label | `github.com/hallettmiket/murmurent_public#western` |
| `--server-host` | The always-online, ssh-gated murmurent server | `biodatsci.schulich.uwo.ca` |
| `--server-account` | SSH login account on that server | `murmurent` |
| `--cc-install-path` | Where Claude Code lives on the server | `/opt/claude` |
| `--mayor-root` | High-level mayor dir (mirrorable to GitHub) | `/mayor/western` |
| `--obsidian-vault` | Centre-level Obsidian / markdown pool | `/mayor/obsidian` |
| `--raw-root` | Centre `raw/` root on the data server | `/data/western/raw` |
| `--refined-root` | Centre `refined/` root on the data server | `/data/western/refined` |

`--data-server` is a legacy alias of `--server-host`. Add `--no-prompt` for
scripted / server runs, and `--no-sentinel` when running under `sudo` or in CI.

### Make your centre joinable

`centre-init` creates the centre. In the following, we do not assume
that perspective members already belong to a Slack workspace.
The next steps are as follows:

1. Encryption key for join requests. `centre-init` generates an `age` keypair
   automatically so that PIs can encrypt their join requests to it; recreate with
   `murmurent centre-age-keygen`.
2. Root signing key (the identity CA). `murmurent centre-root-keygen` — signs PI
   IDs + the revocation list. Back it up offline (see
   [`docs/centre_root_key.md`](docs/centre_root_key.md)).
3. List your centre in the implementations directory: `murmurent centre-hub-publish`
   clones [`murmurent_public`](https://github.com/hallettmiket/murmurent_public),
   writes your directory row, and publishes your signing key + revocation list
   so members can verify IDs. It prints a `git push` for you to run.
4. Set up Slack. Create a `wigamig-<unique-name>` workspace + bot token and
   smoke-test with `murmurent centre-slack-smoke`. Guide:
   [`docs/slack_setup.md`](docs/slack_setup.md).


## Install (developer)

Working on murmurent itself (not deploying a centre):

```bash
git clone https://github.com/hallettmiket/murmurent
cd murmurent
uv sync --extra dev
uv run murmurent --help
```

## Running tests

```bash
uv run pytest
```

## Authors

Mike Hallett &mdash; michael.hallett@uwo.ca
