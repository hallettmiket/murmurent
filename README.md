# Murmurent

Shared agentic-AI infrastructure for academic researchers, labs cores and research centers. 
It lets research groups work independently, pool agents and data when collaboration helps, and
accumulate institutional knowledge across every project. **Documentation: <https://hallettmiket.github.io/murmurent/>** (install,
getting-started vignettes, the agents, labs and centres, the CLI manual).
[`CLAUDE.md`](CLAUDE.md) is the architectural overview Claude Code itself loads.

Murmurent can be used as a standalone agentic AI OS environment, as a means to integrate
members of the same lab, or as a means of integrating labs and core facilities across
a centre or University.

> **Stuck on any step below?** Once you've installed [Claude Code](https://claude.com/claude-code),
> you can just *ask it*. Murmurent wires its own docs and CLI into Claude Code, so
> "walk me through installing Murmurent", "did my install work?", or "how do I
> issue a member card?" all work — Claude Code can run many of these steps for you.

## [Everyone] Download Murmurent

Two ways in. Both end up in the same place; pick one.

### A. From PyPI (recommended)

Nothing to clone, and you never pipe a script into your shell. If you don't
have [uv](https://docs.astral.sh/uv/) yet, install it first — one line:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # skip if you have uv
```

Then:

```bash
uv tool install murmurent
murmurent install
```

If your shell can't find `murmurent` afterwards, close and reopen your terminal
(uv puts it in `~/.local/bin`).

### B. One command

Only needs `git`. This one installs uv for you if it's missing:

```bash
curl -fsSL https://raw.githubusercontent.com/hallettmiket/murmurent/main/scripts/bootstrap.sh | bash
```

To read the installer before running it, clone the repo first and run
`scripts/bootstrap.sh` from inside it.

Either way you need **Python 3.12 or newer**; uv downloads one automatically if
your system hasn't got it, so you don't need to install Python yourself.

This installs the `murmurent` command, wires the shared agents/rules/skills into `~/.claude/`, and
registers the data-governance hooks. On your first run it mints your **identity
key** (your unique ID). Then set your personal info — `murmurent whoami` shows your
handle + key.

### Check the install, any time

```bash
murmurent doctor
```

It checks the Python version, that `pip` and `python` on your PATH belong to the
same interpreter Murmurent runs under, the agent/rule/skill links in `~/.claude/`,
the registered hooks, and (for a clone) that `git pull` will work. Every problem
it finds comes with the one command that fixes it.

### Upgrading

Installed from PyPI:

```bash
uv tool upgrade murmurent
murmurent install
```

Installed from a clone:

```bash
cd ~/repos/murmurent && git pull
uv tool install --python 3.12 --reinstall -e .
murmurent install
```

Then, either way:

```bash
murmurent doctor                 # confirms the upgrade landed
murmurent repo upgrade --all     # brings every Murmurent-ready directory up to the new release
```

Use `uv` for the reinstall. It installs into the interpreter Murmurent already
runs under. The `pip` on your PATH can belong to a different Python (a conda
`base` environment, for example), and then it either installs into the wrong
place or stops with `Package 'murmurent' requires a different Python`.


## Two repositories: which one am I looking at?

| | |
|---|---|
| [**`murmurent`**](https://github.com/hallettmiket/murmurent) | **Releases.** One commit per release, no development history. This is what you install, and what the instructions above clone. |
| [**`murmurent_dev`**](https://github.com/hallettmiket/murmurent_dev) | **Development.** All history, issues, pull requests and design discussion. Has a `DEVELOPING.md` the release does not. |
| [**`murmurent_public`**](https://github.com/hallettmiket/murmurent_public) | **The public directory.** The list of every institution running Murmurent and how to join it, and the **index of all published choreographies** ([`choreographies.tsv`](https://github.com/hallettmiket/murmurent_public/blob/main/choreographies.tsv)): the shared workflows you can install by name with `murmurent choreography list` and `murmurent choreography install <name>`. |

The first two share this README, so the quickest way to tell them apart is the
file list: if you can see `DEVELOPING.md` and a `tests/` directory, you are in
`murmurent_dev`.

- **Using murmurent?** Install from either the PyPI or the one-command route
  above; both give you the latest release.
- **Reporting a bug or asking for a feature?**
  [Open an issue on `murmurent_dev`](https://github.com/hallettmiket/murmurent_dev/issues).
  The release repo has issues turned off, because the discussion belongs where
  the work happens.
- **Working on murmurent itself?** Clone `murmurent_dev` and read its
  [`DEVELOPING.md`](https://github.com/hallettmiket/murmurent_dev/blob/main/DEVELOPING.md):
  dev setup, what `rules/local/` is for, the pre-push checks, and how a release
  is cut. **Do not** develop against the release repo — it has no tests and no
  history.


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
[Getting started](https://hallettmiket.github.io/murmurent/getting_started/).


## [Everyone] Initialize a directory for Murmurent

Murmurent works inside a **repository**: a directory tracked by git, kept under
`~/repos/`. Making a directory **Murmurent-ready** wires the shared agents and
rules into it, so Claude Code sessions opened there can use them. The same
procedure covers a brand-new folder, a repository you have worked in for years,
and one that an older Murmurent release set up. Start by asking, because the
answer decides the step:

```bash
murmurent repo status ~/repos/<directory>
```

| Verdict | What it means | Do this |
|---|---|---|
| `not a git repo` | a plain folder | `git -C ~/repos/<directory> init`, then the next row |
| `plain clone` or `partial` | git, and Murmurent has never set it up | `murmurent repo adopt ~/repos/<directory>` |
| `ready`, bootstrapped by an older version | ready, and newer agents are missing | `murmurent repo upgrade ~/repos/<directory> --all-agents` |
| `ready`, current version | finished | open Claude Code in it |

Adopting writes a `.murmurent.yaml` marker and a `.claude/agents/` folder of
symlinks into the commons, and leaves every other file as it was. Commit both,
so each clone of the repository is ready as well. `murmurent repo list` shows
the verdict for every repository on the machine, and `murmurent repo upgrade
--all` upgrades all of them at once. Details, and how ready repositories are
attached to a project: [Making a repo Murmurent-ready](https://hallettmiket.github.io/murmurent/ready_vs_projects/).


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

5. Clone your lab's governance repository. Your card proves *who you are*;
   the roster of everyone else — and the lab's projects, compliance records,
   and shared Oracle — lives in a separate private repository that every
   member holds a read-only clone of. Ask your PI for its name, then:
   ```bash
   git clone git@github.com:<org>/murmurent_lab_mgmt_<lab>.git \
       ~/repos/murmurent_lab_mgmt_<lab>
   murmurent member list   # should now show the whole lab, not just you
   ```
   Without this clone, `murmurent member list` and the dashboard's members
   panel have nothing to read and will tell you so. Keep it current with
   `git pull` (or the dashboard's **update** button); the PI pushes roster
   changes there. See [The lab-mgmt repo](https://hallettmiket.github.io/murmurent/lab_mgmt/).


## [PIs] If you are a PI of a lab or core ...

Once you have completed your `init`, you need to set up some infrastructure 
for your members.

1. Connect your lab's Slack. This lets member IDs travel by DM instead
   of by hand:
   ```bash
   murmurent group-slack-setup <your-lab>
   ```
   Full details regarding creating the Slack app with security scopes, etc.:
   [Group Slack setup](https://hallettmiket.github.io/murmurent/group_slack_setup/).
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

Full identity flow (enroll → issue → import → revoke): [Membership IDs and the trust chain](https://hallettmiket.github.io/murmurent/identity/).


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
   [The centre root key](https://hallettmiket.github.io/murmurent/centre_root_key/)).
3. List your centre in the implementations directory: `murmurent centre-hub-publish`
   clones [`murmurent_public`](https://github.com/hallettmiket/murmurent_public),
   writes your directory row, and publishes your signing key + revocation list
   so members can verify IDs. It prints a `git push` for you to run.
4. Set up Slack. Create a `murmurent-<unique-name>` workspace + bot token and
   smoke-test with `murmurent centre-slack-smoke`. Guide:
   [Centre Slack setup](https://hallettmiket.github.io/murmurent/slack_setup/).


## Authors

Mike Hallett &mdash; michael.hallett@uwo.ca
