"""
Purpose: Generate murmurent_app_icon.png — Western-purple app icon for the
         macOS dashboard launcher.
Author:  Mike Hallett
Date:    2026-05-11
Input:   sys.argv[1] — output path for the PNG
Output:  512x512 PNG with Western purple background and bold white "W"
"""

import sys
import math
from pathlib import Path


def _require_pillow() -> tuple:
    try:
        from PIL import Image, ImageDraw, ImageFont
        return Image, ImageDraw, ImageFont
    except ImportError:
        print("Pillow not installed — skipping icon generation.", file=sys.stderr)
        sys.exit(1)


SYSTEM_FONTS = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/GeezaPro.ttc",
]


def _rounded_rect_mask(draw, size: int, radius: int, fill: str) -> None:
    x0, y0, x1, y1 = 0, 0, size, size
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
    draw.ellipse([x0, y0, x0 + radius * 2, y0 + radius * 2], fill=fill)
    draw.ellipse([x1 - radius * 2, y0, x1, y0 + radius * 2], fill=fill)
    draw.ellipse([x0, y1 - radius * 2, x0 + radius * 2, y1], fill=fill)
    draw.ellipse([x1 - radius * 2, y1 - radius * 2, x1, y1], fill=fill)


def _draw_w_font(draw, size: int, colour: str, ImageFont) -> bool:
    """Try to draw W using a system font. Returns True on success."""
    font_size = int(size * 0.82)
    for path in SYSTEM_FONTS:
        try:
            font = ImageFont.truetype(path, font_size)
            bbox = draw.textbbox((0, 0), "W", font=font)
            w_w = bbox[2] - bbox[0]
            w_h = bbox[3] - bbox[1]
            x = (size - w_w) / 2 - bbox[0]
            y = (size - w_h) / 2 - bbox[1] - size * 0.03
            draw.text((x, y), "W", fill=colour, font=font)
            return True
        except Exception:
            continue
    return False


def _draw_w_geometric(draw, size: int, colour: str) -> None:
    """Fallback: bold geometric W that fills the icon."""
    margin = size * 0.06
    top = size * 0.14
    bottom = size * 0.86
    stroke = size * 0.22      # very thick — visible even at 16 px

    x0 = margin
    x1 = margin + (size - 2 * margin) * 0.25
    x2 = size / 2
    x3 = size - margin - (size - 2 * margin) * 0.25
    x4 = size - margin
    mid = top + (bottom - top) * 0.50

    def thick_line(ax: float, ay: float, bx: float, by: float) -> None:
        angle = math.atan2(by - ay, bx - ax)
        perp = angle + math.pi / 2
        dx = math.cos(perp) * stroke / 2
        dy = math.sin(perp) * stroke / 2
        draw.polygon(
            [(ax + dx, ay + dy), (bx + dx, by + dy),
             (bx - dx, by - dy), (ax - dx, ay - dy)],
            fill=colour,
        )
        r = stroke / 2
        draw.ellipse([ax - r, ay - r, ax + r, ay + r], fill=colour)
        draw.ellipse([bx - r, by - r, bx + r, by + r], fill=colour)

    thick_line(x0, top, x1, bottom)
    thick_line(x1, bottom, x2, mid)
    thick_line(x2, mid, x3, bottom)
    thick_line(x3, bottom, x4, top)


def generate_icon(output_path: Path, size: int = 512) -> None:
    Image, ImageDraw, ImageFont = _require_pillow()

    PURPLE = "#4F2683"
    WHITE = "#FFFFFF"
    RADIUS = size // 7

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _rounded_rect_mask(draw, size, RADIUS, PURPLE)

    if not _draw_w_font(draw, size, WHITE, ImageFont):
        _draw_w_geometric(draw, size, WHITE)

    img.save(output_path, "PNG")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python murmurent_app_icon.py <output.png>", file=sys.stderr)
        sys.exit(1)
    generate_icon(Path(sys.argv[1]))
