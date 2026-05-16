"""HomeModule — clock status bar + configurable widget slots."""
from __future__ import annotations

import threading
from typing import Any, Optional

from display.renderer import WIDTH, draw_hline
from modules.base import BaseModule
from modules.home.clock import CLOCK_H, render_clock
from modules.registry import register

# ── Layout geometry ────────────────────────────────────────────────────────
# Total canvas height = 192.  Clock occupies y=0..79 (80px).
# One separator pixel at y=80 leaves 111px for widgets.
#
# three_tall: two slots of 55px with a 1px separator between them.
#   slot 0: y=81,  h=55  → ends y=135
#   sep:    y=136
#   slot 1: y=137, h=55  → ends y=191
#
# two_tall: one slot of 111px
#   slot 0: y=81,  h=111 → ends y=191

_WIDGET_Y = CLOCK_H + 1   # 81

_LAYOUTS: dict[str, list[tuple[int, int, int, int]]] = {
    'three_tall': [
        (0, _WIDGET_Y,      WIDTH, 55),
        (0, _WIDGET_Y + 56, WIDTH, 55),
    ],
    'two_tall': [
        (0, _WIDGET_Y, WIDTH, 111),
    ],
}

_SEP = (26, 26, 26)


@register
class HomeModule(BaseModule):
    """Clock status bar with two configurable widget slots below."""

    name        = 'home'
    description = 'Clock with configurable info widgets'
    default_fps = 1

    def __init__(self, config: dict[str, Any]) -> None:
        self._clock_mode:  str = config.get('clock_mode', 'tz_utc')
        self._layout:      str = config.get('layout',     'three_tall')
        self._slot_names: dict[str, str] = {
            '0': config.get('slot_0', 'weather'),
            '1': config.get('slot_1', 'f1_countdown'),
        }
        # weather_cfg is injected by _module_cfg so the weather widget
        # gets lat/lon without the user having to configure them twice.
        self._widget_sources: dict[str, dict] = {
            'weather': config.get('weather_cfg', {}),
        }
        self._widgets: dict[str, Any] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._init_widgets()
        for w in self._widgets.values():
            w.start()

    def stop(self) -> None:
        for w in self._widgets.values():
            w.stop()

    def _slot_keys(self) -> list[str]:
        return ['0'] if self._layout == 'two_tall' else ['0', '1']

    def _init_widgets(self) -> None:
        from widgets.registry import get_widget
        self._widgets.clear()
        for slot in self._slot_keys():
            name = self._slot_names.get(slot, '')
            if not name:
                continue
            cls = get_widget(name)
            if cls is None:
                continue
            cfg = self._widget_sources.get(name, {})
            self._widgets[slot] = cls(cfg)

    def _restart_widgets(self) -> None:
        with self._lock:
            for w in self._widgets.values():
                w.stop()
            self._init_widgets()
            for w in self._widgets.values():
                w.start()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(self, canvas: Any) -> None:
        canvas.Fill(0, 0, 0)
        render_clock(canvas, self._clock_mode)

        # Separator between clock and widget zone
        draw_hline(canvas, 0, CLOCK_H, WIDTH, *_SEP)

        slots = _LAYOUTS.get(self._layout, _LAYOUTS['three_tall'])

        if self._layout == 'three_tall' and len(slots) == 2:
            # Separator between the two widget slots
            _, y0, _, h0 = slots[0]
            draw_hline(canvas, 0, y0 + h0, WIDTH, *_SEP)

        with self._lock:
            widgets = dict(self._widgets)

        for i, (sx, sy, sw, sh) in enumerate(slots):
            w = widgets.get(str(i))
            if w is not None:
                w.render(canvas, sx, sy, sw, sh)

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def get_config(self) -> dict[str, Any]:
        from widgets.registry import all_widgets
        widget_opts = [{'value': '', 'label': '(none)'}] + [
            {'value': n, 'label': n.replace('_', ' ').title()}
            for n in sorted(all_widgets())
        ]
        return {
            '__schema__': {
                'clock_mode': {
                    'type':  'select',
                    'label': 'Clock Mode',
                    'options': [
                        {'value': 'tz_utc',  'label': 'TZ + UTC'},
                        {'value': 'tz_only', 'label': 'TZ Only (larger)'},
                    ],
                },
                'layout': {
                    'type':  'select',
                    'label': 'Layout',
                    'options': [
                        {'value': 'three_tall', 'label': 'Two widgets (3-row)'},
                        {'value': 'two_tall',   'label': 'One widget  (2-row)'},
                    ],
                },
                'slot_0': {'type': 'select', 'label': 'Top Widget',    'options': widget_opts},
                'slot_1': {'type': 'select', 'label': 'Bottom Widget', 'options': widget_opts},
            },
            'clock_mode': self._clock_mode,
            'layout':     self._layout,
            'slot_0':     self._slot_names.get('0', ''),
            'slot_1':     self._slot_names.get('1', ''),
        }

    def set_config(self, cfg: dict[str, Any]) -> None:
        new_mode   = cfg.get('clock_mode', self._clock_mode)
        new_layout = cfg.get('layout',     self._layout)
        new_slots  = {
            '0': cfg.get('slot_0', self._slot_names.get('0', '')),
            '1': cfg.get('slot_1', self._slot_names.get('1', '')),
        }

        self._clock_mode = new_mode

        if new_layout != self._layout or new_slots != self._slot_names:
            self._layout     = new_layout
            self._slot_names = new_slots
            self._restart_widgets()

    @classmethod
    def setup_fields(cls) -> list[dict[str, Any]]:
        return [
            {
                'key':      'clock_mode',
                'label':    'Clock Mode',
                'type':     'select',
                'required': False,
                'default':  'tz_utc',
                'options':  [
                    {'value': 'tz_utc',  'label': 'TZ + UTC'},
                    {'value': 'tz_only', 'label': 'TZ only (larger)'},
                ],
            },
            {
                'key':      'layout',
                'label':    'Layout',
                'type':     'select',
                'required': False,
                'default':  'three_tall',
                'options':  [
                    {'value': 'three_tall', 'label': 'Two widgets (3 sections)'},
                    {'value': 'two_tall',   'label': 'One widget (2 sections)'},
                ],
            },
        ]

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            slots = {k: type(v).__name__ for k, v in self._widgets.items()}
        return {
            'clock_mode': self._clock_mode,
            'layout':     self._layout,
            'widgets':    slots,
        }
