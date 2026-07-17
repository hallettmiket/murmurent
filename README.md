# Murmurent

Shared agentic-AI infrastructure for academic researchers, labs cores and research centers. 
It lets research groups work independently, pool agents and data when collaboration helps, and
accumulate institutional knowledge across every project. See
[`CLAUDE.md`](CLAUDE.md) for the architectural overview and [`docs/`](docs/) for
the full design.

Murmurent can be used as a standalone agentic AI OS environment, as a means to integrate
members of the same lab, or as a means of integrating labs and core facilities across
a centre or University.

> **Stuck on any step below?** Once you've installed [Claude Code](https://claude.com/claude-code),
> you can just *ask it*. Murmurent wires its own docs and CLI into Claude Code, so
> "walk me through installing Murmurent", "did my install work?", or "how do I
> issue a member card?" all work — Claude Code can run many of these steps for you.

## [Everyone] Download Murmurent

Start by installing murmurent. The code is public; one command does it (you only need `git`):

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/murmurent/main/scripts/bootstrap.sh | bash
```

This installs the `murmurent` command, wires the shared agents/rules/skills into `~/.claude/`, and
registers the data-governance hooks. On your first run it mints your **identity
key** (your unique ID). Then set your personal info — `murmurent whoami` shows your
handle + key.


## [Everyone] Set up your identity

```bash
murmurent init          # sets your handle, name, email, official handle, GitHub, Slack (choose member / PI / mayor)
```

The `init` records who you are: your handle/name/email/official (institutional)
handle/GitHub/Slack; everything else builds on it, whether or not you ever
join a lab/core. 
You have a choice to be either (i) a user (termed a 'member'), (ii) a PI who leads 
a lab or core facility, or (iii) a mayor who runs a centre (which consists of multiple labs
and cores). You have to specify one of these three options during the `init` procedure.

You're ready to run Murmurent locally. Several vignettes can help get you started
[`docs/getting_started.md`](docs/getting_started.md).


## Federating individuals, groups and centres 

Murmurent allows members to join labs or cores, and it allows labs/cores to join centres. 
This is based on cryptographic identity cards that establish your identity and "right to belong".

## [Members] If you are a member of a lab whose PI already uses murmurent

You need a **membership ID** (a signed identity certificate) from your PI
to include you in the lab or core. You need to be in the Slack workspace of your
PI. You will also need the official name of your lab or core.

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
   string.
   Confirm that trust-root value with your PI out-of-band
   (in person or by phone, not the same Slack message).
   You must pass it explicitly in the `import-card` command next:
   ```bash
   murmurent import-card bundle.json --trust-root ed25519:Rgmuqeen5X3lW4pFV8GHVFafw0ozSxGk+uUeLC279Fw=
   ```
   
4. Confirm it worked — you don't need to keep the output:
   ```bash
   murmurent whoami        # now lists your group and role
   ```
   `import-card` stores the verified card locally, so from now on Murmurent
   knows you're a member of the lab. 


## [PIs] If you are a PI of a lab or core ...

Once you have completed your `init`, you need to set up some infrastructure 
for your members.

1. Connect your lab's Slack. This lets member IDs travel by DM instead
   of by hand:
   ```bash
   murmurent group-slack-setup <your-lab>
   ```
   Full details regarding creating the Slack app with security scopes, etc.:
   [`docs/group_slack_setup.md`](docs/group_slack_setup.md).
2. Accept members by issuing them IDs. A member runs `murmurent enroll
   --group <your-lab>` and gets instructions to send you the resulting
   request (e.g. a Slack DM). Once you have it:
   ```bash
   murmurent issue-member-card <their-request> --group <your-lab>
   ```
   This automatically DMs the signed bundle back to the member — pass
   `--dm <slack_user_id>` if you already know their Slack id, or `--no-dm`
   to skip Slack and just print the bundle. The member finishes
   with `murmurent import-card <bundle> --trust-root <your-trust-root>`.

Full identity flow (enroll → issue → import → revoke): [`docs/identity.md`](docs/identity.md).


## [PIs] If you are a PI registering your lab or core with an existing centre

If you want to join an existing Murmurent centre, you send the centre's mayor 
an **encrypted join request**, and they send
you back a signed **PI ID**. Now:

1. Find your centre in the public **implementations directory** —
   [`murmurent_public`](https://github.com/hallettmiket/murmurent_public) lists
   every institution running Murmurent, the address to send join requests to, and
   the public key your request is encrypted to. If your institution isn't listed,
   it may not run Murmurent yet.
2. Run the join script. It asks a few questions, encrypts your request to your
   centre's key, and opens your email app ready to send:
   ```sh
   curl -fsSL -O https://raw.githubusercontent.com/hallettmiket/murmurent_public/main/join/murmurent-join.sh
   sh murmurent-join.sh
   ```
   The request is encrypted to your centre's Mayor — only they can read it,
   and nothing about you is posted publicly. Press **Send**. 
3. Once the mayor approves, they send your **PI ID** back for you to import:
   ```bash
   murmurent import-card <bundle> --trust-root <centre-trust-root>
   ```
   Confirm the trust-root value with the mayor
   out-of-band before you rely on it. 

Once you hold your PI ID, you are your lab's certificate authority.



## [Mayors] If you want to establish a new Murmurent centre at your institution as the Mayor...

You'll need:

- **[Claude Code](https://claude.com/claude-code)** — installed and logged in once (OAuth).
- **[GitHub CLI `gh`](https://cli.github.com/)**, authenticated (`gh auth login`) —
  for the centre's GitHub org/repos.
- **[uv](https://docs.astral.sh/uv/)** — the installer adds it if missing.

You bootstrap a new centre with 
```bash
murmurent centre-init
```
and become its founding registrar — see the details below.
Only `--name` and `--institution` are required; everything else
is optional and can be filled in later from the dashboard or with
`murmurent centre-set`. A fully-worked example:

```bash
murmurent centre-init \
  --name "Example Bioconvergence Centre" \
  --institution "Example University" \
  --mayor @the_mayor \
  --unique-name example \
  --join-email murmurent-join@example.edu \
  --slack-workspace T0EXAMPLE \
  --github-org centre-example \
  --public-hub github.com/hallettmiket/murmurent_public#example \
  --server-host lab-server.example.edu \
  --server-account murmurent \
  --cc-install-path /opt/claude \
  --mayor-root /mayor/example \
  --obsidian-vault /mayor/obsidian \
  --raw-root /data/example/raw \
  --refined-root /data/example/refined
