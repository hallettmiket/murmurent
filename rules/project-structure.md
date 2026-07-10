# Project structure

Every murmurent project ``<project>`` lives in three coordinated
locations that share the same name:

| Location | Contents |
|---|---|
| ``~/repos/<project>/`` | working git clone (code) |
| ``$WIGAMIG_LAB_VM_ROOT/raw/<project>/`` | raw inputs (read-only) |
| ``$WIGAMIG_LAB_VM_ROOT/refined/<project>/`` | analysis outputs (append-only) |

The lab's GitHub org (``hallettmiket`` by default) hosts a private
repo with the same name. Working clones are git-aware; the raw/
refined dirs are filesystem-only (no git).

## Naming

- **snake_case** everywhere, where possible.
- One project per name. Use it for the repo, the GitHub repo, the
  raw dir, the refined dir, and the lab_mgmt registry entry. No
  re-use across projects.

## Repo subdirectories

Inside ``~/repos/<project>/``:

| Dir | Purpose |
|---|---|
| ``exp/`` | per-experiment code (one subdir each: ``z_good_name``, integer + meaningful slug) |
| ``src/`` | code shared across experiments (init helpers, common utilities) |
| ``obsolete/`` | code no longer used but not yet deleted |
| ``data/`` | tiny in-repo files (anything >100 KB-ish goes to ``refined/``) |

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

## Refined mirrors exp

The structure of ``$WIGAMIG_LAB_VM_ROOT/refined/<project>/``
mirrors ``~/repos/<project>/exp/``:

```
~/repos/<project>/exp/3_qc/run_all.py
                          │
                          └─▶ writes to
                              $WIGAMIG_LAB_VM_ROOT/refined/<project>/3_qc/...
```

That way the relationship between code and its data is one
``cd`` away.

## Sub-experiments / output kinds

Inside ``refined/<project>/<experiment>/`` you can split by
sub-experiment or by output kind (``figures/``, ``tables/``,
``pkl/``) — whatever makes the directory listing self-evident
to someone walking in cold.
