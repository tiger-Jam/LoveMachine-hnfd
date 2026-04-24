#!/usr/bin/env python3
"""PWA / apple-touch-icon を静的に生成するユーティリティ。

static/icon.svg をソース表現として書き出し、PIL で
192 / 512 / 180 (apple-touch) の PNG を生成する。
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

STATIC = Path(__file__).parent / "static"

# ---- palette (style.css と揃える) ------------------------------------

BG_OUTER = (18, 7, 7)
BG_INNER = (90, 20, 20)
GOLD = (200, 168, 78)
GOLD_BRIGHT = (235, 205, 120)
CREAM = (250, 232, 188)

# ---- SVG source (also used by the web manifest) ----------------------

SVG_SRC = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
  <defs>
    <radialGradient id="bg" cx="50%" cy="50%" r="70%">
      <stop offset="0%" stop-color="#5a1414"/>
      <stop offset="100%" stop-color="#120707"/>
    </radialGradient>
  </defs>
  <rect x="0" y="0" width="512" height="512" rx="96" fill="url(#bg)"/>
  <rect x="28" y="28" width="456" height="456" rx="72"
        fill="none" stroke="#c8a84e" stroke-width="4" opacity="0.85"/>

  <!-- 5-petal blossom -->
  <g transform="translate(256 256)">
    <g fill="#fae8bc" stroke="#c8a84e" stroke-width="5" stroke-linejoin="round">
      {petals}
    </g>
    <circle r="26" fill="#c8a84e"/>
    <circle r="12" fill="#eacd78"/>
  </g>

  <!-- decorative corner dots -->
  {corners}
</svg>"""


def _petals_svg(r_outer: float = 120, r_petal: float = 70) -> str:
    out: list[str] = []
    for i in range(5):
        angle = -math.pi / 2 + i * (2 * math.pi / 5)
        cx = r_outer * math.cos(angle)
        cy = r_outer * math.sin(angle)
        out.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r_petal:.2f}"/>')
    return "\n      ".join(out)


def _corners_svg() -> str:
    out: list[str] = []
    positions = [(64, 64), (448, 64), (64, 448), (448, 448)]
    for x, y in positions:
        out.append(f'<circle cx="{x}" cy="{y}" r="8" fill="#c8a84e" opacity="0.7"/>')
    return "\n  ".join(out)


def write_svg() -> None:
    svg = SVG_SRC.format(petals=_petals_svg(), corners=_corners_svg())
    (STATIC / "icon.svg").write_text(svg, encoding="utf-8")


# ---- PNG rasterization (PIL, no external SVG renderer) ---------------

def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def _radial_bg(size: int) -> Image.Image:
    """Centred radial gradient: inner → outer."""
    img = Image.new("RGB", (size, size), BG_OUTER)
    pixels = img.load()
    cx = cy = size / 2
    max_r = size * 0.7 / 2 * 2  # match SVG r=70%
    for y in range(size):
        for x in range(size):
            d = math.hypot(x - cx, y - cy)
            t = min(d / max_r, 1.0)
            pixels[x, y] = _lerp(BG_INNER, BG_OUTER, t)
    return img


def make_icon(size: int) -> Image.Image:
    scale = size / 512
    img = _radial_bg(size).convert("RGBA")

    # rounded corners mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1],
        radius=int(96 * scale),
        fill=255,
    )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, mask=mask)

    draw = ImageDraw.Draw(out, "RGBA")

    # inner gold frame
    frame_margin = int(28 * scale)
    frame_w = max(3, int(4 * scale))
    draw.rounded_rectangle(
        [frame_margin, frame_margin, size - frame_margin, size - frame_margin],
        radius=int(72 * scale),
        outline=GOLD + (int(0.85 * 255),),
        width=frame_w,
    )

    # corner dots
    for cx, cy in [(64, 64), (448, 64), (64, 448), (448, 448)]:
        r = int(8 * scale)
        draw.ellipse(
            [int(cx * scale) - r, int(cy * scale) - r,
             int(cx * scale) + r, int(cy * scale) + r],
            fill=GOLD + (int(0.7 * 255),),
        )

    # five-petal blossom in the middle
    cx = cy = size // 2
    r_outer = 120 * scale
    r_petal = 70 * scale
    stroke_w = max(2, int(5 * scale))
    for i in range(5):
        a = -math.pi / 2 + i * (2 * math.pi / 5)
        px = cx + r_outer * math.cos(a)
        py = cy + r_outer * math.sin(a)
        draw.ellipse(
            [px - r_petal, py - r_petal, px + r_petal, py + r_petal],
            fill=CREAM,
            outline=GOLD,
            width=stroke_w,
        )

    # centre pistil
    r1 = int(26 * scale)
    r2 = int(12 * scale)
    draw.ellipse([cx - r1, cy - r1, cx + r1, cy + r1], fill=GOLD)
    draw.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], fill=GOLD_BRIGHT)

    # very light blur for softness at smaller sizes
    if size <= 256:
        out = out.filter(ImageFilter.SMOOTH)

    return out


def main() -> None:
    STATIC.mkdir(exist_ok=True)
    write_svg()
    for size, name in [(192, "icon-192.png"), (512, "icon-512.png"), (180, "apple-touch-icon.png")]:
        img = make_icon(size)
        img.save(STATIC / name, optimize=True)
        print(f"wrote static/{name}  ({size}x{size})")
    print("wrote static/icon.svg")


if __name__ == "__main__":
    main()
