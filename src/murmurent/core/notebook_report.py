"""
Purpose: Build a report or an exposition from the lab notebook for one
         audience (issue #294): collect the whole entries whose ``audience``
         admits the reader in a date range, refuse restricted and protected
         ones as ``oracle publish`` does, write the material and a source
         list to a folder for the scribe and the artist, and render one
         self-contained HTML page. Sends nothing.
Author:  Mike Hallett (with Claude Code)
Date:    2026-11-07
Input:   The notes stream (never the sessions stream), ``--for`` and a range.
Output:  ``<out>/material.md``, ``<out>/sources.md``, ``<out>/report.html``;
         ``<out>/narrative.md`` is read if the scribe has written it.

Audience is per entry and a report takes whole entries. To share one
sentence, the author moves it into its own entry; the tool offers no
partial sharing, because a paragraph that mixes audiences is where leaks
happen. Large files stay on the server: the page links to them and embeds
only thumbnails and poster frames from the vault. A movie is never embedded.
"""

from __future__ import annotations

import base64
import datetime as _dt
import html
import mimetypes
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import lab_notebook as _nb
from . import sensitivity as _sens

#: Tiers that never leave the vault, the same set ``oracle publish`` refuses.
BLOCKED_SENSITIVITIES: frozenset[str] = frozenset({"protected", "restricted"})
NARRATIVE_NAME = "narrative.md"
MATERIAL_NAME = "material.md"
SOURCES_NAME = "sources.md"
PAGE_NAME = "report.html"
NARRATIVE_MARK = "<!-- scribe: narrative -->"

WIKILINK = re.compile(r"!?\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")
SERVER_LINK = re.compile(r"`([A-Za-z0-9_.-]+:/[^`\s]+)`")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


class ReportError(RuntimeError):
    """The report cannot be built; the message says why."""


@dataclass
class EntryRef:
    """One whole entry drawn on by the report."""

    path: Path
    rel: str
    date: str
    project: str
    sensitivity: str
    audience: list[str]
    title: str
    body: str
    vault_files: list[str] = field(default_factory=list)   # vault-relative
    server_links: list[str] = field(default_factory=list)  # host:path


@dataclass
class Bundle:
    reader: str
    since: str
    until: str
    included: list[EntryRef] = field(default_factory=list)
    refused: list[tuple[str, str]] = field(default_factory=list)   # (rel, reason)
    considered: int = 0

    @property
    def files(self) -> list[str]:
        out: list[str] = []
        for e in self.included:
            for f in [*e.vault_files, *e.server_links]:
                if f not in out:
                    out.append(f)
        return out


# ---------------------------------------------------------------------------
# Collect
# ---------------------------------------------------------------------------


def collect(paths: _nb.NotebookPaths, *, reader: str, since: str, until: str) -> Bundle:
    """Whole entries whose audience admits ``reader``, dated ``since`` to
    ``until`` inclusive. Restricted and protected entries are refused even
    when their audience admits the reader, and listed as refused."""
    if not _nb.is_valid_audience(reader) or reader == _nb.AUDIENCE_ME:
        raise ReportError(
            f"--for must be supervisor, lab or project:<name>, not {reader!r} "
            "(me is never a reader: an entry with no audience stays in the vault)")
    bundle = Bundle(reader=reader.lower(), since=since, until=until)
    if not paths.notebook.is_dir():
        return bundle
    for path in sorted(paths.notebook.rglob("*.md")):
        if path.name in {"README.md", "index.md", "MEMORY.md"}:
            continue
        try:
            meta, body = _nb.read_entry(path)
        except (OSError, UnicodeDecodeError):
            continue
        date = _nb.entry_date(path, meta)
        if date == "undated" or not (since <= date <= until):
            continue
        bundle.considered += 1
        audiences = _nb.audiences_of(meta)
        if not _nb.audience_admits(audiences, reader):
            continue
        rel = paths.rel(path)
        tier = _sens.normalize(meta.get("sensitivity")) or "standard"
        if tier in BLOCKED_SENSITIVITIES:
            bundle.refused.append((rel, f"sensitivity: {tier} never leaves the vault"))
            continue
        vault_files = [m.group(1).strip() for m in WIKILINK.finditer(body)
                       if "/" in m.group(1) and not m.group(1).startswith(_nb.SESSIONS_SUBFOLDER)]
        bundle.included.append(EntryRef(
            path=path, rel=rel, date=date, project=str(meta.get("project") or ""),
            sensitivity=tier, audience=audiences,
            title=str(meta.get("title") or _first_heading(body) or path.stem), body=body,
            vault_files=[f for f in vault_files if (paths.vault / f).is_file()],
            server_links=sorted({m.group(1) for m in SERVER_LINK.finditer(body)}),
        ))
    bundle.included.sort(key=lambda e: (e.date, e.rel))
    return bundle


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


