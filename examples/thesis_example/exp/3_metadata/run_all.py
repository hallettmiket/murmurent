"""
Purpose: Evidence for claim c3.1 of the example thesis: colony size by country
         of origin. Reads the example paper's data, writes per-country means to
         build/country_means.tsv.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-06
Input: ../paper_example/data/signal.csv
Output: build/country_means.tsv
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
THESIS = HERE.parents[1]
DATA = THESIS.parent / "paper_example" / "data" / "signal.csv"
OUT = THESIS / "build" / "country_means.tsv"


def main() -> None:
    by: dict[str, list[float]] = {}
    for r in csv.DictReader(DATA.open()):
        by.setdefault(r["country"], []).append(float(r["colony_mm"]))
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w") as f:
        f.write("country\tn\tmean_mm\n")
        for c in sorted(by):
            f.write(f"{c}\t{len(by[c])}\t{statistics.mean(by[c]):.2f}\n")
    print(OUT.read_text())


if __name__ == "__main__":
    main()
