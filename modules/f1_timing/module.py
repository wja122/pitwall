"""F1 live timing module — pulls data from F1 MultiViewer's GraphQL API."""
from __future__ import annotations

from typing import Any

from display.fonts import F35
from display.renderer import WIDTH, draw_text_centered
from modules.base import BaseModule
from modules.registry import register
from modules.f1_timing.f1mv import F1MVClient
from modules.f1_timing.renderer import F1TimingRenderer


@register
class F1TimingModule(BaseModule):
    """Live F1 timing tower via F1 MultiViewer."""

    name = 'f1_timing'
    description = 'Live F1 timing tower (requires F1MV)'
    default_fps = 25

    def __init__(self, config: dict[str, Any]) -> None:
        self._host = config.get('host', 'localhost')
        self._port = int(config.get('port', 10101))
        self._client   = F1MVClient(host=self._host, port=self._port)
        self._renderer = F1TimingRenderer()
        self._active   = False

    def start(self) -> None:
        self._active = True
        self._client.start()

    def stop(self) -> None:
        self._active = False
        self._client.stop()

    def render(self, canvas: Any) -> None:
        state, error = self._client.get_state()
        if state is None:
            canvas.Fill(0, 0, 0)
            msg = error or 'WAITING FOR F1MV...'
            draw_text_centered(canvas, F35, WIDTH // 2, 92, 60, 60, 60, msg[:24])
            return
        self._renderer.render(canvas, state)

    def get_config(self) -> dict[str, Any]:
        return {'host': self._host, 'port': self._port}

    def set_config(self, cfg: dict[str, Any]) -> None:
        changed = False
        if 'host' in cfg and cfg['host'] != self._host:
            self._host = cfg['host']
            changed = True
        if 'port' in cfg and int(cfg['port']) != self._port:
            self._port = int(cfg['port'])
            changed = True
        if changed:
            self._client.stop()
            self._client = F1MVClient(host=self._host, port=self._port)
            if self._active:
                self._client.start()

    def get_status(self) -> dict[str, Any]:
        state, error = self._client.get_state()
        return {
            'connected': state is not None,
            'error': error,
            'session': state.session_name if state else None,
            'circuit': state.circuit if state else None,
            'lap': f"{state.current_lap}/{state.total_laps}" if state else None,
        }
