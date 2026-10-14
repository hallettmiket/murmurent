"""
Purpose: create, remove and check the "Murmurent Dashboard" icon: an app in
         ~/Applications on a Mac, an applications-menu entry on Linux.
Author: Mike Hallett (with Claude Code)
Date: 2026-10-14
Input: the running murmurent install; the platform; an optional handle
Output: the launcher files on disk; a LauncherResult describing them

Replaces ``scripts/create_mac_app.sh`` and ``scripts/create_linux_launcher.sh``
(issue #156). Those scripts ``cd`` into a repository folder and run
``uv run murmurent``, so they needed a clone, and a PyPI install, which ships no
``scripts/``, could not make an icon at all. This module writes a launcher that
runs the installed ``murmurent`` program by its full path instead, so it works
however murmurent was installed.

Windows is not supported yet: :func:`create` reports it plainly rather than
pretending.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "Murmurent Dashboard"
PORT = 8770
ICON_NAME = "murmurent_app_icon.png"

MAC = "darwin"
LINUX = "linux"


@dataclass
class LauncherResult:
    """What :func:`create`, :func:`remove` or :func:`status` found or did."""

    platform: str
    supported: bool
    present: bool = False
    location: Path | None = None
    files: list[Path] = field(default_factory=list)
    note: str = ""


def current_platform() -> str:
    """``"darwin"``, ``"linux"``, or whatever else ``sys.platform`` says."""
    p = sys.platform
    return LINUX if p.startswith("linux") else p


def murmurent_program() -> Path:
    """The installed ``murmurent`` command, by full path.

    Looked for beside the running Python first: a ``uv tool`` install and an
    editable development install both put the command in the same ``bin/``
    folder as their Python, and that is the copy that is running now. Falls
    back to whatever ``murmurent`` is on the PATH.
    """
    beside = Path(sys.executable).parent / "murmurent"
    if beside.is_file():
        return beside
    found = shutil.which("murmurent")
    return Path(found) if found else beside


def icon_source() -> Path | None:
    """The icon image: from a clone's ``assets/``, or the packaged copy."""
    from .commons import commons_root, packaged_commons_root

    for root in (commons_root(), packaged_commons_root()):
        p = root / "assets" / ICON_NAME
        if p.is_file():
            return p
    return None


def _data_home() -> Path:
    xdg = os.environ.get("XDG_DATA_HOME")
    return Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"


def _mac_app() -> Path:
    return Path.home() / "Applications" / f"{APP_NAME}.app"


def _linux_paths() -> dict[str, Path]:
    d = _data_home()
    return {
        "desktop": d / "applications" / "murmurent-dashboard.desktop",
        "script": d / "murmurent" / "murmurent-dashboard-launcher.sh",
        "icon": d / "icons" / "murmurent-dashboard.png",
    }


def _launcher_script(shebang: str, open_cmd: str, notify: str, user: str) -> str:
    """The shell script the icon runs: open the dashboard if it is already up,
    otherwise start it in the background and open it when it answers."""
    program = murmurent_program()
    who = (f'MURMURENT_USER="{user}"' if user else
           'MURMURENT_USER="$(head -1 "$HOME/.murmurent/user" 2>/dev/null | tr -d \'[:space:]\')"')
    return f"""{shebang}
# Murmurent Dashboard launcher, written by `murmurent launcher`.
# Re-run `murmurent launcher` after moving or reinstalling murmurent.
PORT={PORT}
URL="http://127.0.0.1:$PORT/"
LOG="$HOME/.murmurent/dashboard.log"
PROGRAM="{program}"

notify() {{ {notify} }}
healthy() {{
  if command -v curl >/dev/null 2>&1; then curl -sf "${{URL}}healthz" >/dev/null 2>&1
  elif command -v wget >/dev/null 2>&1; then wget -q -O /dev/null "${{URL}}healthz" >/dev/null 2>&1
  else return 2; fi
}}

if healthy; then {open_cmd} "$URL" >/dev/null 2>&1; exit 0; fi

if [ ! -x "$PROGRAM" ]; then
  notify "Cannot find murmurent at $PROGRAM. Reinstall it, then run: murmurent launcher"
  exit 1
fi

{who}
export MURMURENT_USER
mkdir -p "$HOME/.murmurent"
nohup "$PROGRAM" dashboard --hifi --port "$PORT" > "$LOG" 2>&1 &

for i in $(seq 1 30); do
  sleep 0.3
  if healthy; then {open_cmd} "$URL" >/dev/null 2>&1; exit 0; fi
done
notify "The dashboard did not start. Details are in ~/.murmurent/dashboard.log"
exit 1
"""


_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key><string>murmurent-launcher</string>
    <key>CFBundleIconFile</key><string>murmurent</string>
    <key>CFBundleIdentifier</key><string>org.murmurent.dashboard</string>
    <key>CFBundleName</key><string>Murmurent Dashboard</string>
    <key>CFBundleDisplayName</key><string>Murmurent Dashboard</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1.0</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
