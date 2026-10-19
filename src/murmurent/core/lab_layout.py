"""
Purpose: The lab's folder protocol (issue #206): what each folder at the top of
         the lab's data root is for, how its subfolders are named, and a check
         that reports anything that does not follow it, for the PI to decide.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-18
Input: the data root (``$MURMURENT_DATA_ROOT``; for example a lab's
       ``/data/lab_xx`` on its server); the lab's projects and member logins;
       optionally ``policy/lab_folders.yaml`` in the lab records repository.
Output: :data:`DEFAULT_FOLDERS`, :func:`folders` and :func:`check`, a list of
        :class:`LayoutFinding` in plain words.

The protocol, as Mike set it out on #206. Each top-level folder has one kind:

- ``immutable/`` (formerly ``raw/``): original data. A file is placed once and
  is then read-only, at most readable by the project. One subfolder per project.
- ``append_only/`` (formerly ``refined/``): a project's analyses and
  intermediate files too large for GitHub. New files and new versions are
  added; nothing is overwritten or deleted. One subfolder per project.
- ``modifiable/``: a project's working data that may change. One subfolder
  per project.
- ``mothballed/``: files waiting to go to long-term storage, after which they
  are removed from the server. People move files here; no agent changes them.
  One subfolder per project.
- ``release/``: the lab's private copy of published papers and software. One
  subfolder per project.
- ``cottage/``: each person's home away from home for large files (conda
  environments, for example), since home folders are small. One subfolder per
  person, named by their login.
- ``tools/``: tools of general use to the lab.
- ``db/``: databases of use to several people.

Folders being phased out (``campervans/``, ``envs/``, ``sandbox/``) are
reported so they shrink over time. Anything else at the top, including loose
files, is reported as unexpected. murmurent never moves, renames or deletes
anything to fix these: it tells the PI.

A lab with a different layout writes its own in ``policy/lab_folders.yaml``:

    folders:
      immutable: per-project
      scratch: shared
    phasing_out: [old_stuff]

Kinds: ``per-project``, ``per-person``, ``shared``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

PER_PROJECT = "per-project"
PER_PERSON = "per-person"
SHARED = "shared"
KINDS = (PER_PROJECT, PER_PERSON, SHARED)


@dataclass(frozen=True)
class Folder:
    name: str
    kind: str
    purpose: str
    legacy_of: str = ""       # "raw" is the former name of "immutable"


DEFAULT_FOLDERS: tuple[Folder, ...] = (
    Folder("immutable", PER_PROJECT, "original data; read-only once placed"),
    Folder("append_only", PER_PROJECT, "analyses and large intermediate files; added to, never overwritten or deleted"),
    Folder("modifiable", PER_PROJECT, "working data that may change"),
    Folder("mothballed", PER_PROJECT, "waiting to go to long-term storage, then removed from the server; people only"),
    Folder("release", PER_PROJECT, "private copy of published papers and software"),
    Folder("cottage", PER_PERSON, "each person's large files (conda environments, for example), one folder per login"),
    Folder("tools", SHARED, "tools of general use to the lab"),
    Folder("db", SHARED, "databases used by several people"),
    Folder("raw", PER_PROJECT, "former name of immutable/", legacy_of="immutable"),
    Folder("refined", PER_PROJECT, "former name of append_only/", legacy_of="append_only"),
)
DEFAULT_PHASING_OUT: tuple[str, ...] = ("campervans", "envs", "sandbox")

LAYOUT_FILE = "lab_folders.yaml"


def _lab_layout_file(env: dict | None = None) -> Path | None:
    try:
        from .millwright_policy import lab_policy_path
        policy = lab_policy_path(env)
    except Exception:  # noqa: BLE001
        return None
    return policy.parent / LAYOUT_FILE if policy is not None else None


def folders(env: dict | None = None) -> tuple[dict[str, Folder], set[str]]:
    """``({name: Folder}, phasing_out)`` for this lab: the defaults, or the
    lab's own ``policy/lab_folders.yaml`` when it has one. A name in a
    ``.yaml`` matches case-insensitively."""
    known = {f.name: f for f in DEFAULT_FOLDERS}
    phasing = set(DEFAULT_PHASING_OUT)
    path = _lab_layout_file(env)
    if path is not None and path.is_file():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            data = {}
        if isinstance(data.get("folders"), dict):
            known = {}
            for name, kind in data["folders"].items():
                kind = str(kind).strip().lower()
                if kind in KINDS:
                    old = next((f for f in DEFAULT_FOLDERS if f.name == str(name)), None)
                    known[str(name).lower()] = Folder(str(name).lower(), kind,
                                                       old.purpose if old else "",
                                                       old.legacy_of if old else "")
        if isinstance(data.get("phasing_out"), list):
            phasing = {str(n).lower() for n in data["phasing_out"]}
    return known, phasing


@dataclass(frozen=True)
class LayoutFinding:
    kind: str          # unexpected | phasing-out | loose-file | not-a-project | not-a-person | both-names
    path: str
    detail: str        # one plain sentence for the PI

    def to_dict(self) -> dict:
        return {"kind": self.kind, "path": self.path, "detail": self.detail}


def _entries(folder: Path) -> list[Path]:
    try:
        return sorted(p for p in folder.iterdir() if not p.name.startswith("."))
    except OSError:
        return []


def check(root: Path, *, projects: set[str], logins: set[str],
          env: dict | None = None) -> list[LayoutFinding]:
    """Compare the data root with the protocol. Reads folder names only."""
    root = Path(root)
    known, phasing = folders(env)
    out: list[LayoutFinding] = []
    proj = {p.lower() for p in projects}
    people = {u.lower() for u in logins}
    present: set[str] = set()
    for entry in _entries(root):
        name = entry.name.lower()
        if entry.is_file():
            out.append(LayoutFinding("loose-file", str(entry),
                f"{entry.name} is a file at the top of the lab folder; files belong "
                "inside a project's folder or a person's cottage."))
            continue
        if not entry.is_dir() or entry.is_symlink():
            continue
        if name in phasing:
            out.append(LayoutFinding("phasing-out", str(entry),
                f"{entry.name}/ is being phased out; ask its owners to move what they "
                "still need into a project's folders or their cottage."))
            continue
        folder = known.get(name)
        if folder is None:
            out.append(LayoutFinding("unexpected", str(entry),
                f"{entry.name}/ is not one of the lab's folders; ask what it is for, then "
                "move it under one of them or add it to the protocol."))
            continue
        present.add(folder.legacy_of or folder.name)
        if folder.legacy_of and (root / folder.legacy_of).is_dir():
            out.append(LayoutFinding("both-names", str(entry),
                f"{entry.name}/ and {folder.legacy_of}/ both exist; {entry.name}/ is the "
                f"former name. `murmurent data migrate` moves it across."))
        for child in _entries(entry):
            if not child.is_dir() or child.name.startswith("."):
                # Loose files are normal in a shared folder (installers in
                # tools/), not in a folder of project or person subfolders.
                if child.is_file() and folder.kind != SHARED:
                    out.append(LayoutFinding("loose-file", str(child),
                        f"{entry.name}/{child.name} is a file directly inside {entry.name}/; "
                        "it belongs in a subfolder."))
                continue
            low = child.name.lower()
            if folder.kind == PER_PROJECT and proj and low not in proj:
                out.append(LayoutFinding("not-a-project", str(child),
                    f"{entry.name}/{child.name}/ does not match any project's name; rename "
                    "it to its project, or make a project for it."))
            elif folder.kind == PER_PERSON and people and low not in people:
                out.append(LayoutFinding("not-a-person", str(child),
                    f"{entry.name}/{child.name}/ does not match any lab member's login."))
    return out


def describe(findings: list[LayoutFinding]) -> list[str]:
    """Plain lines for the PI, grouped by kind."""
    if not findings:
        return ["The lab folder follows the lab's folder protocol."]
    titles = {"unexpected": "Not one of the lab's folders",
              "phasing-out": "Being phased out",
              "loose-file": "Loose files",
              "not-a-project": "Named after no project",
              "not-a-person": "Named after no lab member",
              "both-names": "Old and new folder names both in use"}
    lines = [f"{len(findings)} thing(s) do not follow the lab's folder protocol:"]
    for kind, title in titles.items():
        items = [f for f in findings if f.kind == kind]
        if items:
            lines.append(f"  {title}:")
            lines += [f"    - {f.detail}" for f in items[:20]]
            if len(items) > 20:
                lines.append(f"    - and {len(items) - 20} more")
    return lines


def lab_projects_and_logins() -> tuple[set[str], set[str]]:
    """Every project name murmurent knows (any lab, since another lab's folder
    is not "named after no project"), and this lab's member logins."""
    names: set[str] = set()
    logins: set[str] = set()
    try:
        from . import cert_projects as _cp
        names = {p.name for p in _cp.iter_projects()}
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import membership as _members
        from .project_access import resolve_member_os_user
        for rec in _members.iter_members(include_inactive=True):
            h = rec.handle.lstrip("@")
            logins.add(resolve_member_os_user(h) or h)
    except Exception:  # noqa: BLE001
        pass
    return names, logins


def present_folders(root: Path, env: dict | None = None) -> list[dict]:
    """For the dashboard: each protocol folder, whether it exists here, its
    kind and purpose."""
    known, _ = folders(env)
    out = []
    for f in known.values():
        out.append({"name": f.name, "kind": f.kind, "purpose": f.purpose,
                    "legacy_of": f.legacy_of, "present": (Path(root) / f.name).is_dir()})
    return out


__all__ = ["DEFAULT_FOLDERS", "DEFAULT_PHASING_OUT", "Folder", "LayoutFinding", "check",
           "describe", "folders", "lab_projects_and_logins", "present_folders",
           "PER_PROJECT", "PER_PERSON", "SHARED"]
