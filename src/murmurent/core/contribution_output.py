"""
Purpose: Validate a contribution's produced *output table* against its Phase-1 output
         contract (:mod:`murmurent.core.contribution_contract`). When a contribution is run
         it emits a result table — one row per candidate — carrying the
         candidate-identity key, the reported metric, and (when the contract
         declares one) an uncertainty column. This module reads that table and
         checks it conforms to the contract, so the choreography judge can later
         join heterogeneous contribution outputs on the shared candidate key.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-21
Input: A :class:`~murmurent.core.contribution_contract.ContributionContract` and a path to a
       produced result table (CSV baseline; TSV / Parquet resolved by extension).
Output: :func:`validate_output` returns a list of human-readable problems
        (empty == the table conforms); :func:`read_table` returns
        ``(columns, rows)`` for a supported table file.

Boundary: this module reads + validates a produced output table only. It does
NOT run contributions, align outputs across contributions, or judge them — the judge (an
agent) does the combination. See ``docs/contributions.md`` / ``docs/choreography.md``.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .contribution_contract import ContributionContract

#: Canonical header for the per-row uncertainty column.
UNCERTAINTY_COLUMN = "uncertainty"

#: Extensions handled by :func:`read_table`, grouped by parser.
_DELIMITED: dict[str, str] = {".csv": ",", "": ",", ".tsv": "\t", ".tab": "\t"}
_PARQUET: frozenset[str] = frozenset({".parquet", ".pq"})

#: How many offending row numbers to name before summarising with an ellipsis.
_MAX_ROWS_LISTED = 5


class OutputFormatError(ValueError):
    """Raised when an output table's file format is unsupported or unreadable."""


def acceptable_uncertainty_columns(contract: ContributionContract) -> set[str]:
    """Column names accepted as the uncertainty column for ``contract``.

    Always the canonical ``uncertainty``; also the contract's declared
    uncertainty *kind* (e.g. ``stderr``, ``ci95``) so a table may name the
    column after the estimate it carries. Returns an empty set when the
    contract declares ``uncertainty: none`` (no uncertainty column required).
    """
    kind = (contract.uncertainty or "").strip().lower()
    if not kind or kind == "none":
        return set()
    return {UNCERTAINTY_COLUMN, kind}


def read_table(path: str | Path) -> tuple[list[str], list[dict[str, Any]]]:
    """Read a supported result table into ``(columns, rows)``.

    CSV is the baseline; ``.tsv`` / ``.tab`` are read as tab-delimited and
    ``.parquet`` / ``.pq`` via pandas (a deferred import). A file with no
    extension is treated as CSV. Raises :class:`OutputFormatError` for an
    unsupported extension or a parquet read without pandas available.
    """
    p = Path(path).expanduser()
    suffix = p.suffix.lower()
    if suffix in _DELIMITED:
        return _read_delimited(p, _DELIMITED[suffix])
    if suffix in _PARQUET:
        return _read_parquet(p)
    raise OutputFormatError(
        f"unsupported output format {suffix or '(none)'!r} for {p.name} "
        f"(expected .csv, .tsv, or .parquet)"
    )


def _read_delimited(path: Path, delimiter: str) -> tuple[list[str], list[dict[str, Any]]]:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=delimiter)
        columns = [c for c in (reader.fieldnames or []) if c is not None]
        rows = [dict(r) for r in reader]
    return columns, rows


def _read_parquet(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    try:
        import pandas as pd  # deferred: only needed for parquet outputs
    except Exception as exc:  # pragma: no cover - environment-dependent
        raise OutputFormatError(
            f"reading a parquet output table requires pandas: {exc}"
        ) from exc
    df = pd.read_parquet(path)
    columns = [str(c) for c in df.columns]
    rows = df.to_dict(orient="records")
    return columns, rows


def _fmt_rows(rows: list[int]) -> str:
    """Render a list of 1-based row numbers, capped for readability."""
    head = ", ".join(str(r) for r in rows[:_MAX_ROWS_LISTED])
    if len(rows) > _MAX_ROWS_LISTED:
        head += f", … (+{len(rows) - _MAX_ROWS_LISTED} more)"
    return head


def validate_output(contract: ContributionContract, path: str | Path) -> list[str]:
    """Return a list of problems; an empty list means the table conforms.

    Checks (mechanical only — this does not judge scientific merit):
      - the file exists and is a supported, readable table;
      - it is non-empty (at least one data row);
      - it has the contract's candidate-key column and metric column, and — when
        the contract declares ``uncertainty`` other than ``none`` — an
        uncertainty column (named ``uncertainty`` or after the estimate kind);
      - every row parses: the candidate key is non-blank and the metric value is
        present and numeric.
    """
    problems: list[str] = []
    p = Path(path).expanduser()
    if not p.is_file():
        return [f"output table not found: {p}"]

    try:
        columns, rows = read_table(p)
    except OutputFormatError as exc:
        return [str(exc)]
    except Exception as exc:  # malformed CSV, encoding errors, etc.
        return [f"output table {p.name} could not be read: {exc}"]

    if not rows:
        problems.append(f"output table {p.name} is empty (no data rows)")

    key = (contract.candidate_key or "").strip()
    metric = (contract.metric or "").strip()

    if key and key not in columns:
        problems.append(f"missing candidate-key column {key!r}")
    if metric and metric not in columns:
        problems.append(f"missing metric column {metric!r}")

    accept = acceptable_uncertainty_columns(contract)
    if accept and not (accept & set(columns)):
        problems.append(
            f"missing uncertainty column (expected one of {sorted(accept)}) — "
            f"contract declares uncertainty {contract.uncertainty!r}"
        )

    # Per-row parse checks (only for columns that are actually present).
    if key and key in columns:
        blank = [i for i, r in enumerate(rows, 1) if not str(r.get(key) or "").strip()]
        if blank:
            problems.append(
                f"candidate-key column {key!r} is blank in row(s) {_fmt_rows(blank)}"
            )
    if metric and metric in columns:
        empty: list[int] = []
        bad: list[int] = []
        for i, r in enumerate(rows, 1):
            raw = r.get(metric)
            text = "" if raw is None else str(raw).strip()
            if text == "":
                empty.append(i)
                continue
            try:
                float(text)
            except (TypeError, ValueError):
                bad.append(i)
        if empty:
            problems.append(
                f"metric column {metric!r} is empty in row(s) {_fmt_rows(empty)}"
            )
        if bad:
            problems.append(
                f"metric column {metric!r} is non-numeric in row(s) {_fmt_rows(bad)}"
            )

    return problems
