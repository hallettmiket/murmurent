# The lab folder protocol

A lab keeps its large files in one place on its server, the data root.
The protocol says which folders belong at the top of the data root and what
goes in each, so that everyone, and every agent, puts things in the same
place. murmurent checks the data root against it and tells the PI what does
not follow it. murmurent never moves, renames or deletes anything to fix it.

## The folders

| Folder | What goes in it | Subfolders |
|---|---|---|
| `immutable/` (was `raw/`) | Original data from the lab, a collaborator or a public source. Read-only once placed. | one per project |
| `append_only/` (was `refined/`) | Analyses and intermediate files too large for GitHub. New files and new versions are added; nothing is overwritten or deleted. | one per project |
| `modifiable/` | A project's working data that may change. | one per project |
| `mothballed/` | Files waiting to go to long-term storage, after which they are removed from the server. People move files here; no agent changes them. | one per project |
| `release/` | The lab's private copy of published papers and software. | one per project |
| `cottage/` | Each person's large files, such as conda environments, since home folders are small. | one per person, named by their login |
| `tools/` | Tools of general use to the lab. | shared |
| `db/` | Databases used by several people. | shared |

Nothing else belongs at the top of the data root: no other folders and no
loose files. `campervans/`, `envs/` and `sandbox/` are being phased out, so
do not put anything new in them.

A project's subfolder has the project's own name, for example
`append_only/bc_dcis/`. This is how murmurent knows which project a folder
belongs to.

## Checking the lab folder

On the server, run:

```bash
murmurent space layout
```

It lists, grouped:

- folders that are not part of the protocol;
- folders being phased out;
- loose files, at the top or directly inside a folder of project folders;
- subfolders named after no project, or (in `cottage/`) after no lab member;
- old and new names both in use, for example `raw/` beside `immutable/`.

It reads folder names only, so it takes seconds. The weekly lab scan
(`murmurent space scan-lab`) includes the same list in its report, on the
Space page of the dashboard, and as one line in the PI's Slack summary.

## What the weekly scan does with each folder

- A project's space is the total of its folders in `immutable/`,
  `append_only/`, `modifiable/`, `release/` and `mothballed/`.
- Files in `mothballed/` are counted, but the scan never suggests deleting,
  compressing or mothballing them again.
- Each person's cottage and the shared `tools/` and `db/` folders are
  reported together as "cottages and shared folders", largest first, rather
  than as folders no project claims.

## When something does not follow the protocol

The PI decides. Ask the owner what the folder is for, then either move it
under the right project or person, or add it to the protocol. Agents report;
they do not tidy.

## A lab with a different layout

Write the lab's own layout in `policy/lab_folders.yaml` in the lab records
repository. murmurent then follows that file instead of the table above.

```yaml
folders:            # each folder and its kind: per-project, per-person or shared
  immutable: per-project
  append_only: per-project
  cottage: per-person
  scratch: shared
phasing_out: [old_stuff]
```
