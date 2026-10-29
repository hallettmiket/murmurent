"""
Purpose: Implementation of ``murmurent cite check``: look up every DOI, PMID
         and arXiv ID in a file and report any that do not exist, name a
         different paper, or have been retracted (issue #225).
Author: Mike Hallett (with Claude Code)
Date: 2026-10-23
Input: A ``.bib``, ``.tex``, ``.md`` or text file path, forwarded from
       :mod:`murmurent.cli`.
Output: A report on stdout; exit status 1 when any identifier is NOT FOUND,
        MISMATCH or RETRACTED, so a script or an agent can stop on it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from ..core import cite_check


def cmd_check(path: str, *, as_json: bool) -> None:
    """Check the file at ``path`` and exit non-zero on a failing identifier."""
    results = cite_check.check_file(Path(path))
    click.echo(cite_check.format_report(results, as_json=as_json))
    if any(r.status in cite_check.FAILING for r in results):
        sys.exit(1)
