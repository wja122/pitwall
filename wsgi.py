"""WSGI entry point — loaded by gunicorn via pitwall-start on post-provisioning boots.

Must use --workers 1: DisplayDriver owns a background thread with shared canvas
state that cannot be forked across multiple workers.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from display.driver import DisplayDriver
from modules import registry
from modules.base import BaseModule
from web.app import create_app

CONFIG_PATH         = Path(__file__).parent / 'config.json'
EXAMPLE_CONFIG_PATH = Path(__file__).parent / 'config.example.json'


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.exists():
        return json.loads(CONFIG_PATH.read_text())
    return json.loads(EXAMPLE_CONFIG_PATH.read_text())


def _module_cfg(config: dict[str, Any], name: str) -> dict[str, Any]:
    cfg = dict(config.get('modules', {}).get(name, {}))
    if name == 'f1_timing' and 'host' not in cfg:
        cfg['host'] = config.get('multiviewer_host', 'localhost')
    return cfg


_config = _load_config()

registry.discover()

_driver = DisplayDriver(_config)

_active_name = _config.get('active_module', 'clock')
_module_cls: type[BaseModule] | None = registry.get(_active_name)
if _module_cls is not None:
    _driver.set_module(_module_cls(_module_cfg(_config, _active_name)))

_driver.start()

application = create_app(_driver, _config, CONFIG_PATH)
