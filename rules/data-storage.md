# Data storage — raw is immutable, refined is append-only

All data except very small files in-repo lives under
``$MURMURENT_LAB_VM_ROOT`` (the lab server sets it in the environment):

- **``raw/<project>/``** — original data from the lab, a collaborator,
  or a public resource. **No code may modify these files**, including
  renames. Read-only. Files come in via copy from the source; out
  goes only via copy into ``refined/``.
- **``refined/<project>/<experiment>/``** — outputs of analyses run
  by the project. Mirrors the structure of
  ``~/repos/<project>/exp/<experiment>/`` so the relationship between
  code and its data is obvious.

## Rules enforced by hooks

The murmurent CC hooks (registered by ``murmurent install --hooks``)
block these operations:

- **Any write under ``raw/``** — via
  [`raw_guard`](../src/murmurent/hooks/raw_guard.py). Covers Write,
  Edit, NotebookEdit, and Bash commands that rename, redirect,
  truncate, chmod, or delete files under raw.
- **Delete or overwrite under ``refined/``** — via
  [`protected_paths`](../src/murmurent/hooks/protected_paths.py).
  *New files* under refined/ are allowed (it's append-only); the
  hook only blocks operations that mutate something that already
  exists there.

If you need to genuinely supersede a refined file, follow the lab
versioning convention: write ``file_2.csv`` instead of overwriting
``file_1.csv``. Add the old version to ``ready_to_delete.md`` in
the project's ``src/`` directory.

## Versioning

When there are multiple versions of the same file (code, data, or
analysis), use an integer suffix: ``file_1.csv``, ``file_2.csv``,
…. The largest integer is always the most recent version. Old
versions move to obsolete folders (or get listed in
``ready_to_delete.md``); they're not silently overwritten.

## ``ready_to_delete.md``

Each project's ``src/`` directory should contain a
``ready_to_delete.md`` listing refined files / obsolete code
considered safe to garbage-collect. This is the manifest the
reconciliation routine reads before sweeping.
