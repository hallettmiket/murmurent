# Code style — Python & R

**Demoted from always-loaded:** CC writes code that already follows
most of these defaults. This file is a reference: read it when a
question of style comes up, not on every session.

## General principles

- Write clear, readable code over clever code.
- Prefer explicit over implicit.
- Keep functions short and single-purpose.

## Python

- `snake_case` for variables and functions; `PascalCase` for classes;
  `UPPER_SNAKE_CASE` for constants.
- Type hints on all function signatures.
- `pathlib`, never `os.path`.
- f-strings, never `.format()` or `+`-concatenation.

## R

- Tidyverse style guide.
- `<-` for assignment, not `=`.
- `|>` (native) or `%>%` (magrittr) for piping.
- `snake_case` for variables and functions.

## Naming

- Descriptive names over abbreviations.
- Boolean variables: `is_`, `has_`, `should_` prefixes.
- Functions: verb_noun pattern (`load_samples`, `calculate_qc_metrics`).

## Preferred libraries

- Data manipulation: pandas (Python), tidyverse (R).
- Plotting: matplotlib / seaborn (Python), ggplot2 (R).
- File I/O: CSV, Parquet, HDF5.

## Patterns to avoid

- No hardcoded absolute paths.
- No `print()` for logging — use the `logging` module.
- No wildcard imports (`from x import *`).
- No magic numbers — name them as constants.

## Formatting

Run these tools before committing (don't ask Claude to format):

- Python: `black .` and `isort .`
- R: `styler::style_file()`
