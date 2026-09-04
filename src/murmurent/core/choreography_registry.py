"""
Purpose: read a choreography's self-description, and obtain a choreography from
         a git URL (clone + adopt) so a third party can install one.
Author: Mike Hallett (with Claude Code)
Date: 2026-09-02
Input: a choreography repo's ``.murmurent.yaml``; a git URL or an index name
Output: ChoreographyInfo records; a cloned, murmurent-ready repo

Issue #136. Before this, a third party who installed murmurent had no way to
discover that choreographies existed and no way to obtain one: the only path was
``git clone <url> && murmurent repo adopt``, which requires already knowing the
URL.

A CHOREOGRAPHY DESCRIBES ITSELF. The description is read from the repo's own
``.murmurent.yaml``, never from the index. An index that carried titles and
summaries would be a second copy of each repo's metadata and would drift, and a
stale description advertises a choreography as something it is not. The index
therefore holds locations only; everything a reader is shown comes from the repo.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import repo as _repo

MARKER = ".murmurent.yaml"
KIND = "choreography"


class ChoreographyError(RuntimeError):
    """Raised with a message meant for a person, not a stack trace."""


@dataclass
class ChoreographyInfo:
    """What a choreography says about itself."""

    name: str
    title: str = ""
    summary: str = ""
    mode: str = ""
    target: str = ""
    approaches: list[str] = field(default_factory=list)
    agents: list[str] = field(default_factory=list)
    requires_murmurent: str = ""
    requires_gpu: bool = False
    data_subdir: str = ""
    data_scale: str = ""
    citation: str = ""
    source: str = ""

    @classmethod
    def from_marker(cls, data: dict[str, Any], *, source: str = "") -> ChoreographyInfo:
        req = data.get("requires") or {}
        dat = data.get("data") or {}
        return cls(
            name=str(data.get("name") or ""),
            title=str(data.get("title") or ""),
            summary=" ".join(str(data.get("summary") or "").split()),
            mode=str(data.get("mode") or ""),
            target=str(data.get("target") or ""),
            approaches=[str(a) for a in (data.get("approaches") or [])],
            agents=[str(a) for a in (data.get("agents") or [])],
            requires_murmurent=str(req.get("murmurent") or ""),
            requires_gpu=bool(req.get("gpu")),
            data_subdir=str(dat.get("root_subdir") or ""),
            data_scale=str(dat.get("scale") or ""),
            citation=str(data.get("citation") or ""),
            source=source,
        )


def read_marker(clone: Path) -> ChoreographyInfo:
    """Read ``.murmurent.yaml`` from a clone and require ``kind: choreography``.

    A repo that does not say what it is gets a plain refusal rather than a
    guess: silently treating any repo as a choreography is how someone ends up
    running code that was never meant for this.
    """
    path = Path(clone) / MARKER
    if not path.is_file():
        raise ChoreographyError(
            f"{clone} has no {MARKER}, so it does not describe itself as a "
            "choreography. Ask its maintainer to add one (see "
            "docs/choreography.md), or adopt it as a plain repo with "
            "`murmurent repo adopt`."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ChoreographyError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ChoreographyError(f"{path} must be a YAML mapping")
    kind = str(data.get("kind") or "")
    if kind != KIND:
        raise ChoreographyError(
            f"{path} declares kind: {kind or '(none)'}, not {KIND!r}. "
            "Only a repo that declares itself a choreography is installed as one."
        )
    info = ChoreographyInfo.from_marker(data, source=str(clone))
    if not info.name:
        raise ChoreographyError(f"{path} has no `name`, which is required")
    return info


def _name_from_url(url: str) -> str:
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail[:-4] if tail.endswith(".git") else tail


def clone_choreography(url: str, *, dest: Path | None = None,
                       branch: str = "") -> Path:
    """``git clone`` a choreography under the repos root and return its path.

    Refuses to overwrite an existing directory. Leaves nothing behind on a
    failed clone, so a retry is not blocked by a half-written directory.
    """
    name = _name_from_url(url)
    if not name:
        raise ChoreographyError(f"cannot work out a directory name from {url!r}")
    target = Path(dest) if dest else _repo.repos_root() / name
    if target.exists():
        raise ChoreographyError(
            f"{target} already exists. Move it aside, or point --dest elsewhere."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--quiet"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, str(target)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # git writes the useful part to stderr; pass it through rather than
        # reporting a bare exit code.
        raise ChoreographyError(
            f"git clone failed for {url}:\n{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return target


def missing_agents(info: ChoreographyInfo) -> list[str]:
    """Agents the choreography asks for that this machine has not got.

    Reported rather than installed: the commons is what it is, and a
    choreography naming an agent nobody has is a fact the user should see
    before they start, not a silent shortfall discovered mid-run.
    """
    from .commons import commons_root

    have = {p.stem for p in (commons_root() / "agents").glob("*.md")}
    return [a for a in info.agents if a not in have]
