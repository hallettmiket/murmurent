# Data storage: the immutable and append_only directories

All data except very small files in-repo lives under
``$MURMURENT_DATA_ROOT`` (set in the environment by the data host). The
directory names state the guarantee the hooks enforce:

- **``immutable/<project>/``**: original source data from the lab, a
  collaborator, or a public resource. **No code may modify these files**,
  including renames. Read-only. Files come in via copy from the source;
  out goes only via copy into ``append_only/``.
- **``append_only/<project>/<experiment>/``**: outputs of analyses run by
  the project. New files may be added, but existing files are never
  overwritten or deleted. Mirrors the structure of
  ``~/repos/<project>/exp/<experiment>/`` so the relationship between code
  and its data is obvious.

By convention, ``immutable/`` holds original source data and
``append_only/`` holds derived outputs, but the names describe only the
enforced guarantee. Any other subdirectory under ``$MURMURENT_DATA_ROOT``
carries no hooks.

**Transition note.** The previous directory names ``raw/`` and ``refined/``,
and the previous environment variable ``MURMURENT_LAB_VM_ROOT``, remain
recognized during a deprecation window, so existing deployments keep
working. New code and scaffolding use ``immutable/``, ``append_only/``, and
``MURMURENT_DATA_ROOT``. Run ``murmurent data migrate`` to rename an
existing data root.

## Rules enforced by hooks

The murmurent CC hooks (registered by ``murmurent install --hooks``) block
these operations:

- **Any write under ``immutable/``** (or legacy ``raw/``), via
  [`raw_guard`](../src/murmurent/hooks/raw_guard.py). Covers Write, Edit,
  NotebookEdit, and Bash commands that rename, redirect, truncate, chmod,
  or delete files under it.
- **Delete or overwrite under ``append_only/``** (or legacy ``refined/``),
  via [`protected_paths`](../src/murmurent/hooks/protected_paths.py). New
  files are allowed (it is append-only); the hook only blocks operations
  that mutate something that already exists there.

If you need to genuinely supersede an append_only file, follow the lab
versioning convention: write ``file_2.csv`` instead of overwriting
``file_1.csv``. Add the old version to ``ready_to_delete.md`` in the
project's ``src/`` directory.

## Versioning

When there are multiple versions of the same file (code, data, or
analysis), use an integer suffix: ``file_1.csv``, ``file_2.csv``, …. The
largest integer is always the most recent version. Old versions move to
obsolete folders (or get listed in ``ready_to_delete.md``); they are not
silently overwritten.

## ``ready_to_delete.md``

Each project's ``src/`` directory should contain a ``ready_to_delete.md``
listing append_only files and obsolete code considered safe to
garbage-collect. This is the manifest the reconciliation routine reads
before sweeping.
