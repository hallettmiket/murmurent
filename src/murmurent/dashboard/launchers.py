"""
Purpose: Cross-platform "launch a native app for the user" helpers for the
         dashboard. Two things the Command-Bridge dashboard needs to do from a
         button click: (1) open a murmurent-ready repo in VS Code, and (2) open
         a bare Claude Code CLI session in a terminal (no repo required). The
         dashboard runs as a local desktop app, so these spawn GUI processes in
         the signed-in user's session.
Author: Mike Hallett (with Claude Code)
Date: 2026-07-31
Input: A filesystem path (VS Code) or an optional working directory (CC session).
Output: A dict describing what was launched: {launched, launcher, error, note}.
        Never raises for an "app not found"/"spawn failed" case — the caller
        (an HTTP route) turns a non-launched result into a clean error body.
"""

from __future__ import annotations

import platform
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

# macOS ships the ``code`` CLI inside the app bundle; a PATH ``code`` may be a
# shim that points back here. Try the bundle first so a launch works even when
# LaunchServices hasn't registered the shim. On Linux/other, ``shutil.which``
# is the only source. Order: stable VS Code, then Insiders.
_MAC_CODE_CANDIDATES = (
    "/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code",
    "/Applications/Visual Studio Code - Insiders.app/Contents/Resources/app/bin/code",
)

# Linux terminal emulators, in preference order, with the argv form that runs a
# command. gnome-terminal leads because it is the Debian/Ubuntu/Mint default
# (``x-terminal-emulator`` usually points at it). Each entry maps the shell
# ``script`` string onto that terminal's "run this command" invocation.
def _linux_terminal_argvs(script: str) -> list[list[str]]:
    return [
        ["gnome-terminal", "--", "bash", "-lc", script],
        ["konsole", "-e", "bash", "-lc", script],
        ["alacritty", "-e", "bash", "-lc", script],
        ["kitty", "bash", "-lc", script],
        ["xfce4-terminal", "-e", f"bash -lc {shlex.quote(script)}"],
        ["xterm", "-e", "bash", "-lc", script],
        # Last resort: the Debian alternatives wrapper. ``-e`` is honoured by
        # the wrapper regardless of which terminal it fronts.
        ["x-terminal-emulator", "-e", "bash", "-lc", script],
    ]

_POPEN_KW = dict(
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    stdin=subprocess.DEVNULL,
    close_fds=True,
)


