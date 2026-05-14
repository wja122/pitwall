"""F1 timing tower renderer — stateful, owns the scroll engine.

Call render() once per frame from the display thread.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from display.fonts import F35, F57
from display.renderer import (
    WIDTH, HEIGHT,
    draw_hline, draw_text, draw_text_centered, fill_rect, text_width,
)
from modules.f1_timing.f1mv import DriverRow, TimingState

# ── Layout ────────────────────────────────────────────────────────────────────
HEADER_H  = 17
FLAG_H    = 11
DIVIDER_H = 2
CONTENT_Y = HEADER_H + FLAG_H + DIVIDER_H          # 30

ROW_H     = (HEIGHT - CONTENT_Y - 2) // 10         # 16  (2 = dotted divider)
STATIC_N  = 7
CYCLE_N   = 3

STATIC_Y  = CONTENT_Y                              # 30
DOTTED_Y  = STATIC_Y + STATIC_N * ROW_H            # 142
CYCLE_Y   = DOTTED_Y + 2                           # 144

ACCENT_W  = 2
SECTOR_H  = 2
CONTENT_H = ROW_H - SECTOR_H                       # 14 px of text area per row
TEXT_DY   = (CONTENT_H - 7) // 2                   # centre F57 (7px) in 14px → 3

TLA_X     = 18
GAP_RX    = WIDTH - 2                              # right-align target x

# ── Flag bar ──────────────────────────────────────────────────────────────────
_FLAG: dict[str, dict] = {
    'GREEN':      {'bg': (0,  50,  0),   'fg': (0,  220, 50),  'text': 'GREEN FLAG',  'flash': False},
    'YELLOW':     {'bg': (60, 50,  0),   'fg': (220,180,  0),  'text': 'YELLOW FLAG', 'flash': False},
    'SC':         {'bg': (140,100, 0),   'fg': (255,200,  0),  'text': 'SAFETY CAR',  'flash': False},
    'SC_ENDING':  {'bg': (140,100, 0),   'fg': (255,200,  0),
                   'bg_off': (70, 50, 0),'fg_off': (100,75, 0), 'text': 'SC ENDING',  'flash': True},
    'VSC':        {'bg': (170, 90, 0),   'fg': (255,140,  0),  'text': 'VIRTUAL SC',  'flash': False},
    'VSC_ENDING': {'bg': (170, 90, 0),   'fg': (255,140,  0),
                   'bg_off': (85, 45, 0),'fg_off': (100,60, 0), 'text': 'VSC ENDING', 'flash': True},
    'RED':        {'bg': (150, 0,  0),   'fg': (255,255,255),
                   'bg_off': (60, 0,  0),'fg_off': (100,100,100),'text': 'RED  FLAG', 'flash': True},
}

# ── Sector colours ────────────────────────────────────────────────────────────
_S_PURPLE = (148,   0, 211)
_S_GREEN  = (0,   180,   0)
_S_YELLOW = (180, 160,   0)
_S_GREY   = (45,   45,  45)

_SW = [WIDTH // 3, WIDTH // 3, WIDTH - 2 * (WIDTH // 3)]   # widths: 42, 42, 44
_SX = [0, _SW[0], _SW[0] + _SW[1]]                         # x starts: 0, 42, 84

# ── Scroll ────────────────────────────────────────────────────────────────────
_HOLD_S   = 5.0
_SCROLL_S = 0.5


class _ClipCanvas:
    """Canvas wrapper that silently drops SetPixel calls outside [y_min, y_max)."""

    def __init__(self, inner: Any, y_min: int, y_max: int) -> None:
        self._inner = inner
        self._y_min = y_min
        self._y_max = y_max

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        if self._y_min <= y < self._y_max:
            self._inner.SetPixel(x, y, r, g, b)

    def Fill(self, r: int, g: int, b: int) -> None:
        self._inner.Fill(r, g, b)


@dataclass
class _Scroll:
    group:  int   = 0
    offset: float = 0.0
    phase:  str   = 'HOLD'
    t0:     float = field(default_factory=time.time)


class F1TimingRenderer:
    """Draws one frame of the F1 timing tower to a canvas."""

    def __init__(self) -> None:
        self._scroll = _Scroll()

    def render(self, canvas: Any, state: TimingState) -> None:
        canvas.Fill(0, 0, 0)
        self._tick(len(state.drivers))
        self._header(canvas, state)
        self._flag_bar(canvas, state.track_status)
        self._static_zone(canvas, state.drivers)
        self._dotted_divider(canvas)
        self._cycle_zone(canvas, state.drivers)

    # ── Header ────────────────────────────────────────────────────────────────

    def _header(self, canvas: Any, state: TimingState) -> None:
        draw_text(canvas, F35, 2, 2, 160, 160, 160, state.circuit)
        sess_w = text_width(F35, state.session_name)
        draw_text(canvas, F35, WIDTH - sess_w - 2, 2, 120, 120, 120, state.session_name)
        if state.total_laps > 0:
            lap_str = f"LAP {state.current_lap} / {state.total_laps}"
            draw_text_centered(canvas, F35, WIDTH // 2, 9, 140, 140, 140, lap_str)

    # ── Flag bar ──────────────────────────────────────────────────────────────

    def _flag_bar(self, canvas: Any, status: str) -> None:
        style = _FLAG.get(status, _FLAG['GREEN'])
        on = (not style['flash']) or (int(time.time()) % 2 == 0)
        bg = style['bg']     if on else style.get('bg_off', style['bg'])
        fg = style['fg']     if on else style.get('fg_off', style['fg'])
        fill_rect(canvas, 0, HEADER_H, WIDTH, FLAG_H, *bg)
        ty = HEADER_H + (FLAG_H - 5) // 2
        draw_text_centered(canvas, F35, WIDTH // 2, ty, *fg, style['text'])

    # ── Divider ───────────────────────────────────────────────────────────────

    def _dotted_divider(self, canvas: Any) -> None:
        for x in range(0, WIDTH, 3):
            canvas.SetPixel(x, DOTTED_Y,     50, 50, 50)
            canvas.SetPixel(x, DOTTED_Y + 1, 30, 30, 30)

    # ── Static zone ───────────────────────────────────────────────────────────

    def _static_zone(self, canvas: Any, drivers: list[DriverRow]) -> None:
        for i, driver in enumerate(drivers[:STATIC_N]):
            self._row(canvas, driver, STATIC_Y + i * ROW_H)

    # ── Cycle zone ────────────────────────────────────────────────────────────

    def _cycle_zone(self, canvas: Any, drivers: list[DriverRow]) -> None:
        cycle = drivers[STATIC_N:]
        if not cycle:
            return
        n_groups = max(1, (len(cycle) + CYCLE_N - 1) // CYCLE_N)
        g      = self._scroll.group % n_groups
        g_next = (g + 1) % n_groups
        off    = int(self._scroll.offset)

        cur  = cycle[g      * CYCLE_N : (g      + 1) * CYCLE_N]
        nxt  = cycle[g_next * CYCLE_N : (g_next + 1) * CYCLE_N]

        # Clipped canvas: drops any SetPixel above the cycle zone so scrolling
        # rows can never bleed into the static zone or dotted divider.
        clipped = _ClipCanvas(canvas, CYCLE_Y, HEIGHT)

        for i, driver in enumerate(cur):
            self._row(clipped, driver, CYCLE_Y + i * ROW_H - off)
        if off > 0:
            for i, driver in enumerate(nxt):
                self._row(clipped, driver, CYCLE_Y + (i + CYCLE_N) * ROW_H - off)

    # ── Single driver row ─────────────────────────────────────────────────────

    def _row(self, canvas: Any, driver: DriverRow, row_y: int) -> None:
        ty = row_y + TEXT_DY
        r, g, b = driver.team_color

        # Team colour accent bar
        fill_rect(canvas, 0, row_y, ACCENT_W, CONTENT_H, r, g, b)

        # Position (dim, right-aligned to TLA_X)
        pos_str = str(driver.position)
        pos_x   = TLA_X - 2 - text_width(F57, pos_str)
        draw_text(canvas, F57, pos_x, ty, 100, 100, 100, pos_str)

        # TLA in team colour
        draw_text(canvas, F57, TLA_X, ty, r, g, b, driver.tla)

        # Gap / time — right-aligned, coloured box for penalty/investigation/FL
        t = driver.display_time
        if t:
            tw = text_width(F57, t)
            tx = GAP_RX - tw
            if driver.penalty:
                fill_rect(canvas, tx - 1, row_y, tw + 2, CONTENT_H, 180, 20, 20)
                draw_text(canvas, F57, tx, ty, 0, 0, 0, t)
            elif driver.investigating:
                fill_rect(canvas, tx - 1, row_y, tw + 2, CONTENT_H, 180, 150, 0)
                draw_text(canvas, F57, tx, ty, 0, 0, 0, t)
            elif driver.fastest_lap:
                fill_rect(canvas, tx - 1, row_y, tw + 2, CONTENT_H, 148, 0, 211)
                draw_text(canvas, F57, tx, ty, 0, 0, 0, t)
            else:
                draw_text(canvas, F57, tx, ty, 150, 150, 150, t)

        # Sector bar
        sy = row_y + CONTENT_H
        for idx, sec in enumerate(driver.sectors):
            if sec.purple:
                sc = _S_PURPLE
            elif sec.green:
                sc = _S_GREEN
            elif sec.value:
                sc = _S_YELLOW
            else:
                sc = _S_GREY
            fill_rect(canvas, _SX[idx], sy, _SW[idx], SECTOR_H, *sc)

    # ── Scroll tick ───────────────────────────────────────────────────────────

    def _tick(self, n_drivers: int) -> None:
        s = self._scroll
        n_cycle  = max(0, n_drivers - STATIC_N)
        n_groups = max(1, (n_cycle + CYCLE_N - 1) // CYCLE_N)
        elapsed  = time.time() - s.t0

        if s.phase == 'HOLD':
            if elapsed >= _HOLD_S:
                s.phase = 'SCROLL'
                s.t0 = time.time()
        else:
            progress = min(1.0, elapsed / _SCROLL_S)
            s.offset = progress * ROW_H
            if progress >= 1.0:
                s.group  = (s.group + 1) % n_groups
                s.offset = 0.0
                s.phase  = 'HOLD'
                s.t0     = time.time()
