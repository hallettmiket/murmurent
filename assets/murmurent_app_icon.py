"""
Purpose: Generate the brand-purple murmurent monogram icon — the app icon for
         the desktop dashboard launcher (PNG) and the browser-tab favicon
         (multi-resolution ICO).
Author:  Mike Hallett
Date:    2026-05-11
Input:   sys.argv[1] — output path; the suffix picks the format (.png or .ico)
         --letter <L>  monogram to draw (default: M, for Murmurent)
         --size <px>   PNG edge length (default: 512; ignored for .ico)
Output:  Rounded-square icon, brand purple ground, bold white monogram.
         A .ico carries the 16/32/48 px sizes a browser tab picks from.
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


# Tried in order. Bold faces first: the monogram has to survive a 16 px
# browser tab, where a regular weight closes up into a smudge. The macOS
# paths came first historically; without the Linux ones every non-Mac run
# fell through to the geometric fallback.
SYSTEM_FONTS = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
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


def _draw_letter_font(draw, size: int, colour: str, ImageFont,
                      letter: str) -> bool:
    """Try to draw ``letter`` using a system font. Returns True on success."""
    font_size = int(size * 0.82)
    for path in SYSTEM_FONTS:
        try:
            font = ImageFont.truetype(path, font_size)
            bbox = draw.textbbox((0, 0), letter, font=font)
            w_w = bbox[2] - bbox[0]
            w_h = bbox[3] - bbox[1]
            x = (size - w_w) / 2 - bbox[0]
            y = (size - w_h) / 2 - bbox[1] - size * 0.03
            draw.text((x, y), letter, fill=colour, font=font)
            return True
        except Exception:
            continue
    return False


def _draw_m_geometric(draw, size: int, colour: str) -> None:
    """Fallback: bold geometric M, used when no system font is available.

    Two vertical stems and a centre V, which reads as an M at 16 px far more
    reliably than a splayed four-diagonal form. Every coordinate is inset by
    at least the stroke's cap radius so nothing spills past the rounded
    square -- the bug the old W geometry carried unnoticed, because the
    macOS font path always won before it could be exercised.
    """
    stroke = size * 0.15
    cap = stroke / 2

    left = size * 0.24
    right = size * 0.76
    centre = size * 0.50
    top = size * 0.26
    bottom = size * 0.76
    vertex = size * 0.56          # the bottom of the centre V

    def thick_line(ax: float, ay: float, bx: float, by: float) -> None:
        angle = math.atan2(by - ay, bx - ax)
        perp = angle + math.pi / 2
        dx = math.cos(perp) * cap
        dy = math.sin(perp) * cap
        draw.polygon(
            [(ax + dx, ay + dy), (bx + dx, by + dy),
             (bx - dx, by - dy), (ax - dx, ay - dy)],
            fill=colour,
        )
        for px, py in ((ax, ay), (bx, by)):
            draw.ellipse([px - cap, py - cap, px + cap, py + cap], fill=colour)

    thick_line(left, bottom, left, top)        # left stem
    thick_line(left, top, centre, vertex)      # \ of the V
    thick_line(centre, vertex, right, top)     # / of the V
    thick_line(right, top, right, bottom)      # right stem


PURPLE = "#4F2683"
WHITE = "#FFFFFF"

# The sizes a browser picks from for a tab, the bookmark bar, and a pinned
# shortcut. 16 is the one that actually shows in the tab, and it is why the
# monogram is drawn this heavy.
ICO_SIZES = (16, 32, 48)


def render(size: int, letter: str = "M"):
    """Return an RGBA image of the monogram icon at ``size`` px."""
    Image, ImageDraw, ImageFont = _require_pillow()
    radius = size // 7

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    _rounded_rect_mask(draw, size, radius, PURPLE)

    if not _draw_letter_font(draw, size, WHITE, ImageFont, letter):
        if letter.upper() == "M":
            _draw_m_geometric(draw, size, WHITE)
        else:
            # No geometric fallback for other letters; a missing glyph is
            # better caught loudly than shipped as a blank purple square.
            raise RuntimeError(
                f"no system font could draw {letter!r} and there is no "
                f"geometric fallback for it"
            )
    return img


def generate_icon(output_path: Path, size: int = 512, letter: str = "M") -> None:
    """Write the icon to ``output_path``; the suffix picks the format.

    ``.ico`` ignores ``size`` and writes the ICO_SIZES set instead, each
    rendered at its own resolution rather than downsampled from one master —
    the thick strokes stay crisp at 16 px that way.
    """
    if output_path.suffix.lower() == ".ico":
        frames = [render(s, letter) for s in ICO_SIZES]
        # Pillow writes every `sizes` entry from the base image, so hand it
        # the largest and let it embed the rest.
        frames[-1].save(output_path, format="ICO",
                        sizes=[(s, s) for s in ICO_SIZES])
    else:
        render(size, letter).save(output_path, "PNG")


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: python murmurent_app_icon.py <output.png|.ico> "
              "[--letter M] [--size 512]", file=sys.stderr)
        sys.exit(1)

    out = Path(args[0])
    letter = "M"
    size = 512
    for flag, value in zip(args[1::2], args[2::2]):
        if flag == "--letter":
            letter = value
        elif flag == "--size":
            size = int(value)
        else:
            print(f"unknown option {flag}", file=sys.stderr)
            sys.exit(1)

    generate_icon(out, size=size, letter=letter)
    print(f"wrote {out}")
