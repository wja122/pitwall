"""Clock + weather module.

Shows local time (12hr) and UTC (24hr) in the top two-thirds, current
weather conditions in the bottom third.  Weather is fetched from the
OpenWeatherMap current-conditions API every 10 minutes.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from display.fonts import F35, F57
from display.renderer import (
    WIDTH, HEIGHT,
    draw_hline,
    draw_text,
    draw_text_centered,
    draw_text_centered_scaled,
    draw_text_scaled,
    fill_rect,
    text_width,
    text_width_scaled,
)
from modules.base import BaseModule
from modules.registry import register

_WEATHER_POLL_INTERVAL = 600  # 10 minutes
_OWM_URL = "https://api.openweathermap.org/data/2.5/weather"

# ---------------------------------------------------------------------------
# Layout (y coordinates — adjust here to tweak spacing)
# ---------------------------------------------------------------------------
_Y_DATE_H      = 11   # height of date bar
_Y_DATE_TEXT   = 3    # date F35 baseline
_Y_DATE_SEP    = 11   # separator line

_Y_LOCAL_TIME  = 15   # "12:34" F57 3× top
_Y_LOCAL_SCALE = 3
_Y_LOCAL_TZ    = 41   # timezone abbrev F35

_Y_LOCAL_SEP   = 52   # separator below local time section

_Y_UTC_TIME    = 60   # "UTC  HH:MM" F57 1×
_Y_UTC_SEP     = 76   # separator below UTC section

_Y_CITY        = 84   # city name F35
_Y_TEMP        = 95   # temperature F57 3×
_Y_TEMP_SCALE  = 3
_Y_CONDITION   = 122  # condition string F35
_Y_WEATHER_SEP = 132  # separator
_Y_HL          = 138  # high / low F35
_Y_HUM_WIND    = 148  # humidity + wind F35
_Y_FEELS       = 158  # feels-like F35
_Y_UPDATED     = 168  # "UPD HH:MM AM" F35 (very dim)


# ---------------------------------------------------------------------------
# Weather data
# ---------------------------------------------------------------------------

@dataclass
class _WeatherData:
    temp: float
    temp_high: float
    temp_low: float
    temp_feels: float
    description: str
    humidity: int
    wind_speed: float
    wind_deg: int
    city: str
    fetched_at: float = field(default_factory=time.time)
    error: Optional[str] = None


def _compass(deg: int) -> str:
    dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    return dirs[round(deg / 45) % 8]


def _weather_error_label(error: str) -> str:
    """Convert a raw error string into a short displayable label."""
    if '401' in error:
        return 'KEY INACTIVE'
    if '404' in error:
        return 'CITY NOT FOUND'
    if '429' in error:
        return 'RATE LIMITED'
    if 'TIMEOUT' in error.upper():
        return 'TIMED OUT'
    return 'FETCH FAILED'


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

@register
class ClockModule(BaseModule):
    """Local + UTC clock with OpenWeatherMap current conditions."""

    name = 'clock'
    description = 'Local + UTC time with current weather'
    default_fps = 1

    def __init__(self, config: dict[str, Any]) -> None:
        self._api_key: str = config.get('api_key', '')
        self._location: str = config.get('location', 'Pittsburgh, PA')
        self._units: str = config.get('units', 'imperial')

        self._weather: Optional[_WeatherData] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        if self._api_key:
            self._thread = threading.Thread(
                target=self._weather_loop, daemon=True, name='clock-weather'
            )
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, canvas: Any) -> None:
        canvas.Fill(0, 0, 0)
        now_local = datetime.now().astimezone()
        now_utc = datetime.now(timezone.utc)
        with self._lock:
            weather = self._weather

        self._draw_date_bar(canvas, now_local)
        self._draw_local_time(canvas, now_local)
        self._draw_utc(canvas, now_utc)
        self._draw_weather(canvas, weather)

    def _draw_date_bar(self, canvas: Any, now: datetime) -> None:
        fill_rect(canvas, 0, 0, WIDTH, _Y_DATE_H, 0, 0, 18)
        day  = now.strftime('%a').upper()
        mon  = now.strftime('%b').upper()
        date_str = f"{day} {mon} {now.day}"
        draw_text_centered(canvas, F35, WIDTH // 2, _Y_DATE_TEXT, 110, 110, 120, date_str)
        draw_hline(canvas, 0, _Y_DATE_SEP, WIDTH, 45, 45, 55)

    def _draw_local_time(self, canvas: Any, now: datetime) -> None:
        scale = _Y_LOCAL_SCALE

        # "1:34" or "12:34" — %-I strips the leading zero on Linux/macOS
        time_str = now.strftime('%-I:%M')
        t_w = text_width_scaled(F57, time_str, scale)
        t_h = F57['_height'] * scale
        t_x = (WIDTH - t_w) // 2
        draw_text_scaled(canvas, F57, t_x, _Y_LOCAL_TIME, 255, 255, 255, time_str, scale)

        # AM / PM — vertically centered with the large time block
        ampm = now.strftime('%p')
        pm_y = _Y_LOCAL_TIME + (t_h - F57['_height']) // 2
        pm_x = t_x + t_w + 3
        draw_text(canvas, F57, pm_x, pm_y, 200, 200, 200, ampm)

        # Timezone abbreviation (e.g. "EDT", "UTC", "PST")
        tz_str = now.strftime('%Z')
        draw_text_centered(canvas, F35, WIDTH // 2, _Y_LOCAL_TZ, 255, 140, 0, tz_str)

        draw_hline(canvas, 0, _Y_LOCAL_SEP, WIDTH, 45, 45, 45)

    def _draw_utc(self, canvas: Any, now_utc: datetime) -> None:
        time_str = now_utc.strftime('%H:%M')
        label = 'UTC'
        gap = F57['_advance']
        total_w = text_width(F57, label) + gap + text_width(F57, time_str)
        x = (WIDTH - total_w) // 2
        draw_text(canvas, F57, x, _Y_UTC_TIME, 90, 90, 90, label)
        draw_text(canvas, F57, x + text_width(F57, label) + gap, _Y_UTC_TIME, 170, 170, 170, time_str)
        draw_hline(canvas, 0, _Y_UTC_SEP, WIDTH, 45, 45, 45)

    def _draw_weather(self, canvas: Any, weather: Optional[_WeatherData]) -> None:
        if weather is None:
            msg = 'LOADING...' if self._api_key else 'NO API KEY'
            draw_text_centered(canvas, F35, WIDTH // 2, 140, 80, 80, 80, msg)
            return

        if weather.error:
            label = _weather_error_label(weather.error)
            draw_text_centered(canvas, F35, WIDTH // 2, _Y_CITY,      200, 60, 60, 'WEATHER ERROR')
            draw_text_centered(canvas, F35, WIDTH // 2, _Y_CITY + 12, 160, 50, 50, label)
            draw_text_centered(canvas, F35, WIDTH // 2, _Y_CITY + 24,  80, 80, 80, 'CHECK CONSOLE')
            return

        unit = '°F' if self._units == 'imperial' else '°C'
        scale = _Y_TEMP_SCALE

        # City name (strip comma, uppercase, truncate to fit)
        city = weather.city.upper()
        draw_text_centered(canvas, F35, WIDTH // 2, _Y_CITY, 180, 180, 180, city)

        # Temperature
        temp_str = f"{round(weather.temp)}{unit}"
        draw_text_centered_scaled(canvas, F57, WIDTH // 2, _Y_TEMP, 255, 255, 255, temp_str, scale)

        # Condition (truncate if somehow too long)
        cond = weather.description.upper()
        if text_width(F35, cond) > WIDTH:
            # trim word by word
            words = cond.split()
            cond = ''
            for w in words:
                candidate = (cond + ' ' + w).strip()
                if text_width(F35, candidate) <= WIDTH:
                    cond = candidate
                else:
                    break
        draw_text_centered(canvas, F35, WIDTH // 2, _Y_CONDITION, 140, 165, 210, cond)

        draw_hline(canvas, 0, _Y_WEATHER_SEP, WIDTH, 35, 35, 35)

        # High / low
        hi = round(weather.temp_high)
        lo = round(weather.temp_low)
        hl = f"H:{hi}{unit}  L:{lo}{unit}"
        draw_text_centered(canvas, F35, WIDTH // 2, _Y_HL, 160, 160, 160, hl)

        # Humidity + wind
        wind_dir = _compass(weather.wind_deg)
        wind_spd = round(weather.wind_speed)
        wind_unit = 'MPH' if self._units == 'imperial' else 'M/S'
        hw = f"HUM:{weather.humidity}%  {wind_spd}{wind_unit} {wind_dir}"
        draw_text_centered(canvas, F35, WIDTH // 2, _Y_HUM_WIND, 130, 130, 130, hw)

        # Feels like
        fl = f"FEELS LIKE {round(weather.temp_feels)}{unit}"
        draw_text_centered(canvas, F35, WIDTH // 2, _Y_FEELS, 110, 110, 110, fl)

        # Updated timestamp
        upd_time = datetime.fromtimestamp(weather.fetched_at).strftime('%-I:%M %p')
        draw_text_centered(canvas, F35, WIDTH // 2, _Y_UPDATED, 60, 60, 60, f"UPD {upd_time}")

    # ------------------------------------------------------------------
    # Weather fetching
    # ------------------------------------------------------------------

    def _store_error(self, msg: str) -> None:
        """Record a fetch error, keeping last good data if available."""
        with self._lock:
            if self._weather is None or self._weather.error:
                self._weather = _WeatherData(
                    temp=0, temp_high=0, temp_low=0, temp_feels=0,
                    description='', humidity=0, wind_speed=0, wind_deg=0,
                    city=self._location, error=msg,
                )
            # If we have good data, keep it silently (network blip)

    def _weather_loop(self) -> None:
        while not self._stop.is_set():
            self._fetch_weather()
            self._stop.wait(_WEATHER_POLL_INTERVAL)

    def _fetch_weather(self) -> None:
        try:
            resp = requests.get(
                _OWM_URL,
                params={
                    'q': self._location,
                    'appid': self._api_key,
                    'units': self._units,
                },
                timeout=10,
            )
            resp.raise_for_status()
            d = resp.json()
            w = _WeatherData(
                temp=d['main']['temp'],
                temp_high=d['main']['temp_max'],
                temp_low=d['main']['temp_min'],
                temp_feels=d['main']['feels_like'],
                description=d['weather'][0]['description'],
                humidity=d['main']['humidity'],
                wind_speed=d['wind']['speed'],
                wind_deg=d['wind'].get('deg', 0),
                city=d['name'],
            )
            with self._lock:
                self._weather = w
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            body = ''
            try:
                body = exc.response.json().get('message', '')
            except Exception:
                pass
            print(f'[clock] weather HTTP {code}: {body or exc}')
            self._store_error(f'HTTP {code}: {body}' if body else f'HTTP {code}')
        except requests.Timeout:
            print('[clock] weather fetch timed out')
            self._store_error('TIMEOUT')
        except Exception as exc:
            print(f'[clock] weather fetch error: {exc}')
            self._store_error(str(exc)[:60])

    # ------------------------------------------------------------------
    # Config / status
    # ------------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        return {
            'api_key': self._api_key,
            'location': self._location,
            'units': self._units,
        }

    def set_config(self, cfg: dict[str, Any]) -> None:
        with self._lock:
            if 'api_key' in cfg:
                self._api_key = cfg['api_key']
            if 'location' in cfg:
                self._location = cfg['location']
            if 'units' in cfg:
                self._units = cfg['units']
        # Restart weather thread if api_key newly set
        if self._api_key and (self._thread is None or not self._thread.is_alive()):
            self._thread = threading.Thread(
                target=self._weather_loop, daemon=True, name='clock-weather'
            )
            self._thread.start()

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            w = self._weather
        return {
            'has_weather': w is not None and w.error is None,
            'location': self._location,
            'weather_error': w.error if w else None,
            'weather_age_s': round(time.time() - w.fetched_at) if w else None,
        }
