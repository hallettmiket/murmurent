"""
Purpose: SSH-side helpers for adopting an existing remote clone as a
         murmurent project — writes CHARTER.md on the host and runs the
         layer-2 CC bootstrap (``.claude/agents/`` + ``CLAUDE.md``)
         over a single batched SSH session.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-17
Input: A :class:`Host` (the remote where the clone lives) + the rendered
       charter body + project metadata (name, agents to symlink).
Output: ``list[Probe]`` — one row per discrete step, same shape the
        install wizard already emits so the dashboard renders both
        flows the same way.

The local-adopt equivalent is :mod:`core.projectize` — for a local
clone the CHARTER write and bootstrap_local happen against the
filesystem directly; for a remote clone we have to go over SSH. We
keep the two paths separate so a) the SSH protocol noise doesn't
contaminate the local-adopt happy path, and b) the local tests can
run without any network.

Why a single batched script: each SSH handshake on lab-server costs
~2-3 seconds (key verify + login shell). Writing CHARTER, sweeping
agent symlinks, creating new ones, and writing CLAUDE.md as separate
calls would be 4-5× slower than one ``bash -lc`` doing all of it.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

from . import hosts as _hosts
from . import preflight as _pf
from . import remote as _remote


# Agent names already get validated by :mod:`core.projectize` (and the
# CC bootstrap in :mod:`core.remote_install`); we re-validate here so
# the SSH snippet's ``for a in <names>`` loop never sees a shell
# metacharacter. The regex matches the same alphabet the local
# bootstrap accepts.
_AGENT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Project name appears in path expansions (``$HOME/repos/<name>``);
# restrict to the same safe alphabet so the path can't be poisoned.
_PROJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class RemoteAdoptError(Exception):
    """Raised when remote_adopt can't even attempt the SSH session
    (host not registered, missing project name, etc.). Distinct from
    a failed probe — that's a successful round-trip with a fail row."""

    detail: str

    def __str__(self) -> str:  # pragma: no cover - cosmetic
        return self.detail


