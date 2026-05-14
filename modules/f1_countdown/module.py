"""F1 countdown module — counts down to the next F1 session."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import requests

from display.fonts import F35, F57
from display.renderer import (
    WIDTH,
    draw_hline,
    draw_text_centered,
    draw_text_centered_scaled,
    fill_rect,
)
from modules.base import BaseModule
from modules.registry import register

_JOLPICA_URL = "https://api.jolpi.ca/ergast/f1/{year}/races.json"
_POLL_INTERVAL = 4 * 3600

# (Jolpica field name, display label, counts as "main" session for filtering)
_SESSION_KEYS: list[tuple[str, str, bool]] = [
    ('FirstPractice',    'FP1',         False),
    ('SecondPractice',   'FP2',         False),
    ('ThirdPractice',    'FP3',         False),
    ('SprintShootout',   'SPRINT QUAL', True),
    ('SprintQualifying', 'SPRINT QUAL', True),
    ('Sprint',           'SPRINT',      True),
    ('Qualifying',       'QUALIFYING',  True),
]

_SESSION_DURATION_MIN: dict[str, int] = {
    'FP1': 90, 'FP2': 90, 'FP3': 90,
    'SPRINT QUAL': 50, 'QUALIFYING': 65,
    'SPRINT': 35, 'RACE': 125,
}

_SESSION_COLOR: dict[str, tuple[int, int, int]] = {
    'FP1':         (0,   110, 200),
    'FP2':         (0,   110, 200),
    'FP3':         (0,   110, 200),
    'QUALIFYING':  (220, 180,   0),
    'SPRINT QUAL': (200, 100,   0),
    'SPRINT':      (220, 130,   0),
    'RACE':        (210,  30,  30),
}

# Y layout — days hero (>= 24 h remaining)
_DH_RACE_Y  = 8
_DH_SEP1_Y  = 17
_DH_SESS_Y  = 22
_DH_SEP2_Y  = 31
_DH_DAYS_Y  = 46   # F57 4× = 28 px tall
_DH_DLBL_Y  = 82
_DH_SEP3_Y  = 100
_DH_DATE_Y  = 108
_DH_TIME_Y  = 118

# Y layout — hours hero (1 h – 24 h remaining)
_HH_RACE_Y  = 8
_HH_SEP1_Y  = 17
_HH_DATE_Y  = 22
_HH_TIME_Y  = 30
_HH_SEP2_Y  = 38
_HH_SESS_Y  = 44
_HH_SEP3_Y  = 53
_HH_HMS_Y   = 70   # F57 2× = 14 px tall
_HH_BAR_Y   = 188

# Y layout — minutes hero (< 1 h remaining)
_MH_RACE_Y  = 8
_MH_SEP1_Y  = 17
_MH_DATE_Y  = 22
_MH_TIME_Y  = 30
_MH_SEP2_Y  = 38
_MH_SESS_Y  = 44
_MH_SEP3_Y  = 53
_MH_MS_Y    = 68   # F57 3× = 21 px tall
_MH_BAR_Y   = 188


@dataclass
class _F1Session:
    race_name: str
    session_type: str
    is_main: bool
    start_utc: datetime


def _parse_dt(date: str, time_str: str) -> datetime:
    dt = datetime.fromisoformat(f"{date}T{time_str.rstrip('Z')}")
    return dt.replace(tzinfo=timezone.utc)


def _abbrev_race(name: str) -> str:
    return name.replace('Grand Prix', 'GP').upper()


@register
class F1CountdownModule(BaseModule):
    """Counts down to the next F1 session."""

    name = 'f1_countdown'
    description = 'Countdown to next F1 session'
    default_fps = 1

    def __init__(self, config: dict[str, Any]) -> None:
        self._show_all: bool = config.get('show_all_sessions', True)
        self._sessions: list[_F1Session] = []
        self._fetch_error: Optional[str] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._schedule_loop, daemon=True, name='f1-countdown'
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, canvas: Any) -> None:
        canvas.Fill(0, 0, 0)
        now = datetime.now(timezone.utc)

        with self._lock:
            sessions = list(self._sessions)
            error = self._fetch_error

        if not sessions:
            self._render_loading(canvas, error)
            return

        target = self._next_session(sessions, now)
        if target is None:
            draw_text_centered(canvas, F35, WIDTH // 2, 88, 60, 60, 60, 'NO SESSIONS FOUND')
            return

        delta = target.start_utc - now
        total_secs = int(delta.total_seconds())
        duration = timedelta(minutes=_SESSION_DURATION_MIN.get(target.session_type, 90))

        if delta < timedelta(0) and -delta <= duration:
            self._render_live(canvas, target)
            return

        color = _SESSION_COLOR.get(target.session_type, (180, 180, 180))
        local_dt = target.start_utc.astimezone()
        race = _abbrev_race(target.race_name)
        sess = target.session_type

        if total_secs >= 86400:
            days = total_secs // 86400
            self._render_days(canvas, race, sess, color, days, local_dt)
        elif total_secs >= 3600:
            h = total_secs // 3600
            m = (total_secs % 3600) // 60
            s = total_secs % 60
            self._render_hours(canvas, race, sess, color, h, m, s, local_dt, total_secs)
        else:
            m = total_secs // 60
            s = total_secs % 60
            self._render_minutes(canvas, race, sess, color, m, s, local_dt, total_secs)

    def _render_days(self, canvas: Any, race: str, sess: str,
                     color: tuple[int, int, int], days: int,
                     local_dt: datetime) -> None:
        r, g, b = color
        draw_text_centered(canvas, F35, WIDTH // 2, _DH_RACE_Y, 180, 180, 180, race)
        draw_hline(canvas, 0, _DH_SEP1_Y, WIDTH, 40, 40, 40)
        draw_text_centered(canvas, F35, WIDTH // 2, _DH_SESS_Y, r, g, b, f"-- {sess} --")
        draw_hline(canvas, 0, _DH_SEP2_Y, WIDTH, 40, 40, 40)
        draw_text_centered_scaled(canvas, F57, WIDTH // 2, _DH_DAYS_Y,
                                  255, 255, 255, str(days), 4)
        draw_text_centered(canvas, F35, WIDTH // 2, _DH_DLBL_Y, 70, 70, 70, 'DAYS')
        draw_hline(canvas, 0, _DH_SEP3_Y, WIDTH, 40, 40, 40)
        draw_text_centered(canvas, F35, WIDTH // 2, _DH_DATE_Y, 80, 80, 80,
                           local_dt.strftime('%a %d %b').upper())
        draw_text_centered(canvas, F35, WIDTH // 2, _DH_TIME_Y, 70, 70, 70,
                           local_dt.strftime('%-I:%M %p %Z'))

    def _render_hours(self, canvas: Any, race: str, sess: str,
                      color: tuple[int, int, int], h: int, m: int, s: int,
                      local_dt: datetime, total_secs: int) -> None:
        r, g, b = color
        draw_text_centered(canvas, F35, WIDTH // 2, _HH_RACE_Y, 180, 180, 180, race)
        draw_hline(canvas, 0, _HH_SEP1_Y, WIDTH, 40, 40, 40)
        draw_text_centered(canvas, F35, WIDTH // 2, _HH_DATE_Y, 90, 90, 90,
                           local_dt.strftime('%a %d %b').upper())
        draw_text_centered(canvas, F35, WIDTH // 2, _HH_TIME_Y, 75, 75, 75,
                           local_dt.strftime('%-I:%M %p %Z'))
        draw_hline(canvas, 0, _HH_SEP2_Y, WIDTH, 40, 40, 40)
        draw_text_centered(canvas, F35, WIDTH // 2, _HH_SESS_Y, r, g, b, f"-- {sess} --")
        draw_hline(canvas, 0, _HH_SEP3_Y, WIDTH, 40, 40, 40)
        draw_text_centered_scaled(canvas, F57, WIDTH // 2, _HH_HMS_Y,
                                  255, 255, 255, f"{h:02d}:{m:02d}:{s:02d}", 2)
        _draw_progress(canvas, total_secs, 86400, _HH_BAR_Y)

    def _render_minutes(self, canvas: Any, race: str, sess: str,
                        color: tuple[int, int, int], m: int, s: int,
                        local_dt: datetime, total_secs: int) -> None:
        r, g, b = color
        draw_text_centered(canvas, F35, WIDTH // 2, _MH_RACE_Y, 180, 180, 180, race)
        draw_hline(canvas, 0, _MH_SEP1_Y, WIDTH, 40, 40, 40)
        draw_text_centered(canvas, F35, WIDTH // 2, _MH_DATE_Y, 90, 90, 90,
                           local_dt.strftime('%a %d %b').upper())
        draw_text_centered(canvas, F35, WIDTH // 2, _MH_TIME_Y, 75, 75, 75,
                           local_dt.strftime('%-I:%M %p %Z'))
        draw_hline(canvas, 0, _MH_SEP2_Y, WIDTH, 40, 40, 40)
        draw_text_centered(canvas, F35, WIDTH // 2, _MH_SESS_Y, r, g, b, f"-- {sess} --")
        draw_hline(canvas, 0, _MH_SEP3_Y, WIDTH, 40, 40, 40)
        draw_text_centered_scaled(canvas, F57, WIDTH // 2, _MH_MS_Y,
                                  255, 255, 255, f"{m:02d}:{s:02d}", 3)
        _draw_progress(canvas, total_secs, 3600, _MH_BAR_Y)

    def _render_live(self, canvas: Any, session: _F1Session) -> None:
        flash = int(time.time()) % 2 == 0
        if flash:
            canvas.Fill(0, 55, 15)
            fg = (0, 240, 70)
        else:
            canvas.Fill(0, 35, 10)
            fg = (0, 180, 50)
        draw_text_centered(canvas, F35, WIDTH // 2, 68, *fg, 'SESSION')
        draw_text_centered(canvas, F57, WIDTH // 2, 80, *fg, 'LIVE')
        r, g, b = _SESSION_COLOR.get(session.session_type, (180, 180, 180))
        draw_text_centered(canvas, F35, WIDTH // 2,  98, r, g, b, session.session_type)
        draw_text_centered(canvas, F35, WIDTH // 2, 112, 110, 110, 110,
                           _abbrev_race(session.race_name))

    def _render_loading(self, canvas: Any, error: Optional[str]) -> None:
        if error:
            draw_text_centered(canvas, F35, WIDTH // 2, 88, 200, 60, 60, 'SCHEDULE ERROR')
            draw_text_centered(canvas, F35, WIDTH // 2, 100, 100, 40, 40, error[:20])
        else:
            draw_text_centered(canvas, F35, WIDTH // 2, 92, 60, 60, 60, 'LOADING...')

    # ------------------------------------------------------------------
    # Session selection
    # ------------------------------------------------------------------

    def _next_session(self, sessions: list[_F1Session], now: datetime) -> Optional[_F1Session]:
        """Return the next upcoming or currently live session."""
        for s in sessions:
            if not self._show_all and not s.is_main:
                continue
            end = s.start_utc + timedelta(minutes=_SESSION_DURATION_MIN.get(s.session_type, 90))
            if now < end:
                return s
        return None

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _schedule_loop(self) -> None:
        self._fetch_schedule()
        while not self._stop.is_set():
            self._stop.wait(_POLL_INTERVAL)
            if not self._stop.is_set():
                self._fetch_schedule()

    def _fetch_schedule(self) -> None:
        now = datetime.now(timezone.utc)
        all_sessions: list[_F1Session] = []
        all_sessions.extend(self._fetch_year(now.year))
        if now.month >= 11:
            all_sessions.extend(self._fetch_year(now.year + 1))
        cutoff = now - timedelta(hours=3)
        future = sorted(
            (s for s in all_sessions if s.start_utc >= cutoff),
            key=lambda x: x.start_utc,
        )
        with self._lock:
            self._sessions = future
            if future:
                self._fetch_error = None

    def _fetch_year(self, year: int) -> list[_F1Session]:
        try:
            resp = requests.get(_JOLPICA_URL.format(year=year), timeout=15)
            resp.raise_for_status()
            races = resp.json()['MRData']['RaceTable']['Races']
            sessions: list[_F1Session] = []
            for race in races:
                name = race['raceName']
                for key, label, is_main in _SESSION_KEYS:
                    if key in race:
                        entry = race[key]
                        try:
                            dt = _parse_dt(entry['date'], entry['time'])
                            sessions.append(_F1Session(name, label, is_main, dt))
                        except (KeyError, ValueError):
                            pass
                try:
                    dt = _parse_dt(race['date'], race['time'])
                    sessions.append(_F1Session(name, 'RACE', True, dt))
                except (KeyError, ValueError):
                    pass
            return sessions
        except Exception as exc:
            msg = 'TIMEOUT' if 'timeout' in str(exc).lower() else str(exc)[:20]
            print(f'[f1_countdown] fetch error ({year}): {exc}')
            with self._lock:
                if not self._sessions:
                    self._fetch_error = msg
            return []

    # ------------------------------------------------------------------
    # Config / status
    # ------------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        return {'show_all_sessions': self._show_all}

    def set_config(self, cfg: dict[str, Any]) -> None:
        if 'show_all_sessions' in cfg:
            self._show_all = bool(cfg['show_all_sessions'])

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            n = len(self._sessions)
            err = self._fetch_error
            nxt = self._sessions[0] if self._sessions else None
        return {
            'sessions_loaded': n,
            'fetch_error': err,
            'next_race': nxt.race_name if nxt else None,
            'next_session': nxt.session_type if nxt else None,
        }


def _draw_progress(canvas: Any, remaining: int, total: int, bar_y: int) -> None:
    """Bottom progress bar: fills left-to-right as the session approaches."""
    filled_px = int(((total - remaining) / total) * WIDTH)
    fill_rect(canvas, 0, bar_y, WIDTH, 3, 15, 15, 15)
    if filled_px > 0:
        fill_rect(canvas, 0, bar_y, filled_px, 3, 0, 180, 80)
