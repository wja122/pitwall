"""Pitwall Flask admin panel.

create_app(driver, config, config_path) — main factory, call from main.py.

Custom functions defined here:

_get_system_stats() -> dict
    Reads Pi-specific system information:
    - CPU temp from /sys/class/thermal/thermal_zone0/temp (millidegrees → °C)
    - Memory usage from /proc/meminfo (MemTotal / MemAvailable)
    - Uptime from /proc/uptime (first field, seconds)
    - LAN IP via a UDP connect trick (no traffic sent, picks the default-route interface)
    Returns graceful None values on dev machines where these paths don't exist.

_save_config(config, path)
    Writes the in-memory config dict to config.json. Protected by a module-level
    threading.Lock so concurrent POST requests don't interleave writes.

_module_cfg(config, name) -> dict
    Merges per-module config from config.json with any runtime globals that
    modules expect to find in their init dict (e.g. injects multiviewer_host
    into f1_timing config so the module doesn't need to read globals itself).

_build_led_mask(scale, fill) -> np.ndarray
    Precomputes a (HEIGHT*scale × WIDTH*scale) boolean mask. True = inside the
    circular LED emitter; False = black PCB gap. Built once at import time and
    reused by every MJPEG frame. Uses np.ogrid + broadcasting — no Python loop.

_make_led_frame(raw) -> PIL.Image
    Converts a raw 128×192×3 RGB byte buffer to a physically-simulated LED
    panel JPEG for the MJPEG preview stream.
    Steps:
      1. Nearest-neighbour upscale by _SCALE (np.repeat)
      2. Zero out black PCB gaps via _LED_MASK
      3. Gaussian glow/bloom overlay at _GLOW weight to simulate LED bleed
"""
from __future__ import annotations

import io
import json
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
from flask import Flask, Response, jsonify, render_template, request
from PIL import Image, ImageFilter

from display.driver import DisplayDriver, HEIGHT, WIDTH
from modules import registry
from modules.weather.module import WeatherAlert, WeatherModule

# ---------------------------------------------------------------------------
# LED simulation constants
# ---------------------------------------------------------------------------
_SCALE      = 5      # screen pixels per LED
_LED_FILL   = 0.63   # emitter diameter as fraction of pitch
_GLOW       = 0.30   # bleed weight between neighbours
_STREAM_FPS = 15

_PHYS_W_MM = WIDTH  * 3   # 384 mm
_PHYS_H_MM = HEIGHT * 3   # 576 mm


def _build_led_mask(scale: int, fill: float) -> np.ndarray:
    """Boolean mask, True inside LED emitter circle, False in PCB gap."""
    y, x = np.ogrid[:scale, :scale]
    cx = cy = (scale - 1) / 2.0
    r_sq = (scale * fill / 2.0) ** 2
    cell = (x - cx) ** 2 + (y - cy) ** 2 <= r_sq
    return np.tile(cell, (HEIGHT, WIDTH))


_LED_MASK = _build_led_mask(_SCALE, _LED_FILL)


def _make_led_frame(raw: bytes) -> Image.Image:
    """Convert raw RGB bytes → physically-simulated LED panel image."""
    arr = np.frombuffer(raw, dtype=np.uint8).reshape(HEIGHT, WIDTH, 3)
    big = np.repeat(np.repeat(arr, _SCALE, axis=0), _SCALE, axis=1).copy()
    big[~_LED_MASK] = 0
    base = Image.fromarray(big, 'RGB')
    glow = base.filter(ImageFilter.GaussianBlur(radius=_SCALE * 0.6))
    result = np.clip(
        big.astype(np.float32) + np.array(glow, dtype=np.float32) * _GLOW,
        0, 255,
    ).astype(np.uint8)
    return Image.fromarray(result, 'RGB')


# ---------------------------------------------------------------------------
# System stats
# ---------------------------------------------------------------------------

def _get_system_stats() -> dict[str, Any]:
    """Read Pi system info from /sys and /proc. Returns None for unavailable values."""
    stats: dict[str, Any] = {}

    try:
        raw = Path('/sys/class/thermal/thermal_zone0/temp').read_text().strip()
        stats['cpu_temp_c'] = round(int(raw) / 1000, 1)
    except Exception:
        stats['cpu_temp_c'] = None

    try:
        meminfo = Path('/proc/meminfo').read_text()
        mem: dict[str, int] = {}
        for line in meminfo.splitlines():
            parts = line.split()
            if parts[0] in ('MemTotal:', 'MemAvailable:'):
                mem[parts[0]] = int(parts[1])
        total = mem.get('MemTotal:', 0)
        avail = mem.get('MemAvailable:', 0)
        used  = total - avail
        stats['mem_total_mb'] = round(total / 1024)
        stats['mem_used_mb']  = round(used  / 1024)
        stats['mem_pct']      = round(used / total * 100) if total else 0
    except Exception:
        stats['mem_total_mb'] = stats['mem_used_mb'] = stats['mem_pct'] = None

    try:
        uptime_s = float(Path('/proc/uptime').read_text().split()[0])
        h, rem   = divmod(int(uptime_s), 3600)
        m        = rem // 60
        stats['uptime']   = f'{h}h{m:02d}m'
        stats['uptime_s'] = int(uptime_s)
    except Exception:
        stats['uptime'] = stats['uptime_s'] = None

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        stats['ip'] = s.getsockname()[0]
        s.close()
    except Exception:
        stats['ip'] = None

    return stats


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_config_lock = threading.Lock()


