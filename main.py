"""Pitwall entry point.

Starts the display driver, discovers modules, activates the configured module,
and serves the admin web panel.  On dev machines without rgbmatrix the driver
runs in stub mode; open http://localhost:5000 for the admin panel and preview.

On first boot (provisioning_complete == false in config), runs AP setup mode
instead: brings up the PITWALL hotspot, shows setup instructions on the matrix,
and serves a captive portal on port 80 for WiFi credential entry.
"""
from __future__ import annotations

import json
import signal
import sys
from pathlib import Path
from typing import Any

from display.driver import DisplayDriver
from display.fonts import F35, F57
from display.renderer import (
    draw_text_centered,
    draw_text_centered_scaled,
    fill_rect,
)
from eink.serial_push import EinkPusher
from modules import registry
from modules.base import BaseModule
from provisioning.ap_mode import APMode
from provisioning.captive_portal import create_portal_app
from provisioning import wifi_setup
from web.app import create_app

CONFIG_PATH         = Path(__file__).parent / 'config.json'
EXAMPLE_CONFIG_PATH = Path(__file__).parent / 'config.example.json'


def load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return json.loads(EXAMPLE_CONFIG_PATH.read_text())


def _module_cfg(config: dict[str, Any], name: str) -> dict[str, Any]:
    """Build per-module config, injecting global keys where relevant."""
    cfg = dict(config.get('modules', {}).get(name, {}))
    if name == 'f1_timing' and 'host' not in cfg:
        cfg['host'] = config.get('multiviewer_host', 'localhost')
    return cfg


# ---------------------------------------------------------------------------
# Provisioning setup display
# ---------------------------------------------------------------------------

class SetupModule(BaseModule):
    """Renders WiFi setup instructions on the LED matrix during AP mode."""

    name        = 'setup'
    description = 'AP provisioning screen'
    default_fps = 2

    def start(self) -> None: pass
    def stop(self)  -> None: pass
    def get_config(self) -> dict[str, Any]: return {}
    def set_config(self, cfg: dict[str, Any]) -> None: pass
    def get_status(self) -> dict[str, Any]: return {}

    def render(self, canvas: Any) -> None:
        mid = 64

        # Red header bar
        fill_rect(canvas, 0, 0, 128, 6, 225, 6, 0)

        # "PITWALL" — F57 × 3 (123px wide, 21px tall), centered
        draw_text_centered_scaled(canvas, F57, mid, 10, 255, 255, 255, 'PITWALL', 3)

        # "SETUP MODE" — F35, dim
        draw_text_centered(canvas, F35, mid, 36, 150, 150, 150, 'SETUP MODE')

        fill_rect(canvas, 8, 46, 112, 1, 55, 55, 55)

        # WiFi join instruction
        draw_text_centered(canvas, F35, mid, 52, 110, 110, 110, 'JOIN WIFI:')
        draw_text_centered(canvas, F57, mid, 62, 255, 255, 255, 'PITWALL')

        fill_rect(canvas, 8, 76, 112, 1, 55, 55, 55)

        # IP address to visit
        draw_text_centered(canvas, F35, mid, 82, 110, 110, 110, 'THEN VISIT:')
        draw_text_centered(canvas, F57, mid, 92, 80, 220, 180, '192.168.4.1')

        draw_text_centered(canvas, F35, mid, 108, 90, 90, 90, 'TO CONFIGURE')


# ---------------------------------------------------------------------------
# Provisioning orchestrator
# ---------------------------------------------------------------------------

def run_provisioning(config: dict[str, Any], config_path: Path) -> None:
    """Scan networks, start AP, show setup screen, serve captive portal.

    Blocks until the Pi reboots (on successful WiFi connection) or until
    the process is killed.  Failed connection attempts restart the AP and
    surface the error on the portal's next page load.
    """

    SSID = 'PITWALL'
    GATEWAY = '10.3.3.3'

    print('[provisioning] starting AP setup mode')

    networks = wifi_setup.scan_wifi_networks()
    print(f'[provisioning] {len(networks)} network(s) found')

    ap = APMode()
    ap.start()
    print(f'[provisioning] AP up — SSID: {SSID}  gateway: {GATEWAY}')

    driver = DisplayDriver(config)
    driver.set_module(SetupModule())
    driver.start()

    EinkPusher.push_setup_once(config.get('eink_port', '/dev/ttyACM0'), SSID, GATEWAY)

    def on_connect(ssid: str, password: str) -> None:
        print(f'[provisioning] trying {ssid!r} (timeout 20s)')
        ap.stop()
        try:
            wifi_setup.connect_and_reboot(ssid, password, config_path)
        except RuntimeError as exc:
            print(f'[provisioning] connection failed: {exc} — restarting AP')
            ap.start()
            raise  # portal catches this, stores it for next GET /

    portal = create_portal_app(on_connect=on_connect, networks=networks)
    print('[provisioning] captive portal running on :80')
    portal.run(host='0.0.0.0', port=80, debug=False, use_reloader=False)


# ---------------------------------------------------------------------------
# Normal startup
# ---------------------------------------------------------------------------

def main() -> None:
    config = load_config()

    if not config.get('provisioning_complete', False):
        run_provisioning(config, CONFIG_PATH)
        return  # unreachable — ends in reboot or process kill

    registry.discover()

    driver = DisplayDriver(config)

    active_name = config.get('active_module', 'clock')
    module_cls  = registry.get(active_name)
    if module_cls is not None:
        driver.set_module(module_cls(_module_cfg(config, active_name)))
        print(f'[main] active module: {active_name}')
    else:
        print(f'[main] no module named {active_name!r} found — display will be blank')

    driver.start()

    pusher = EinkPusher(config.get('eink_port', '/dev/ttyACM0'), driver)
    pusher.start()

    app = create_app(driver, config, CONFIG_PATH)

    def _shutdown(sig: int, _frame: Any) -> None:
        print('\n[main] shutting down')
        pusher.stop()
        driver.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    print('[main] admin panel at http://localhost:5000')
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


if __name__ == '__main__':
    main()
