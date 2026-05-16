from __future__ import annotations

import time
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

import requests

from modules.base import BaseModule
from modules.registry import register
from display.fonts import F35, F57
from display.icons import ALERT_ICON, ALERT_ICON_W, draw_icon
from display.renderer import (
    WIDTH, HEIGHT,
    draw_hline, draw_text, draw_text_centered,
    draw_text_centered_scaled, draw_text_scaled,
    fill_rect, text_width,
)

_NWS_POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
_NWS_ALERTS_URL = "https://api.weather.gov/alerts/active"

_WEATHER_INTERVAL = 600  # 10 minutes
_ALERTS_INTERVAL  = 120  # 2 minutes
_NWS_TIMEOUT      = 30   # NWS can be slow; 10s is too tight

_NWS_HEADERS = {'User-Agent': 'pitwall/1.0 (github.com/pitwall)'}


def _c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


def _kmh_to_mph(kmh: float) -> float:
    return kmh * 0.621371


def _compass(deg: int) -> str:
    dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
    return dirs[round(deg / 45) % 8]


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DailyForecast:
    dt: int
    temp_min: float
    temp_max: float
    condition: str


@dataclass
class WeatherAlert:
    event: str
    severity: str
    urgency: str
    headline: str
    expires: str
    damage_threat: str
    pds: bool
    certainty: str


@dataclass
class WeatherData:
    temp: float
    condition: str
    feels_like: float
    temp_high: float
    temp_low: float
    wind_speed: float
    wind_deg: int
    humidity: int
    fetch_time: float
    daily_forecasts: list[DailyForecast]
    alerts: list[WeatherAlert]
    error: str | None = None


# ---------------------------------------------------------------------------
# Module
# ---------------------------------------------------------------------------