def _save_config(config: dict[str, Any], path: Path) -> None:
    """Write config dict to disk, serialised under a lock."""
    with _config_lock:
        path.write_text(json.dumps(config, indent=2))


def _module_cfg(config: dict[str, Any], name: str) -> dict[str, Any]:
    """Merge global config keys into per-module config dict at activation time."""
    cfg = dict(config.get('modules', {}).get(name, {}))
    if name == 'f1_timing' and 'host' not in cfg:
        cfg['host'] = config.get('multiviewer_host', 'localhost')
    if name == 'home':
        cfg['weather_cfg'] = config.get('modules', {}).get('weather', {})
    return cfg


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app(
    driver: DisplayDriver,
    config: dict[str, Any],
    config_path: Path,
) -> Flask:
    """Create the Pitwall Flask admin app.

    Args:
        driver:      DisplayDriver owning the display thread and active module.
        config:      Mutable config dict loaded from config.json. Modified
                     in-place when settings are saved so the running system
                     stays in sync without a restart.
        config_path: Absolute path to config.json for persistence.
    """
    app = Flask(__name__)

    # ------------------------------------------------------------------
    # Index + setup wizard + preview stream
    # ------------------------------------------------------------------

    @app.route('/')
    def index() -> str:
        return render_template(
            'index.html',
            dw=WIDTH, dh=HEIGHT,
            pw=WIDTH * _SCALE, ph=HEIGHT * _SCALE,
            phys_w=_PHYS_W_MM, phys_h=_PHYS_H_MM,
            scale=_SCALE,
        )

    @app.route('/setup')
    def setup_page() -> str:
        return render_template('setup.html')

    @app.route('/api/setup/fields')
    def api_setup_fields() -> Response:
        modules_data = [
            {
                'name':           name,
                'description':    cls.description,
                'fields':         cls.setup_fields(),
                'current_config': config.get('modules', {}).get(name, {}),
            }
            for name, cls in sorted(registry.all_modules().items())
        ]
        return jsonify({
            'setup_complete': config.get('setup_complete', False),
            'active_module':  config.get('active_module', 'clock'),
            'modules':        modules_data,
        })

    @app.route('/api/setup/complete', methods=['POST'])
    def api_setup_complete() -> Response:
        from modules.setup.module import SetupModule  # local import avoids circular
        data = request.get_json(force=True) or {}

        for mod_name, mod_cfg in (data.get('module_configs') or {}).items():
            if registry.get(mod_name) is None:
                continue
            config.setdefault('modules', {})[mod_name] = {
                **config.get('modules', {}).get(mod_name, {}),
                **{k: v for k, v in mod_cfg.items() if v not in (None, '')},
            }

        active = data.get('active_module') or config.get('active_module', 'clock')
        module_cls = registry.get(active)
        if module_cls is not None:
            config['active_module'] = active
            driver.set_module(module_cls(_module_cfg(config, active)))

        config['setup_complete'] = True
        config['show_setup_qr']  = False
        _save_config(config, config_path)
        return jsonify({'ok': True, 'active_module': config['active_module']})

    if driver.is_stub:
        @app.route('/preview/stream')
        def preview_stream() -> Response:
            """MJPEG stream with LED panel physics simulation. Stub mode only."""
            def generate():
                while True:
                    raw = driver.get_preview_frame()
                    img = _make_led_frame(raw)
                    buf = io.BytesIO()
                    img.save(buf, format='JPEG', quality=88)
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n'
                        + buf.getvalue()
                        + b'\r\n'
                    )
                    time.sleep(1.0 / _STREAM_FPS)

            return Response(
                generate(),
                mimetype='multipart/x-mixed-replace; boundary=frame',
            )

    # ------------------------------------------------------------------
    # Status + system
    # ------------------------------------------------------------------

    @app.route('/api/status')
    def api_status() -> Response:
        mod = driver._module
        return jsonify({
            'mode':       mod.name if mod else 'none',
            'fps':        round(driver.frame_buffer.fps, 1),
            'stub':       driver.is_stub,
            'power':      driver._power,
            'brightness': driver._brightness,
        })

    @app.route('/api/system')
    def api_system() -> Response:
        return jsonify(_get_system_stats())

    # ------------------------------------------------------------------
    # Modules + widgets
    # ------------------------------------------------------------------

    @app.route('/api/widgets')
    def api_widgets() -> Response:
        from widgets.registry import all_widgets
        return jsonify([
            {
                'name':              name,
                'description':       cls.description,
                'supported_heights': cls.supported_heights,
            }
            for name, cls in sorted(all_widgets().items())
        ])

    @app.route('/api/modules')
    def api_modules() -> Response:
        active_name = driver._module.name if driver._module else None
        modules = [
            {
                'name':        name,
                'description': cls.description,
                'default_fps': cls.default_fps,
                'is_active':   name == active_name,
            }
            for name, cls in sorted(registry.all_modules().items())
        ]
        return jsonify(modules)

    @app.route('/api/module/<name>/activate', methods=['POST'])
    def api_activate(name: str) -> Response:
        module_cls = registry.get(name)
        if module_cls is None:
            return jsonify({'error': f'unknown module: {name}'}), 404
        driver.set_module(module_cls(_module_cfg(config, name)))
        config['active_module'] = name
        _save_config(config, config_path)
        return jsonify({'active': name})

    # ------------------------------------------------------------------
    # Module config
    # ------------------------------------------------------------------

    @app.route('/api/module/<name>/config', methods=['GET'])
    def api_get_module_config(name: str) -> Response:
        mod = driver._module
        if mod and mod.name == name:
            return jsonify(mod.get_config())
        return jsonify(config.get('modules', {}).get(name, {}))

    @app.route('/api/module/<name>/config', methods=['POST'])
    def api_set_module_config(name: str) -> Response:
        data = request.get_json(force=True) or {}
        config.setdefault('modules', {})[name] = {
            **config.get('modules', {}).get(name, {}),
            **data,
        }
        _save_config(config, config_path)
        mod = driver._module
        if mod and mod.name == name:
            mod.set_config(data)
        return jsonify({'saved': name})

    # ------------------------------------------------------------------
    # Display controls
    # ------------------------------------------------------------------

    @app.route('/api/brightness', methods=['POST'])
    def api_brightness() -> Response:
        val        = (request.get_json(force=True) or {}).get('brightness', 75)
        brightness = max(0, min(100, int(val)))
        driver.set_brightness(brightness)
        config['brightness'] = brightness
        _save_config(config, config_path)
        return jsonify({'brightness': brightness})

    @app.route('/api/power', methods=['POST'])
    def api_power() -> Response:
        val = (request.get_json(force=True) or {}).get('on', True)
        driver.set_power(bool(val))
        return jsonify({'power': bool(val)})

    # ------------------------------------------------------------------
    # Global config
    # ------------------------------------------------------------------

    @app.route('/api/config', methods=['GET'])
    def api_get_config() -> Response:
        safe = {k: v for k, v in config.items() if k != 'wifi_password'}
        return jsonify(safe)

    @app.route('/api/config', methods=['POST'])
    def api_set_config() -> Response:
        data    = request.get_json(force=True) or {}
        ALLOWED = {
            'multiviewer_host', 'multiviewer_auto_switch',
            'multiviewer_hold_seconds', 'gpio_slowdown', 'brightness',
        }
        for k, v in data.items():
            if k in ALLOWED:
                config[k] = v
        _save_config(config, config_path)
        return jsonify({'saved': True})

    # ------------------------------------------------------------------
    # Debug
    # ------------------------------------------------------------------

    @app.route('/api/debug/alert/<kind>', methods=['POST'])
    def api_debug_alert(kind: str) -> Response:
        mod = driver._module
        if not isinstance(mod, WeatherModule):
            return jsonify({'error': 'weather module not active'}), 400

        expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

        alerts: dict[str, WeatherAlert | None] = {
            'watch': WeatherAlert(
                event='Severe Thunderstorm Watch',
                severity='Moderate', urgency='Expected',
                headline='Severe Thunderstorm Watch in effect until this evening',
                expires=expires, damage_threat='', pds=False, certainty='Possible',
            ),
            'stsw': WeatherAlert(
                event='Severe Thunderstorm Warning',
                severity='Severe', urgency='Immediate',
                headline='Severe Thunderstorm Warning — considerable damage threat',
                expires=expires, damage_threat='CONSIDERABLE', pds=False, certainty='Observed',
            ),
            'destructive': WeatherAlert(
                event='Severe Thunderstorm Warning',
                severity='Extreme', urgency='Immediate',
                headline='Severe Thunderstorm Warning — destructive',
                expires=expires, damage_threat='DESTRUCTIVE', pds=False, certainty='Observed',
            ),
            'tornado': WeatherAlert(
                event='Tornado Warning',
                severity='Extreme', urgency='Immediate',
                headline='Tornado Warning in effect',
                expires=expires, damage_threat='', pds=False, certainty='Observed',
            ),
            'pds': WeatherAlert(
                event='Tornado Warning',
                severity='Extreme', urgency='Immediate',
                headline='PARTICULARLY DANGEROUS SITUATION — Tornado Warning',
                expires=expires, damage_threat='', pds=True, certainty='Observed',
            ),
            'flood': WeatherAlert(
                event='Flash Flood Warning',
                severity='Severe', urgency='Immediate',
                headline='Flash Flood Warning — considerable flooding',
                expires=expires, damage_threat='CONSIDERABLE', pds=False, certainty='Observed',
            ),
            'clear': None,
        }

        if kind not in alerts:
            return jsonify({'error': f'unknown kind: {kind}'}), 400

        with mod._lock:
            mod._alerts = [alerts[kind]] if alerts[kind] else []
        return jsonify({'injected': kind})

    return app
