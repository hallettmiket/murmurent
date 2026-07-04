"""Prepare this centre's listing in the public ``wigamig_public`` hub.

A brand-new mayor is listed on the public directory by adding one row to
``join/directory.tsv`` (machine-readable, read by ``wigamig-join.sh``) and one
row to the README table (human-readable). This module automates the mechanical
parts — clone the hub if it isn't already local, then add/update the centre's
row in both files — but deliberately stops **before** ``git commit``/``push``:
publishing to a public repo stays the mayor's explicit act.

Design notes
------------
- Git calls go through an injectable ``runner`` (defaults to ``subprocess.run``)
  so the clone path is unit-testable without a network.
- ``upsert_*`` are idempotent: re-running updates the centre's existing row
  (matched by exact label, by age recipient, or by replacing a not-live
  placeholder for the same institution) rather than appending duplicates.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HUB_REMOTE = "https://github.com/hallettmiket/wigamig_public.git"


class HubPublishError(RuntimeError):
    """Raised for actionable hub-publish failures (bad state, clone error)."""


@dataclass
class HubPublishResult:
    hub_dir: Path
    cloned: bool
    directory_action: str          # "added" | "updated" | "unchanged"
    readme_action: str             # "added" | "updated" | "unchanged"
    row: str                       # the directory.tsv row (institution\temail\tkey)


def default_hub_dir() -> Path:
    """Where the mayor's working clone of the public hub lives."""
    return Path.home() / "repos" / "wigamig_public"


def directory_label(institution: str, name: str) -> str:
    """The directory's institution column: ``Institution (Centre name)``."""
    institution = (institution or "").strip()
    name = (name or "").strip()
    return f"{institution} ({name})" if name else institution


# ---------------------------------------------------------------------------
# clone
# ---------------------------------------------------------------------------

def ensure_hub_clone(hub_dir: Path, remote: str = DEFAULT_HUB_REMOTE,
                     *, runner=subprocess.run) -> bool:
    """Clone the hub into ``hub_dir`` if it isn't already a git checkout.

    Returns True if a clone happened, False if an existing clone was reused.
    Raises HubPublishError if ``hub_dir`` exists but isn't a git clone.
    """
    if (hub_dir / ".git").is_dir():
        return False
    if hub_dir.exists() and any(hub_dir.iterdir()):
        raise HubPublishError(
            f"{hub_dir} exists but is not a git clone — move it aside and retry."
        )
    hub_dir.parent.mkdir(parents=True, exist_ok=True)
    proc = runner(["git", "clone", remote, str(hub_dir)],
                  capture_output=True, text=True)
    if proc.returncode != 0:
        raise HubPublishError(
            f"git clone {remote} failed: {(proc.stderr or '').strip() or 'unknown error'}"
        )
    return True


# ---------------------------------------------------------------------------
# directory.tsv
# ---------------------------------------------------------------------------

def _is_placeholder_row(cols: list[str], institution: str) -> bool:
    """A not-live row for the same institution (label present, email/key blank)."""
    if not cols:
        return False
    label = cols[0].strip()
    same_inst = label == institution.strip() or label.startswith(institution.strip() + " (")
    live = len(cols) >= 3 and cols[1].strip() and cols[2].strip()
    return same_inst and not live


def upsert_directory(hub_dir: Path, institution: str, name: str,
                     email: str, recipient: str) -> str:
    """Add/update the centre's row in ``join/directory.tsv``.

    Returns "added", "updated", or "unchanged".
    """
    path = hub_dir / "join" / "directory.tsv"
    if not path.is_file():
        raise HubPublishError(f"directory.tsv not found at {path}")

    label = directory_label(institution, name)
    row = f"{label}\t{email}\t{recipient}"
    lines = path.read_text(encoding="utf-8").splitlines()

    matched_idx = None
    for i, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cols = line.split("\t")
        first = cols[0].strip()
        if first == label or (len(cols) >= 3 and cols[2].strip() == recipient) \
                or _is_placeholder_row(cols, institution):
            matched_idx = i
            break

    if matched_idx is not None:
        if lines[matched_idx] == row:
            return "unchanged"
        action = "updated"
        lines[matched_idx] = row
    else:
        action = "added"
        # drop a trailing blank line, append the row, keep a final newline
        while lines and not lines[-1].strip():
            lines.pop()
        lines.append(row)

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return action