@register
class WeatherModule(BaseModule):
    """Current conditions, 3-day forecast, and NWS weather alerts."""

    name        = 'weather'
    description = 'Current conditions, 3-day forecast, and weather alerts'
    default_fps = 10

    def __init__(self, config: dict[str, Any]) -> None:
        self._lat: Optional[float] = config.get('lat')
        self._lon: Optional[float] = config.get('lon')
        self._units = config.get('units', 'imperial')

        self._forecast_url:  Optional[str] = None
        self._stations_url:  Optional[str] = None

        self._data: Optional[WeatherData] = None
        self._alerts: list[WeatherAlert] = []
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._weather_thread: Optional[threading.Thread] = None
        self._alerts_thread:  Optional[threading.Thread] = None
        self._ticker_x: float = float(WIDTH)
        self._takeover_since: float = 0.0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        if self._lat is None or self._lon is None:
            print('[weather] lat/lon not configured — fetch disabled')
            return
        self._weather_thread = threading.Thread(
            target=self._weather_loop, daemon=True, name='weather-nws-current'
        )
        self._alerts_thread = threading.Thread(
            target=self._alerts_loop, daemon=True, name='weather-nws-alerts'
        )
        self._weather_thread.start()
        self._alerts_thread.start()

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, canvas: Any) -> None:
        with self._lock:
            data   = self._data
            alerts = self._alerts[:]

        warning = next(
            (a for a in alerts if self._is_takeover_alert(a)), None
        )
        if warning:
            if self._takeover_since == 0.0:
                self._takeover_since = time.time()
            if time.time() - self._takeover_since < 60:
                self._draw_warning_takeover(canvas, warning)
                return
        else:
            self._takeover_since = 0.0

        now = datetime.now().astimezone()
        self._draw_header(canvas, now)
        self._draw_current(canvas, data)
        if warning:
            self._draw_alert_in_forecast_zone(canvas, warning)
        else:
            self._draw_forecast(canvas, data)
        self._draw_alert_footer(canvas, alerts)

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------

    _HEADER_H = 12   # y 0-11
    _MID_Y    = 96   # divider between current and forecast
    _FOOTER_Y = 180  # y 180-191
    _COL_CX   = [21, 64, 107]  # forecast column centres

    def _draw_header(self, canvas: Any, now: datetime) -> None:
        fill_rect(canvas, 0, 0, WIDTH, self._HEADER_H, 0, 0, 18)
        header_str = now.strftime('%a %b %-d  %-I:%M %p').upper()
        draw_text_centered(canvas, F35, WIDTH // 2, 3, 140, 140, 150, header_str)
        draw_hline(canvas, 0, self._HEADER_H - 1, WIDTH, 40, 40, 50)

    def _draw_current(self, canvas: Any, data: Optional[WeatherData]) -> None:
        y0 = self._HEADER_H

        if data is None:
            draw_text_centered(canvas, F35, WIDTH // 2, y0 + 36, 80, 80, 80, 'LOADING...')
            draw_hline(canvas, 0, self._MID_Y, WIDTH, 40, 40, 50)
            return

        if data.error:
            draw_text_centered(canvas, F35, WIDTH // 2, y0 + 30, 200, 60, 60, 'FETCH ERROR')
            draw_text_centered(canvas, F35, WIDTH // 2, y0 + 42, 140, 40, 40, data.error[:20])
            draw_hline(canvas, 0, self._MID_Y, WIDTH, 40, 40, 50)
            return

        unit = '\xb0F' if self._units == 'imperial' else '\xb0C'

        # Big temperature
        temp_str = f"{round(data.temp)}{unit}"
        draw_text_centered_scaled(canvas, F57, WIDTH // 2, y0 + 6, 255, 255, 255, temp_str, 3)

        # Condition
        cond = data.condition.upper()
        draw_text_centered(canvas, F35, WIDTH // 2, y0 + 36, 140, 165, 210, cond)

        # Feels like
        fl = f"FEELS {round(data.feels_like)}{unit}"
        draw_text_centered(canvas, F35, WIDTH // 2, y0 + 46, 120, 120, 130, fl)

        # Today high/low
        hl = f"H:{round(data.temp_high)}{unit}  L:{round(data.temp_low)}{unit}"
        draw_text_centered(canvas, F35, WIDTH // 2, y0 + 56, 160, 160, 160, hl)

        # Wind + humidity
        wind_str = f"{round(data.wind_speed)}{'MPH' if self._units == 'imperial' else 'M/S'} {_compass(data.wind_deg)}"
        hum_str  = f"HUM {data.humidity}%"
        row = f"{wind_str}  {hum_str}"
        draw_text_centered(canvas, F35, WIDTH // 2, y0 + 66, 110, 110, 120, row)

        draw_hline(canvas, 0, self._MID_Y, WIDTH, 40, 40, 50)

    def _draw_forecast(self, canvas: Any, data: Optional[WeatherData]) -> None:
        y0 = self._MID_Y + 1

        if data is None or data.error or not data.daily_forecasts:
            draw_text_centered(canvas, F35, WIDTH // 2, y0 + 36, 60, 60, 60, 'NO FORECAST')
            draw_hline(canvas, 0, self._FOOTER_Y - 1, WIDTH, 40, 40, 50)
            return

        unit = '\xb0F' if self._units == 'imperial' else '\xb0C'

        for i, (cx, day) in enumerate(zip(self._COL_CX, data.daily_forecasts)):
            # Column dividers (between columns only)
            if i > 0:
                draw_hline(canvas, cx - 21, y0, 1, 40, 40, 50)

            day_name = datetime.fromtimestamp(day.dt).strftime('%a').upper()
            draw_text_centered(canvas, F35, cx, y0 + 4,  160, 160, 160, day_name)
            draw_text_centered(canvas, F57, cx, y0 + 14, 220, 220, 220, f"{round(day.temp_max)}{unit}")
            draw_text_centered(canvas, F57, cx, y0 + 26,  90,  90,  90, f"{round(day.temp_min)}{unit}")
            draw_text_centered(canvas, F35, cx, y0 + 38, 120, 140, 180, day.condition.upper()[:6])

        draw_hline(canvas, 0, self._FOOTER_Y - 1, WIDTH, 40, 40, 50)
    
    def _draw_alert_in_forecast_zone(self, canvas: Any, alert: WeatherAlert) -> None:
        y0 = self._MID_Y + 1
        _, dim = self._takeover_colors(alert)
        fill_rect(canvas, 0, y0, WIDTH, self._FOOTER_Y - y0, *dim)

        icon_x = (WIDTH - ALERT_ICON_W) // 2
        draw_icon(canvas, icon_x, y0 + 4, 255, 255, 255, ALERT_ICON, ALERT_ICON_W)

        event_lines = alert.event.upper().split()
        mid   = len(event_lines) // 2
        line1 = ' '.join(event_lines[:mid])
        line2 = ' '.join(event_lines[mid:])

        draw_text_centered(canvas, F57, WIDTH // 2, y0 + 22, 255, 255, 255, line1)
        draw_text_centered(canvas, F57, WIDTH // 2, y0 + 34, 255, 255, 255, line2)
        draw_text_centered(canvas, F35, WIDTH // 2, y0 + 50, 255, 220, 0, 'UNTIL')

        try:
            exp = datetime.fromisoformat(alert.expires).astimezone()
            exp_str = exp.strftime('%-I:%M %p').upper()
        except Exception:
            exp_str = alert.expires[:16]
        draw_text_centered(canvas, F57, WIDTH // 2, y0 + 60, 255, 200, 0, exp_str)
        
    def _draw_alert_footer(self, canvas: Any, alerts: list[WeatherAlert]) -> None:
        y0 = self._FOOTER_Y

        watches = [a for a in alerts if a.severity not in ('Extreme', 'Severe')]

        if not watches:
            fill_rect(canvas, 0, y0, WIDTH, HEIGHT - y0, 0, 22, 0)
            draw_text_centered(canvas, F35, WIDTH // 2, y0 + 3, 0, 140, 0, 'ALL CLEAR')
            return

        # Yellow ticker background
        fill_rect(canvas, 0, y0, WIDTH, HEIGHT - y0, 30, 25, 0)

        # Build ticker text from all watches/advisories
        text = '  *  '.join(a.event.upper() for a in watches)
        tw = text_width(F35, text)

        # Advance scroll position
        self._ticker_x -= 1.0
        if self._ticker_x < -tw:
            self._ticker_x = float(WIDTH)

        draw_text(canvas, F35, int(self._ticker_x), y0 + 3, 255, 220, 0, text)
    
    @staticmethod
    def _takeover_colors(alert: WeatherAlert) -> tuple[tuple[int,int,int], tuple[int,int,int]]:
        if 'Tornado' in alert.event:
            return (180, 0, 0), (80, 0, 0)
        if 'Flood' in alert.event:
            return (0, 60, 180), (0, 20, 80)
        return (180, 90, 0), (80, 35, 0)  
        
    def _draw_warning_takeover(self, canvas: Any, alert: WeatherAlert) -> None:
        elapsed = time.time() - self._takeover_since

        # Flash-in: 0.6s intro — alternating white/black at 10Hz, then color
        if elapsed < 0.6:
            phase = int(elapsed / 0.1) % 2
            if phase == 0:
                fill_rect(canvas, 0, 0, WIDTH, HEIGHT, 255, 255, 255)
            else:
                fill_rect(canvas, 0, 0, WIDTH, HEIGHT, 0, 0, 0)
            return

        bright_col, dim_col = self._takeover_colors(alert)
        bg = bright_col if int(time.time() * 2) % 2 == 0 else dim_col
        fill_rect(canvas, 0, 0, WIDTH, HEIGHT, *bg)

        icon_x = (WIDTH - ALERT_ICON_W) // 2
        draw_icon(canvas, icon_x, 30, 255, 255, 255, ALERT_ICON, ALERT_ICON_W)

        # PDS badge
        if alert.pds:
            draw_text_centered(canvas, F35, WIDTH // 2, 20, 255, 255, 0, 'PDS')

        event_lines = alert.event.upper().split()
        mid   = len(event_lines) // 2
        line1 = ' '.join(event_lines[:mid])
        line2 = ' '.join(event_lines[mid:])

        draw_text_centered(canvas, F57, WIDTH // 2, 72, 255, 255, 255, line1)
        draw_text_centered(canvas, F57, WIDTH // 2, 84, 255, 255, 255, line2)
        draw_text_centered(canvas, F35, WIDTH // 2, 108, 255, 220, 0, 'UNTIL')

        try:
            exp = datetime.fromisoformat(alert.expires).astimezone()
            exp_str = exp.strftime('%-I:%M %p').upper()
        except Exception:
            exp_str = alert.expires[:16]
        draw_text_centered(canvas, F57, WIDTH // 2, 118, 255, 200, 0, exp_str)

    # ------------------------------------------------------------------
    # Config / status
    # ------------------------------------------------------------------

    @classmethod
    def setup_fields(cls) -> list[dict]:
        return [
            {
                'key':         'lat',
                'label':       'Latitude',
                'type':        'number',
                'required':    True,
                'placeholder': '40.4406',
                'hint':        'Decimal degrees — find yours at maps.google.com',
                'step':        'any',
            },
            {
                'key':         'lon',
                'label':       'Longitude',
                'type':        'number',
                'required':    True,
                'placeholder': '-79.9959',
                'step':        'any',
            },
            {
                'key':      'units',
                'label':    'Units',
                'type':     'select',
                'required': False,
                'default':  'imperial',
                'options':  [
                    {'value': 'imperial', 'label': 'Imperial (°F, mph)'},
                    {'value': 'metric',   'label': 'Metric (°C, km/h)'},
                ],
            },
        ]

    def get_config(self) -> dict[str, Any]:
        return {
            'lat':   self._lat,
            'lon':   self._lon,
            'units': self._units,
        }

    def set_config(self, cfg: dict[str, Any]) -> None:
        with self._lock:
            if 'lat'   in cfg: self._lat   = cfg['lat']
            if 'lon'   in cfg: self._lon   = cfg['lon']
            if 'units' in cfg: self._units = cfg['units']

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            d = self._data
            alert_count = len(self._alerts)
        return {
            'has_data':    d is not None and d.error is None,
            'error':       d.error if d else None,
            'age_s':       round(time.time() - d.fetch_time) if d else None,
            'alert_count': alert_count,
        }

    # ------------------------------------------------------------------
    # Loops
    # ------------------------------------------------------------------

    def _weather_loop(self) -> None:
        while not self._stop.is_set():
            self._fetch_nws_weather()
            self._stop.wait(_WEATHER_INTERVAL)

    def _alerts_loop(self) -> None:
        while not self._stop.is_set():
            self._fetch_nws_alerts()
            self._stop.wait(_ALERTS_INTERVAL)

    # ------------------------------------------------------------------
    # Fetchers
    # ------------------------------------------------------------------

    def _resolve_nws_endpoints(self) -> bool:
        """Fetch and cache the forecast + stations URLs from the NWS points API."""
        if self._forecast_url and self._stations_url:
            return True
        try:
            url = _NWS_POINTS_URL.format(lat=self._lat, lon=self._lon)
            resp = requests.get(url, headers=_NWS_HEADERS, timeout=_NWS_TIMEOUT)
            resp.raise_for_status()
            props = resp.json()['properties']
            self._forecast_url = props['forecast']
            self._stations_url = props['observationStations']
            return True
        except Exception as exc:
            print(f'[weather] NWS points failed: {exc}')
            return False

    def _fetch_nws_weather(self) -> None:
        if not self._resolve_nws_endpoints():
            return
        try:
            # Nearest observation station
            st_resp = requests.get(
                self._stations_url, headers=_NWS_HEADERS,
                params={'limit': 1}, timeout=_NWS_TIMEOUT,
            )
            st_resp.raise_for_status()
            features = st_resp.json().get('features', [])
            if not features:
                self._store_error('NO STATIONS')
                return
            station_id = features[0]['properties']['stationIdentifier']

            # Latest observation (current conditions)
            obs_resp = requests.get(
                f'https://api.weather.gov/stations/{station_id}/observations/latest',
                headers=_NWS_HEADERS, timeout=_NWS_TIMEOUT,
            )
            obs_resp.raise_for_status()
            obs = obs_resp.json()['properties']

            temp_c = obs['temperature']['value']
            if temp_c is None:
                self._store_error('NO OBS DATA')
                return

            wind_kmh = obs['windSpeed']['value'] or 0
            wind_deg = int(obs['windDirection']['value'] or 0)
            humidity = int(obs['relativeHumidity']['value'] or 0)
            condition = obs.get('textDescription', 'Unknown')

            hi = (obs.get('heatIndex') or {}).get('value')
            wc = (obs.get('windChill') or {}).get('value')
            feels_c = hi if hi is not None else (wc if wc is not None else temp_c)

            # Forecast — periods alternate day/night; NWS returns °F for US
            fc_resp = requests.get(self._forecast_url, headers=_NWS_HEADERS, timeout=_NWS_TIMEOUT)
            fc_resp.raise_for_status()
            periods   = fc_resp.json()['properties']['periods']
            daytime   = [p for p in periods if p['isDaytime']]
            nighttime = [p for p in periods if not p['isDaytime']]

            temp_high = float(daytime[0]['temperature'])   if daytime   else _c_to_f(temp_c)
            temp_low  = float(nighttime[0]['temperature']) if nighttime else _c_to_f(temp_c)

            daily = []
            for i, p in enumerate(daytime[1:4], start=1):
                low = float(nighttime[i]['temperature']) if i < len(nighttime) else float(p['temperature'])
                daily.append(DailyForecast(
                    dt=int(datetime.fromisoformat(p['startTime']).timestamp()),
                    temp_max=float(p['temperature']),
                    temp_min=low,
                    condition=p['shortForecast'],
                ))

            with self._lock:
                current_alerts = self._alerts[:]

            w = WeatherData(
                temp=_c_to_f(temp_c),
                feels_like=_c_to_f(feels_c),
                temp_high=temp_high,
                temp_low=temp_low,
                condition=condition,
                humidity=humidity,
                wind_speed=_kmh_to_mph(wind_kmh),
                wind_deg=wind_deg,
                fetch_time=time.time(),
                daily_forecasts=daily,
                alerts=current_alerts,
            )
            with self._lock:
                self._data = w

        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            print(f'[weather] NWS weather HTTP {code}')
            self._store_error(f'HTTP {code}')
        except requests.Timeout:
            print('[weather] NWS weather timed out')
            self._store_error('TIMEOUT')
        except Exception as exc:
            print(f'[weather] NWS weather error: {exc}')
            self._store_error(str(exc)[:60])

    def _fetch_nws_alerts(self) -> None:
        try:
            resp = requests.get(
                _NWS_ALERTS_URL,
                headers=_NWS_HEADERS,
                params={'point': f'{self._lat},{self._lon}'},
                timeout=_NWS_TIMEOUT,
            )
            resp.raise_for_status()
            d = resp.json()
            alerts = [
                WeatherAlert(
                    event=prop.get('event', 'Unknown Alert'),
                    severity=prop.get('severity', 'Unknown'),
                    urgency=prop.get('urgency', 'Unknown'),
                    headline=prop.get('headline', ''),
                    expires=prop.get('expires', ''),
                    certainty=prop.get('certainty', 'Unknown'),
                )
                for feature in d.get('features', [])
                if (prop := feature.get('properties', {}))
            ]
            with self._lock:
                self._alerts = alerts
        except requests.HTTPError as exc:
            code = exc.response.status_code if exc.response is not None else 0
            print(f'[weather] NWS alerts HTTP {code}')
        except requests.Timeout:
            print('[weather] NWS alerts timed out')
        except Exception as exc:
            print(f'[weather] NWS alerts error: {exc}')

    def _is_takeover_alert(self, alert: WeatherAlert) -> bool:
        if alert.pds:
            return True
        match alert.event:
            case _ if 'Tornado' in alert.event:
                return True
            case _ if 'Flash Flood Emergency' in alert.event:
                return True
            case _ if 'Severe Thunderstorm Warning' in alert.event:
                return alert.damage_threat in ('CONSIDERABLE', 'DESTRUCTIVE')
            case _ if 'Flash Flood Warning' in alert.event:
                return alert.damage_threat in ('CONSIDERABLE', 'CATASTROPHIC')
            case _:
                return False
        

    def _store_error(self, msg: str) -> None:
        """Record a fetch error, preserving last good data if available."""
        with self._lock:
            if self._data is None or self._data.error:
                self._data = WeatherData(
                    temp=0, condition='', feels_like=0,
                    temp_high=0, temp_low=0, wind_speed=0, wind_deg=0,
                    humidity=0, fetch_time=time.time(),
                    daily_forecasts=[], alerts=[], error=msg,
                )