# ---------------------------------------------------------------------------
# Write the folder
# ---------------------------------------------------------------------------


def default_out_dir(paths: _nb.NotebookPaths, bundle: Bundle) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", bundle.reader.lower()).strip("_")
    return paths.reports / f"{bundle.until}_{slug}"


def sources_text(bundle: Bundle) -> str:
    lines = [f"# Sources drawn on: report for {bundle.reader}, {bundle.since} to {bundle.until}", ""]
    lines.append(f"Entries considered in the range: {bundle.considered}; included: "
                 f"{len(bundle.included)}; refused: {len(bundle.refused)}.")
    lines.append("")
    lines.append("## Entries (whole; audience is per entry)")
    for e in bundle.included:
        lines.append(f"- {e.rel} ({e.date}, project {e.project or 'general'}, "
                     f"audience {', '.join(e.audience)}, {e.sensitivity})")
    if not bundle.included:
        lines.append("- none")
    lines.append("")
    lines.append("## Files")
    for f in bundle.files:
        where = "on the server (linked, not copied)" if ":/" in f else "from the vault (embedded)"
        lines.append(f"- {f}: {where}")
    if not bundle.files:
        lines.append("- none")
    lines.append("")
    lines.append("## Refused")
    for rel, why in bundle.refused:
        lines.append(f"- {rel}: {why}")
    if not bundle.refused:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def material_text(bundle: Bundle) -> str:
    lines = [f"# Material for the scribe: report for {bundle.reader}, {bundle.since} to {bundle.until}", "",
             "Each section is one whole entry, as written. Draft the narrative from these and "
             "nothing else; leave a gap rather than invent. Machine-made text is marked in the "
             "entries and stays marked.", ""]
    for e in bundle.included:
        lines.append(f"## {e.date}: {e.title}  ({e.rel})")
        lines.append("")
        lines.append(e.body.strip())
        lines.append("")
    return "\n".join(lines)


def write_bundle(paths: _nb.NotebookPaths, bundle: Bundle, out_dir: Path, *,
                 title: str = "") -> dict[str, Path]:
    """Write material, sources and the page into ``out_dir``. An existing
    ``narrative.md`` there (the scribe's) goes into the page."""
    out_dir.mkdir(parents=True, exist_ok=True)
    material = out_dir / MATERIAL_NAME
    sources = out_dir / SOURCES_NAME
    page = out_dir / PAGE_NAME
    material.write_text(material_text(bundle), encoding="utf-8")
    sources.write_text(sources_text(bundle), encoding="utf-8")
    narrative = out_dir / NARRATIVE_NAME
    narrative_md = narrative.read_text(encoding="utf-8") if narrative.is_file() else ""
    page.write_text(render_page(paths, bundle, title=title, narrative_md=narrative_md),
                    encoding="utf-8")
    out = {"material": material, "sources": sources, "page": page}
    if narrative_md:
        out["narrative"] = narrative
    return out


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

_CSS = """
body{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;max-width:52rem;margin:2rem auto;
padding:0 1rem;line-height:1.5;color:#222;background:#fff}
h1{font-size:1.7rem}h2{font-size:1.3rem;margin-top:2.2rem;border-top:1px solid #ddd;padding-top:1rem}
h3{font-size:1.05rem}img{max-width:100%;height:auto;border:1px solid #ddd}
blockquote{border-left:4px solid #c9a227;background:#fff8e1;margin:0.8rem 0;padding:0.4rem 0.8rem}
.meta{color:#666;font-size:0.9rem}.narrative{background:#f4f7fb;padding:0.8rem 1rem;border-radius:6px}
.gap{color:#a33}code{background:#f3f3f3;padding:0 0.2rem}table{border-collapse:collapse}
td,th{border:1px solid #ddd;padding:0.2rem 0.5rem;text-align:left}
"""


