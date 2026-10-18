"""
Purpose: Carry a member's profile change to the PI, and let the PI apply it to
         the lab roster (issue #187; #34 "Option A").
Author: Mike Hallett (with Claude Code)
Date: 2026-10-18
Input: the member's staged profile block (core.member_profile); the lab
       management repo on GitHub, through the `gh` command.
Output: one open issue per member on the lab management repo, titled
        "Profile update: @<handle>"; on the PI's side, the edits applied to
        ``members/<handle>.md``, committed and pushed, and the issue closed.

Why an issue. Members have read-only access to the lab management repo, so
they cannot push their own roster entry (#34). Read access is enough to open
an issue, though, and the PI can read issues. So a member's save opens (or
updates) one issue holding their changes as YAML, and the PI's
``murmurent reconcile`` applies it.

Why it is safe. Anyone who can read the repo can open an issue with any
title. The PI's side therefore applies an issue only when the GitHub account
that opened it is the GitHub login already recorded on that member's roster
entry. An issue for a member with no GitHub login on file is reported, not
applied, and a change to the GitHub login itself is never taken from an issue.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

TITLE_PREFIX = "Profile update: @"
LABEL = "profile-update"
MARKER = "<!-- murmurent:profile-update v1 -->"

#: ``run(argv) -> CompletedProcess``; injectable so tests never call GitHub.
Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _gh(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *argv], capture_output=True, text=True, timeout=30)


def lab_mgmt_slug(root: Path | None = None) -> str | None:
    """``owner/repo`` of the lab management repo on GitHub, from its clone's
    ``origin`` remote; None when there is no GitHub remote."""
    try:
        from .repo import lab_mgmt_repo_root
        root = root or lab_mgmt_repo_root()
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def _norm(handle: str) -> str:
    return (handle or "").strip().lstrip("@").lower()


def render_body(handle: str, block: dict) -> str:
    """The issue body: a sentence for people, then the changes as YAML."""
    edits = {k: v for k, v in block.items() if k != "handle"}
    shown = yaml.safe_dump({"handle": f"@{_norm(handle)}", "edits": edits},
                           sort_keys=False, allow_unicode=True)
    return (f"{MARKER}\n@{_norm(handle)} changed their profile in the murmurent "
            "dashboard. The PI's `murmurent reconcile` applies it to the lab "
            "roster and closes this issue. An empty value clears that field.\n\n"
            f"```yaml\n{shown}```\n")


def parse_body(body: str) -> tuple[str, dict] | None:
    """``(handle, edits)`` from an issue body made by :func:`render_body`."""
    if MARKER not in (body or ""):
        return None
    m = re.search(r"```yaml\n(.*?)```", body, re.S)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("edits"), dict):
        return None
    return _norm(str(data.get("handle") or "")), data["edits"]


@dataclass
class RelayResult:
    ok: bool
    detail: str
    issue: int | None = None

    def to_probe(self) -> dict:
        return {"name": "sent to your PI", "status": "ok" if self.ok else "warn",
                "detail": self.detail, "required": False}


def send_profile_update(handle: str, block: dict, *, run: Runner = _gh,
                        slug: str | None = None) -> RelayResult:
    """Open, or update, this member's "Profile update" issue. Never raises."""
    slug = slug or lab_mgmt_slug()
    if not slug:
        return RelayResult(False, "the lab management repo has no GitHub copy, so "
                                  "your PI was not sent the change; tell them directly.")
    title = f"{TITLE_PREFIX}{_norm(handle)}"
    body = render_body(handle, block)
    try:
        found = run(["issue", "list", "--repo", slug, "--state", "open", "--search",
                     f'"{title}" in:title', "--json", "number,title"])
        number = None
        if found.returncode == 0:
            for item in json.loads(found.stdout or "[]"):
                if item.get("title") == title:
                    number = int(item["number"])
                    break
        if number is not None:
            res = run(["issue", "edit", str(number), "--repo", slug, "--body", body])
        else:
            res = run(["issue", "create", "--repo", slug, "--title", title,
                       "--body", body, "--label", LABEL])
            if res.returncode != 0 and "label" in (res.stderr or "").lower():
                # The repo has no such label yet; the title is what counts.
                res = run(["issue", "create", "--repo", slug, "--title", title,
                           "--body", body])
            if res.returncode == 0:
                m = re.search(r"/issues/(\d+)", res.stdout or "")
                number = int(m.group(1)) if m else None
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return RelayResult(False, f"could not reach GitHub ({exc}); your PI was not "
                                  "sent the change yet. Save again later.")
    if res.returncode != 0:
        why = (res.stderr or res.stdout or "").strip().splitlines()
        return RelayResult(False, "GitHub refused the update"
                           + (f" ({why[-1]})" if why else "")
                           + "; your PI was not sent the change yet.")
    where = f"issue #{number}" if number else "an issue"
    return RelayResult(True, f"sent to your PI as {where} on {slug}; it reaches the "
                             "lab roster when they next run murmurent reconcile.",
                       issue=number)


