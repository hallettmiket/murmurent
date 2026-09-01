# Project structure

Every murmurent project ``<project>`` lives in three coordinated
locations that share the same name:

| Location | Contents |
|---|---|
| ``~/repos/<project>/`` | working git clone (code) |
| ``$MURMURENT_DATA_ROOT/immutable/<project>/`` | original source inputs (read-only) |
| ``$MURMURENT_DATA_ROOT/append_only/<project>/`` | analysis outputs (append-only) |

The lab's GitHub org (``hallettmiket`` by default) hosts a private
repo with the same name. Working clones are git-aware; the
immutable/append_only dirs are filesystem-only (no git). (The legacy
names ``raw/``/``refined/`` and ``MURMURENT_LAB_VM_ROOT`` remain
recognized during the transition; run ``murmurent data migrate`` to
rename an existing root.)

## Naming

- **snake_case** everywhere, where possible.
- One project per name. Use it for the repo, the GitHub repo, the
  immutable dir, the append_only dir, and the lab_mgmt registry entry.
  No re-use across projects.

## Repo subdirectories

Inside ``~/repos/<project>/``:

| Dir | Purpose |
|---|---|
| ``exp/`` | per-experiment code (one subdir each: ``z_good_name``, integer + meaningful slug) |
| ``src/`` | code shared across experiments (init helpers, common utilities) |
| ``obsolete/`` | code no longer used but not yet deleted |
| ``data/`` | tiny in-repo files (anything >100 KB-ish goes to ``append_only/``) |

Each ``exp/<n>_<name>/`` subdir holds an experiment. Convention:
``run_all.R`` / ``run_all.py`` / ``run_all.ipynb`` is the entry
point — the first thing a new reader opens. Each experiment
should carry a ``README.md`` explaining purpose + parameters
(conda env, expected runtime, etc.).

## ``src/`` is shared-across-experiments

``src/`` is for code that multiple experiments need:

- R: ``init.R`` (sourced from each ``exp/<n>/run_all.R``).
- Python: an ``Init`` class (or module) that defines paths +
  global constants for the project.

Keep this minimal — heavy logic belongs in the experiment that
uses it.

## append_only mirrors exp

The structure of ``$MURMURENT_DATA_ROOT/append_only/<project>/``
mirrors ``~/repos/<project>/exp/``:

```
~/repos/<project>/exp/3_qc/run_all.py
                          │
                          └─▶ writes to
                              $MURMURENT_DATA_ROOT/append_only/<project>/3_qc/...
```

That way the relationship between code and its data is one
``cd`` away.

## Sub-experiments / output kinds

Inside ``append_only/<project>/<experiment>/`` you can split by
sub-experiment or by output kind (``figures/``, ``tables/``,
``pkl/``) — whatever makes the directory listing self-evident
to someone walking in cold.
