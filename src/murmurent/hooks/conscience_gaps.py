"""
Purpose: Claude Code ``PostToolUse`` hook that harvests the ``## Gap register``
         table out of every conscience report written under
         ``outputs/conscience/`` and accumulates it, so the EDID resources
         learns what it is missing from reviews that actually needed something
         rather than from someone remembering to update it.
Author:  Mike Hallett (with Claude Code)
Date:    2026-08-29
Input:   PostToolUse tool-call JSON on stdin (CC hook contract).
Output:  Empty stdout on the quiet path; ``hookSpecificOutput`` with
         ``additionalContext`` when a report arrives with no gap register.

Storage is **local by default**, and that is a privacy property, not a
convenience. Gap text is free prose the agent wrote about whatever document it
just reviewed — "no source on consent framing for incarcerated participants"
names someone's study. The murmurent repo is public, so nothing is written
there:

  ``~/.murmurent/edid_gaps/gap_log.md``       append-only ledger, one line per
                                              miss. Never rewritten, so a bad
                                              parse adds noise but can never
                                              destroy history.
  ``~/.murmurent/edid_gaps/gap_register.md``  derived view — deduplicated,
                                              hit-counted, ranked. Regenerated
                                              in full from the ledger, so it
                                              has no merge state to get wrong.

Sharing a gap centre-wide is a deliberate promote step a person performs, and
that step is where someone reads the text before it becomes public — the same
shape as personal Oracle versus Lab Oracle. The cost is real and worth naming:
hit counts only aggregate across the centre for gaps somebody promoted, so the
ranking is partial by construction.

Two files in the repo are **read, never written**:
``docs/edid_gap_decisions.md`` (gaps filled or declined centre-wide, so a
decision made once stops nagging everyone) and ``docs/edid_resources.md``
(scope tags, for the mis-scope check).

**This hook never writes to** ``docs/edid_resources.md``. That file decides
what the conscience is allowed to cite, and nothing automatic may touch it:
an agent whose misses could silently become citable sources could manufacture
support for anything it wanted to say. The bookworm reads the register, a
person approves, and only then do the resources change. Same dry-run-then-apply
split as ``docs/reconcile.md``, for the same reason.

Failure policy: **never block, never raise.** A malformed report, an
unwritable path, or an unreadable ledger costs a tally, and that is strictly
better than a hook that breaks every Write in the session. The one thing it
does say out loud is when a report carries no gap register at all — the loop
failing silently would look exactly like the loop working.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import IO, Any

REPORT_DIR_PARTS = ("outputs", "conscience")
GAP_HEADING = re.compile(r"^\s*#{1,6}\s*gap register\b", re.IGNORECASE)
ANY_HEADING = re.compile(r"^\s*#{1,6}\s+")
SEPARATOR_ROW = re.compile(r"^\s*\|[\s:|-]+\|\s*$")
LOG_NAME = "gap_log.md"
REGISTER_NAME = "gap_register.md"
DECISIONS_NAME = "edid_gap_decisions.md"
POOL_NAME = "edid_resources.md"
VALID_KINDS = frozenset({"no-source", "no-source (regional)", "blocked"})
NUDGE_THRESHOLD = 3
SCOPE_TAG = re.compile(r"`\[(binds|from) ([^\]]+)\]`")
MD_LINK = re.compile(r"\((https?://[^)\s]+)\)")


def local_store() -> Path:
    """Where a member's own gap ledger lives. Never the public repo."""
    import os
    base = os.environ.get("MURMURENT_HOME")
    root = Path(base).expanduser() if base else Path("~/.murmurent").expanduser()
    return root / "edid_gaps"


