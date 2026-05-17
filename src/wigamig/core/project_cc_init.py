"""
Purpose: Layer-2 CC bootstrap (per-project ``.claude/`` + CLAUDE.md).
Author: Mike Hallett (with Claude Code)
Date: 2026-05-15
Input: Project working-tree path, list of agents to symlink, paths to
       the wigamig commons.
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
    ``wigamig_root`` is the wigamig clone (``~/repos/wigamig``) — its
    ``agents/`` subdir is what we symlink from.

    Returns one Probe per discrete step. The caller decides whether to
    surface them inline or just log.

    Idempotency: re-running sweeps existing symlinks under
    ``.claude/agents/`` that point into the wigamig commons (so a
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
            detail=f"wigamig commons not at {agents_src} — skipped",
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
    # remove links whose target is inside the wigamig agents dir —
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
                detail=f"no {a}.md in wigamig commons",
                required=False,
            ))
            continue
        try:
            if dest.is_symlink() or dest.exists():
                dest.unlink()
            dest.symlink_to(src)
            probes.append(Probe(
                name=f"cc_agent: {a}", status="ok",
                detail=f"{dest} -> wigamig commons",
                required=False,
            ))
        except OSError as exc:
            probes.append(Probe(
                name=f"cc_agent: {a}", status="fail",
                detail=f"symlink {dest}: {exc}",
                required=False,
            ))

    # VSCode chrome — same settings wigamig uses for itself, so every
    # wigamig project opens with the title template, activity bar on
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

    # CC hooks settings — points at wigamig's hook handler script so
    # subagent start/stop events for this project land in the shared
    # ~/.wigamig/agents.log (which the BR pane tails). Only the hooks
    # block is written; permissions accumulate per-project as the
    # user grants them and live in .claude/settings.local.json.
    cc_settings = project_dir / ".claude" / "settings.json"
    if cc_settings.is_file():
        probes.append(Probe(
            name="cc_settings", status="ok",
            detail=f"{cc_settings} (already exists, preserved)",
            required=False,
        ))
    else:
        try:
            cc_settings.parent.mkdir(parents=True, exist_ok=True)
            cc_settings.write_text(
                _cc_settings_json(hook_path=wigamig_root / "scripts" / "wigamig_log_agent_event.sh"),
                encoding="utf-8",
            )
            probes.append(Probe(
                name="cc_settings", status="ok",
                detail=f"created {cc_settings}",
                required=False,
            ))
        except OSError as exc:
            probes.append(Probe(
                name="cc_settings", status="warn",
                detail=f"write {cc_settings}: {exc}",
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
        "Auto-generated by wigamig. Replace this stub with project-specific\n"
        "context: research question, members, data sources, choreography,\n"
        "sensitivity classification.\n"
        "\n"
        "## Agents wired up for this project\n"
        "\n"
        "See `.claude/agents/` — symlinks into `~/repos/wigamig/agents/`.\n"
        f"Selected: {selected}.\n"
        "\n"
        "## Data locations\n"
        "\n"
        f"{paths_block}\n"
        "\n"
        "## wigamig commons\n"
        "\n"
        "Lab-wide agents + rules live in `~/repos/wigamig/`. This project\n"
        "inherits from `~/.claude/` (Layer 1) AND overrides via `.claude/`\n"
        "here (Layer 2). See [[project-cc-commons-layered]] in lab oracle.\n"
    )


def _vscode_settings_json() -> str:
    """Same chrome wigamig uses for itself: window title, activity bar
    on the right, sidebar on the right, terminals default to the editor
    area (so the 4-quadrant layout works), and noise hidden from the
    Explorer. ``${rootName}`` makes the title auto-customize per project
    so we don't need a template — the same JSON works for every repo.
    """
    return json.dumps({
        "//": (
            "Per-folder VSCode settings for a wigamig project. Written by "
            "core.project_cc_init.bootstrap_local. Edit freely — wigamig "
            "preserves user-modified files on re-bootstrap."
        ),
        "window.title": "Wigamig — ${rootName}${separator}${activeEditorMedium}${separator}${dirty}",
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


def _cc_settings_json(*, hook_path: Path) -> str:
    """Minimal .claude/settings.json carrying just the hooks block so
    subagent start/stop events from this project land in the BR-pane
    log. No permissions — those grow per-project and live in the
    sibling settings.local.json.

    ``hook_path`` is an absolute path on this machine; the file is
    therefore per-machine. Add ``.claude/settings.json`` to the
    project's .gitignore if you don't want to share machine paths
    across collaborators (or symlink to a portable equivalent later).
    """
    return json.dumps({
        "//": (
            "Per-project CC hooks for the wigamig subagent reporter. "
            "Hook path is machine-specific; gitignore if you want to "
            "share the project across users."
        ),
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Agent",
                    "hooks": [{"type": "command", "command": str(hook_path)}],
                }
            ],
            "SubagentStop": [
                {
                    "hooks": [{"type": "command", "command": str(hook_path)}],
                }
            ],
        },
    }, indent=2) + "\n"
