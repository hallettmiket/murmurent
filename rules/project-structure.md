# Project structure

Every murmurent project ``<project>`` lives in three coordinated
locations that share the same name. ``<repos>`` below is this machine's
**repositories folder**: ``~/repos`` unless you chose another
(``murmurent config repos-root`` shows or sets it; people also use
``~/repo`` or ``~/repositories``). Never assume ``~/repos``.

| Location | Contents |
|---|---|
| ``<repos>/<project>/<project>/`` | working git clone (code), inside the project folder |
| ``$MURMURENT_DATA_ROOT/immutable/<project>/`` | original source inputs (read-only) |
| ``$MURMURENT_DATA_ROOT/append_only/<project>/`` | analysis outputs (append-only) |

The lab's GitHub org (``hallettmiket`` by default) hosts a private
repo with the same name. Working clones are git-aware; the
immutable/append_only dirs are filesystem-only (no git). (The legacy
names ``raw/``/``refined/`` and ``MURMURENT_LAB_VM_ROOT`` remain
recognized during the transition; run ``murmurent data migrate`` to
rename an existing root.)

## The project folder

A project is usually several git repositories. Keep them as **separate
repositories** (a manuscript gets hundreds of commits that do not belong in
the code's history), but in **one folder named for the project**, each
keeping its full name:

```
<repos>/<project>/
    <project>/              code: exp/, src/, obsolete/, data/
    <project>_manuscript/   LaTeX, figures, bibliography (often synced with Overleaf)
    <project>_seminar/      slides: PowerPoint, HTML or beamer
```

The full names matter: each is also the GitHub repository's name and its
folder's name under the data root, so moving into a project folder changes
only the location. New projects are made this way. The **flat layout**
(``<repos>/<project>/`` as the code repository, with
``<repos>/<project>_manuscript/`` beside it) stays fully valid: nobody has
to move, and murmurent finds a repository in either layout. To keep new
projects flat: ``murmurent config project-layout flat``. To move an existing
project into a folder: ``murmurent project gather <project>`` (shows its plan
first; this machine only). The lab records repository
(``murmurent_lab_mgmt_<lab>``) belongs to a lab, not a project, and stays
directly in ``<repos>``.

## Naming

- **snake_case** everywhere, where possible.
- One project per name. Use it for the repo, the GitHub repo, the
  immutable dir, the append_only dir, and the lab_mgmt registry entry.
  No re-use across projects.

## Repo subdirectories

Inside the code repository (``<repos>/<project>/<project>/``, or
``<repos>/<project>/`` in the flat layout):

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
mirrors the code repository's ``exp/``:

```
<repos>/<project>/<project>/exp/3_qc/run_all.py
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
