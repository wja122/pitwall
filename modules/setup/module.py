"""SetupModule — QR code display during first-boot configuration.

Not registered with @register. Activated explicitly by wsgi.py when
setup_complete is false or show_setup_qr is true.
"""
from __future__ import annotations

import socket
from typing import Any

import qrcode  # type: ignore[import]

from display.fonts import F35
from display.renderer import (
    HEIGHT, WIDTH,
    draw_hline, draw_text_centered, draw_text_centered_scaled,
    fill_rect,
)
from modules.base import BaseModule

# Layout constants (all y values are canvas row offsets)
_CX          = WIDTH // 2
_Y_TITLE     = 20   # "PITWALL" scale-2 text (10 px tall)
_Y_SUBTITLE  = 34   # "SCAN TO SETUP" text   (5 px tall)
_Y_SEP       = 43   # 1-px separator
_Y_QR        = 47   # top of QR block
_QR_SCALE    = 4    # LED pixels per QR module
_Y_IP        = 169  # IP address text below QR


def _get_ip() -> str | None:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


def _build_matrix(url: str) -> list[list[bool]]:
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    return qr.get_matrix()


class SetupModule(BaseModule):
    """Displays a scannable QR code on the LED panel during setup."""

    name        = 'setup'
    description = 'First-time configuration'
    default_fps = 1

    def __init__(self) -> None:
        self._ip:     str | None             = None
        self._url:    str | None             = None
        self._matrix: list[list[bool]] | None = None

    def start(self) -> None:
        self._refresh()

    def stop(self) -> None:
        pass

    def _refresh(self) -> None:
        """Re-check IP and regenerate QR only if it changed."""
        ip = _get_ip()
        if ip == self._ip:
            return
        self._ip = ip
        if ip:
            self._url = f'http://{ip}/setup'
            self._matrix = _build_matrix(self._url)
        else:
            self._url = None
            self._matrix = None

    def render(self, canvas: Any) -> None:
        canvas.Fill(0, 0, 0)
        self._refresh()

        # "PITWALL" in red, scale 2
        draw_text_centered_scaled(canvas, F35, _CX, _Y_TITLE,
                                  232, 0, 45, 'PITWALL', 2)

        # Instruction text
        draw_text_centered(canvas, F35, _CX, _Y_SUBTITLE,
                           100, 100, 100, 'SCAN TO SETUP')

        draw_hline(canvas, 0, _Y_SEP, WIDTH, 28, 28, 28)

        if self._matrix is not None:
            self._draw_qr(canvas)
            draw_text_centered(canvas, F35, _CX, _Y_IP,
                               70, 70, 70, self._ip or '')
        else:
            draw_text_centered(canvas, F35, _CX, HEIGHT // 2,
                               80, 80, 80, 'CONNECTING...')

    def _draw_qr(self, canvas: Any) -> None:
        matrix = self._matrix
        assert matrix is not None
        size       = len(matrix)
        pixel_size = size * _QR_SCALE
        x_off      = (WIDTH - pixel_size) // 2

        # White background so the quiet zone is visible (improves scannability)
        fill_rect(canvas, x_off, _Y_QR, pixel_size, pixel_size, 255, 255, 255)

        # Dark modules drawn black over the white background
        for row_idx, row in enumerate(matrix):
            for col_idx, dark in enumerate(row):
                if dark:
                    fill_rect(canvas,
                              x_off + col_idx * _QR_SCALE,
                              _Y_QR  + row_idx * _QR_SCALE,
                              _QR_SCALE, _QR_SCALE,
                              0, 0, 0)

    def get_config(self) -> dict[str, Any]:
        return {}

    def set_config(self, cfg: dict[str, Any]) -> None:
        pass

    def get_status(self) -> dict[str, Any]:
        return {'ip': self._ip, 'url': self._url}
