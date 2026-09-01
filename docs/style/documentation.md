# Documentation conventions

**Demoted from always-loaded.** Reference doc; read when authoring a
new script header or a `README.md`.

## `README.md` per repo

Every repository should have a `README.md` with:

- Project title + one-line description.
- Authors + contact.
- Dependencies + environment setup.
- How to reproduce the analysis.
- Expected inputs + outputs.
- License (if applicable).

## Script headers

Every script begins with a header.

### Python

```python
"""
Purpose: Brief description of what this script does.
Author:  Your Name
Date:    YYYY-MM-DD
Input:   Description of expected inputs.
Output:  Description of outputs generated.
"""
```

### R (top-of-file comment)

```r
#' Purpose: Brief description of what this script does.
#' Author:  Your Name
#' Date:    YYYY-MM-DD
#' Input:   Description of expected inputs.
#' Output:  Description of outputs generated.
```

### R function docstrings (Roxygen2)

```r
#' Calculate QC metrics for single-cell data
#'
#' @param counts_matrix Raw counts matrix (cells x genes)
#' @param min_genes Minimum genes per cell (default: 200)
#' @return A data frame of QC metrics per cell
#' @export
#' @examples
#' qc <- calculate_qc_metrics(counts)
```

## Inline comments

- Explain **why**, not what.
- Comment complex logic or non-obvious decisions.
- Avoid redundant comments (`# increment counter`).

## Analysis directories

Each analysis dir should contain:

- `README.md` explaining purpose + workflow.
- `environment.yml` or `requirements.txt` for reproducibility.
- Notebook comments explaining biological interpretation (when
  the analysis is bioinformatics).

## `CHANGELOG.md`

For significant projects, maintain a `CHANGELOG.md`. When files
have multiple versions, use the integer-suffix convention
(`file_1.csv`, `file_2.csv`, …); the largest integer is always
newest.