murmurent centre-status      # confirms you are the founding registrar
```

Each parameter, with an example:

| Flag | What it is | Example |
|---|---|---|
| `--name` *(required)* | Display name of the centre | `"Example Bioconvergence Centre"` |
| `--institution` *(required)* | Hosting institution | `"Example University"` |
| `--mayor` | Your `@handle` (defaults to `$MURMURENT_USER`, then the OS user) | `@the_mayor` |
| `--unique-name` | Short, institution-agnostic id — drives repo / Slack / group names | `example` |
| `--join-email` | Public address PIs send join requests to (listed in the directory) | `murmurent-join@example.edu` |
| `--slack-workspace` | Your Slack workspace / team id (the `T…` id) | `T0EXAMPLE` |
| `--github-org` | The centre's GitHub org / dedicated account | `centre-example` |
| `--public-hub` | Global onboarding hub + this centre's label | `github.com/hallettmiket/murmurent_public#example` |
| `--server-host` | The always-online, ssh-gated murmurent server | `lab-server.example.edu` |
| `--server-account` | SSH login account on that server | `murmurent` |
| `--cc-install-path` | Where Claude Code lives on the server | `/opt/claude` |
| `--mayor-root` | High-level mayor dir (mirrorable to GitHub) | `/mayor/example` |
| `--obsidian-vault` | Centre-level Obsidian / markdown pool | `/mayor/obsidian` |
| `--raw-root` | Centre `raw/` root on the data server | `/data/example/raw` |
| `--refined-root` | Centre `refined/` root on the data server | `/data/example/refined` |

`--data-server` is a legacy alias of `--server-host`. Add `--no-prompt` for
scripted / server runs, and `--no-sentinel` when running under `sudo` or in CI.

### Make your centre joinable

We cannot assume
that prospective members already belong to the Centre's Slack workspace.
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
4. Set up Slack. Create a `murmurent-<unique-name>` workspace + bot token and
   smoke-test with `murmurent centre-slack-smoke`. Guide:
   [`docs/slack_setup.md`](docs/slack_setup.md).


## Authors

Mike Hallett &mdash; michael.hallett@example.edu