def build_remote_adopt_script(
    *,
    clone_path: str,
    project: str,
    charter_text: str,
    agents: list[str],
) -> str:
    """Render the batched bash that runs over SSH for a remote adopt.

    Emits records the install-wizard parser already understands
    (``<step>:<status>:<detail>``), in the order:
      - ``charter:…`` — wrote CHARTER.md, or preserved an existing one
      - ``cc_agent: <name>:…`` — one per agent symlink attempt
      - ``cc_claude_md:…`` — wrote CLAUDE.md stub, or preserved existing

    Safety:
      - ``clone_path`` is shell-quoted (``shlex.quote``).
      - Agent names are pre-filtered to ``[A-Za-z0-9_-]+`` so the
        ``for a in <names>`` loop is safe to interpolate.
      - CHARTER body uses a *quoted* heredoc delimiter
        (``<<'__WIGAMIG_CHARTER_EOF__'``) so ``$VAR`` references inside
        the charter aren't expanded by the remote shell.
    """
    if not _PROJECT_NAME_RE.match(project):
        raise RemoteAdoptError(f"unsafe project name: {project!r}")
    safe_agents = [a for a in agents if isinstance(a, str) and _AGENT_NAME_RE.match(a)]
    agents_csv = " ".join(safe_agents)
    dest_q = shlex.quote(clone_path)

    # The CHARTER body should never contain our delimiter, but defend
    # against the pathological case (and against future maintainers
    # using a different heredoc tag) by asserting up front.
    if "__WIGAMIG_CHARTER_EOF__" in charter_text:
        raise RemoteAdoptError(
            "charter body contains the heredoc delimiter — refusing to write"
        )

    # NOTE: we don't strictly *need* the ssh-side ``[ -f ".../CHARTER.md" ]``
    # check (the endpoint layer already validates), but the script is the
    # last line of defence: if the user races us by writing CHARTER between
    # the endpoint's preflight and this run, we still preserve their file.
    lines = [
        f'DEST={dest_q}',
        # Charter step.
        'if [ ! -d "$DEST/.git" ]; then',
        '  echo "charter:fail:not a git working tree: $DEST"',
        'elif [ -f "$DEST/CHARTER.md" ]; then',
        '  echo "charter:ok:already exists at $DEST/CHARTER.md (preserved)"',
        'else',
        "  cat > \"$DEST/CHARTER.md\" <<'__WIGAMIG_CHARTER_EOF__'",
        charter_text.rstrip("\n"),
        "__WIGAMIG_CHARTER_EOF__",
        '  if [ -f "$DEST/CHARTER.md" ]; then',
        '    echo "charter:ok:wrote $DEST/CHARTER.md"',
        '  else',
        '    echo "charter:fail:write returned no file at $DEST/CHARTER.md"',
        '  fi',
        'fi',
        # CC bootstrap — only runs when the clone is present AND the
        # murmurent commons is checked out on the host. Mirrors the
        # equivalent block in remote_install._build_script so behaviour
        # is identical to the install-wizard path.
        'WIG="$HOME/repos/wigamig"',
        'if [ -d "$DEST/.git" ] && [ -d "$WIG/agents" ]; then',
        '  mkdir -p "$DEST/.claude/agents"',
        '  for f in "$DEST/.claude/agents"/*.md; do',
        '    [ -L "$f" ] || continue',
        '    target=$(readlink "$f")',
        '    case "$target" in',
        '      */repos/wigamig/agents/*) rm -f "$f" ;;',
        '    esac',
        '  done',
        f'  for a in {agents_csv}; do',
        '    src="$WIG/agents/$a.md"',
        '    if [ -f "$src" ]; then',
        '      ln -sfn "$src" "$DEST/.claude/agents/$a.md"',
        '      echo "cc_agent:ok:$a -> wigamig/agents/$a.md"',
        '    else',
        '      echo "cc_agent:warn:$a (no $a.md in murmurent commons)"',
        '    fi',
        '  done',
        '  if [ ! -f "$DEST/CLAUDE.md" ]; then',
        '    cat > "$DEST/CLAUDE.md" <<__CLAUDE_MD_EOF__',
        f'# {project}',
        '',
        'Auto-generated by murmurent at adopt time. Replace this stub with',
        'project-specific context, including: research question, members,',
        'data sources, choreography, sensitivity classification.',
        '',
        '## Agents wired up for this project',
        '',
        'See `.claude/agents/` — symlinks into `~/repos/wigamig/agents/`.',
        f'Selected at adopt time: {agents_csv or "(none)"}.',
        '',
        '## murmurent commons',
        '',
        'Lab-wide agents + rules live in `~/repos/wigamig/`. This project',
        'inherits from there; project-specific overrides go in `.claude/`.',
        '__CLAUDE_MD_EOF__',
        '    echo "cc_claude_md:ok:created $DEST/CLAUDE.md"',
        '  else',
        '    echo "cc_claude_md:ok:already exists at $DEST/CLAUDE.md"',
        '  fi',
        # VSCode chrome — same intent as bootstrap_local's local write.
        # Heredoc is unquoted on the JSON delimiter so we keep the
        # JSON exactly as authored; safe because the JSON contains no
        # shell metacharacters that would expand.
        '  if [ ! -f "$DEST/.vscode/settings.json" ]; then',
        '    mkdir -p "$DEST/.vscode"',
        "    cat > \"$DEST/.vscode/settings.json\" <<'__WIGAMIG_VSCODE_EOF__'",
        _vscode_settings_for_ssh(),
        '__WIGAMIG_VSCODE_EOF__',
        '    echo "vscode_settings:ok:created $DEST/.vscode/settings.json"',
        '  else',
        '    echo "vscode_settings:ok:already exists at $DEST/.vscode/settings.json"',
        '  fi',
        # CC hooks settings — points at the remote's murmurent commons
        # script (resolved at script-runtime via $WIG). On lab-server
        # this expands to /home/UWO/the_pi/repos/wigamig/scripts/...
        '  if [ ! -f "$DEST/.claude/settings.json" ]; then',
        "    cat > \"$DEST/.claude/settings.json\" <<__WIGAMIG_CC_EOF__",
        _cc_settings_for_ssh_template(),
        '__WIGAMIG_CC_EOF__',
        '    echo "cc_settings:ok:created $DEST/.claude/settings.json"',
        '  else',
        '    echo "cc_settings:ok:already exists at $DEST/.claude/settings.json"',
        '  fi',
        'else',
        '  echo "cc_init:warn:skipped (clone missing or murmurent commons not at $WIG)"',
        'fi',
    ]
    return "\n".join(lines)


