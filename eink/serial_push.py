"""E-ink serial pusher.

Sends newline-delimited JSON to the Heltec Vision Master E213 (ESP32-S3)
over USB serial at 115200 baud. Pushes on mode/IP change and on a 60-second
heartbeat. Reconnects automatically if the port drops.
"""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

import serial  # type: ignore[import]

if TYPE_CHECKING:
    from display.driver import DisplayDriver

_BAUD         = 115200
_HEARTBEAT_S  = 60
_RECONNECT_S  = 10
_IP_TTL       = 30.0

_MODE_NAMES: dict[str, str] = {
    'f1_timing':    'F1 LIVE',
    'f1_countdown': 'F1 COUNTDOWN',
    'f1_standings': 'F1 STANDINGS',
    'clock':        'CLOCK',
    'weather':      'WEATHER',
    'nfl':          'NFL',
}


def _get_uptime() -> str:
    try:
        uptime_s = float(Path('/proc/uptime').read_text().split()[0])
        h, rem   = divmod(int(uptime_s), 3600)
        m        = rem // 60
        return f'{h}h{m:02d}m'
    except Exception:
        return ''


def _build_detail(name: str, status: dict[str, Any]) -> str:
    """Extract a one-line detail string from a module's get_status() result."""
    if name == 'f1_timing':
        if status.get('connected') and status.get('circuit'):
            detail = status['circuit']
            lap = status.get('lap')
            if lap:
                detail += f' · LAP {lap}'
            return detail
    elif name == 'f1_countdown':
        race = status.get('next_race')
        sess = status.get('next_session')
        if race and sess:
            return f"{race.replace('Grand Prix', 'GP').upper()} · {sess}"
    elif name == 'weather':
        n = status.get('alert_count', 0)
        if n:
            return f'{n} ALERT{"S" if n > 1 else ""}'
    return ''


class EinkPusher:
    """Background thread that pushes serial status payloads to the E-ink display."""

    @staticmethod
    def push_setup_once(port: str, ssid: str, ip: str, password: str = '') -> None:
        """One-shot provisioning payload — no thread required."""
        payload = {
            'mode':     'setup',
            'ssid':     ssid,
            'password': password,
            'ip':       ip,
            'detail':   'Connect to configure WiFi',
        }
        line = (json.dumps(payload, separators=(',', ':')) + '\n').encode()
        try:
            with serial.Serial(port, baudrate=_BAUD, timeout=2) as ser:
                ser.write(line)
        except Exception as exc:
            print(f'[eink] push_setup_once failed: {exc}')

    def __init__(self, port: str, driver: 'DisplayDriver') -> None:
        self._port              = port
        self._driver            = driver
        self._ser: Optional[serial.Serial] = None
        self._stop              = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_sent:        Optional[dict[str, Any]] = None
        self._last_push_t:      float = 0.0
        self._last_reconnect_t: float = 0.0
        self._ip_cache:         str   = ''
        self._ip_cache_t:       float = 0.0

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name='eink-pusher'
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # -------------------------------------------------------------------------

    def _loop(self) -> None:
        while not self._stop.is_set():
            self._ensure_connected()
            if self._ser is not None:
                payload = self._build_payload()
                now     = time.time()
                last    = self._last_sent
                changed = (
                    last is None
                    or payload['mode'] != last['mode']
                    or payload['ip']   != last['ip']
                )
                if changed or (now - self._last_push_t) >= _HEARTBEAT_S:
                    self._push(payload)
            self._stop.wait(1.0)

    def _ensure_connected(self) -> None:
        if self._ser is not None:
            return
        now = time.time()
        if now - self._last_reconnect_t < _RECONNECT_S:
            return
        self._last_reconnect_t = now
        try:
            self._ser = serial.Serial(self._port, baudrate=_BAUD, timeout=1)
            print(f'[eink] connected on {self._port}')
        except Exception as exc:
            print(f'[eink] connect failed ({self._port}): {exc}')

    def _build_payload(self) -> dict[str, Any]:
        mod  = self._driver._module
        fps  = round(self._driver.frame_buffer.fps, 1)
        mode = _MODE_NAMES.get(mod.name, mod.name.upper()) if mod else 'NONE'
        try:
            detail = _build_detail(mod.name, mod.get_status()) if mod else ''
        except Exception:
            detail = ''
        return {
            'mode':   mode,
            'status': 'ok',
            'ip':     self._get_ip(),
            'fps':    fps,
            'uptime': _get_uptime(),
            'detail': detail,
        }

    def _push(self, payload: dict[str, Any]) -> None:
        try:
            line = (json.dumps(payload, separators=(',', ':')) + '\n').encode()
            self._ser.write(line)  # type: ignore[union-attr]
            self._last_sent   = payload
            self._last_push_t = time.time()
        except Exception as exc:
            print(f'[eink] write error: {exc} — will reconnect')
            try:
                self._ser.close()  # type: ignore[union-attr]
            except Exception:
                pass
            self._ser = None

    def _get_ip(self) -> str:
        now = time.time()
        if now - self._ip_cache_t < _IP_TTL:
            return self._ip_cache
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            self._ip_cache = s.getsockname()[0]
            s.close()
        except Exception:
            self._ip_cache = ''
        self._ip_cache_t = now
        return self._ip_cache