def _wmctrl_window_ids(class_token: str) -> list[str]:
    """IDs of currently-open windows whose WM_CLASS contains ``class_token``.

    Used to snapshot existing terminal windows *before* we spawn a new one, so
    the raiser can tell the new window apart from ones already on screen.
    """
    if not shutil.which("wmctrl"):
        return []
    try:
        out = subprocess.run(
            ["wmctrl", "-lx"], capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ids: list[str] = []
    for line in out.splitlines():
        # "0x0123  0  gnome-terminal-server.Gnome-terminal  host  title"
        parts = line.split(None, 4)
        if len(parts) >= 3 and class_token.lower() in parts[2].lower():
            ids.append(parts[0])
    return ids


_TERM_CLASS_TOKENS = (
    "gnome-terminal", "konsole", "alacritty", "kitty", "xfce4-terminal", "xterm",
)


def _session_running(cd_prefix: str) -> bool:
    """True if a Claude Code session is already running for this working dir.

    Matches on the exact ``cd <dir> 2>/dev/null`` prefix embedded in the shell
    script we launch, so a session in repo A is distinct from one in repo B or a
    bare ($HOME) session. While ``claude`` runs, its parent ``bash -lc '<script>'``
    stays alive carrying that cmdline; after the session ends the ``exec bash``
    replaces the argv, so a finished session correctly reads as "not running".
    """
    try:
        out = subprocess.run(
            ["ps", "-eo", "args"], capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    for line in out.splitlines():
        if cd_prefix in line and "claude" in line and "exec bash" in line:
            return True
    return False


def _raise_claude_window() -> bool:
    """Best-effort: bring an existing Claude Code terminal to the front.

    gnome-terminal runs a single server process for all its windows, so a
    session can't be mapped to its window by PID. We instead prefer a window
    whose title Claude Code set (``✳ Claude Code``), falling back to the most
    recent terminal-class window. Good enough to satisfy "don't open a second
    one — just show me the one that's there".
    """
    if not shutil.which("wmctrl"):
        return False
    try:
        out = subprocess.run(
            ["wmctrl", "-lx"], capture_output=True, text=True, timeout=3,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    term_ids: list[str] = []
    claude_titled: list[str] = []
    for line in out.splitlines():
        p = line.split(None, 4)
        if len(p) < 3:
            continue
        cls = p[2].lower()
        title = p[4] if len(p) >= 5 else ""
        if any(tok in cls for tok in _TERM_CLASS_TOKENS):
            term_ids.append(p[0])
            if "claude" in title.lower() or "✳" in title:
                claude_titled.append(p[0])
    target = claude_titled[-1] if claude_titled else (term_ids[-1] if term_ids else None)
    if not target:
        return False
    try:
        subprocess.run(["wmctrl", "-i", "-a", target], timeout=3)
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _activate_macos_terminal() -> None:
    """Bring Terminal.app to the front (macOS analogue of _raise_claude_window)."""
    try:
        subprocess.Popen(  # noqa: S603
            ["osascript", "-e", 'tell application "Terminal" to activate'],
            **_POPEN_KW,
        )
    except OSError:
        pass


def _raise_new_window(class_token: str, before_ids: list[str]) -> None:
    """Bring the newly-created terminal window to the foreground.

    Freshly-spawned terminals frequently open *behind* the browser/IDE under
    focus-stealing-prevention, so the launch feels like it did nothing. We poll
    (in a detached helper, so the HTTP response isn't blocked) for a window of
    ``class_token`` that wasn't present before the spawn and activate it via
    ``wmctrl``. No-op if ``wmctrl`` is unavailable.
    """
    if not shutil.which("wmctrl"):
        return
    # A short, self-contained poller. ~5s of 0.2s ticks covers the window-map
    # delay; it activates the first genuinely-new matching window then exits.
    poller = (
        "import subprocess, time, sys\n"
        "tok = %r\n"
        "before = set(%r)\n"
        "for _ in range(25):\n"
        "    try:\n"
        "        out = subprocess.run(['wmctrl','-lx'], capture_output=True, text=True, timeout=3).stdout\n"
        "    except Exception:\n"
        "        out = ''\n"
        "    for line in out.splitlines():\n"
        "        p = line.split(None, 4)\n"
        "        if len(p) >= 3 and tok in p[2].lower() and p[0] not in before:\n"
        "            subprocess.run(['wmctrl','-i','-a',p[0]])\n"
        "            sys.exit(0)\n"
        "    time.sleep(0.2)\n"
    ) % (class_token.lower(), list(before_ids))
    try:
        subprocess.Popen([sys.executable, "-c", poller], **_POPEN_KW)  # noqa: S603
    except OSError:
        pass


def resolve_code_bin() -> str | None:
    """Return a runnable path to the VS Code ``code`` CLI, or ``None``."""
    for cand in (*_MAC_CODE_CANDIDATES, shutil.which("code") or "",
                 shutil.which("code-insiders") or ""):
        if cand and Path(cand).is_file():
            return cand
    return None


def open_in_vscode(path: Path | str, *, new_window: bool = True) -> dict:
    """Open ``path`` (a repo/folder) in VS Code via the ``code`` CLI.

    Cross-platform: the ``code`` CLI takes a folder argument identically on
    macOS, Linux, and Windows, so no per-OS window logic is needed here (unlike
    the positioned macOS ``open_murmurent.sh`` launcher, which the caller may
    still prefer on macOS). Returns a result dict; ``launched`` is False with a
    human-readable ``error`` when ``code`` is missing or the spawn fails.
    """
    target = str(Path(path).expanduser())
    code_bin = resolve_code_bin()
    if not code_bin:
        return {
            "launched": False,
            "launcher": None,
            "error": "VS Code CLI ('code') not found on PATH. Install VS Code "
                     "and enable the 'code' command (Command Palette → "
                     "'Shell Command: Install code command in PATH').",
            "note": None,
        }
    argv = [code_bin]
    if new_window:
        argv.append("--new-window")
    argv.append(target)
    try:
        subprocess.Popen(argv, **_POPEN_KW)  # noqa: S603 — argv is a list, never shelled
    except OSError as exc:
        return {"launched": False, "launcher": code_bin,
                "error": f"code launcher failed: {exc}", "note": None}
    return {"launched": True, "launcher": code_bin, "error": None,
            "note": f"Opened {target} in VS Code."}


# TODO(llm-selection): the launched agent CLI is hardcoded to Claude Code
# (``claude``). Generalize this to let the user pick which agent runs in the
# terminal — e.g. Claude Code, OpenAI Codex, or another CLI — via a param
# threaded down from the dashboard (``POST /api/workspace/claude-session`` would
# grow an ``agent``/``cli`` field, or a new endpoint). Resolve the binary the
# same way (``shutil.which``) and keep the window-raise logic unchanged.
# See issue #41 (item 3) discussion; revisit when a second CLI is supported.
def launch_claude_session(*, cwd: str | None = None) -> dict:
    """Open a native terminal running a bare ``claude`` (Claude Code) session.

    No repo is required — this is the "just give me a CC session to work in"
    button. If ``cwd`` is given the terminal starts there, else ``$HOME``. The
    terminal runs ``claude`` and then drops to an interactive shell (``exec
    bash``) so the window survives Claude Code exiting (e.g. a first-run login
    prompt) instead of vanishing. Returns the same result-dict shape as
    :func:`open_in_vscode`.
    """
    workdir = str(Path(cwd).expanduser()) if cwd else str(Path.home())
    claude_bin = shutil.which("claude") or "claude"
    # ``-lc`` (login shell) so ~/.local/bin and the rest of the user's PATH are
    # present even if the dashboard was started from a minimal environment.
    cd_prefix = f"cd {shlex.quote(workdir)} 2>/dev/null"
    script = f"{cd_prefix}; {shlex.quote(claude_bin)}; exec bash"

    system = platform.system()

    # Idempotency: the launch button gets clicked repeatedly. If a Claude Code
    # session is already running for THIS working dir, don't spawn a duplicate
    # terminal — bring the existing one to the front instead.
    if _session_running(cd_prefix):
        if system == "Darwin":
            _activate_macos_terminal()
        else:
            _raise_claude_window()
        return {
            "launched": False,
            "already_open": True,
            "launcher": None,
            "error": None,
            "note": f"A Claude Code session is already open for {workdir} — "
                    "brought its terminal to the front.",
        }

    if system == "Darwin":
        # ``do script`` needs a double-quoted AppleScript string. shlex.quote
        # only ever emits single quotes, so the script text contains no ``"`` —
        # safe to wrap verbatim.
        osa = (
            f'tell application "Terminal" to do script "{script}"\n'
            'tell application "Terminal" to activate'
        )
        try:
            subprocess.Popen(["osascript", "-e", osa], **_POPEN_KW)  # noqa: S603
        except OSError as exc:
            return {"launched": False, "launcher": "Terminal.app",
                    "error": f"osascript failed: {exc}", "note": None}
        return {"launched": True, "launcher": "Terminal.app", "error": None,
                "note": f"Opened a Claude Code session in Terminal (cwd: {workdir})."}

    # Linux / other: try known terminal emulators in order.
    tried: list[str] = []
    for argv in _linux_terminal_argvs(script):
        term = argv[0]
        tried.append(term)
        if not shutil.which(term):
            continue
        # Snapshot existing windows of this terminal's class *before* spawning,
        # so the raiser can identify the one we're about to create.
        before = _wmctrl_window_ids(term)
        try:
            subprocess.Popen(argv, **_POPEN_KW)  # noqa: S603
        except OSError:
            continue
        # Pull the new window to the foreground — otherwise it opens behind the
        # browser/IDE and the launch looks like it did nothing.
        _raise_new_window(term, before)
        return {"launched": True, "launcher": term, "error": None,
                "note": f"Opened a Claude Code session in {term} (cwd: {workdir})."}
    return {
        "launched": False,
        "launcher": None,
        "error": "No terminal emulator found (tried: " + ", ".join(tried) + "). "
                 "Install one (e.g. gnome-terminal) or open a terminal yourself "
                 "and run 'claude'.",
        "note": None,
    }
