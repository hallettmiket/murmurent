"""
Purpose: Read/write the lab's git-providers list + member git_logins.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-15
Input: ``lab_mgmt/lab.md`` frontmatter, ``lab_mgmt/members/<h>.md`` frontmatter.
Output: ``GitProvider`` records, dict mappings; backward-compat migration helpers.

Phase 2/3 of the providers refactor (see project-git-providers-model
memory). This module is the single source of truth for translating
between the YAML on disk and the typed objects the rest of the code
uses.

Migration philosophy: never error on legacy lab.md / member.md files
that pre-date this refactor. The resolvers synthesize a default
``github`` provider from ``github_org`` and back-fill
``git_logins["github"]`` from ``contact.github`` so the dashboard
keeps working through the transition.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

VALID_KINDS: tuple[str, ...] = ("github", "gitea", "local-bare")
DEFAULT_GITHUB_ID = "github"


@dataclass
class GitProvider:
    """One git origin server option for a lab.

    ``id`` is what projects + members reference (e.g. ``github``,
    ``biodatsci_gitea``). ``kind`` decides the dispatcher: how to
    construct the clone URL, what API to use for collaborator-add,
    whether a deploy key is needed, etc.

    ``target`` is the kind-specific connection string:
      - ``github``     → org/user name (e.g. ``hallettmiket``)
      - ``gitea``      → base URL (e.g. ``https://biodatsci/gitea``)
      - ``local-bare`` → absolute server-side directory (e.g.
                         ``/data/lab_vm/wigamig/repos``). The host part
                         comes from ``lab_base``.
    """

    id: str
    kind: str = "github"
    label: str = ""
    target: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def parse_providers(meta: dict[str, Any]) -> list[GitProvider]:
    """Read the ``git_providers:`` block from lab.md frontmatter.

    Skips malformed entries (missing id, unknown kind) silently — the
    Lab Settings UI is the only authoritative writer, so anything weird
    on disk is hand-edited and best ignored rather than crashing the
    dashboard.
    """
    raw = meta.get("git_providers")
    if not isinstance(raw, list):
        return []
    out: list[GitProvider] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        pid = str(entry.get("id") or "").strip()
        if not pid:
            continue
        kind = str(entry.get("kind") or "github").strip().lower()
        if kind not in VALID_KINDS:
            continue
        out.append(GitProvider(
            id=pid,
            kind=kind,
            label=str(entry.get("label") or "").strip(),
            target=str(entry.get("target") or "").strip(),
        ))
    return out


def resolve_providers(meta: dict[str, Any]) -> list[GitProvider]:
    """Return the lab's git providers, synthesizing a github default
    from the legacy ``github_org`` field when no ``git_providers:``
    block is on disk yet.

    Used everywhere we need to know "what providers does this lab
    support" — the UI, the new-project flow, the join-request guard.
    """
    declared = parse_providers(meta)
    if declared:
        return declared
    org = str(meta.get("github_org") or "").strip()
    if not org:
        return []
    return [GitProvider(
        id=DEFAULT_GITHUB_ID,
        kind="github",
        label=f"GitHub ({org})",
        target=org,
    )]


def dump_providers(providers: list[GitProvider]) -> list[dict]:
    """Serialize for writing back to lab.md frontmatter."""
    return [
        {"id": p.id, "kind": p.kind, "label": p.label, "target": p.target}
        for p in providers
    ]


def find_provider(providers: list[GitProvider], pid: str) -> GitProvider | None:
    """Lookup by id, case-sensitive. Returns ``None`` when the id
    doesn't match anything in the list."""
    for p in providers:
        if p.id == pid:
            return p
    return None


# ---------------------------------------------------------------------------
# Per-member git_logins
# ---------------------------------------------------------------------------


def parse_logins(meta: dict[str, Any]) -> dict[str, str]:
    """Read the ``git_logins:`` map from a member's frontmatter.

    Back-fills ``git_logins["github"]`` from the legacy
    ``contact.github`` field so members who haven't re-saved their
    profile since the refactor still resolve correctly. The back-fill
    is read-only: it does not mutate the on-disk file.
    """
    raw = meta.get("git_logins")
    out: dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            if not k or v in (None, ""):
                continue
            out[str(k)] = str(v).strip().lstrip("@")
    if "github" not in out:
        contact = meta.get("contact") if isinstance(meta.get("contact"), dict) else {}
        legacy = (contact or {}).get("github")
        if legacy:
            out["github"] = str(legacy).strip().lstrip("@")
    return out


def dump_logins(logins: dict[str, str]) -> dict[str, str]:
    """Serialize for writing back to a member's frontmatter.

    Empty values are dropped (so re-saving a profile with one provider
    deleted cleans up the YAML rather than leaving ``provider: null``).
    """
    return {k: v for k, v in logins.items() if v}
