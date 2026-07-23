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

## Data tiering & residency

The data root is a **per-machine** resource, not a synced one:
``$MURMURENT_DATA_ROOT`` resolves locally on each box, and the
``raw_guard`` + ``protected_paths`` hooks enforce immutability /
append-only **on the machine where the data physically lives**. There is
no notion of replicating it across machines, by design. Repos sync via
GitHub and the personal vault syncs via git; the data root is **reached,
not replicated**.

Residency follows sensitivity tier:

- **Tier-3 (clinical, and very large genomic) data is server-resident.**
  It stays on a lab server and is **reached over the network** — an SSH
  session on the server, an ``sshfs`` / remote mount, or running the
  experiment on the server via VS Code Remote-SSH — with
  ``$MURMURENT_DATA_ROOT`` pointing at the server-side tree. It is
  **never replicated onto a laptop**: multi-GB binaries are the wrong
  payload for git/GitHub regardless, and clinical data must not land on a
  portable device at all.
- **Tier-1 / derived small outputs** may live in ``append_only/`` on a
  laptop for offline work and be copied up to the server later. This is
  the only tier that is expected to appear on a portable machine's data
  root.

### Enforcement (preflight)

Registering a project's data root on a machine runs a residency preflight
(`core.preflight.probe_tier3_residency`). It combines two facts:

- the **machine ROLE** — ``laptop`` vs ``host`` — from
  `core.machine_registry.machine_kind` (the same role the Wave-2 machine
  badge shows: an explicit ``$MURMURENT_MACHINE_ROLE`` override, else a
  hostname ending in ``server`` ⇒ host, else laptop); and
- the **project sensitivity** — ``standard | restricted | clinical`` from
  `cert_projects.CertProject.sensitivity`.

On a **laptop**, binding a **clinical / tier-3** project's data root is
**refused** with: *"clinical/tier-3 data must stay on a server; reach it
over SSH, don't replicate it to a laptop."* On a **host / server** it is
allowed (that is the data root's proper home). Standard / restricted
tiers are unrestricted on any machine — the guard is non-blocking for
them. The refusal is a required-fail probe surfaced at the
project-workspace-initialize step; it is never silently dropped.
