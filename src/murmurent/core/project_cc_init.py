"""
Purpose: Layer-2 CC bootstrap (per-project ``.claude/`` + CLAUDE.md).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-15
Input: Project working-tree path, list of agents to symlink, paths to
       the murmurent commons.
Output: ``[Probe]`` rows the UI renders inline.

Pairs with [[project-cc-commons-layered]]: Layer 1 (per-machine) is
``scripts/setup.sh``; Layer 2 (per-project) is this module.

Two callers:
  - ``POST /api/workspace/initialize`` — runs this for local installs
    (the remote install path uses the equivalent inlined bash snippet
    in :mod:`core.remote_install`). The two flows produce the same
    end-state by design.
  - ``scripts/backfill_local_repos.py`` — one-shot walk of
    ``~/repos/<project>`` for the legacy machines where projects
    existed before the install-wizard refactor landed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .preflight import Probe

_AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

_OVERLEAF_MARKER = "<!-- murmurent:overleaf-manuscript -->"


def _overleaf_manuscript_claude_md(project: str, repo_name: str) -> str:
    """The CLAUDE.md a manuscript repo (role=manuscript, Overleaf-synced) gets, so
    any CC session in it follows the pull-first rules (see rules/manuscript.md)."""
    title = repo_name or project or "manuscript"
    return (f"{_OVERLEAF_MARKER}\n"
            f"# CLAUDE.md — {title} (Overleaf-synced manuscript)\n\n"
            f"This repo is the manuscript for **{project or title}**, synchronised "
            "with **Overleaf via GitHub**. Overleaf pushes to `main`, so the remote "
            "can be ahead of your local clone at any time. Rules (managed by "
            "murmurent — see the commons' `rules/manuscript.md`):\n\n"
            "- **`git pull` BEFORE editing.** Skipping this risks clobbering edits "
            "made in Overleaf and produces painful conflicts.\n"
            "- **Commit + push promptly** after a coherent block so Overleaf can "
            "fetch.\n"
            "- **No feature branches** — Overleaf only tracks `main`.\n"
            "- **No bulk reformatting** (rewrapping, reordering) — Overleaf reads "
            "whitespace churn as content changes and it buries real edits.\n"
            "- **Do not compile locally**; Overleaf compiles. Do not edit "
            "`*.aux`/`*.bbl`/`*.blg`/`*.log`/`*.out`/`*.synctex.gz`.\n"
            "- **On a `git pull` conflict, Overleaf edits are authoritative** — "
            "stop and ask before resolving.\n")


def write_overleaf_manuscript_note(repo_dir, *, project: str = "",
                                   repo_name: str = "") -> bool:
    """Ensure an Overleaf-manuscript ``CLAUDE.md`` in ``repo_dir`` (a manuscript
    repo's clone). Idempotent: writes only when the dir exists and has no CLAUDE.md
    (a user-authored one is preserved). Returns True when it wrote the note."""
    d = Path(repo_dir).expanduser()
    if not d.is_dir():
        return False
    claude_md = d / "CLAUDE.md"
    if claude_md.is_file():
        return False
    try:
        claude_md.write_text(_overleaf_manuscript_claude_md(project, repo_name),
                             encoding="utf-8")
        return True
    except OSError:
        return False


def bootstrap_local(
    project_dir: Path,
    wigamig_root: Path,
    *,
    agents: list[str] | None,
    project_name: str | None = None,
    raw_path: str | None = None,
    refined_path: str | None = None,
    notebook_path: str | None = None,
) -> list[Probe]:
    """Symlink picked agents + write CLAUDE.md stub for a local project.

    ``project_dir`` is the working tree (``~/repos/<project>``).
    ``wigamig_root`` is the murmurent clone (``~/repos/murmurent``) — its
    ``agents/`` subdir is what we symlink from.

    Returns one Probe per discrete step. The caller decides whether to
    surface them inline or just log.

    Idempotency: re-running sweeps existing symlinks under
    ``.claude/agents/`` that point into the murmurent commons (so a
    re-install with a different pick doesn't leave stale links).
    Non-symlink files survive untouched (preserves user-authored
    project-specific agents).
    """
    probes: list[Probe] = []
    name = project_name or project_dir.name

    if not project_dir.is_dir():
        probes.append(Probe(
            name="cc_init", status="fail",
            detail=f"project dir not found: {project_dir}",
            required=False,
        ))
        return probes

    agents_src = wigamig_root / "agents"
    if not agents_src.is_dir():
        probes.append(Probe(
            name="cc_init", status="warn",
            detail=f"murmurent commons not at {agents_src} — skipped",
            required=False,
        ))
        return probes

    # Filter agent names to the same safe alphabet the remote shell
    # snippet uses; both code paths converge on the same end-state.
    safe_agents = [
        a for a in (agents or [])
        if isinstance(a, str) and _AGENT_NAME_RE.match(a.strip())
    ]

    claude_agents = project_dir / ".claude" / "agents"
    try:
        claude_agents.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        probes.append(Probe(
            name="cc_init", status="fail",
            detail=f"mkdir {claude_agents}: {exc}",
            required=False,
        ))
        return probes

    # Sweep stale wigamig-commons symlinks before re-creating. Only
    # remove links whose target is inside the murmurent agents dir —
    # user-authored .md files and symlinks to elsewhere stay.
    wig_agents_prefix = str(agents_src) + "/"
    for f in claude_agents.iterdir():
        if not f.is_symlink():
            continue
        try:
            target = str(f.readlink())
        except OSError:
            continue
        if target.startswith(wig_agents_prefix) or target == str(agents_src):
            try:
                f.unlink()
            except OSError:
                pass

    # Materialize the new pick. Missing source files surface as a
    # yellow row instead of silent skip — the user wants to know if
    # they typed an agent name that doesn't match the commons.
    for a in safe_agents:
        src = agents_src / f"{a}.md"
        dest = claude_agents / f"{a}.md"
        if not src.is_file():
            probes.append(Probe(
                name=f"cc_agent: {a}", status="warn",
                detail=f"no {a}.md in murmurent commons",
                required=False,
            ))
            continue
        try:
            if dest.is_symlink() or dest.exists():
                dest.unlink()
            dest.symlink_to(src)
            probes.append(Probe(
                name=f"cc_agent: {a}", status="ok",
                detail=f"{dest} -> murmurent commons",
                required=False,
            ))
        except OSError as exc:
            probes.append(Probe(
                name=f"cc_agent: {a}", status="fail",
                detail=f"symlink {dest}: {exc}",
                required=False,
            ))

    # VSCode chrome — same settings murmurent uses for itself, so every
    # murmurent project opens with the title template, activity bar on
    # the right, and terminals defaulting to the editor area (the
    # foundation for the 4-quadrant layout). Skipped if the project
    # already has a .vscode/settings.json — preserves user edits.
    vscode_dir = project_dir / ".vscode"
    vscode_settings = vscode_dir / "settings.json"
    if vscode_settings.is_file():
        probes.append(Probe(
            name="vscode_settings", status="ok",
            detail=f"{vscode_settings} (already exists, preserved)",
            required=False,
        ))
    else:
        try:
            vscode_dir.mkdir(parents=True, exist_ok=True)
            vscode_settings.write_text(
                _vscode_settings_json(),
                encoding="utf-8",
            )
            probes.append(Probe(
                name="vscode_settings", status="ok",
                detail=f"created {vscode_settings}",
                required=False,
            ))
        except OSError as exc:
            probes.append(Probe(
                name="vscode_settings", status="warn",
                detail=f"write {vscode_settings}: {exc}",
                required=False,
            ))

    # CC hooks no longer live per-project — they're now merged into the
    # user-global ~/.claude/settings.json by `murmurent install --hooks`
    # so they fire for every project on this machine, sharing a single
    # ~/.murmurent/agents.log. We don't write .claude/settings.json here
    # any more.
    #
    # Defensive: if the user later creates a per-project
    # .claude/settings.json (e.g. for project-specific permissions
    # they don't want global), add it to the project's .gitignore so
    # machine-absolute paths and per-machine grants don't escape to
    # collaborators. Done once per project; idempotent.
    gitignore = project_dir / ".gitignore"
    ignore_line = ".claude/settings.json"
    try:
        if gitignore.is_file():
            existing = gitignore.read_text(encoding="utf-8")
            already = any(
                line.strip() == ignore_line
                for line in existing.splitlines()
            )
            if already:
                probes.append(Probe(
                    name="gitignore", status="ok",
                    detail=f"{gitignore} already lists {ignore_line}",
                    required=False,
                ))
            else:
                sep = "" if existing.endswith("\n") else "\n"
                gitignore.write_text(
                    existing + sep + ignore_line + "\n",
                    encoding="utf-8",
                )
                probes.append(Probe(
                    name="gitignore", status="ok",
                    detail=f"appended {ignore_line} to {gitignore}",
                    required=False,
                ))
        else:
            gitignore.write_text(
                "# murmurent: machine-local CC settings (paths, grants)\n"
                + ignore_line + "\n",
                encoding="utf-8",
            )
            probes.append(Probe(
                name="gitignore", status="ok",
                detail=f"created {gitignore} with {ignore_line}",
                required=False,
            ))
    except OSError as exc:
        probes.append(Probe(
            name="gitignore", status="warn",
            detail=f"write {gitignore}: {exc}",
            required=False,
        ))

    # CLAUDE.md stub. Skip if user already authored one.
    claude_md = project_dir / "CLAUDE.md"
    if claude_md.is_file():
        probes.append(Probe(
            name="cc_claude_md", status="ok",
            detail=f"{claude_md} (already exists, preserved)",
            required=False,
        ))
    else:
        try:
            claude_md.write_text(_stub(
                project=name,
                agents=safe_agents,
                raw_path=raw_path,
                refined_path=refined_path,
                notebook_path=notebook_path,
            ), encoding="utf-8")
            probes.append(Probe(
                name="cc_claude_md", status="ok",
                detail=f"created {claude_md}",
                required=False,
            ))
        except OSError as exc:
            probes.append(Probe(
                name="cc_claude_md", status="fail",
                detail=f"write {claude_md}: {exc}",
                required=False,
            ))

    return probes


def _stub(
    *,
    project: str,
    agents: list[str],
    raw_path: str | None,
    refined_path: str | None,
    notebook_path: str | None,
) -> str:
    """Render the per-project CLAUDE.md stub.

    Kept terse — the user / agents are expected to expand it with
    research question, members, choreography, etc. The auto-generated
    part is bounded by a header so a future migration can rewrite it
    without disturbing user additions below.
    """
    selected = " ".join(agents) if agents else "(none — Layer-1 commons covers all)"
    paths = []
    if raw_path:
        paths.append(f"- raw: `{raw_path}/{project}`")
    if refined_path:
        paths.append(f"- refined: `{refined_path}/{project}`")
    if notebook_path:
        paths.append(f"- notebooks: `{notebook_path}`")
    paths_block = "\n".join(paths) if paths else "_(no install manifest yet — install via the dashboard to populate)_"
    return (
        f"# {project}\n"
        "\n"
        "Auto-generated by murmurent. Replace this stub with project-specific\n"
        "context: research question, members, data sources, choreography,\n"
        "sensitivity classification.\n"
        "\n"
        "## Agents wired up for this project\n"
        "\n"
        "See `.claude/agents/` — symlinks into `~/repos/murmurent/agents/`.\n"
        f"Selected: {selected}.\n"
        "\n"
        "## Data locations\n"
        "\n"
        f"{paths_block}\n"
        "\n"
        "## murmurent commons\n"
        "\n"
        "Lab-wide agents + rules live in `~/repos/murmurent/`. This project\n"
        "inherits from `~/.claude/` (Layer 1) AND overrides via `.claude/`\n"
        "here (Layer 2). See [[project-cc-commons-layered]] in lab oracle.\n"
    )


def _vscode_settings_json() -> str:
    """Same chrome murmurent uses for itself: window title, activity bar
    on the right, sidebar on the right, terminals default to the editor
    area (so the 4-quadrant layout works), and noise hidden from the
    Explorer. ``${rootName}`` makes the title auto-customize per project
    so we don't need a template — the same JSON works for every repo.
    """
    return json.dumps({
        "//": (
            "Per-folder VSCode settings for a murmurent project. Written by "
            "core.project_cc_init.bootstrap_local. Edit freely — murmurent "
            "preserves user-modified files on re-bootstrap."
        ),
        "window.title": "Murmurent — ${rootName}${separator}${activeEditorMedium}${separator}${dirty}",
        "window.titleSeparator": "  ·  ",
        "workbench.activityBar.location": "end",
        "workbench.sideBar.location": "right",
        "terminal.integrated.defaultLocation": "editor",
        "terminal.integrated.tabs.location": "right",
        "files.exclude": {
            "**/.pytest_cache": True,
            "**/__pycache__": True,
            "**/.venv": True,
        },
    }, indent=2) + "\n"


# NOTE: ``_cc_settings_json`` removed 2026-05-17 when the murmurent
# subagent-reporter hooks moved from per-project ``.claude/settings.json``
# into the user-global ``~/.claude/settings.json`` (single source of
# truth, no machine-absolute paths leaking into project repos).
# ``murmurent install --hooks`` is the canonical writer of the global
# entry; bootstrap_local manages the project-level .gitignore so any
# *user*-created .claude/settings.json doesn't escape to git.