def deployment_scopes() -> set[str]:
    """Scopes that bind this deployment, e.g. {"UWO", "CA"}.

    Empty means unconfigured, and the mis-scope check stays silent rather than
    guessing — warning every citation would train the reader to ignore it.
    """
    import os
    raw = os.environ.get("MURMURENT_EDID_SCOPE", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


def read_decisions(path: Path) -> dict[str, tuple[str, str]]:
    """Centre-wide gap decisions: key -> (state, reason).

    ``filled`` and ``declined`` both stop a gap counting. A gap somebody
    decided against must stop nudging, or the nudges get tuned out and the
    whole loop dies quietly.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for line in text.splitlines():
        if not line.strip().startswith("|") or SEPARATOR_ROW.match(line):
            continue
        cells = _split_row(line)
        if len(cells) < 3 or cells[1].strip().lower() in {"state", ""}:
            continue
        state = cells[1].strip().strip("`").lower()
        if state in {"filled", "declined"}:
            out[_norm_key(cells[0])] = (state, cells[2].strip())
    return out


def pool_scopes(pool_path: Path) -> dict[str, str]:
    """Map each resource URL to its scope tag, for the mis-scope check."""
    try:
        text = pool_path.read_text(encoding="utf-8")
    except OSError:
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        tag = SCOPE_TAG.search(line)
        if not tag:
            continue
        for url in MD_LINK.findall(line):
            out[url] = tag.group(2)
    return out


def scope_mismatches(report_text: str, pool_path: Path,
                     scopes: set[str]) -> list[tuple[str, str]]:
    """Citations in the report that are scoped somewhere this reader is not.

    This catches the failure the agent cannot catch in itself. A missing source
    fails honestly — it says it cannot cite anything. A mis-scoped one is a
    confident wrong answer wearing a legitimate-looking citation, and neither
    party notices.
    """
    if not scopes:
        return []
    tagged = pool_scopes(pool_path)
    hits: list[tuple[str, str]] = []
    for url in set(MD_LINK.findall(report_text)):
        where = tagged.get(url)
        if where and where not in scopes:
            hits.append((url, where))
    return sorted(hits)

LOG_HEADER = """# EDID gap log — append-only

One line per miss recorded by the [conscience](../agents/conscience.md) in a
report's `## Gap register`. Appended by `murmurent.hooks.conscience_gaps`;
**never edit or reorder this file** — [`edid_gap_register.md`](edid_gap_register.md)
is regenerated from it, and the resources themselves are only ever changed by the
bookworm with a person's approval.

| Date | Needed | Domain | Kind | Report |
|---|---|---|---|---|
"""


def _is_conscience_report(path_text: str) -> bool:
    """True for a markdown file under some ``outputs/conscience/`` directory."""
    if not path_text:
        return False
    path = Path(path_text)
    if path.suffix.lower() != ".md":
        return False
    parts = tuple(path.parts)
    return any(
        parts[i : i + 2] == REPORT_DIR_PARTS for i in range(max(0, len(parts) - 1))
    )


def _split_row(line: str) -> list[str]:
    """Split one markdown table row into stripped cells."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_gap_register(text: str) -> tuple[list[dict[str, str]], bool]:
    """Extract gap rows from a report.

    Returns ``(rows, found_section)``. ``found_section`` distinguishes "the
    report declared an empty register" from "the report has no register at
    all" — only the second is worth warning about.
    """
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if GAP_HEADING.match(ln)), None)
    if start is None:
        return [], False
    rows: list[dict[str, str]] = []
    seen_header = False
    for line in lines[start + 1 :]:
        if ANY_HEADING.match(line):
            break
        if not line.strip().startswith("|"):
            continue
        if SEPARATOR_ROW.match(line):
            continue
        cells = _split_row(line)
        if len(cells) < 4:
            continue
        if not seen_header:
            # First table row is the header; skip it without inspecting text,
            # so a report that renames the columns still parses.
            seen_header = True
            continue
        needed, domain, _why, kind = cells[0], cells[1], cells[2], cells[3]
        if not needed:
            continue
        kind_norm = kind.strip().strip("`").lower()
        rows.append({
            "needed": needed,
            "domain": domain or "—",
            "kind": kind_norm if kind_norm in VALID_KINDS else "no-source",
        })
    return rows, True


def _norm_key(needed: str) -> str:
    """Dedupe key: case- and punctuation-insensitive, so near-repeats merge."""
    return re.sub(r"[^a-z0-9]+", " ", needed.lower()).strip()


