# Setting up your personal vault

Your **personal vault** is a knowledge base of markdown notes that lives in a
folder on your machine. Murmurent uses the [Obsidian](https://obsidian.md)
application as the basis for the vault: Obsidian is a free note-taking program
that reads and edits a folder of markdown files and provides linking, search,
and a graph view over your notes.

Within the vault, Murmurent recognizes three folders:

- **`oracle/`**: your personal Oracle, the structured findings and decisions
  that the Oracle agent records and retrieves (see
  [The Oracle](oracle-workflow.md)).
- **`lab-notebook/`**: your daily lab-notebook entries.
- **`maps-legends/`**: your own index of the vault, documenting your
  categories and conventions and where things live. It is the
  human-readable guide to your vault; Murmurent's code leaves it entirely to
  you, and Oracle entries may reference it through `[[wikilinks]]`.

Murmurent backs the vault as a private GitHub repository named
`murmurent_vault` on your own GitHub account, so your notes are
version-controlled, survive a lost laptop, and stay in sync across your
machines. The vault folder lives on your machine, where you edit it in
Obsidian, and is pushed to this repository; `murmurent vault init` creates the
repository and the initial folders for you.

New members are offered a vault during `murmurent init`. If you already have an
Obsidian vault with notes in it, you adopt that existing vault rather than
starting fresh (see the two cases below).

## Before you start

- **Install Obsidian.** Murmurent does not install Obsidian for you.
  Download and install it first from [obsidian.md](https://obsidian.md).
  `murmurent vault init` creates the vault folder and its GitHub repository,
  but you open and edit the vault in Obsidian.
- **Authenticate the GitHub CLI.** The vault repository is created on *your*
  GitHub account, so Murmurent acts as you. Run `gh auth login` and answer the
  prompts:

  ```text
  ? What account do you want to log into?  GitHub.com
  ? What is your preferred protocol for Git operations?  HTTPS
  ? Authenticate Git with your GitHub credentials?  Yes
  ? How would you like to authenticate GitHub CLI?  Login with a web browser
  ! First copy your one-time code: XXXX-XXXX
    Press Enter to open github.com in your browser...
  ```

  Confirm it worked:

  ```bash
  gh auth status   # should show: Logged in to github.com as <your-username>
  ```
- Have Murmurent installed and up to date (`murmurent --version`).

## Two cases

**You have NO Obsidian vault yet.** Just run:

```bash
murmurent vault init
```

It creates `murmurent_vault`, scaffolds `oracle/ lab-notebook/ maps-legends/`,
clones it (default `~/repos/murmurent_vault`, or pass `--path` for an iCloud
folder), and pins it.

**You already have an Obsidian vault with notes.** Adopt it. First preview it
(this changes nothing and pushes nothing):

```bash
murmurent vault init --adopt --dry-run --path "/path/to/your/obsidian-vault"
```

The preview shows exactly what would go to GitHub vs stay local. By default
(the **Murmurent scope**), only `oracle/`, `lab-notebook/`, and `maps-legends/`
(plus a `CLAUDE.md`) are tracked; every other folder in your vault (health,
journal, personal notes, …) stays local and is never pushed. Read the list,
then run it for real:

```bash
murmurent vault init --adopt --path "/path/to/your/obsidian-vault"
```

That git-inits your vault, creates the private `murmurent_vault` repo, pushes
only the Murmurent folders, and points Murmurent at it. Your dashboard's Oracle
and Notebook panels do not change: they become git-backed.

## Symlinked vault folders

If your `oracle/` (or `lab-notebook/` / `maps-legends/`) is a **symbolic link**
(e.g. Obsidian pointing at `~/.claude/agent-memory/oracle`), git can't follow
it, so that folder **silently won't get pushed**. After adopting, check:

```bash
git -C "/path/to/your/obsidian-vault" ls-files | sed 's|/.*||' | sort -u
```

If `oracle` is missing from that list but you have oracle notes, it's a symlink.
Make the vault the real home (one copy, backed up, and the old location keeps
working via a reverse symlink). Replace `<VAULT>` and `<REAL>` (the symlink
target from `readlink <VAULT>/oracle`):

```bash
cp -R "<REAL>" ~/oracle_backup            # safety copy first
rm "<VAULT>/oracle"                        # remove the symlink (target untouched)
mv "<REAL>" "<VAULT>/oracle"               # move real content into the vault
ln -s "<VAULT>/oracle" "<REAL>"            # reverse: old path now points at the vault
git -C "<VAULT>" add oracle/ && git -C "<VAULT>" commit -m "vault: add oracle" && git -C "<VAULT>" push
```

## Sensitive notes stay off GitHub

The Murmurent scope already keeps your personal folders local. On top of that, a
git pre-commit hook refuses to commit any note tagged `sensitivity: clinical`:
clinical/PHI-tagged notes never reach GitHub, even a private repo. If you
genuinely want your *whole* vault backed (minus clinical-tagged files), use
`--adopt --include-all` instead, but that pushes your personal folders too, so
only do it deliberately.

## Day to day

- `murmurent vault sync`: commit + push new oracle/notebook entries (best-effort).
- `murmurent vault info`: where the clone is + how fresh it is.
- `murmurent vault paths`: the resolved oracle / lab-notebook / maps-legends
  paths (what the agents consult).

The lab (group) vault is separate: it is the existing lab-mgmt repo,
already shared and synced, and is not set up here.
