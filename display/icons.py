"""Bitmap icons for the LED matrix display.

Each icon is a list of integers, one per row, MSB-first (same convention as
the bitmap fonts). Bit width is stored alongside as a separate constant.

Example — a 13×13 icon where bit 12 = leftmost column, bit 0 = rightmost:

    ROW = 0b0000001000000   ← single pixel at column 6 (center of 13-wide)

Draw with draw_icon(canvas, x, y, r, g, b, icon_data, icon_width).
"""
from __future__ import annotations

from display.renderer import Canvas, HEIGHT, WIDTH


def draw_icon(
    canvas: Canvas,
    x: int,
    y: int,
    r: int,
    g: int,
    b: int,
    icon: list[int],
    width: int,
) -> None:
    """Blit a bitmap icon at (x, y) in the given colour."""
    for row_idx, row_bits in enumerate(icon):
        py = y + row_idx
        if py < 0 or py >= HEIGHT:
            continue
        for bit_idx in range(width):
            if row_bits & (1 << (width - 1 - bit_idx)):
                px = x + bit_idx
                if 0 <= px < WIDTH:
                    canvas.SetPixel(px, py, r, g, b)


# ---------------------------------------------------------------------------
# Icons
# ---------------------------------------------------------------------------

# 13×13 alert triangle — replace with your pixel art
# Placeholder: solid upward-pointing triangle
ALERT_ICON_W = 13
ALERT_ICON: list[int] = [
    0b0000111110000,  # row  0
    0b0001000001000,  # row  1
    0b0010001000100,  # row  2
    0b0100001000010,  # row  3
    0b1000001000001,  # row  4
    0b1000001000001,  # row  5
    0b1000001000001,  # row  6
    0b1000001000001,  # row  7
    0b1000000000001,  # row  8
    0b0100000000010,  # row  9
    0b0010001000100,  # row 10
    0b0001000001000,  # row 11
    0b0000111110000,  # row 12
]