def append_to_log(log_path: Path, rows: list[dict[str, str]], report: str, today: str) -> None:
    """Append rows to the ledger, creating it with its header if absent."""
    if not rows:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not log_path.exists():
        log_path.write_text(LOG_HEADER, encoding="utf-8")
    existing = log_path.read_text(encoding="utf-8")
    prefix = "" if existing.endswith("\n") else "\n"
    lines = [
        f"| {today} | {r['needed']} | {r['domain']} | `{r['kind']}` | {report} |"
        for r in rows
    ]
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(prefix + "\n".join(lines) + "\n")


def read_log(log_path: Path) -> list[dict[str, str]]:
    """Parse the ledger back into rows. Unreadable ledger yields no rows."""
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.strip().startswith("|") or SEPARATOR_ROW.match(line):
            continue
        cells = _split_row(line)
        if len(cells) < 5 or cells[0].strip().lower() == "date":
            continue
        rows.append({
            "date": cells[0],
            "needed": cells[1],
            "domain": cells[2],
            "kind": cells[3].strip("`"),
            "report": cells[4],
        })
    return rows


def build_register(rows: list[dict[str, str]],
                   decisions: dict[str, tuple[str, str]] | None = None) -> str:
    """Render the derived register: deduplicated, hit-counted, ranked."""
    tally: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = _norm_key(row["needed"])
        if not key:
            continue
        entry = tally.setdefault(key, {
            "needed": row["needed"],
            "domains": set(),
            "kinds": set(),
            "hits": 0,
            "first": row["date"],
            "last": row["date"],
        })
        entry["hits"] += 1
        entry["domains"].add(row["domain"])
        entry["kinds"].add(row["kind"])
        entry["last"] = max(entry["last"], row["date"])
        entry["first"] = min(entry["first"], row["date"])
    decisions = decisions or {}
    for key, entry in tally.items():
        state, reason = decisions.get(key, ("open", ""))
        entry["state"] = state
        entry["reason"] = reason
    ranked = sorted(
        tally.values(),
        key=lambda e: (e["state"] != "open", -e["hits"], e["needed"].lower()),
    )
    body = "\n".join(
        "| {hits} | {needed} | {domains} | {kinds} | {state} | {first} | {last} |".format(
            hits=e["hits"],
            needed=e["needed"],
            domains=", ".join(sorted(d for d in e["domains"] if d)) or "—",
            kinds=", ".join(f"`{k}`" for k in sorted(e["kinds"])),
            state=f"`{e['state']}`" + (f" — {e['reason']}" if e["reason"] else ""),
            first=e["first"],
            last=e["last"],
        )
        for e in ranked
    )
    return (
        "# EDID gap register — ranked by how often a review was blocked\n\n"
        "**Generated. Do not edit.** Regenerated from "
        "[`edid_gap_log.md`](edid_gap_log.md) by "
        "`murmurent.hooks.conscience_gaps` every time a conscience report is "
        "written.\n\n"
        "**Hit count is the priority.** A gap recorded once is a note. A gap "
        "recorded eleven times is the next thing to fix, and it earned that "
        "ranking by blocking eleven real reviews rather than by seeming "
        "important to someone. `no-source` means nothing in the resources covers "
        "it; `blocked` means something does but sits unretrieved on the "
        "ingestion backlog.\n\n"
        "The [bookworm](../agents/bookworm.md) works the top of this list. "
        "Nothing here is citable, and nothing becomes citable without a "
        "person approving its entry into "
        "[`edid_resources.md`](edid_resources.md).\n\n"
        "A gap marked `filled` or `declined` in "
        "[`edid_gap_decisions.md`](edid_gap_decisions.md) sinks to the bottom "
        "and stops nudging. A decision taken once should not have to be taken "
        "again every time the gap recurs — that is how a nudge becomes noise "
        "and then becomes ignored.\n\n"
        "| Hits | Needed | Domain | Kind | State | First seen | Last seen |\n"
        "|---|---|---|---|---|---|---|\n"
        f"{body}\n"
    )


