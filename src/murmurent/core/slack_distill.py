"""
Purpose: Distill one day's slack mirror into oracle entries via an LLM
         call, using the Oracle agent's prompt as the system message.
         Drafts land with ``status: draft``; the PI approves them on
         the dashboard before they surface to members.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-08
Input: One mirror file at ``<lab-mgmt>/slack/<channel>/<date>.md``;
       ``$ANTHROPIC_API_KEY`` for the LLM call.
Output: Zero or more draft oracle entries at
        ``<lab-mgmt>/oracle/<date>_<channel>_<topic-slug>.md``.

Distillation is intentionally cautious: anything not clearly a
*decision*, *new finding*, or *open question* is dropped. The LLM is
given the full mirror and asked to either return ``NO_ORACLE_ENTRIES_TODAY``
or one or more frontmatter+body blocks per the oracle file schema.

When ``$ANTHROPIC_API_KEY`` is unset (CI, fresh checkout), the
distiller writes a single placeholder draft so the rest of the
pipeline (drafts panel, approval flow) can still be exercised.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol

from .frontmatter import dump_document, parse_file
from .repo import lab_mgmt_repo_root, murmurent_repo_root

ORACLE_SUBDIR = "oracle"
ORACLE_AGENT_FILE = "agents/oracle.md"

# Per the design doc, this is the prompt template applied to each
# day's mirror. Keep it tight; the LLM is expensive.
DISTILLATION_PROMPT = """\
You are the Oracle agent for the {lab_name}.

You are summarising one day of Slack activity in the {channel} channel.
The full day's mirror is provided below.

Goal: extract NEW knowledge, decisions, or open questions. Skip
chitchat, scheduling, code-paste-without-context.

For each oracle-worthy item, produce:

  ---
  title: '<one-line title, under 80 chars>'
  author: '@murmurent-oracle'
  date: {date}
  source_channel: {channel}
  source_date: {date}
  source_messages: ['<HH:MM>', '<HH:MM>']
  participants: ['@a', '@b']
  tags: [<short kebab tags>]
  status: draft
  ---

  # <title>

  <2-4 paragraph summary in the lab's voice>

  ## Provenance

  [[slack/{channel}/{date}]] — messages at <HH:MM>, <HH:MM>.

If the day had nothing worth promoting, return EXACTLY this single line:
  NO_ORACLE_ENTRIES_TODAY

Separate multiple entries with the literal line "---ORACLE-ENTRY-SEPARATOR---".

Slack mirror for {channel} on {date}:
============================================================
{mirror_body}
============================================================
"""

ENTRY_SEPARATOR = "---ORACLE-ENTRY-SEPARATOR---"
NO_ENTRIES = "NO_ORACLE_ENTRIES_TODAY"


class DistillError(Exception):
    pass


# ---------------------------------------------------------------------------
# LLM client (mockable interface)
# ---------------------------------------------------------------------------


class LLMLike(Protocol):
    def complete(self, *, prompt: str, system: str = "") -> str: ...


@dataclass(frozen=True)
class StubLLM:
    """No-network LLM used when ``$ANTHROPIC_API_KEY`` is missing.

    Returns a single placeholder entry so downstream tooling (drafts
    panel, approve flow) is exercised. The PI sees clearly that this
    came from the stub, not a real distillation.
    """

    def complete(self, *, prompt: str, system: str = "") -> str:
        return (
            "---\n"
            "title: '(stub) distillation placeholder'\n"
            "author: '@murmurent-oracle'\n"
            "date: STUB\n"
            "tags: [stub]\n"
            "status: draft\n"
            "---\n\n"
            "# Stub distillation\n\n"
            "No ANTHROPIC_API_KEY was set, so the distiller wrote this "
            "placeholder draft instead of calling the LLM. Set the env "
            "var and re-run `murmurent slack distil` to get real output.\n"
        )


@dataclass(frozen=True)
class AnthropicLLM:
    """Wraps the Anthropic SDK with a single ``complete`` method."""

    model: str = "claude-sonnet-5"

    def complete(self, *, prompt: str, system: str = "") -> str:
        try:
            import anthropic  # type: ignore[import-not-found]
        except ImportError as exc:
            raise DistillError(
                "anthropic SDK not installed; "
                "`uv sync --extra slack` and retry."
            ) from exc
        client = anthropic.Anthropic()  # picks up ANTHROPIC_API_KEY
        msg = client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=system or "You are a careful summariser.",
            messages=[{"role": "user", "content": prompt}],
        )
        # Concat any text blocks in the reply.
        out: list[str] = []
        for block in msg.content:
            if getattr(block, "type", "") == "text":
                out.append(block.text)
        return "\n".join(out)


def make_llm() -> LLMLike:
    """Pick the LLM based on env. Stub when no API key."""
    return AnthropicLLM() if os.environ.get("ANTHROPIC_API_KEY") else StubLLM()


# ---------------------------------------------------------------------------
# System prompt — the Oracle agent's definition
# ---------------------------------------------------------------------------


def oracle_system_prompt() -> str:
    """Read agents/oracle.md as the LLM's system prompt."""
    path = murmurent_repo_root() / ORACLE_AGENT_FILE
    if not path.is_file():
        return "You are the Oracle agent. Distill carefully."
    return parse_file(path).body