def _vscode_settings_for_ssh() -> str:
    """Same content :mod:`core.project_cc_init._vscode_settings_json`
    emits — duplicated here so we don't reach across module
    boundaries from the bash-script builder. Kept in sync by hand;
    test :func:`tests/test_chrome_propagation.py::test_local_and_remote_vscode_match`
    pins them."""
    # Hard-coded to avoid the json import dance inside an f-string;
    # the content is small and rarely changes.
    return (
        '{\n'
        '  "//": "Per-folder VSCode settings for a murmurent project. Written by remote-adopt. Edit freely.",\n'
        '  "window.title": "Murmurent — ${rootName}${separator}${activeEditorMedium}${separator}${dirty}",\n'
        '  "window.titleSeparator": "  ·  ",\n'
        '  "workbench.activityBar.location": "end",\n'
        '  "workbench.sideBar.location": "right",\n'
        '  "terminal.integrated.defaultLocation": "editor",\n'
        '  "terminal.integrated.tabs.location": "right",\n'
        '  "files.exclude": {\n'
        '    "**/.pytest_cache": true,\n'
        '    "**/__pycache__": true,\n'
        '    "**/.venv": true\n'
        '  }\n'
        '}'
    )


def _cc_settings_for_ssh_template() -> str:
    """JSON for ``.claude/settings.json`` with the hooks block. Written
    via an *unquoted* heredoc on the remote so ``$WIG`` expands to
    ``$HOME/repos/wigamig`` at runtime — the script sets ``WIG`` just
    above this block. The hook path therefore comes out as e.g.
    ``/home/UWO/the_pi/repos/wigamig/scripts/wigamig_log_agent_event.sh``,
    which is what we want on every host."""
    cmd = "$WIG/scripts/wigamig_log_agent_event.sh"
    return (
        '{\n'
        '  "//": "Per-project CC hooks for the murmurent subagent reporter.",\n'
        '  "hooks": {\n'
        '    "PreToolUse": [\n'
        '      {\n'
        '        "matcher": "Agent",\n'
        f'        "hooks": [{{"type": "command", "command": "{cmd}"}}]\n'
        '      }\n'
        '    ],\n'
        '    "SubagentStop": [\n'
        '      {\n'
        f'        "hooks": [{{"type": "command", "command": "{cmd}"}}]\n'
        '      }\n'
        '    ]\n'
        '  }\n'
        '}'
    )


def parse_remote_adopt_output(stdout: str) -> list[_pf.Probe]:
    """Convert ``<step>:<status>:<detail>`` records into Probes.

    Same parser shape as :func:`core.remote_install.parse_output`, but
    the required-step set is just ``{charter}``: the install wizard
    requires both ``murmurent`` and ``repo`` because it might need to
    clone the repo first; adopt assumes the clone exists and only
    needs CHARTER to land.
    """
    REQUIRED = {"charter"}
    out: list[_pf.Probe] = []
    for raw in (stdout or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        name, status, detail = parts
        if status not in ("ok", "warn", "fail"):
            status = "fail"
        out.append(_pf.Probe(
            name=name, status=status, detail=detail,
            required=(name in REQUIRED),
        ))
    return out


def adopt_remote_clone(
    *,
    host: _hosts.Host,
    clone_path: str,
    project: str,
    charter_text: str,
    agents: list[str],
    timeout: int = 90,
) -> list[_pf.Probe]:
    """Run the batched remote-adopt script on ``host`` and parse probes.

    Returns a single ``ssh`` probe with status=fail when SSH itself
    fails (connection refused, key rejected, host unknown). When SSH
    succeeds, returns one Probe per record the script emitted.

    The caller (the dashboard endpoint) is responsible for surfacing
    these probes back to the UI and translating any required failure
    into the appropriate HTTP status.
    """
    script = build_remote_adopt_script(
        clone_path=clone_path,
        project=project,
        charter_text=charter_text,
        agents=agents,
    )
    remote = _remote.Remote(host)
    try:
        res = remote.run(script, check=False, timeout=timeout)
    except _remote.RemoteError as exc:
        return [_pf.Probe(
            name="ssh", status="fail",
            detail=(exc.stderr or str(exc)).strip() or "ssh failed",
            required=True,
        )]
    if not res.ok and not res.stdout.strip():
        return [_pf.Probe(
            name="ssh", status="fail",
            detail=(res.stderr or "").strip() or f"rc={res.returncode}",
            required=True,
        )]
    return parse_remote_adopt_output(res.stdout)


__all__ = [
    "RemoteAdoptError",
    "build_remote_adopt_script",
    "parse_remote_adopt_output",
    "adopt_remote_clone",
]
