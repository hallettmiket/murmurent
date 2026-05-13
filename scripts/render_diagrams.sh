#!/usr/bin/env bash
# Purpose: Render every .dot source in docs/diagrams/ to SVG + PNG.
# Author:  Mike Hallett (with Claude Code)
# Date:    2026-05-13
# Input:   docs/diagrams/*.dot
# Output:  docs/diagrams/<name>.svg, docs/diagrams/<name>.png
# Usage:   bash scripts/render_diagrams.sh
#
# Requires Graphviz (`brew install graphviz` on macOS;
# `apt install graphviz` on biodatsci/Ubuntu). The script exits with
# a helpful message if `dot` is not on PATH.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DIAGRAM_DIR="${REPO_DIR}/docs/diagrams"

if ! command -v dot >/dev/null 2>&1; then
  cat >&2 <<'EOF'
ERROR: Graphviz (`dot`) is not on PATH.

Install:
  macOS:    brew install graphviz
  Ubuntu:   sudo apt install graphviz

Then re-run: bash scripts/render_diagrams.sh
EOF
  exit 1
fi

shopt -s nullglob
sources=("${DIAGRAM_DIR}"/*.dot)
if [[ ${#sources[@]} -eq 0 ]]; then
  echo "no .dot files in ${DIAGRAM_DIR}" >&2
  exit 0
fi

for src in "${sources[@]}"; do
  base="$(basename "${src}" .dot)"
  svg="${DIAGRAM_DIR}/${base}.svg"
  png="${DIAGRAM_DIR}/${base}.png"
  echo "rendering ${base}.dot → ${base}.svg + ${base}.png"
  dot -Tsvg -o "${svg}" "${src}"
  dot -Tpng -Gdpi=180 -o "${png}" "${src}"
done

echo "done — outputs in ${DIAGRAM_DIR}"
