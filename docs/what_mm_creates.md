# What Murmurent creates

Murmurent creates a small set of git repositories and local files that work
together: some are shared across everyone using Murmurent, some belong to
one lab, and some live only on your own machine.

| Item | Where it lives | What it holds | Owned by |
|---|---|---|---|
| [`hallettmiket/murmurent`](https://github.com/hallettmiket/murmurent) | GitHub (public) | the commons: agents, rules, hooks, MCP servers, CLI, dashboard, shared across the centre | the centre; everyone clones it |
| [`hallettmiket/murmurent_public`](https://github.com/hallettmiket/murmurent_public) | GitHub (public) | the global directory of institutions running Murmurent, plus registrar contacts for join requests | the centre; public |
| `<your-org>/murmurent_lab_mgmt_<lab>` | GitHub (private) | your lab or core's governance repo: roster, project registry (`cert_projects/`), inventory, the lab oracle (curated shared findings), audit records | the PI; members get read access |
| `<you>/murmurent_vault` | GitHub (private) | your personal vault: `oracle/` (your findings), `lab-notebook/` (daily notes), `murmurent_data/` (reference files: PDFs, spreadsheets), `maps-legends/` (your vault index) | you, alone |
| `~/repos/murmurent` | your machine | the working clone of the commons; `~/.claude/agents` and `~/.claude/rules` symlink into it | you, per machine |
| `~/repos/murmurent_lab_mgmt_<lab>` | your machine | the working clone of your lab's governance repo | you, per machine |
| `~/.claude/agents/`, `~/.claude/rules/`, `~/.claude/skills/` | your machine | symlinks into the commons clone, put there by `scripts/setup.sh` | you, per machine |
| `~/.claude/settings.json` | your machine | registered hooks (raw_guard, protected_paths, …) and MCP servers (`murmurent-oracle`, `murmurent-inventory`, …) | you, per machine |
| `~/.claude/agent-memory/` | your machine | per-agent working memory | you, per machine |
| `~/.claude/murmurent-preferences.yaml` | your machine | your personal preference profile (agent defaults you've overridden) | you, per machine |
| `~/.murmurent/machine.yaml` | your machine | this machine's Murmurent configuration | you, per machine |
| `~/.murmurent/keys/` | your machine | your cryptographic identity key material | you, per machine |
| `~/.murmurent/` identity/membership cards | your machine | your signed identity certificate and any lab/core membership cards you've imported | you, per machine |
| `~/.murmurent/lab_info/` | your machine (a registrar's machine, if you run one) | the centre-wide registry: every lab, core, and common SEA in the centre | the registrar |
| `~/.murmurent/agents.log` | your machine | the activity log the dashboard tails | you, per machine |
| your Obsidian personal-vault clone | your machine (or a synced folder, e.g. iCloud) | the working copy of `murmurent_vault`, what you actually read and edit in Obsidian | you |
| `$MURMURENT_LAB_VM_ROOT/raw/`, `$MURMURENT_LAB_VM_ROOT/refined/` | the lab server | bulk project data: `raw/` (immutable originals) and `refined/` (append-only analysis outputs) | the lab; shared by every member |

## Public vs. private, per-machine vs. shared

Two repos are public: `hallettmiket/murmurent` (the commons code, meant to
be read and cloned by anyone) and `hallettmiket/murmurent_public` (the
directory of institutions running Murmurent). Every other GitHub repo above
is private: a lab's governance repo grants read access only to that lab's
members, and a personal vault grants access to no one but its owner.

Everything under `~/repos/`, `~/.claude/`, and `~/.murmurent/` lives on a
single machine and gets set up fresh on each machine you use Murmurent from
(see [`setup.md`](setup.md) for per-machine wiring). The GitHub repos are
what carry your Oracle, notebook, and lab knowledge between machines: clone
the same private repos on a second laptop and Murmurent has the same state
available there. The lab server's `$MURMURENT_LAB_VM_ROOT/{raw,refined}/`
is shared infrastructure the whole lab points at, rather than something each
machine keeps its own copy of.

This page consolidates what was previously split across
[`setup.md`](setup.md)'s "What Murmurent installs on your machine" section
and [`index.md`](index.md)'s Repositories table.