@dataclass
class IngestItem:
    issue: int
    handle: str
    author: str
    applied: bool
    detail: str


@dataclass
class IngestReport:
    items: list[IngestItem] = field(default_factory=list)
    detail: str = ""


def _roster_github(meta: dict) -> str:
    logins = meta.get("git_logins") if isinstance(meta.get("git_logins"), dict) else {}
    contact = meta.get("contact") if isinstance(meta.get("contact"), dict) else {}
    return str(logins.get("github") or contact.get("github") or "").strip().lstrip("@").lower()


def ingest_profile_updates(*, apply: bool, run: Runner = _gh, slug: str | None = None,
                           lab_mgmt: Path | None = None) -> IngestReport:
    """Apply open "Profile update" issues to the roster (the PI's side).

    An issue is applied only when its author is the GitHub login on that
    member's roster entry. With ``apply`` False, reports what would happen.
    Commits and pushes the roster once, then comments on and closes each
    applied issue. Never raises.
    """
    from . import git_persist
    from . import member_profile as _mp
    from .frontmatter import dump_document, parse_file
    from .repo import lab_mgmt_repo_root

    report = IngestReport()
    root = lab_mgmt or lab_mgmt_repo_root()
    slug = slug or lab_mgmt_slug(root)
    if not slug:
        report.detail = "the lab management repo has no GitHub copy; nothing to read."
        return report
    try:
        res = run(["issue", "list", "--repo", slug, "--state", "open", "--limit", "100",
                   "--search", f'"{TITLE_PREFIX.strip()}" in:title',
                   "--json", "number,title,body,author"])
        issues = json.loads(res.stdout or "[]") if res.returncode == 0 else []
        if res.returncode != 0:
            report.detail = (res.stderr or "could not list issues").strip().splitlines()[-1]
            return report
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        report.detail = f"could not reach GitHub ({exc})"
        return report

    changed: list[Path] = []
    for it in issues:
        if not str(it.get("title") or "").startswith(TITLE_PREFIX):
            continue
        number = int(it["number"])
        author = str((it.get("author") or {}).get("login") or "").lower()
        parsed = parse_body(str(it.get("body") or ""))
        if parsed is None:
            report.items.append(IngestItem(number, "?", author, False,
                                           "not a murmurent profile update; left alone"))
            continue
        handle, edits = parsed
        path = root / "members" / f"{handle}.md"
        if not path.is_file():
            report.items.append(IngestItem(number, handle, author, False,
                                           f"@{handle} is not on the roster"))
            continue
        doc = parse_file(path)
        on_file = _roster_github(doc.meta or {})
        if not on_file:
            report.items.append(IngestItem(number, handle, author, False,
                "no GitHub login on file for this member, so the issue's author "
                "cannot be checked; add it to their roster entry first"))
            continue
        if author != on_file:
            report.items.append(IngestItem(number, handle, author, False,
                f"opened by @{author}, but @{handle}'s GitHub login is @{on_file}; "
                "not applied"))
            continue
        # The GitHub login is the proof of identity: never change it from an issue.
        safe = {k: v for k, v in edits.items() if k != "git_logins"}
        if isinstance(safe.get("contact"), dict):
            safe["contact"] = {k: v for k, v in safe["contact"].items() if k != "github"}
        if apply:
            new_meta = _mp.apply_edits_to_meta(doc.meta or {}, safe)
            path.write_text(dump_document(new_meta, doc.body or ""), encoding="utf-8")
            changed.append(path)
        report.items.append(IngestItem(number, handle, author, apply,
                                       "applied" if apply else "would apply"))

    if apply and changed:
        probes = []
        for i, path in enumerate(changed):
            # One commit per member file (commit_and_push commits one file),
            # pushed once after the last.
            probes += git_persist.commit_and_push(
                path, message=f"profile update from @{path.stem} (#187)",
                push=(i == len(changed) - 1))
        if any(p.status == "fail" for p in probes):
            report.detail = "applied locally, but the commit or push failed; issues left open"
            return report
        for item in report.items:
            if item.applied:
                try:
                    run(["issue", "close", str(item.issue), "--repo", slug, "--comment",
                         "Applied to the lab roster by `murmurent reconcile`. Thank you."])
                except (OSError, subprocess.SubprocessError):
                    pass
    return report
