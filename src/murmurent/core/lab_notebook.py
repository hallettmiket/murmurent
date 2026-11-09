"""
Purpose: The personal lab notebook's two streams (issues #292, #293, #294):
         the member's own daily notes in ``<vault>/<notebook_subfolder>/``
         and the record of what was said to Claude Code in
         ``<vault>/sessions/<date>/``. Resolves where both live, writes
         entries and prompts, migrates pasted prompts out of old entries,
         and knows each entry's audience.
Author:  Mike Hallett (with Claude Code)
Date:    2026-11-07
Input:   The personal vault on this machine (``$MURMURENT_VAULT_ROOT``, else
         the registered vault, else the most recently opened Obsidian vault).
Output:  Markdown files under the vault; nothing outside it.

The notes stream is what the oracle's ``notebook`` tier reads; the sessions
stream is the new ``sessions`` tier. Both stay in the personal vault. A
session file is never published to the lab oracle, because a prompt can
carry a patient identifier or a secret pasted for a one-off.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import sensitivity as _sens
from .frontmatter import dump_document, split_frontmatter

ENV_VAULT = "MURMURENT_VAULT_ROOT"
ENV_NOTEBOOK = "MURMURENT_NOTEBOOK_DIR"
ENV_SESSIONS = "MURMURENT_SESSIONS_DIR"
DEFAULT_NOTEBOOK_SUBFOLDER = "lab-notebook"
SESSIONS_SUBFOLDER = "sessions"
ATTACHMENTS_SUBFOLDER = "attachments"
OBSOLETE_SUBFOLDER = "obsolete"
REPORTS_SUBFOLDER = "reports"
PASTED_NAME = "pasted.md"

#: Who may read an entry. ``me`` is the default and never leaves the vault.
AUDIENCE_ME = "me"
AUDIENCE_SUPERVISOR = "supervisor"
AUDIENCE_LAB = "lab"
AUDIENCE_PROJECT_PREFIX = "project:"
FIXED_AUDIENCES: tuple[str, ...] = (AUDIENCE_ME, AUDIENCE_SUPERVISOR, AUDIENCE_LAB)

DATE_RE = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})(?:_(?P<slug>.+))?$")


class NotebookError(RuntimeError):
    """The notebook cannot be found or written."""


# ---------------------------------------------------------------------------
# Where things live
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NotebookPaths:
    """Every folder the notebook uses, all inside one personal vault."""

    vault: Path
    notebook: Path
    sessions: Path
    attachments: Path
    obsolete: Path
    reports: Path

    def rel(self, path: Path) -> str:
        """``path`` relative to the vault, as an Obsidian link target."""
        try:
            return path.resolve().relative_to(self.vault.resolve()).as_posix()
        except ValueError:
            return str(path)


def notebook_subfolder() -> str:
    """The notes folder's name inside the vault (``lab-notebook`` unless the
    machine settings say otherwise)."""
    try:
        from ..dashboard import machine_settings as _ms  # noqa: PLC0415

        sub = _ms.load().notebook_subfolder
        if sub:
            return str(sub)
    except Exception:  # noqa: BLE001 - machine settings are best-effort
        pass
    return DEFAULT_NOTEBOOK_SUBFOLDER


def vault_root() -> Path | None:
    """The personal vault on this machine, or ``None`` when none is known.

    Order: ``$MURMURENT_VAULT_ROOT``; the parent of ``$MURMURENT_NOTEBOOK_DIR``;
    the vault registered in the machine settings; the most recently opened
    Obsidian vault.
    """
    pin = os.environ.get(ENV_VAULT, "").strip()
    if pin:
        return Path(pin).expanduser()
    nb = os.environ.get(ENV_NOTEBOOK, "").strip()
    if nb:
        return Path(nb).expanduser().parent
    try:
        from . import vault_sync as _vs  # noqa: PLC0415

        root = _vs.personal_vault_root()
        if root is not None:
            return root
    except Exception:  # noqa: BLE001
        pass
    try:
        from . import obsidian as _obsidian  # noqa: PLC0415

        v = _obsidian.preferred_vault()
        if v is not None:
            return v.path
    except Exception:  # noqa: BLE001
        pass
    return None


def resolve_paths(root: Path | None = None) -> NotebookPaths | None:
    """All notebook folders for the vault at ``root`` (default: this
    machine's). ``None`` when no vault is known. Creates nothing."""
    vault = root or vault_root()
    if vault is None:
        return None
    nb = os.environ.get(ENV_NOTEBOOK, "").strip()
    notebook = Path(nb).expanduser() if (nb and root is None) else vault / notebook_subfolder()
    se = os.environ.get(ENV_SESSIONS, "").strip()
    sessions = Path(se).expanduser() if (se and root is None) else vault / SESSIONS_SUBFOLDER
    return NotebookPaths(
        vault=vault,
        notebook=notebook,
        sessions=sessions,
        attachments=vault / ATTACHMENTS_SUBFOLDER,
        obsolete=vault / OBSOLETE_SUBFOLDER,
        reports=vault / REPORTS_SUBFOLDER,
    )


def require_paths() -> NotebookPaths:
    paths = resolve_paths()
    if paths is None:
        raise NotebookError(
            "no personal vault is known on this machine: run `murmurent vault init`, "
            "or set MURMURENT_VAULT_ROOT to the vault folder"
        )
    return paths


# ---------------------------------------------------------------------------
# Entries (the notes stream)
# ---------------------------------------------------------------------------


def entry_path(paths: NotebookPaths, date: str) -> Path:
    """Today's entry: ``<notebook>/<date>.md`` (the flat layout)."""
    return paths.notebook / f"{date}.md"


def read_entry(path: Path) -> tuple[dict[str, Any], str]:
    """``(frontmatter, body)`` of an entry. Missing frontmatter reads as ``{}``."""
    text = path.read_text(encoding="utf-8")
    raw_meta, body = split_frontmatter(text)
    if raw_meta is None:
        return {}, text
    try:
        meta = yaml.safe_load(raw_meta) or {}
    except yaml.YAMLError:
        return {}, text
    return (meta if isinstance(meta, dict) else {}), body


def ensure_entry(
    path: Path,
    *,
    date: str,
    project: str = "general",
    sensitivity: str = "standard",
    audience: str = AUDIENCE_ME,
    tags: list[str] | None = None,
) -> bool:
    """Create the entry with its frontmatter when it does not exist. Returns
    True when it was created. An existing entry is left exactly as it is: the
    notebook is not a form, and nothing here rewrites what a person wrote."""
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "title": date,
        "date": date,
        "project": project or "general",
        "sensitivity": _sens.normalize(sensitivity) or "standard",
        "audience": audience or AUDIENCE_ME,
        "tags": list(tags or []),
    }
    body = f"# {date}\n\nSessions: [[{SESSIONS_SUBFOLDER}/{date}]]\n"
    path.write_text(dump_document(meta, body), encoding="utf-8")
    return True


