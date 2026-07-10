"""
Purpose: Single-session SSH bootstrap of a project on a remote lab server.
Author: Mike Hallett (with Claude Code)
Date: 2026-05-15
Input: Host + project name + per-project paths + optional repo URL.
Output: ``[Probe]`` (one per step) parsed from one batched SSH call.

The install wizard used to make 3 separate SSH calls (one per
raw/refined/notebook mkdir). On lab-server, where a 3-strike auth
lockout costs 30 minutes, that's wasteful. This module produces a
single bash snippet that:

  1. Probes ``murmurent --version`` on the host (required).
  2. ``mkdir -p`` each per-project dir (raw / refined / notebook).
  3. Optionally ``git clone`` the project repo into ``~/repos/<project>``.

Each step prints one line ``<name>:<status>:<detail>`` on stdout. The
parser turns those into Probe objects the dashboard renders. One
SSH connection per install — combined with the ControlMaster socket
the user already established for lab-server, an install is typically
zero additional auth handshakes.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from . import hosts as _hosts
from . import remote as _remote
from .preflight import Probe


@dataclass
class InstallTargets:
    """Inputs to the batched install script.

    All paths are interpreted on the *remote* host. ``repo_url`` is
    optional — when present, the script clones into
    ``~/repos/<project>``; when absent, the clone step is omitted and
    the UI is expected to surface a manual checklist item instead.
    """

    project: str
    raw_path: str             # parent (e.g. /data/lab_vm/wigamig/raw)
    refined_path: str         # parent (e.g. /data/lab_vm/wigamig/refined)
    notebook_path: str        # absolute (e.g. /data/lab_vm/wigamig/notebooks)
    repo_url: str | None = None
    # Agents the user picked at install time. After the clone succeeds
    # we symlink ``~/repos/wigamig/agents/<name>.md`` into
    # ``~/repos/<project>/.claude/agents/`` so Claude Code in the
    # project's working tree sees exactly this selection. Names are
    # validated against ``[A-Za-z0-9_-]+`` to keep them safe to inline
    # into the shell snippet.
    agents: list[str] | None = None


def build_script(t: InstallTargets) -> str:
    """Return the bash snippet to run over a single SSH session.

    Output format on stdout: ``<step>:<status>:<detail>`` per line.
    ``status`` is ``ok``, ``warn``, or ``fail``. The Python parser
    handles unknown statuses gracefully (treats them as ``fail``).
    """
    # Reject project names that contain anything that would be unsafe
    # to interpolate into a shell script. Charter validation already
    # enforces snake_case, but defense-in-depth: refuse here too.
    if not _safe_project_name(t.project):
        raise ValueError(f"unsafe project name for shell script: {t.project!r}")
    project = t.project
    raw_proj      = f"{t.raw_path.rstrip('/')}/{project}"
    refined_proj  = f"{t.refined_path.rstrip('/')}/{project}"
    notebook_dir  = t.notebook_path.rstrip("/")

    lines: list[str] = []
    # 0) Remote $HOME — printed so the laptop can resolve ``~/repos/<project>``
    # into an absolute path for VSCode Remote-SSH later. Cheap; one
    # variable expansion. Distinct probe name so the parser can pick it
    # out without scanning all rows.
    lines.append('echo "homedir:ok:$HOME"')
    # 1) murmurent presence (REQUIRED). bash -lc gives us login PATH so
    # ~/.local/bin is on it without us hardcoding it.
    lines.append(
        'WIGV=$(murmurent --version 2>&1 | head -1); '
        'if [ -n "$WIGV" ] && echo "$WIGV" | grep -q -i murmurent; '
        'then echo "murmurent:ok:$WIGV"; '
        'else echo "murmurent:fail:$WIGV  -- run scripts/install_remote.sh on your laptop"; fi'
    )
    # 2) per-project dirs.
    for label, path in (
        ("raw", raw_proj),
        ("refined", refined_proj),
        ("notebook", notebook_dir),
    ):
        if not path:
            continue
        q = shlex.quote(path)
        lines.append(
            f'if [ -d {q} ]; then echo "{label}:ok:{path} (already exists)"; '
            f'elif mkdir -p {q} 2>/dev/null && [ -d {q} ]; then echo "{label}:ok:created {path}"; '
            f'else echo "{label}:fail:mkdir failed for {path}"; fi'
        )
    # 3) clone the project repo, if asked. Use ``DEST=$HOME/...`` so the
    # remote shell does the home-dir expansion — we can't shlex.quote
    # the literal ``$HOME/repos/...`` since that would prevent expansion.
    # Project name is restricted to ``[A-Za-z0-9_-]+`` by
    # _safe_project_name above, so interpolation is safe.
    # Validate agent names up-front so the safety guarantee for the CC
    # bootstrap snippet below (raw interpolation into a for-loop) holds.
    safe_agents: list[str] = []
    for a in (t.agents or []):
        a_str = str(a).strip()
        if a_str and _PROJECT_NAME_RE.match(a_str):
            safe_agents.append(a_str)
    if t.repo_url:
        url_q = shlex.quote(t.repo_url)
        lines.append(
            f'DEST="$HOME/repos/{project}"; '
            f'if [ -d "$DEST/.git" ]; then '
            f'  echo "repo:ok:already cloned at $DEST"; '
            # First attempt: ensure parent + clone, capturing combined
            # stdout/stderr so we can show the real failure reason on
            # the no-luck branch instead of swallowing it.
            f'elif mkdir -p "$HOME/repos" && '
            f'     CLONE_LOG=$(git clone {url_q} "$DEST" 2>&1) && '
            f'     [ -d "$DEST/.git" ]; then '
            f'  echo "repo:ok:cloned {t.repo_url} into $DEST"; '
            f'else '
            # Fallback: re-run clone (idempotent — DEST is removed by
            # the prior failed attempt if the network died mid-way) to
            # grab a clean error message. ``tr`` flattens newlines so
            # the line-oriented parser still gets a single record.
            f'  err=$(git clone {url_q} "$DEST" 2>&1 | tr "\\n" " " | tr -s " " | head -c 400); '
            f'  echo "repo:fail:git clone failed: $err"; '
            f'fi'
        )
        # 4) Bootstrap the project's Claude Code env. Only runs when the
        # clone landed and the murmurent commons is present on the host
        # (cloned by ``scripts/install_remote.sh`` to ~/repos/wigamig).
        # Each picked agent becomes a symlink into the murmurent commons
        # so a) the project sees exactly the agents the user chose at
        # install time, and b) updates to the commons flow through
        # automatically.
        agents_csv = " ".join(safe_agents)
        # CLAUDE.md content is written via a quoted here-doc; project
        # name is safe (validated above). Keep it terse — a minimum
        # viable stub that the user / agents can expand later.
        lines.append(
            f'DEST="$HOME/repos/{project}"; '
            f'WIG="$HOME/repos/wigamig"; '
            f'if [ -d "$DEST/.git" ] && [ -d "$WIG/agents" ]; then '
            f'  mkdir -p "$DEST/.claude/agents"; '
            # Sweep stale agent symlinks. Re-install with a different
            # agent pick must not leave the previous selection lingering
            # — but only delete symlinks that point into the murmurent
            # commons, so user-authored project-specific agent files
            # (non-symlink .md in .claude/agents/) survive.
            f'  for f in "$DEST/.claude/agents"/*.md; do '
            f'    [ -L "$f" ] || continue; '
            f'    target=$(readlink "$f"); '
            f'    case "$target" in '
            f'      */repos/wigamig/agents/*) rm -f "$f" ;; '
            f'    esac; '
            f'  done; '
            f'  for a in {agents_csv}; do '
            f'    src="$WIG/agents/$a.md"; '
            f'    if [ -f "$src" ]; then '
            f'      ln -sfn "$src" "$DEST/.claude/agents/$a.md"; '
            f'      echo "cc_agent:ok:$a -> wigamig/agents/$a.md"; '
            f'    else '
            f'      echo "cc_agent:warn:$a (no $a.md in murmurent commons)"; '
            f'    fi; '
            f'  done; '
            f'  if [ ! -f "$DEST/CLAUDE.md" ]; then '
            f'    cat > "$DEST/CLAUDE.md" <<__EOF__\n'
            f'# {project}\n'
            f'\n'
            f'Auto-generated by murmurent at install time. Replace this stub with\n'
            f'project-specific context, including: research question, members,\n'
            f'data sources, choreography, sensitivity classification.\n'
            f'\n'
            f'## Agents wired up for this project\n'
            f'\n'
            f'See `.claude/agents/` — symlinks into `~/repos/wigamig/agents/`.\n'
            f'Selected at install time: {agents_csv or "(none)"}.\n'
            f'\n'
            f'## Data locations\n'
            f'\n'
            f'- raw: `{t.raw_path}/{project}`\n'
            f'- refined: `{t.refined_path}/{project}`\n'
            f'- notebooks: `{t.notebook_path}`\n'
            f'\n'
            f'## murmurent commons\n'
            f'\n'
            f'Lab-wide agents + rules live in `~/repos/wigamig/`. This project\n'
            f'inherits from there; project-specific overrides go in `.claude/`.\n'
            f'__EOF__\n'
            f'    echo "cc_claude_md:ok:created $DEST/CLAUDE.md"; '
            f'  else '
            f'    echo "cc_claude_md:ok:already exists at $DEST/CLAUDE.md"; '
            f'  fi; '
            f'else '
            f'  echo "cc_init:warn:skipped (clone missing or murmurent commons not at $WIG)"; '
            f'fi'
        )

    return "; ".join(lines)


import re as _re
_PROJECT_NAME_RE = _re.compile(r"^[A-Za-z0-9_-]+$")


def _safe_project_name(name: str) -> bool:
    """Project names allowed into the SSH script.

    Restricted to ``[A-Za-z0-9_-]+`` so shell metacharacters can't sneak
    into the ``$HOME/repos/<project>`` path. Charter validation already
    enforces this elsewhere; this is a belt-and-braces guard.
    """
    return bool(name) and bool(_PROJECT_NAME_RE.match(name))


def parse_output(stdout: str) -> list[Probe]:
    """Convert ``<step>:<status>:<detail>`` lines into Probes.

    Order in the returned list matches the order of lines in stdout —
    the UI can render them top-to-bottom as the install timeline.

    Steps that are required for the install to be considered successful:
      - ``murmurent``: install can't proceed without the binary on the host
      - ``repo``: the whole point of a remote install is that the working
                  tree lives on the remote; a missing clone there means
                  VSCode Remote-SSH has nothing to open.
    """
    REQUIRED = {"murmurent", "repo"}
    probes: list[Probe] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        name, status, detail = parts
        if status not in ("ok", "warn", "fail"):
            status = "fail"
        probes.append(Probe(
            name=name, status=status, detail=detail,
            required=(name in REQUIRED),
        ))
    return probes


def install(host_obj: _hosts.Host, t: InstallTargets) -> list[Probe]:
    """Run the batched install script on ``host_obj`` and return probes.

    Returns a single ``ssh`` probe with ``fail`` status when SSH itself
    fails (connection refused, key rejected). When SSH succeeds, returns
    one probe per step regardless of individual step outcomes.
    """
    remote = _remote.Remote(host_obj)
    script = build_script(t)
    try:
        res = remote.run(script, check=False, timeout=120)
    except _remote.RemoteError as exc:
        return [Probe(
            name="ssh",
            status="fail",
            detail=(exc.stderr or str(exc)).strip() or "ssh failed",
            required=True,
        )]
    # An ssh-level failure produces no stdout — surface the stderr.
    if not (res.stdout or "").strip():
        return [Probe(
            name="ssh",
            status="fail",
            detail=(res.stderr or "").strip() or f"rc={res.returncode}",
            required=True,
        )]
    return parse_output(res.stdout)