# ---------------------------------------------------------------------------
# Distill one mirror
# ---------------------------------------------------------------------------


@dataclass
class DistillResult:
    mirror_path: Path
    drafts_written: list[Path]
    raw_response: str


def distill_mirror(
    *,
    mirror_path: Path,
    channel_name: str,
    date: _dt.date,
    lab_name: str = "lab",
    llm: LLMLike | None = None,
) -> DistillResult:
    """Run distillation on one mirror file. Returns paths of any drafts written."""
    if not mirror_path.is_file():
        raise DistillError(f"mirror not found: {mirror_path}")
    parsed = parse_file(mirror_path)
    mirror_body = parsed.body

    llm = llm or make_llm()
    prompt = DISTILLATION_PROMPT.format(
        lab_name=lab_name,
        channel=channel_name,
        date=date.isoformat(),
        mirror_body=mirror_body,
    )
    raw = llm.complete(prompt=prompt, system=oracle_system_prompt())
    raw = raw.strip()

    if NO_ENTRIES in raw:
        return DistillResult(mirror_path=mirror_path, drafts_written=[], raw_response=raw)

    written: list[Path] = []
    blocks = [b.strip() for b in raw.split(ENTRY_SEPARATOR) if b.strip()]
    for i, block in enumerate(blocks):
        path = _write_draft(block, channel_name=channel_name, date=date, index=i)
        if path is not None:
            written.append(path)
    return DistillResult(mirror_path=mirror_path, drafts_written=written, raw_response=raw)


def _write_draft(
    text: str,
    *,
    channel_name: str,
    date: _dt.date,
    index: int,
) -> Path | None:
    """Persist one LLM-produced block as a draft oracle entry."""
    out_dir = lab_mgmt_repo_root() / ORACLE_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    # Try to extract the title for a meaningful filename; otherwise use index.
    m = re.search(r"^title:\s*['\"]?(?P<title>[^'\"\n]+)['\"]?\s*$", text, re.MULTILINE)
    if m:
        slug = _slugify(m.group("title"))
    else:
        slug = f"distill_{index + 1}"
    filename = f"{date.isoformat()}_{channel_name}_{slug}.md"
    path = out_dir / filename
    # The text the LLM returned is supposed to be a full markdown doc
    # already (frontmatter + body). Persist as-is, but force status=draft
    # in case the LLM forgot.
    forced = _force_status_draft(text)
    path.write_text(forced + ("\n" if not forced.endswith("\n") else ""), encoding="utf-8")
    return path


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(s: str, *, max_len: int = 48) -> str:
    out = _SLUG_RE.sub("_", s.lower()).strip("_")
    return out[:max_len].strip("_") or "untitled"


def _force_status_draft(text: str) -> str:
    """Make sure the entry has ``status: draft`` in its frontmatter."""
    if "status: draft" in text:
        return text
    if text.startswith("---"):
        # insert before the closing ---
        end = text.find("---", 3)
        if end > 0:
            return text[:end] + "status: draft\n" + text[end:]
    return "---\nstatus: draft\n---\n\n" + text


# ---------------------------------------------------------------------------
# Approval flow (drafts → published)
# ---------------------------------------------------------------------------


def iter_drafts() -> list[Path]:
    """Return paths of all oracle markdown files with ``status: draft``."""
    odir = lab_mgmt_repo_root() / ORACLE_SUBDIR
    if not odir.is_dir():
        return []
    drafts: list[Path] = []
    for path in sorted(odir.glob("*.md")):
        try:
            meta = parse_file(path).meta or {}
        except Exception:
            continue
        if str(meta.get("status", "")).lower() == "draft":
            drafts.append(path)
    return drafts


def is_draft(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        meta = parse_file(path).meta or {}
    except Exception:
        return False
    return str(meta.get("status", "")).lower() == "draft"


def approve_draft(path: Path, *, approver: str) -> Path:
    """Flip a draft to ``status: published`` and stamp ``approved_by``."""
    if not path.is_file():
        raise DistillError(f"oracle entry not found: {path}")
    parsed = parse_file(path)
    meta = parsed.meta or {}
    meta["status"] = "published"
    meta["approved_by"] = approver if approver.startswith("@") else f"@{approver}"
    meta["approved_at"] = _dt.date.today().isoformat()
    path.write_text(dump_document(meta, parsed.body), encoding="utf-8")
    return path


def decline_draft(path: Path, *, reason: str) -> Path:
    """Move a draft to ``status: declined`` (kept on disk for the audit trail)."""
    if not path.is_file():
        raise DistillError(f"oracle entry not found: {path}")
    if not reason:
        raise DistillError("decline requires a reason")
    parsed = parse_file(path)
    meta = parsed.meta or {}
    meta["status"] = "declined"
    meta["decline_reason"] = reason
    path.write_text(dump_document(meta, parsed.body), encoding="utf-8")
    return path
