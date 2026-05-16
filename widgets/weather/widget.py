"""Weather widget — current conditions from NWS, no API key required."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from display.fonts import F35, F57
from display.renderer import draw_hline, draw_text, draw_text_centered, draw_text_centered_scaled, fill_rect, text_width
from widgets.base import BaseWidget
from widgets.registry import register_widget

_NWS_POINTS_URL  = 'https://api.weather.gov/points/{lat},{lon}'
_NWS_HEADERS     = {'User-Agent': 'pitwall/1.0 (github.com/pitwall)'}
_NWS_TIMEOUT     = 30
_POLL_INTERVAL   = 600  # 10 minutes


def _c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def _kmh_to_mph(kmh: float) -> float:
    return kmh * 0.621371


def _compass(deg: int) -> str:
    dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    return dirs[round(deg / 45) % 8]


@dataclass
class _Conditions:
    temp:      float
    temp_hi:   float
    temp_lo:   float
    feels:     float
    condition: str
    humidity:  int
    wind_spd:  float
    wind_dir:  int
    fetch_t:   float
    units:     str
    error:     Optional[str] = None


@register_widget
class WeatherWidget(BaseWidget):
    """Current conditions strip using the NWS observation API."""

    name              = 'weather'
    description       = 'Current conditions and high/low'
    supported_heights = [55, 111]

    def __init__(self, config: dict[str, Any]) -> None:
        self._lat:   Optional[float] = config.get('lat')
        self._lon:   Optional[float] = config.get('lon')
        self._units: str             = config.get('units', 'imperial')

        self._forecast_url: Optional[str] = None
        self._station_url:  Optional[str] = None

        self._data: Optional[_Conditions] = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._stop.clear()
        if self._lat is None or self._lon is None:
            return
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name='widget-weather',
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, canvas: Any, x: int, y: int, w: int, h: int) -> None:
        with self._lock:
            data = self._data

        cx = x + w // 2

        if data is None or data.error:
            msg = data.error if data else ('NO LOCATION' if self._lat is None else 'LOADING...')
            draw_text_centered(canvas, F35, cx, y + h // 2 - 2, 60, 60, 60, msg or 'ERROR')
            return

        imperial = data.units == 'imperial'
        temp_val = round(data.temp)
        hi_val   = round(data.temp_hi)
        lo_val   = round(data.temp_lo)
        unit_chr = 'F' if imperial else 'C'
        wind_spd = round(data.wind_spd)
        wind_lbl = 'MPH' if imperial else 'KMH'
        wind_dir = _compass(data.wind_dir)

        cond = data.condition.upper()
        if len(cond) > 18:
            cond = cond[:17] + '.'

        if h >= 90:
            self._render_tall(canvas, x, y, w, h, cx,
                              temp_val, hi_val, lo_val, unit_chr,
                              wind_spd, wind_lbl, wind_dir, data.humidity, cond)
        else:
            self._render_compact(canvas, x, y, w, h, cx,
                                 temp_val, hi_val, lo_val, unit_chr,
                                 wind_spd, wind_lbl, wind_dir, data.humidity, cond)

    def _render_compact(self, canvas: Any, x: int, y: int, w: int, h: int, cx: int,
                        temp: int, hi: int, lo: int, unit: str,
                        wspd: int, wlbl: str, wdir: str, hum: int, cond: str) -> None:
        draw_text_centered(canvas, F35, cx, y + 3, 80, 80, 80, cond)
        draw_hline(canvas, x, y + 10, w, 22, 22, 22)
        draw_text_centered_scaled(canvas, F57, cx, y + 13, 255, 255, 255, str(temp), 2)
        # unit label right of the temp block
        tw = text_width(F57, str(temp)) * 2
        ux = cx + tw // 2 + 3
        draw_text(canvas, F35, ux, y + 13, 140, 140, 140, unit)
        draw_text_centered(canvas, F35, cx, y + 29, 70, 70, 70, f'H:{hi} L:{lo}')
        draw_text_centered(canvas, F35, cx, y + 36, 60, 60, 60, f'{wdir} {wspd}{wlbl} HUM:{hum}%')
        draw_hline(canvas, x, y + h - 2, w, 22, 22, 22)

    def _render_tall(self, canvas: Any, x: int, y: int, w: int, h: int, cx: int,
                     temp: int, hi: int, lo: int, unit: str,
                     wspd: int, wlbl: str, wdir: str, hum: int, cond: str) -> None:
        draw_text_centered(canvas, F35, cx, y + 5, 80, 80, 80, cond)
        draw_hline(canvas, x, y + 13, w, 22, 22, 22)
        draw_text_centered_scaled(canvas, F57, cx, y + 17, 255, 255, 255, str(temp), 3)
        tw = text_width(F57, str(temp)) * 3
        ux = cx + tw // 2 + 3
        draw_text(canvas, F35, ux, y + 17, 140, 140, 140, unit)
        draw_hline(canvas, x, y + 41, w, 22, 22, 22)
        draw_text_centered(canvas, F35, cx, y + 45, 70, 70, 70, f'HIGH {hi}{unit}   LOW {lo}{unit}')
        draw_text_centered(canvas, F35, cx, y + 53, 60, 60, 60, f'WIND {wdir} {wspd} {wlbl}')
        draw_text_centered(canvas, F35, cx, y + 61, 55, 55, 55, f'HUMIDITY {hum}%')
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

    def _resolve_endpoints(self) -> bool:
        if self._forecast_url and self._station_url:
            return True
        try:
            url  = _NWS_POINTS_URL.format(lat=self._lat, lon=self._lon)
            resp = requests.get(url, headers=_NWS_HEADERS, timeout=_NWS_TIMEOUT)
            resp.raise_for_status()
            props = resp.json()['properties']
            self._forecast_url = props['forecast']
            self._station_url  = props['observationStations']
            return True
        except Exception as exc:
            print(f'[widget:weather] points API failed: {exc}')
            return False

    def _fetch(self) -> None:
        if not self._resolve_endpoints():
            return
        try:
            # Nearest observation station
            st = requests.get(self._station_url, headers=_NWS_HEADERS,
                              params={'limit': 1}, timeout=_NWS_TIMEOUT)
            st.raise_for_status()
            feats = st.json().get('features', [])
            if not feats:
                self._store_error('NO STATIONS')
                return
            sid = feats[0]['properties']['stationIdentifier']

            obs = requests.get(
                f'https://api.weather.gov/stations/{sid}/observations/latest',
                headers=_NWS_HEADERS, timeout=_NWS_TIMEOUT,
            )
            obs.raise_for_status()
            p = obs.json()['properties']

            temp_c = p['temperature']['value']
            if temp_c is None:
                self._store_error('NO OBS DATA')
                return

            wind_kmh = p['windSpeed']['value'] or 0
            wind_deg = int(p['windDirection']['value'] or 0)
            humidity = int(p['relativeHumidity']['value'] or 0)
            condition = p.get('textDescription', 'Unknown')
            hi_c = (p.get('heatIndex') or {}).get('value')
            wc   = (p.get('windChill') or {}).get('value')
            feels_c = hi_c if hi_c is not None else (wc if wc is not None else temp_c)

            # Forecast for today's high/low
            fc = requests.get(self._forecast_url, headers=_NWS_HEADERS, timeout=_NWS_TIMEOUT)
            fc.raise_for_status()
            periods = fc.json()['properties']['periods'][:2]
            temps = [period['temperature'] for period in periods]
            hi_f  = max(temps)
            lo_f  = min(temps)

            imperial = self._units == 'imperial'
            if imperial:
                temp  = _c_to_f(temp_c)
                feels = _c_to_f(feels_c)
                wind  = _kmh_to_mph(wind_kmh)
            else:
                temp  = temp_c
                feels = feels_c
                wind  = wind_kmh

            if not imperial:
                hi_f = (hi_f - 32) * 5 / 9
                lo_f = (lo_f - 32) * 5 / 9

            with self._lock:
                self._data = _Conditions(
                    temp=temp, temp_hi=hi_f, temp_lo=lo_f, feels=feels,
                    condition=condition, humidity=humidity,
                    wind_spd=wind, wind_dir=wind_deg,
                    fetch_t=time.time(), units=self._units,
                )
        except Exception as exc:
            print(f'[widget:weather] fetch error: {exc}')
            self._store_error(str(exc)[:20])

    def _store_error(self, msg: str) -> None:
        with self._lock:
            if self._data is None:
                self._data = _Conditions(
                    temp=0, temp_hi=0, temp_lo=0, feels=0,
                    condition='', humidity=0, wind_spd=0, wind_dir=0,
                    fetch_t=time.time(), units=self._units, error=msg,
                )
