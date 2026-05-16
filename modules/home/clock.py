"""Clock strip renderer for the Home module — always occupies the top 80px."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from display.fonts import F35, F57
from display.renderer import (
    WIDTH,
    draw_hline, draw_text, draw_text_centered,
    draw_text_centered_scaled, fill_rect, text_width,
)

CLOCK_H = 80   # pixels reserved for the clock strip

# ── Shared palette ─────────────────────────────────────────────────────────
_DATE_BG  = (14, 14, 14)
_SEP      = (26, 26, 26)
_WHITE    = (255, 255, 255)
_DIM      = (90,  90,  90)
_DIMMER   = (60,  60,  60)
_FAINT    = (38,  38,  38)


def render_clock(canvas: Any, mode: str) -> None:
    """Render the 80-px clock strip at y=0.

    mode: 'tz_utc'  — local time (scale 2) + UTC time below
          'tz_only' — local time only (scale 3), larger
    """
    now_local = datetime.now().astimezone()
    now_utc   = datetime.now(timezone.utc)

    # Date bar — common to both modes
    fill_rect(canvas, 0, 0, WIDTH, 10, *_DATE_BG)
    date_str = now_local.strftime('%a %-d %b').upper()
    draw_text_centered(canvas, F35, WIDTH // 2, 3, *_DIM, date_str)
    draw_hline(canvas, 0, 10, WIDTH, *_SEP)

    if mode == 'tz_only':
        _render_tz_only(canvas, now_local)
    else:
        _render_tz_utc(canvas, now_local, now_utc)

    # Bottom separator — marks end of clock zone / start of widget zone
    draw_hline(canvas, 0, CLOCK_H - 1, WIDTH, *_SEP)


def _render_tz_only(canvas: Any, now: datetime) -> None:
    """Local time fills most of the 80px strip — nothing else."""
    time_str = now.strftime('%-I:%M')
    ampm_tz  = now.strftime('%p · %Z')

    # Time: F57×3 (21 px tall) starting at y=14
    draw_text_centered_scaled(canvas, F57, WIDTH // 2, 14, *_WHITE, time_str, 3)

    # AM/PM and timezone below
    draw_hline(canvas, 0, 38, WIDTH, *_SEP)
    draw_text_centered(canvas, F35, WIDTH // 2, 42, *_DIM, ampm_tz)
    draw_hline(canvas, 0, 50, WIDTH, *_FAINT)


def _render_tz_utc(canvas: Any, now_local: datetime, now_utc: datetime) -> None:
    """Local time (scale 2) + UTC time — two clocks in 80px."""
    time_local = now_local.strftime('%-I:%M')
    ampm_tz    = now_local.strftime('%p · %Z')
    time_utc   = now_utc.strftime('%H:%M')

    # Local time: F57×2 (14 px tall) starting at y=13
    draw_text_centered_scaled(canvas, F57, WIDTH // 2, 13, *_WHITE, time_local, 2)

    # AM/PM + TZ label
    draw_text_centered(canvas, F35, WIDTH // 2, 29, *_DIM, ampm_tz)
    draw_hline(canvas, 0, 36, WIDTH, *_SEP)

    # UTC section
    draw_text_centered(canvas, F35, WIDTH // 2, 39, *_DIMMER, 'UTC')
    # UTC time: F57×1 (7 px tall)
    draw_text_centered(canvas, F57, WIDTH // 2, 47, 110, 110, 110, time_utc)
    draw_hline(canvas, 0, 57, WIDTH, *_FAINT)
