"""
Purpose: Evidence for claim c1 of the example paper: colonies grown in serum
         are larger than controls. Reads data/signal.csv, writes the group
         means, their difference and a permutation p-value to
         build/results.tsv. No dependencies beyond the standard library, so a
         reader can re-run it anywhere.
Author: Mike Hallett (with Claude Code)
Date: 2026-11-06
Input: data/signal.csv (isolate, medium, colony_mm, country)
Output: build/results.tsv
"""

from __future__ import annotations

import csv
import random
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
PACKAGE = HERE.parents[1]
DATA = PACKAGE / "data" / "signal.csv"
OUT = PACKAGE / "build" / "results.tsv"


def main() -> None:
    rows = list(csv.DictReader(DATA.open()))
    by = {}
    for r in rows:
        by.setdefault(r["medium"], []).append(float(r["colony_mm"]))
    control, serum = by["control"], by["serum"]
    observed = statistics.mean(serum) - statistics.mean(control)
    pooled = control + serum
    rng = random.Random(0)
    n_perm, hits = 5000, 0
    for _ in range(n_perm):
        rng.shuffle(pooled)
        if statistics.mean(pooled[len(control):]) - statistics.mean(pooled[:len(control)]) >= observed:
            hits += 1
    p = (hits + 1) / (n_perm + 1)
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w") as f:
        f.write("measure\tvalue\n")
        f.write(f"mean_control_mm\t{statistics.mean(control):.2f}\n")
        f.write(f"mean_serum_mm\t{statistics.mean(serum):.2f}\n")
        f.write(f"difference_mm\t{observed:.2f}\n")
        f.write(f"permutation_p\t{p:.4f}\n")
    print(OUT.read_text())


if __name__ == "__main__":
    main()