def harvest(report_path: Path, store: Path, repo_docs: Path, today: str,
            scopes: set[str] | None = None) -> dict[str, Any]:
    """Read one report: append its gaps, regenerate the register, check scope."""
    try:
        text = report_path.read_text(encoding="utf-8")
    except OSError:
        return {"status": "unreadable"}
    mismatched = scope_mismatches(
        text, repo_docs / POOL_NAME,
        deployment_scopes() if scopes is None else scopes,
    )
    rows, found = parse_gap_register(text)
    if not found:
        return {"status": "missing-section", "mismatched": mismatched}
    store.mkdir(parents=True, exist_ok=True)
    log_path = store / LOG_NAME
    append_to_log(log_path, rows, report_path.name, today)
    decisions = read_decisions(repo_docs / DECISIONS_NAME)
    all_rows = read_log(log_path)
    (store / REGISTER_NAME).write_text(
        build_register(all_rows, decisions), encoding="utf-8")

    # Threshold: speak only for an OPEN gap this report just pushed over the
    # line. Below it, silence — a nudge on every run is one nobody reads.
    counts: dict[str, int] = {}
    for row in all_rows:
        counts[_norm_key(row["needed"])] = counts.get(_norm_key(row["needed"]), 0) + 1
    crossed = [
        (r["needed"], counts[_norm_key(r["needed"])])
        for r in rows
        if counts.get(_norm_key(r["needed"]), 0) >= NUDGE_THRESHOLD
        and decisions.get(_norm_key(r["needed"]), ("open", ""))[0] == "open"
    ]
    return {
        "status": "harvested",
        "rows": len(rows),
        "crossed": crossed,
        "mismatched": mismatched,
    }


def evaluate(payload: dict[str, Any], store: Path | None = None,
             today: str | None = None, repo_docs: Path | None = None,
             scopes: set[str] | None = None) -> dict[str, Any]:
    """Decide what, if anything, this tool call means for the gap register."""
    tool = payload.get("tool_name") or payload.get("tool") or ""
    if tool not in {"Write", "Edit", "NotebookEdit"}:
        return {"status": "skip"}
    args = payload.get("tool_input") or payload.get("input") or {}
    if not isinstance(args, dict):
        return {"status": "skip"}
    target = str(args.get("file_path") or "")
    if not _is_conscience_report(target):
        return {"status": "skip"}
    if repo_docs is None:
        from ..core.repo import murmurent_repo_root
        repo_docs = murmurent_repo_root() / "docs"
    return harvest(
        Path(target),
        Path(store) if store is not None else local_store(),
        Path(repo_docs),
        today or date.today().isoformat(),
        scopes,
    )


def main(stdin: IO[str] | None = None, stdout: IO[str] | None = None) -> int:
    """Read PostToolUse JSON from stdin; stay silent unless something is off."""
    src = stdin or sys.stdin
    dst = stdout or sys.stdout
    raw_text = src.read()
    if not raw_text.strip():
        return 0
    try:
        call = json.loads(raw_text)
    except json.JSONDecodeError:
        return 0
    try:
        result = evaluate(call if isinstance(call, dict) else {})
    except Exception:  # noqa: BLE001 - a hook must never break the session
        return 0
    notes: list[str] = []
    if result.get("status") == "missing-section":
        notes.append(
            "This conscience report has no '## Gap register' section, so nothing "
            "was recorded about what the resources could not support. Add the section "
            "— even empty — so the EDID resources keep learning from real misses. "
            "See agents/conscience.md, Output conventions."
        )
    for url, where in result.get("mismatched") or []:
        notes.append(
            f"Scope mismatch: this report cites {url}, which is scoped to "
            f"{where} and this deployment is not. Cite it as {where}'s source, "
            "not as this reader's rule — or say the resources have nothing for their "
            "jurisdiction. See agents/conscience.md, Scope."
        )
    for needed, hits in result.get("crossed") or []:
        notes.append(
            f"{hits} reviews have now been blocked by the same gap: {needed}. "
            "Nothing in the resources supports a flag here, so each of those was "
            "reported as an unsourced observation. Worth dispatching the "
            "bookworm — or recording a decision in docs/edid_gap_decisions.md "
            "if this is deliberately out of scope, which stops it asking again."
        )
    if notes:
        dst.write(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n\n".join(notes),
            },
        }))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