def render_page(paths: _nb.NotebookPaths, bundle: Bundle, *, title: str = "",
                narrative_md: str = "") -> str:
    kind = "Exposition for the lab" if bundle.reader == _nb.AUDIENCE_LAB else f"Report for {bundle.reader}"
    title = title or f"{kind}, {bundle.since} to {bundle.until}"
    parts = [
        "<!doctype html>", "<html lang=\"en\"><head><meta charset=\"utf-8\">",
        f"<title>{html.escape(title)}</title>", f"<style>{_CSS}</style></head><body>",
        f"<h1>{html.escape(title)}</h1>",
        f"<p class=\"meta\">Built {_dt.datetime.now().strftime('%Y-%m-%d %H:%M')} from "
        f"{len(bundle.included)} notebook entr{'y' if len(bundle.included) == 1 else 'ies'}, "
        f"each marked for this audience. Text in a shaded box was made by a machine "
        f"(a transcription or an image description) and is not the record.</p>",
        "<h2>Narrative</h2>", NARRATIVE_MARK,
    ]
    if narrative_md.strip():
        parts.append(f"<div class=\"narrative\">{_md_to_html(narrative_md, paths)}</div>")
    else:
        parts.append("<p class=\"narrative gap\">[Narrative to be drafted by the scribe from "
                     f"{MATERIAL_NAME}; the entries below are the record.]</p>")
    parts.append("<h2>Entries</h2>")
    if not bundle.included:
        parts.append("<p>No entry in this range is marked for this audience.</p>")
    for e in bundle.included:
        parts.append(f"<h3>{html.escape(e.date)}: {html.escape(e.title)}</h3>")
        parts.append(f"<p class=\"meta\">{html.escape(e.rel)}; project {html.escape(e.project or 'general')}</p>")
        parts.append(_md_to_html(e.body, paths))
    parts.append("<h2>Sources</h2>")
    parts.append(_md_to_html(sources_text(bundle).split("\n", 1)[1], paths))
    parts.append("</body></html>")
    return "\n".join(parts)


def _embed(paths: _nb.NotebookPaths, rel: str) -> str | None:
    p = paths.vault / rel
    if p.suffix.lower() not in IMAGE_SUFFIXES or not p.is_file():
        return None
    mime = mimetypes.guess_type(p.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"


def _inline(text: str, paths: _nb.NotebookPaths) -> str:
    """Inline markdown: escapes, then wikilinks, server links, code, bold."""
    out = html.escape(text, quote=False)

    def wl(m: re.Match) -> str:
        target = m.group(1).strip()
        embed = m.group(0).startswith("!")
        uri = _embed(paths, target) if embed else None
        if uri:
            return f"<img src=\"{uri}\" alt=\"{html.escape(target)}\">"
        return f"<span class=\"meta\">[{html.escape(target)} (in the author's vault)]</span>"

    out = re.sub(r"!?\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]", wl, out)

    def sl(m: re.Match) -> str:
        link = m.group(1)
        host = link.split(":", 1)[0]
        return (f"<code>{html.escape(link)}</code> <span class=\"meta\">(the original is on "
                f"{html.escape(host)}; a reader with an account opens it there, "
                f"<code>murmurent notebook open {html.escape(link)}</code>; a reader without one "
                f"sees only the thumbnail)</span>")

    out = re.sub(r"`([A-Za-z0-9_.-]+:/[^`\s]+)`", sl, out)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<!\w)_([^_]+)_(?!\w)", r"<em>\1</em>", out)
    return out


def _md_to_html(md: str, paths: _nb.NotebookPaths) -> str:
    """A small markdown renderer: headings, paragraphs, lists, quotes, fences."""
    out: list[str] = []
    para: list[str] = []
    mode = ""  # "", "ul", "quote", "fence"

    def flush() -> None:
        nonlocal para, mode
        if mode == "ul":
            out.append("<ul>" + "".join(f"<li>{_inline(x, paths)}</li>" for x in para) + "</ul>")
        elif mode == "quote":
            out.append("<blockquote>" + "<br>".join(_inline(x, paths) for x in para) + "</blockquote>")
        elif mode == "fence":
            out.append("<pre><code>" + html.escape("\n".join(para)) + "</code></pre>")
        elif para:
            out.append(f"<p>{_inline(' '.join(para), paths)}</p>")
        para, mode = [], ""

    for line in md.splitlines():
        s = line.rstrip()
        if mode == "fence":
            if s.strip().startswith("```"):
                flush()
            else:
                para.append(line)
            continue
        if s.strip().startswith("```"):
            flush()
            mode = "fence"
            continue
        if not s.strip():
            flush()
            continue
        h = re.match(r"^(#{1,6})\s+(.*)$", s)
        if h:
            flush()
            level = min(len(h.group(1)) + 2, 6)
            out.append(f"<h{level}>{_inline(h.group(2), paths)}</h{level}>")
            continue
        if s.lstrip().startswith("- ") or s.lstrip().startswith("* "):
            if mode != "ul":
                flush()
                mode = "ul"
            para.append(s.lstrip()[2:])
            continue
        if s.startswith(">"):
            if mode != "quote":
                flush()
                mode = "quote"
            para.append(s[1:].strip())
            continue
        if mode in ("ul", "quote"):
            flush()
        para.append(s.strip())
    flush()
    return "\n".join(out)


__all__ = ["ReportError", "EntryRef", "Bundle", "collect", "write_bundle", "render_page",
           "default_out_dir", "sources_text", "material_text", "BLOCKED_SENSITIVITIES",
           "NARRATIVE_NAME", "MATERIAL_NAME", "SOURCES_NAME", "PAGE_NAME"]
