"""
Purpose: Implementations of ``murmurent experiment ...`` subcommands.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-07
Input: CLI arguments forwarded from :mod:`murmurent.cli`.
Output: Side effects on the project repo's ``exp/`` tree, the data root's
        immutable + append-only dirs, and ``notebook.md`` frontmatter.
"""

from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..core import lab_vm
from ..core.frontmatter import dump_document, parse_file
from ..core.identity import resolve as resolve_identity
from ..core.ingest import IngestPlan, execute_ingest, format_plan, plan_ingest
from ..core.notebook import VALID_STATUSES, render_notebook, update_with_ingest
from ..core.projects import find_project, iter_local_projects
from ..core.repo import ProjectRepo

EXPERIMENT_SUBDIRS = ("pages", "sketches", "data")
EXPERIMENT_DIR_PATTERN = re.compile(r"^(?P<idx>\d+)_(?P<slug>[a-z0-9_]+)$")


def _today() -> str:
    return _dt.date.today().isoformat()


def _resolve_repo(project_name: str) -> ProjectRepo:
    repo = find_project(project_name)
    if repo is None:
        raise click.ClickException(f"Project not found locally: {project_name}")
    return repo


def _list_experiments(repo: ProjectRepo) -> list[Path]:
    exp_root = repo.path / "exp"
    if not exp_root.is_dir():
        return []
    return sorted(
        p for p in exp_root.iterdir() if p.is_dir() and EXPERIMENT_DIR_PATTERN.match(p.name)
    )


def _next_experiment_index(repo: ProjectRepo) -> int:
    indices: list[int] = []
    for p in _list_experiments(repo):
        m = EXPERIMENT_DIR_PATTERN.match(p.name)
        if m:
            indices.append(int(m.group("idx")))
    return (max(indices) + 1) if indices else 1


def _resolve_experiment(repo: ProjectRepo, slug_or_dir: str) -> Path:
    """Resolve an experiment directory by full ``<idx>_<slug>`` or bare ``<slug>``."""
    exp_root = repo.path / "exp"
    full = exp_root / slug_or_dir
    if full.is_dir():
        return full
    if EXPERIMENT_DIR_PATTERN.match(slug_or_dir):
        raise click.ClickException(f"Experiment dir not found: {full}")
    # Bare slug - find the unique <idx>_<slug>.
    matches = [
        p
        for p in _list_experiments(repo)
        if EXPERIMENT_DIR_PATTERN.match(p.name).group("slug") == slug_or_dir  # type: ignore[union-attr]
    ]
    if not matches:
        raise click.ClickException(f"No experiment matching slug {slug_or_dir!r} in {exp_root}")
    if len(matches) > 1:
        names = ", ".join(p.name for p in matches)
        raise click.ClickException(
            f"Slug {slug_or_dir!r} is ambiguous in {exp_root}: {names}. "
            "Pass the full <idx>_<slug>."
        )
    return matches[0]


def cmd_new(
    project_name: str,
    slug: str,
    *,
    status: str = "planned",
    analysis_status: str = "not_started",
    performer: list[str] | None = None,
) -> Path:
    """``murmurent experiment new`` — scaffold ``exp/<n>_<slug>/`` and lab-VM dirs."""
    repo = _resolve_repo(project_name)
    if not EXPERIMENT_DIR_PATTERN.match(f"1_{slug}"):
        raise click.ClickException(
            f"slug must be lowercase snake_case (matched against /^\\d+_{{slug}}$/): {slug!r}"
        )
    idx = _next_experiment_index(repo)
    exp_name = f"{idx}_{slug}"
    exp_dir = repo.path / "exp" / exp_name
    exp_dir.mkdir(parents=True, exist_ok=False)
    for sub in EXPERIMENT_SUBDIRS:
        (exp_dir / sub).mkdir(parents=True, exist_ok=True)

    if performer is None:
        identity = resolve_identity(allow_unknown=True)
        performer = [f"@{identity.handle}"]
    notebook_text = render_notebook(
        project=project_name,
        experiment=exp_name,
        date=_today(),
        performer=performer,
        status=status,
        analysis_status=analysis_status,
    )
    (exp_dir / "notebook.md").write_text(notebook_text, encoding="utf-8")

    (exp_dir / "README.md").write_text(
        f"# {exp_name}\n\n"
        f"Experiment {exp_name} of project {project_name}.\n\n"
        "See `notebook.md` for the lab notebook entry, `run_all.py` for the entry-point analysis script, and "
        "the `pages/`, `sketches/`, `data/` subfolders for documentation media.\n",
        encoding="utf-8",
    )
    (exp_dir / "run_all.py").write_text(
        '"""\n'
        f"Purpose: Entry-point analysis script for experiment {exp_name}.\n"
        "Author: TBD\n"
        f"Date: {_today()}\n"
        "Input: see notebook.md immutable_data section.\n"
        "Output: see notebook.md append_only_data section.\n"
        '"""\n\n'
        "from __future__ import annotations\n\n\n"
        "def main() -> int:\n"
        '    """Run the experiment\'s analysis pipeline. Stub for v1."""\n'
        '    print("run_all stub - implement me")\n'
        "    return 0\n\n\n"
        'if __name__ == "__main__":\n'
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )

    lab_vm.ensure_experiment_dirs(project_name, exp_name)
    click.echo(f"Created {exp_dir}")
    click.echo(
        f"Data immutable:   {lab_vm.experiment_immutable_dir(project_name, exp_name)}\n"
        f"Data append_only: {lab_vm.experiment_append_only_dir(project_name, exp_name)}"
    )
    return exp_dir


