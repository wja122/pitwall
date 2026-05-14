"""Canvas drawing utilities.

All functions accept any object implementing SetPixel / Fill (real FrameCanvas
or StubCanvas).  Import the Canvas Protocol for type annotations.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from display.fonts import F57, F35

WIDTH = 128
HEIGHT = 192


@runtime_checkable
class Canvas(Protocol):
    """Structural type satisfied by both rgbmatrix FrameCanvas and StubCanvas."""

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None: ...
    def Fill(self, r: int, g: int, b: int) -> None: ...


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def fill_rect(canvas: Canvas, x: int, y: int, w: int, h: int,
              r: int, g: int, b: int) -> None:
    for row in range(y, min(y + h, HEIGHT)):
        for col in range(x, min(x + w, WIDTH)):
            canvas.SetPixel(col, row, r, g, b)


def draw_hline(canvas: Canvas, x: int, y: int, w: int,
               r: int, g: int, b: int) -> None:
    for col in range(x, min(x + w, WIDTH)):
        if 0 <= y < HEIGHT:
            canvas.SetPixel(col, y, r, g, b)


def draw_vline(canvas: Canvas, x: int, y: int, h: int,
               r: int, g: int, b: int) -> None:
    for row in range(y, min(y + h, HEIGHT)):
        if 0 <= x < WIDTH:
            canvas.SetPixel(x, row, r, g, b)


def draw_line(canvas: Canvas, x1: int, y1: int, x2: int, y2: int,
              r: int, g: int, b: int) -> None:
    """Bresenham line."""
    dx, dy = abs(x2 - x1), abs(y2 - y1)
    sx = 1 if x1 < x2 else -1
    sy = 1 if y1 < y2 else -1
    err = dx - dy
    while True:
        if 0 <= x1 < WIDTH and 0 <= y1 < HEIGHT:
            canvas.SetPixel(x1, y1, r, g, b)
        if x1 == x2 and y1 == y2:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x1 += sx
        if e2 < dx:
            err += dx
            y1 += sy


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def draw_text(canvas: Canvas, font: dict, x: int, y: int,
              r: int, g: int, b: int, text: str) -> int:
    """Draw text using a bitmap font.  Returns x position after last glyph."""
    advance = font['_advance']
    width = font['_width']
    cx = x
    for char in text.upper():
        glyph = font.get(char)
        if glyph is None:
            cx += advance
            continue
        for row_idx, row_bits in enumerate(glyph):
            py = y + row_idx
            if py >= HEIGHT or py < 0:
                continue
            for bit_idx in range(width):
                if row_bits & (1 << (width - 1 - bit_idx)):
                    px = cx + bit_idx
                    if 0 <= px < WIDTH:
                        canvas.SetPixel(px, py, r, g, b)
        cx += advance
    return cx


def text_width(font: dict, text: str) -> int:
    """Pixel width of a text string (without trailing advance gap)."""
    if not text:
        return 0
    advance = font['_advance']
    width = font['_width']
    # All characters use full advance except potentially the last
    return (len(text) - 1) * advance + width


def draw_text_centered(canvas: Canvas, font: dict, cx: int, y: int,
                       r: int, g: int, b: int, text: str) -> int:
    """Draw text horizontally centered at cx."""
    x = cx - text_width(font, text) // 2
    return draw_text(canvas, font, x, y, r, g, b, text)


# ---------------------------------------------------------------------------
# Scaled text (pixel-doubling / tripling for large display elements)
# ---------------------------------------------------------------------------

def text_width_scaled(font: dict, text: str, scale: int) -> int:
    """Pixel width of text rendered at pixel scale (e.g. scale=3 → 3× size)."""
    if not text:
        return 0
    advance = font['_advance']
    width = font['_width']
    return (len(text) - 1) * advance * scale + width * scale


def draw_text_scaled(canvas: Canvas, font: dict, x: int, y: int,
                     r: int, g: int, b: int, text: str, scale: int) -> int:
    """Draw text with each source pixel expanded to scale×scale pixels."""
    advance = font['_advance']
    width = font['_width']
    cx = x
    for char in text.upper():
        glyph = font.get(char)
        if glyph is None:
            cx += advance * scale
            continue
        for row_idx, row_bits in enumerate(glyph):
            for bit_idx in range(width):
                if row_bits & (1 << (width - 1 - bit_idx)):
                    fill_rect(canvas,
                              cx + bit_idx * scale,
                              y + row_idx * scale,
                              scale, scale, r, g, b)
        cx += advance * scale
    return cx


def draw_text_centered_scaled(canvas: Canvas, font: dict, cx: int, y: int,
                               r: int, g: int, b: int, text: str,
                               scale: int) -> int:
    """Draw scaled text centered at cx."""
    x = cx - text_width_scaled(font, text, scale) // 2
    return draw_text_scaled(canvas, font, x, y, r, g, b, text, scale)