# ---------------------------------------------------------------------------
# README table
# ---------------------------------------------------------------------------

def _md_cells(line: str) -> list[str]:
    """Cells of a markdown table row ``| a | b | c |`` -> [a, b, c]."""
    s = line.strip()
    if not s.startswith("|"):
        return []
    parts = s.split("|")[1:-1]        # drop the leading/trailing empties
    return [p.strip() for p in parts]


def upsert_readme(hub_dir: Path, institution: str, name: str,
                  email: str, recipient: str) -> str:
    """Add/update the centre's row in the README's institutions table.

    Table columns: ``Institution | Installation | Email to join | age key``.
    Returns "added", "updated", or "unchanged".
    """
    path = hub_dir / "README.md"
    if not path.is_file():
        raise HubPublishError(f"README.md not found at {path}")

    lines = path.read_text(encoding="utf-8").splitlines()
    row = f"| {institution} | {name} | {email} | {recipient} |"

    # Locate the table: header row containing "Installation", then a separator
    # ("|---|"), then data rows until a non-"|" line.
    header_idx = None
    for i, line in enumerate(lines):
        cells = _md_cells(line)
        if cells and any(c.lower() == "installation" for c in cells):
            header_idx = i
            break
    if header_idx is None:
        raise HubPublishError("could not find the institutions table in README.md")

    sep_idx = header_idx + 1
    if sep_idx >= len(lines) or set(lines[sep_idx].replace("|", "").strip()) - set("-: ") != set():
        raise HubPublishError("institutions table separator row not found in README.md")

    # data rows
    data_start = sep_idx + 1
    data_end = data_start
    while data_end < len(lines) and lines[data_end].strip().startswith("|"):
        data_end += 1

    matched_idx = None
    for i in range(data_start, data_end):
        cells = _md_cells(lines[i])
        if len(cells) < 4:
            continue
        inst_c, inst_i, email_c, key_c = cells[0], cells[1], cells[2], cells[3]
        is_placeholder = inst_c == institution and key_c.startswith("_(")
        if inst_i == name or recipient in key_c or is_placeholder:
            matched_idx = i
            break

    if matched_idx is not None:
        if lines[matched_idx].strip() == row:
            return "unchanged"
        lines[matched_idx] = row
        action = "updated"
    else:
        lines.insert(data_end, row)
        action = "added"

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return action


# ---------------------------------------------------------------------------
# orchestrator
# ---------------------------------------------------------------------------

def prepare_listing(*, institution: str, name: str, email: str, recipient: str,
                    hub_dir: Path | None = None, remote: str = DEFAULT_HUB_REMOTE,
                    runner=subprocess.run) -> HubPublishResult:
    """Clone-if-needed + upsert both files. Does NOT commit or push."""
    for field, val in (("institution", institution), ("name", name),
                       ("join_email", email), ("age_recipient", recipient)):
        if not (val or "").strip():
            raise HubPublishError(
                f"centre profile is missing {field!r}; "
                "set it (age key via `wigamig centre-age-keygen`) before publishing."
            )
    hub_dir = hub_dir or default_hub_dir()
    cloned = ensure_hub_clone(hub_dir, remote, runner=runner)
    dir_action = upsert_directory(hub_dir, institution, name, email, recipient)
    readme_action = upsert_readme(hub_dir, institution, name, email, recipient)
    return HubPublishResult(
        hub_dir=hub_dir, cloned=cloned,
        directory_action=dir_action, readme_action=readme_action,
        row=f"{directory_label(institution, name)}\t{email}\t{recipient}",
    )