"""


def _mac_icon(png: Path, resources: Path) -> bool:
    """Convert ``png`` to the Mac's ``.icns`` format with the Mac's own tools.
    Returns False (default icon) when ``sips``/``iconutil`` are unavailable."""
    if not (shutil.which("sips") and shutil.which("iconutil")):
        return False
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "murmurent.iconset"
        iconset.mkdir()
        for sz in (16, 32, 128, 256, 512):
            for scale, suffix in ((1, ""), (2, "@2x")):
                px = str(sz * scale)
                subprocess.run(
                    ["sips", "-z", px, px, "-s", "format", "png", str(png),
                     "--out", str(iconset / f"icon_{sz}x{sz}{suffix}.png")],
                    capture_output=True, check=False,
                )
        r = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(resources / "murmurent.icns")],
            capture_output=True, check=False,
        )
        return r.returncode == 0


def _create_mac(user: str) -> LauncherResult:
    app = _mac_app()
    if app.exists():
        shutil.rmtree(app)
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    script = macos / "murmurent-launcher"
    script.write_text(_launcher_script(
        "#!/bin/zsh -l", "open",
        "osascript -e \"display notification \\\"$1\\\" with title \\\"Murmurent Dashboard\\\"\" "
        ">/dev/null 2>&1 || true;", user), encoding="utf-8")
    script.chmod(0o755)
    (app / "Contents" / "Info.plist").write_text(_PLIST, encoding="utf-8")
    (app / "Contents" / "PkgInfo").write_text("APPL????", encoding="utf-8")
    png = icon_source()
    has_icon = bool(png) and _mac_icon(png, resources)
    if shutil.which("xattr"):
        subprocess.run(["xattr", "-cr", str(app)], capture_output=True, check=False)
    return LauncherResult(
        platform=MAC, supported=True, present=True, location=app, files=[app],
        note="" if has_icon else "made with the default icon",
    )


def _create_linux(user: str) -> LauncherResult:
    p = _linux_paths()
    for f in p.values():
        f.parent.mkdir(parents=True, exist_ok=True)
    p["script"].write_text(_launcher_script(
        "#!/usr/bin/env bash", "xdg-open",
        'command -v notify-send >/dev/null 2>&1 && notify-send "Murmurent Dashboard" "$1" || true;',
        user), encoding="utf-8")
    p["script"].chmod(0o755)
    png = icon_source()
    icon = "utilities-terminal"   # a stock icon every desktop theme has
    written = [p["desktop"], p["script"]]
    if png:
        shutil.copyfile(png, p["icon"])
        icon = str(p["icon"])
        written.append(p["icon"])
    p["desktop"].write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Version=1.0\n"
        f"Name={APP_NAME}\n"
        "GenericName=Research dashboard\n"
        "Comment=Open the Murmurent dashboard in your browser\n"
        f"Exec={p['script']}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Categories=Development;\n"
        "Keywords=murmurent;dashboard;research;\n"
        "StartupNotify=true\n",
        encoding="utf-8",
    )
    p["desktop"].chmod(0o755)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(p["desktop"].parent)],
                       capture_output=True, check=False)
    return LauncherResult(platform=LINUX, supported=True, present=True,
                          location=p["desktop"], files=written)


def create(*, user: str = "", platform: str | None = None) -> LauncherResult:
    """Write the icon for this platform, replacing any earlier one.

    ``user`` fixes the handle the dashboard opens as (for a shared demo
    machine); by default the launcher reads ``~/.murmurent/user`` each time.
    """
    plat = platform or current_platform()
    if plat == MAC:
        return _create_mac(user)
    if plat == LINUX:
        return _create_linux(user)
    return LauncherResult(platform=plat, supported=False,
                          note="no dashboard icon on this platform yet")


def status(*, platform: str | None = None) -> LauncherResult:
    """Whether the icon exists, without changing anything."""
    plat = platform or current_platform()
    if plat == MAC:
        app = _mac_app()
        return LauncherResult(platform=MAC, supported=True, present=app.is_dir(),
                              location=app)
    if plat == LINUX:
        desktop = _linux_paths()["desktop"]
        return LauncherResult(platform=LINUX, supported=True,
                              present=desktop.is_file(), location=desktop)
    return LauncherResult(platform=plat, supported=False)


def remove(*, platform: str | None = None) -> LauncherResult:
    """Delete exactly the files :func:`create` writes, and nothing else."""
    plat = platform or current_platform()
    removed: list[Path] = []
    if plat == MAC:
        app = _mac_app()
        if app.is_dir():
            shutil.rmtree(app)
            removed.append(app)
    elif plat == LINUX:
        for f in _linux_paths().values():
            if f.is_file():
                f.unlink()
                removed.append(f)
    else:
        return LauncherResult(platform=plat, supported=False)
    return LauncherResult(platform=plat, supported=True, present=False, files=removed)


def where_to_find(result: LauncherResult) -> str:
    """One plain sentence telling the member where the icon is."""
    if result.platform == MAC:
        return ("You now have a Murmurent Dashboard icon in your Applications folder. "
                "Drag it to your Dock to open the dashboard with one click.")
    if result.platform == LINUX:
        return ("You now have a Murmurent Dashboard icon in your applications menu "
                "(search for \"murmurent\").")
    return ("There is no dashboard icon for this platform yet. "
            "Start the dashboard with: murmurent dashboard --hifi")
