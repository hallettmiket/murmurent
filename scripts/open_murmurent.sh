#!/usr/bin/env bash
# Open a wigamig repo in VSCode, sized to 80% of available screen space.
# If a second monitor is present, place on that monitor; otherwise use
# the laptop screen.
#
# This is the launcher half of the "wigamig in VSCode" workflow. The
# inner 4-quadrant layout (CC top-left, code top-right, shell bottom-
# left, agent log bottom-right) is configured per-folder via
# .vscode/settings.json + .vscode/tasks.json — VSCode persists the
# editor-group state, so you arrange the quadrants once and it sticks
# across opens.
#
# Usage:
#   scripts/open_murmurent.sh                # opens murmurent itself
#   scripts/open_murmurent.sh ~/repos/<other>  # opens another repo
#
# macOS only — uses /usr/bin/python3 + AppKit for screen enumeration
# (PyObjC ships with the system Python on every modern macOS) and
# osascript to position the window.

set -euo pipefail

REPO="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
REPO="$(cd "$REPO" && pwd)"
REPO_NAME="$(basename "$REPO")"

CODE="/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code"
[[ -x "$CODE" ]] || CODE="code"

# 1. Enumerate displays.
#
# Uses osascript + AppKit (via JavaScript-for-Automation) instead of
# Python+PyObjC — the system /usr/bin/python3 on recent macOS is a
# CommandLineTools shim that doesn't ship PyObjC, but JXA can always
# reach Cocoa. NSScreen frames are in points with y=0 at the bottom
# of the primary display; we flip to top-left for osascript window
# positioning.
#
# Output: one display per line, "x y w h is_primary", largest first.
SCREENS=$(osascript -l JavaScript <<'JXA'
ObjC.import('AppKit');
const screens = $.NSScreen.screens;
const primary = $.NSScreen.mainScreen;
const count = screens.count;
let maxTop = 0;
for (let i = 0; i < count; i++) {
    const f = screens.objectAtIndex(i).frame;
    const top = f.origin.y + f.size.height;
    if (top > maxTop) maxTop = top;
}
const rows = [];
for (let i = 0; i < count; i++) {
    const s = screens.objectAtIndex(i);
    const f = s.frame;
    const x = Math.round(f.origin.x);
    const w = Math.round(f.size.width);
    const h = Math.round(f.size.height);
    const yTop = Math.round(maxTop - f.origin.y - f.size.height);
    const isPrimary = s.isEqual(primary) ? 1 : 0;
    rows.push({ area: w * h, line: `${x} ${yTop} ${w} ${h} ${isPrimary}` });
}
rows.sort((a, b) => b.area - a.area);
rows.map(r => r.line).join('\n');
JXA
)
N_DISPLAYS=$(echo "$SCREENS" | wc -l | tr -d ' ')

# 2. Pick the target display.
#
# >1 displays: use the external (non-primary). Most Mac setups treat
# the laptop screen as primary, so "external" usually means a bigger
# monitor where you want VSCode to live.
#
# 1 display: use it (the laptop).
if [[ "$N_DISPLAYS" -gt 1 ]]; then
    TARGET=$(echo "$SCREENS" | awk '$5 == 0 {print; exit}')
    [[ -z "$TARGET" ]] && TARGET=$(echo "$SCREENS" | head -n 1)
    PLACE="external monitor"
else
    TARGET=$(echo "$SCREENS" | head -n 1)
    PLACE="laptop screen"
fi
read -r SX SY SW SH _ <<< "$TARGET"

# 3. Compute the 80% rectangle, centred.
SCALE_NUM=80; SCALE_DEN=100
WIN_W=$(( SW * SCALE_NUM / SCALE_DEN ))
WIN_H=$(( SH * SCALE_NUM / SCALE_DEN ))
WIN_X=$(( SX + (SW - WIN_W) / 2 ))
WIN_Y=$(( SY + (SH - WIN_H) / 2 ))

echo "wigamig launcher"
echo "  repo:    $REPO"
echo "  display: $PLACE  (${SW}x${SH} at ${SX},${SY})"
echo "  window:  ${WIN_W}x${WIN_H} at ${WIN_X},${WIN_Y}"

# 4. Open the repo + position the window.
#
# We `code <repo>` then poll for the window before sending the position
# command. VSCode takes 1-3s to render on a cold start; on warm starts
# it's instant. The poll keeps the launcher snappy without flaky sleeps.
"$CODE" "$REPO" &

for _ in {1..40}; do
    if osascript -e 'tell application "System Events" to count windows of process "Code"' \
            2>/dev/null | grep -qv '^0$'; then
        break
    fi
    sleep 0.1
done

osascript -e 'tell application "Visual Studio Code" to activate' >/dev/null 2>&1 || true
osascript <<EOF >/dev/null 2>&1 || true
tell application "System Events" to tell process "Code"
    set position of front window to {$WIN_X, $WIN_Y}
    set size     of front window to {$WIN_W, $WIN_H}
end tell
EOF

echo "  opened $REPO_NAME — first time? arrange the 4 quadrants once;"
echo "  VSCode will restore the layout on every subsequent open."