def cmd_list(project_name: str | None) -> int:
    """``murmurent experiment list`` — print all experiments and their statuses."""
    repos: list[ProjectRepo] = []
    if project_name is None:
        repos = iter_local_projects()
    else:
        repos = [_resolve_repo(project_name)]

    console = Console()
    table = Table(title="Experiments")
    table.add_column("project")
    table.add_column("experiment")
    table.add_column("status")
    table.add_column("analysis_status")
    table.add_column("performer")

    found = False
    for repo in repos:
        for exp_dir in _list_experiments(repo):
            notebook = exp_dir / "notebook.md"
            if not notebook.is_file():
                continue
            try:
                parsed = parse_file(notebook)
            except Exception:
                continue
            performer = parsed.meta.get("performer") or []
            performer_str = ", ".join(performer) if isinstance(performer, list) else str(performer)
            table.add_row(
                repo.path.name,
                exp_dir.name,
                str(parsed.meta.get("status", "?")),
                str(parsed.meta.get("analysis_status", "?")),
                performer_str,
            )
            found = True
    if not found:
        click.echo("No experiments found.")
        return 0
    console.print(table)
    return 0


def cmd_status(project_name: str, slug: str, set_value: str) -> int:
    """``murmurent experiment status`` — flip the notebook ``status`` field."""
    if set_value not in VALID_STATUSES:
        raise click.ClickException(f"--set must be one of {VALID_STATUSES!r}; got {set_value!r}")
    repo = _resolve_repo(project_name)
    exp_dir = _resolve_experiment(repo, slug)
    notebook = exp_dir / "notebook.md"
    parsed = parse_file(notebook)
    current = parsed.meta.get("status")
    parsed.meta["status"] = set_value
    notebook.write_text(dump_document(parsed.meta, parsed.body), encoding="utf-8")
    click.echo(f"{exp_dir.name} status: {current} -> {set_value}")
    return 0


def cmd_ingest(
    project_name: str,
    slug: str,
    source: str,
    *,
    instrument: str | None,
    accept: bool,
    dry_run: bool,
) -> int:
    """``murmurent experiment ingest`` — classify, prompt, copy, chmod, hash, update notebook."""
    repo = _resolve_repo(project_name)
    exp_dir = _resolve_experiment(repo, slug)
    plan: IngestPlan = plan_ingest(
        project=project_name,
        experiment=exp_dir.name,
        source=source,
        instrument=instrument,
    )
    click.echo(format_plan(plan))
    if dry_run:
        click.echo("[--dry-run] no files copied.")
        return 0
    if plan.total == 0:
        click.echo("No regular files in source; nothing to ingest.")
        return 0
    if not accept:
        choice = click.prompt(
            "[a]ccept  [c]ancel ?",
            type=click.Choice(["a", "c"], case_sensitive=False),
            default="c",
            show_default=True,
        ).lower()
        if choice != "a":
            click.echo("Cancelled.")
            return 1

    result = execute_ingest(plan)
    notebook = exp_dir / "notebook.md"
    parsed = parse_file(notebook)
    parsed.meta = update_with_ingest(
        parsed.meta,
        raw_files=result.raw,
        instrument_files=result.instrument_outputs,
    )
    notebook.write_text(dump_document(parsed.meta, parsed.body), encoding="utf-8")

    click.echo(f"Copied {len(result.raw)} raw files -> {result.raw_dir}")
    click.echo(
        f"Copied {len(result.instrument_outputs)} derived files -> "
        f"{lab_vm.experiment_instrument_outputs_dir(project_name, exp_dir.name)}"
    )
    click.echo(f"chmod a-w applied recursively to {result.raw_dir}")
    click.echo(f"Updated {notebook}")
    return 0