def append_block(path: Path, lines: list[str]) -> None:
    """Add ``lines`` at the end of an entry, separated by one blank line."""
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    path.write_text(existing + "\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")


def time_heading(when: _dt.datetime, label: str = "") -> str:
    stamp = when.strftime("%H:%M")
    return f"## {stamp} {label}".rstrip()


# ---------------------------------------------------------------------------
# Sessions (the prompts stream)
# ---------------------------------------------------------------------------


def session_file(paths: NotebookPaths, date: str, session_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", session_id or "unknown")[:80] or "unknown"
    return paths.sessions / date / f"{safe}.md"


def _fence_for(text: str) -> str:
    """A backtick fence longer than any run of backticks in ``text``, so the
    prompt is stored verbatim whatever it contains."""
    longest = max((len(m.group(0)) for m in re.finditer(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def record_prompt(
    paths: NotebookPaths,
    *,
    session_id: str,
    prompt: str,
    when: _dt.datetime,
    project: str = "",
    repository: str = "",
    commit: str = "",
    sensitivity: str = "standard",
) -> Path:
    """Append one prompt to the session's file, creating it with frontmatter
    on the first prompt. Returns the file."""
    date = when.strftime("%Y-%m-%d")
    path = session_file(paths, date, session_id)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = {
            "title": f"Claude Code session {session_id} on {date}",
            "date": date,
            "project": project or "general",
            "sensitivity": _sens.normalize(sensitivity) or "standard",
            "audience": AUDIENCE_ME,
            "tags": ["session"],
            "sources": [],
            "stream": "sessions",
            "session": session_id,
        }
        body = f"# Session {session_id}\n\nNotes for the day: [[{notebook_subfolder()}/{date}]]\n"
        path.write_text(dump_document(meta, body), encoding="utf-8")
    fence = _fence_for(prompt)
    lines = [
        f"## {when.strftime('%H:%M:%S')}",
        f"- project: {project or '(none)'}",
        f"- repository: {repository or '(none)'}",
        f"- commit: {commit or '(none)'}",
        "",
        f"{fence}text",
        prompt.rstrip("\n"),
        fence,
    ]
    append_block(path, lines)
    return path


# ---------------------------------------------------------------------------
# Audience
# ---------------------------------------------------------------------------


def audiences_of(meta: dict[str, Any]) -> list[str]:
    """The entry's audience list, normalised. Missing or empty means ``me``."""
    raw = meta.get("audience")
    if raw is None or raw == "":
        return [AUDIENCE_ME]
    values = raw if isinstance(raw, list) else [raw]
    out: list[str] = []
    for v in values:
        s = str(v).strip().lower()
        if s and s not in out:
            out.append(s)
    return out or [AUDIENCE_ME]


def is_valid_audience(value: str) -> bool:
    v = (value or "").strip().lower()
    if v in FIXED_AUDIENCES:
        return True
    return v.startswith(AUDIENCE_PROJECT_PREFIX) and len(v) > len(AUDIENCE_PROJECT_PREFIX)


def audience_admits(entry_audiences: list[str], reader: str) -> bool:
    """Whether a reader named by ``--for`` may see an entry.

    ``supervisor`` sees what is marked for the supervisor and what is marked
    for the whole lab; ``lab`` sees only what is marked for the lab; a project
    sees only what is marked for that project. ``me`` is never a reader, so an
    entry with no audience never leaves the vault.
    """
    r = (reader or "").strip().lower()
    if r == AUDIENCE_ME or not r:
        return False
    for a in entry_audiences:
        if a == r:
            return True
        if r == AUDIENCE_SUPERVISOR and a == AUDIENCE_LAB:
            return True
    return False


# ---------------------------------------------------------------------------
# Split: move pasted prompts out of old entries
# ---------------------------------------------------------------------------

#: A block this long, in the second person, is a prompt someone pasted by hand.
PROMPT_MIN_CHARS = 200
_SECOND_PERSON = re.compile(
    r"\b(you|your|you're|yours|please|claude|cc)\b", re.IGNORECASE
)
_IMPERATIVE_START = re.compile(
    r"^\s*(?:>\s*)?(?:please\s+)?(?:write|make|add|implement|fix|create|update|read|check|"
    r"run|look|do|change|move|rename|refactor|build|draft|explain|find|review|"
    r"remove|delete|rewrite|open|use|go|tell|show|list|give|put|don't|do not|never)\b",
    re.IGNORECASE,
)


def looks_like_prompt(block: str) -> bool:
    """Whether a paragraph reads as an instruction to Claude Code rather than
    a note: long, and addressed to a second person or opening with an order."""
    text = block.strip()
    if len(text) < PROMPT_MIN_CHARS:
        return False
    if text.startswith("#") or text.startswith("```"):
        return False
    hits = len(_SECOND_PERSON.findall(text))
    return hits >= 2 or (hits >= 1 and bool(_IMPERATIVE_START.match(text)))


def split_blocks(body: str) -> list[str]:
    """Paragraphs of ``body``, keeping fenced code together even when it
    contains blank lines. Blank-line separators are kept at the end of the
    block they follow, so joining the blocks reproduces the text."""
    blocks: list[str] = []
    current: list[str] = []
    in_fence = False
    for line in body.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
        current.append(line)
        if not in_fence and stripped == "" and any(l.strip() for l in current):
            blocks.append("".join(current))
            current = []
    if current:
        blocks.append("".join(current))
    return blocks


@dataclass
class SplitMove:
    """One entry's pasted prompts and where they go."""

    entry: Path
    date: str
    blocks: list[str] = field(default_factory=list)
    target: Path | None = None
    obsolete_copy: Path | None = None

    @property
    def chars(self) -> int:
        return sum(len(b) for b in self.blocks)


def entry_date(path: Path, meta: dict[str, Any]) -> str:
    """The entry's date: frontmatter, else the filename, else ``undated``."""
    d = meta.get("date")
    if d:
        return str(d)[:10]
    m = DATE_RE.match(path.stem)
    return m.group("date") if m else "undated"


def _versioned(path: Path) -> Path:
    """``path`` if free, else ``name_2``, ``name_3``: nothing is overwritten."""
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1


def plan_split(paths: NotebookPaths) -> list[SplitMove]:
    """Every entry with prompt-shaped blocks, and where each would go."""
    moves: list[SplitMove] = []
    if not paths.notebook.is_dir():
        return moves
    for entry in sorted(paths.notebook.rglob("*.md")):
        if entry.name in {"README.md", "index.md", "MEMORY.md"}:
            continue
        try:
            meta, body = read_entry(entry)
        except (OSError, UnicodeDecodeError):
            continue
        prompts = [b for b in split_blocks(body) if looks_like_prompt(b)]
        if not prompts:
            continue
        date = entry_date(entry, meta)
        rel = entry.relative_to(paths.notebook)
        moves.append(SplitMove(
            entry=entry,
            date=date,
            blocks=prompts,
            target=paths.sessions / date / PASTED_NAME,
            obsolete_copy=_versioned(paths.obsolete / paths.notebook.name / rel),
        ))
    return moves


def apply_split(paths: NotebookPaths, moves: list[SplitMove]) -> list[str]:
    """Carry out ``moves``: copy the original under ``obsolete/``, append the
    prompt blocks to ``sessions/<date>/pasted.md``, rewrite the entry without
    them and with a link to where they went. Deletes nothing. Returns one
    line per entry saying what moved."""
    report: list[str] = []
    for mv in moves:
        meta, body = read_entry(mv.entry)
        assert mv.obsolete_copy is not None and mv.target is not None
        mv.obsolete_copy.parent.mkdir(parents=True, exist_ok=True)
        mv.obsolete_copy.write_bytes(mv.entry.read_bytes())

        mv.target.parent.mkdir(parents=True, exist_ok=True)
        if not mv.target.exists():
            tmeta = {
                "title": f"Prompts pasted into the notebook on {mv.date}",
                "date": mv.date,
                "project": str(meta.get("project") or "general"),
                "sensitivity": _sens.normalize(meta.get("sensitivity")) or "standard",
                "audience": AUDIENCE_ME,
                "tags": ["session", "pasted"],
                "sources": [],
                "stream": "sessions",
            }
            mv.target.write_text(
                dump_document(tmeta, f"# Pasted prompts, {mv.date}\n"), encoding="utf-8")
        moved_lines = [f"## From [[{notebook_subfolder()}/{mv.entry.stem}]]", ""]
        for b in mv.blocks:
            moved_lines.append(b.rstrip("\n"))
            moved_lines.append("")
        append_block(mv.target, moved_lines)

        kept = "".join(b for b in split_blocks(body) if b not in mv.blocks)
        link = f"Pasted prompts moved to [[{SESSIONS_SUBFOLDER}/{mv.date}/{Path(PASTED_NAME).stem}]]\n"
        new_body = kept.rstrip("\n") + "\n\n" + link
        if meta:
            mv.entry.write_text(dump_document(meta, new_body), encoding="utf-8")
        else:
            mv.entry.write_text(new_body, encoding="utf-8")
        report.append(
            f"{paths.rel(mv.entry)}: moved {len(mv.blocks)} block(s), {mv.chars} characters, "
            f"to {paths.rel(mv.target)}; original kept at {paths.rel(mv.obsolete_copy)}"
        )
    return report


__all__ = [
    "NotebookError", "NotebookPaths", "resolve_paths", "require_paths", "vault_root",
    "notebook_subfolder", "entry_path", "read_entry", "ensure_entry", "append_block",
    "time_heading", "session_file", "record_prompt", "audiences_of", "is_valid_audience",
    "audience_admits", "looks_like_prompt", "split_blocks", "plan_split", "apply_split",
    "SplitMove", "entry_date", "SESSIONS_SUBFOLDER", "ATTACHMENTS_SUBFOLDER",
    "AUDIENCE_ME", "AUDIENCE_SUPERVISOR", "AUDIENCE_LAB", "AUDIENCE_PROJECT_PREFIX",
]
