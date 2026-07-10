"""
Purpose: Generate clearly-fake instrument data for the murmurent smoke-test
         tutorial. All values are obviously synthetic (fake OHIPs ``0000-000-NNN``,
         random base FASTQ, etc.); nothing here represents real PHI or real
         sequencing data.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: An output directory.
Output: A directory of fake FASTQ + clinicopath CSV + count matrix CSV +
        compound table CSV, suitable as a `murmurent experiment ingest` source.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import random
import sys
from pathlib import Path

DEFAULT_NUM_FASTQ = 4
DEFAULT_READS_PER_FASTQ = 200
DEFAULT_READ_LENGTH = 75
DEFAULT_NUM_PATIENTS = 30
DEFAULT_NUM_GENES = 200
DEFAULT_NUM_CELLS = 80
DEFAULT_NUM_COMPOUNDS = 25

BASES = "ACGT"


def write_fastq_gz(
    path: Path,
    *,
    n_reads: int,
    read_length: int,
    rng: random.Random,
    sample_id: str,
) -> None:
    """Write a fake gzipped FASTQ file with ``n_reads`` random-base reads."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="ascii") as fh:
        for i in range(n_reads):
            seq = "".join(rng.choice(BASES) for _ in range(read_length))
            qual = "I" * read_length
            fh.write(f"@FAKE:{sample_id}:read{i:06d}\n")
            fh.write(seq + "\n")
            fh.write("+\n")
            fh.write(qual + "\n")


def write_clinicopath(path: Path, *, n_patients: int, rng: random.Random, project: str) -> None:
    """Write a fake clinicopathology CSV with obviously-fake OHIPs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    grades = ["1", "2", "3"]
    er_pr = ["pos", "neg"]
    rows = []
    for i in range(1, n_patients + 1):
        rows.append(
            {
                "sample_id": f"{project[:6]}_S{i:03d}",
                "fake_ohip": f"0000-000-{i:03d}",
                "grade": rng.choice(grades),
                "ER": rng.choice(er_pr),
                "PR": rng.choice(er_pr),
                "age_at_diagnosis": str(rng.randint(35, 78)),
            }
        )
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_count_matrix(path: Path, *, n_genes: int, n_cells: int, rng: random.Random) -> None:
    """Write a fake gene x cell CSV count matrix."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        header = ["gene"] + [f"cell{j:04d}" for j in range(n_cells)]
        writer.writerow(header)
        for g in range(n_genes):
            row = [f"GENE_{g:04d}"]
            row.extend(str(rng.randint(0, 100)) for _ in range(n_cells))
            writer.writerow(row)


def write_compound_table(path: Path, *, n_compounds: int, rng: random.Random) -> None:
    """Write a fake CSV of compound IDs with mol weight and SMILES placeholders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["compound_id", "mol_weight", "logP", "fake_smiles"])
        for i in range(1, n_compounds + 1):
            writer.writerow(
                [
                    f"FAKE_CMP_{i:04d}",
                    f"{rng.uniform(150, 600):.2f}",
                    f"{rng.uniform(-1, 5):.2f}",
                    "".join(rng.choices("CN(=)O[]/", k=20)),
                ]
            )


def write_qc_html(path: Path, *, sample_id: str) -> None:
    """Write a tiny fake QC HTML report (instrument-derived)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"<html><body><h1>Fake QC report for {sample_id}</h1>"
        "<p>This file is intentionally fake; it is the kind of file the ingest "
        "verb classifies as <em>derived</em> rather than raw.</p></body></html>\n",
        encoding="utf-8",
    )


def write_summary_pdf(path: Path) -> None:
    """Write a minimal valid-looking PDF stub (instrument-derived)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # Real PDF parsing is out of scope; we just want the file to look plausible
    # and have a `.pdf` extension so the ingest classifier marks it derived.
    path.write_bytes(b"%PDF-1.4\n% fake summary PDF for murmurent smoke test\n%%EOF\n")


def generate_dcis_sequencing(out_dir: Path, *, rng: random.Random) -> None:
    """Generate the fake `dcis_sc_tutorial` sequencing-export bundle."""
    samples = ["S001", "S002", "S003", "S004"]
    for sid in samples:
        write_fastq_gz(
            out_dir / f"DCIS_{sid}_R1.fastq.gz",
            n_reads=DEFAULT_READS_PER_FASTQ,
            read_length=DEFAULT_READ_LENGTH,
            rng=rng,
            sample_id=sid,
        )
        write_fastq_gz(
            out_dir / f"DCIS_{sid}_R2.fastq.gz",
            n_reads=DEFAULT_READS_PER_FASTQ,
            read_length=DEFAULT_READ_LENGTH,
            rng=rng,
            sample_id=sid,
        )
    # Instrument metadata (raw per profile)
    (out_dir / "RunInfo.xml").write_text(
        '<?xml version="1.0"?><RunInfo><FakeRun id="FAKE_RUN_001"/></RunInfo>\n',
        encoding="utf-8",
    )
    (out_dir / "SampleSheet.csv").write_text(
        "Sample_ID,Sample_Name\n" + "\n".join(f"DCIS_{s},{s}" for s in samples) + "\n",
        encoding="utf-8",
    )
    # Instrument-derived (should be classified as derived by the profile)
    write_qc_html(out_dir / "run_qc.html", sample_id="FAKE_RUN_001")
    write_summary_pdf(out_dir / "run_summary.pdf")


def generate_dcis_clinical(out_dir: Path, *, rng: random.Random) -> None:
    """Generate the fake clinicopathology table for `dcis_sc_tutorial`."""
    write_clinicopath(
        out_dir / "clinicopath_v1.csv",
        n_patients=DEFAULT_NUM_PATIENTS,
        rng=rng,
        project="dcis",
    )


def generate_dcis_counts(out_dir: Path, *, rng: random.Random) -> None:
    """Generate a fake gene x cell count matrix for `dcis_sc_tutorial`."""
    write_count_matrix(
        out_dir / "count_matrix_v1.csv",
        n_genes=DEFAULT_NUM_GENES,
        n_cells=DEFAULT_NUM_CELLS,
        rng=rng,
    )


def generate_bbb_compounds(out_dir: Path, *, rng: random.Random) -> None:
    """Generate the fake compound table for `bbb_drug_screen`."""
    write_compound_table(
        out_dir / "compound_table_v1.csv",
        n_compounds=DEFAULT_NUM_COMPOUNDS,
        rng=rng,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        required=True,
        type=Path,
        help="Output directory (will be created).",
    )
    parser.add_argument(
        "--bundle",
        choices=["dcis_sequencing", "dcis_clinical", "dcis_counts", "bbb_compounds"],
        required=True,
    )
    parser.add_argument("--seed", type=int, default=20260507)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rng = random.Random(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.bundle == "dcis_sequencing":
        generate_dcis_sequencing(args.out, rng=rng)
    elif args.bundle == "dcis_clinical":
        generate_dcis_clinical(args.out, rng=rng)
    elif args.bundle == "dcis_counts":
        generate_dcis_counts(args.out, rng=rng)
    elif args.bundle == "bbb_compounds":
        generate_bbb_compounds(args.out, rng=rng)
    else:  # pragma: no cover - argparse already restricts
        raise SystemExit(f"unknown bundle: {args.bundle}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
