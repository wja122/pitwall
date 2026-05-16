"""F1 countdown widget — next session countdown from Jolpica/Ergast API."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from display.fonts import F35, F57
from display.renderer import draw_hline, draw_text_centered, draw_text_centered_scaled, fill_rect
from widgets.base import BaseWidget
from widgets.registry import register_widget

_JOLPICA_URL   = 'https://api.jolpi.ca/ergast/f1/{year}/races.json'
_POLL_INTERVAL = 4 * 3600

_SESSION_KEYS: list[tuple[str, str]] = [
    ('FirstPractice',    'FP1'),
    ('SecondPractice',   'FP2'),
    ('ThirdPractice',    'FP3'),
    ('SprintShootout',   'SPRINT QUAL'),
    ('SprintQualifying', 'SPRINT QUAL'),
    ('Sprint',           'SPRINT'),
    ('Qualifying',       'QUALIFYING'),
]

_SESSION_COLOR: dict[str, tuple[int, int, int]] = {
    'FP1':         (0,   110, 200),
    'FP2':         (0,   110, 200),
    'FP3':         (0,   110, 200),
    'QUALIFYING':  (220, 180,   0),
    'SPRINT QUAL': (200, 100,   0),
    'SPRINT':      (220, 130,   0),
    'RACE':        (210,  30,  30),
}

_SESSION_DURATION_MIN: dict[str, int] = {
    'FP1': 90, 'FP2': 90, 'FP3': 90,
    'SPRINT QUAL': 50, 'QUALIFYING': 65,
    'SPRINT': 35, 'RACE': 125,
}


@dataclass
class _Session:
    race_name:    str
    session_type: str
    start_utc:    datetime


def _parse_dt(date: str, time_str: str) -> datetime:
    dt = datetime.fromisoformat(f"{date}T{time_str.rstrip('Z')}")
    return dt.replace(tzinfo=timezone.utc)


def _abbrev(name: str) -> str:
    return name.replace('Grand Prix', 'GP').upper()


@register_widget
class F1CountdownWidget(BaseWidget):
    """Counts down to the next F1 session."""

    name              = 'f1_countdown'
    description       = 'Next F1 session countdown'
    supported_heights = [55, 111]

    def __init__(self, config: dict[str, Any]) -> None:
        self._sessions: list[_Session] = []
        self._error:    Optional[str]  = None
        self._lock  = threading.Lock()
        self._stop  = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name='widget-f1-countdown',
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, canvas: Any, x: int, y: int, w: int, h: int) -> None:
        cx  = x + w // 2
        now = datetime.now(timezone.utc)

        with self._lock:
            sessions = list(self._sessions)
            error    = self._error

        if not sessions:
            msg = error or 'LOADING...'
            draw_text_centered(canvas, F35, cx, y + h // 2 - 2, 60, 60, 60, msg)
            return

        target = next(
            (s for s in sessions
             if now < s.start_utc + timedelta(minutes=_SESSION_DURATION_MIN.get(s.session_type, 90))),
            None,
        )
        if target is None:
            draw_text_centered(canvas, F35, cx, y + h // 2 - 2, 50, 50, 50, 'SEASON COMPLETE')
            return

        delta     = target.start_utc - now
        total_s   = int(delta.total_seconds())
        color     = _SESSION_COLOR.get(target.session_type, (160, 160, 160))
        race      = _abbrev(target.race_name)
        sess      = target.session_type
        local_dt  = target.start_utc.astimezone()

        if h >= 90:
            self._render_tall(canvas, x, y, w, h, cx, race, sess, color, total_s, local_dt)
        else:
            self._render_compact(canvas, x, y, w, h, cx, race, sess, color, total_s, local_dt)

    def _render_compact(self, canvas: Any, x: int, y: int, w: int, h: int, cx: int,
                        race: str, sess: str, color: tuple, total_s: int,
                        local_dt: datetime) -> None:
        r, g, b = color

        if total_s < 0:
            draw_text_centered(canvas, F35, cx, y + 3, 0, 200, 60, 'LIVE NOW')
            draw_text_centered(canvas, F35, cx, y + 11, r, g, b, sess)
            draw_hline(canvas, x, y + 18, w, 22, 22, 22)
            draw_text_centered(canvas, F35, cx, y + 22, 130, 130, 130, race)
            return

        draw_text_centered(canvas, F35, cx, y + 3, 140, 140, 140, race)
        draw_hline(canvas, x, y + 10, w, 22, 22, 22)
        draw_text_centered(canvas, F35, cx, y + 13, r, g, b, sess)

        if total_s >= 86400:
            d = total_s // 86400
            hh = (total_s % 86400) // 3600
            countdown = f'{d}D {hh:02d}H'
        elif total_s >= 3600:
            hh = total_s // 3600
            mm = (total_s % 3600) // 60
            countdown = f'{hh:02d}:{mm:02d}:{(total_s % 60):02d}'
        else:
            mm = total_s // 60
            countdown = f'{mm:02d}:{(total_s % 60):02d}'

        draw_text_centered_scaled(canvas, F57, cx, y + 21, 255, 255, 255, countdown, 2)
        date_str = local_dt.strftime('%a %-d %b  %-I:%M %p').upper()
        draw_text_centered(canvas, F35, cx, y + 37, 60, 60, 60, date_str)
        draw_hline(canvas, x, y + h - 2, w, 22, 22, 22)

    def _render_tall(self, canvas: Any, x: int, y: int, w: int, h: int, cx: int,
                     race: str, sess: str, color: tuple, total_s: int,
                     local_dt: datetime) -> None:
        r, g, b = color

        if total_s < 0:
            draw_text_centered(canvas, F35, cx, y + 10, 0, 220, 70, 'SESSION LIVE')
            draw_text_centered(canvas, F35, cx, y + 22, r, g, b, sess)
            draw_text_centered(canvas, F35, cx, y + 34, 110, 110, 110, race)
            return

        draw_text_centered(canvas, F35, cx, y + 5, 150, 150, 150, race)
        draw_hline(canvas, x, y + 13, w, 22, 22, 22)
        draw_text_centered(canvas, F35, cx, y + 17, r, g, b, f'-- {sess} --')
        draw_hline(canvas, x, y + 25, w, 22, 22, 22)

        if total_s >= 86400:
            d  = total_s // 86400
            hh = (total_s % 86400) // 3600
            draw_text_centered_scaled(canvas, F57, cx, y + 32, 255, 255, 255, str(d), 3)
            draw_text_centered(canvas, F35, cx, y + 57, 70, 70, 70, f'DAYS  {hh:02d}H REMAINING')
        elif total_s >= 3600:
            hh = total_s // 3600
            mm = (total_s % 3600) // 60
            ss = total_s % 60
            draw_text_centered_scaled(canvas, F57, cx, y + 32, 255, 255, 255, f'{hh:02d}:{mm:02d}:{ss:02d}', 2)
            draw_text_centered(canvas, F35, cx, y + 50, 70, 70, 70, 'HOURS REMAINING')
        else:
            mm = total_s // 60
            draw_text_centered_scaled(canvas, F57, cx, y + 32, 255, 255, 255, f'{mm:02d}:{(total_s % 60):02d}', 3)
            draw_text_centered(canvas, F35, cx, y + 57, 70, 70, 70, 'MINUTES REMAINING')

        draw_hline(canvas, x, y + 65, w, 22, 22, 22)
        date_str = local_dt.strftime('%a %-d %b  %-I:%M %p %Z').upper()
        draw_text_centered(canvas, F35, cx, y + 69, 65, 65, 65, date_str)
        draw_hline(canvas, x, y + h - 2, w, 22, 22, 22)

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------

    def _loop(self) -> None:
        self._fetch()
        while not self._stop.is_set():
            self._stop.wait(_POLL_INTERVAL)
            if not self._stop.is_set():
                self._fetch()

    def _fetch(self) -> None:
        now = datetime.now(timezone.utc)
        all_sessions: list[_Session] = []
        all_sessions.extend(self._fetch_year(now.year))
        if now.month >= 11:
            all_sessions.extend(self._fetch_year(now.year + 1))
        cutoff = now - timedelta(hours=3)
        future = sorted(
            (s for s in all_sessions if s.start_utc >= cutoff),
            key=lambda s: s.start_utc,
        )
        with self._lock:
            self._sessions = future
            if future:
                self._error = None

    def _fetch_year(self, year: int) -> list[_Session]:
        try:
            resp = requests.get(_JOLPICA_URL.format(year=year), timeout=15)
            resp.raise_for_status()
            races = resp.json()['MRData']['RaceTable']['Races']
            out: list[_Session] = []
            for race in races:
                name = race['raceName']
                for key, label in _SESSION_KEYS:
                    if key in race:
                        e = race[key]
                        try:
                            out.append(_Session(name, label, _parse_dt(e['date'], e['time'])))
                        except (KeyError, ValueError):
                            pass
                try:
                    out.append(_Session(name, 'RACE', _parse_dt(race['date'], race['time'])))
                except (KeyError, ValueError):
                    pass
            return out
        except Exception as exc:
            print(f'[widget:f1_countdown] fetch error ({year}): {exc}')
            with self._lock:
                if not self._sessions:
                    self._error = str(exc)[:20]
            return []
