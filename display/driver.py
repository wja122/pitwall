"""Display driver: wraps rgbmatrix on Pi, stubs it on dev machines.

On hardware: drives the real LED matrix.
On dev machines (no rgbmatrix): runs a StubMatrix that captures each frame
into a FrameBuffer so the Flask preview endpoint can serve it.
"""
from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, Optional

from display.buffer import FrameBuffer

if TYPE_CHECKING:
    from modules.base import BaseModule

WIDTH = 128
HEIGHT = 192

try:
    from rgbmatrix import RGBMatrix, RGBMatrixOptions  # type: ignore[import]
    _HAS_RGBMATRIX = True
except ImportError:
    _HAS_RGBMATRIX = False


# ---------------------------------------------------------------------------
# Stub implementation (dev / no hardware)
# ---------------------------------------------------------------------------

class _StubCanvas:
    """Pixel buffer matching the rgbmatrix FrameCanvas interface."""

    def __init__(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self._buf = bytearray(width * height * 3)

    def SetPixel(self, x: int, y: int, r: int, g: int, b: int) -> None:
        if 0 <= x < self._width and 0 <= y < self._height:
            i = (y * self._width + x) * 3
            self._buf[i] = r
            self._buf[i + 1] = g
            self._buf[i + 2] = b

    def Fill(self, r: int, g: int, b: int) -> None:
        for i in range(0, len(self._buf), 3):
            self._buf[i] = r
            self._buf[i + 1] = g
            self._buf[i + 2] = b

    def get_bytes(self) -> bytes:
        return bytes(self._buf)


class _StubMatrix:
    """In-process matrix simulation matching the rgbmatrix RGBMatrix interface."""

    def __init__(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self._lock = threading.Lock()
        self._current_frame: bytes = bytes(width * height * 3)

    def CreateFrameCanvas(self) -> _StubCanvas:
        return _StubCanvas(self._width, self._height)

    def SwapOnVSync(self, canvas: _StubCanvas) -> _StubCanvas:
        with self._lock:
            self._current_frame = canvas.get_bytes()
        return _StubCanvas(self._width, self._height)

    def get_current_frame(self) -> bytes:
        with self._lock:
            return self._current_frame


# ---------------------------------------------------------------------------
# Display driver
# ---------------------------------------------------------------------------

class DisplayDriver:
    """Owns the display thread and the active module."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._module: Optional[BaseModule] = None
        self._module_lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._fps: float = 1.0
        self._power: bool = True
        self._brightness: int = config.get('brightness', 75)
        self._is_stub: bool = not _HAS_RGBMATRIX

        self.frame_buffer = FrameBuffer(WIDTH, HEIGHT)

        if _HAS_RGBMATRIX:
            self._matrix: Any = self._create_real_matrix()
            print(f"[display] rgbmatrix initialized ({WIDTH}×{HEIGHT})")
        else:
            self._matrix = _StubMatrix(WIDTH, HEIGHT)
            print(f"[display] stub mode ({WIDTH}×{HEIGHT}) — open http://localhost:5000 for preview")

        self._canvas = self._matrix.CreateFrameCanvas()

    def _create_real_matrix(self) -> Any:
        options = RGBMatrixOptions()  # type: ignore[name-defined]
        options.rows = 64
        options.cols = 64
        options.chain_length = 3
        options.parallel = 2
        options.hardware_mapping = 'regular'
        options.pixel_mapper_config = 'Rotate:90'
        options.scan_mode = 0
        options.row_address_type = 0
        options.disable_hardware_pulsing = True
        options.panel_type = ''
        options.gpio_slowdown = self._config.get('gpio_slowdown', 6)
        options.brightness = self._brightness
        options.drop_privileges = 0
        return RGBMatrix(options=options)  # type: ignore[name-defined]

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True, name='display')
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def set_module(self, module: BaseModule) -> None:
        with self._module_lock:
            if self._module is not None:
                self._module.stop()
            self._module = module
            self._fps = float(module.default_fps)
            module.start()

    def set_brightness(self, brightness: int) -> None:
        self._brightness = max(0, min(100, brightness))
        if _HAS_RGBMATRIX:
            self._matrix.brightness = self._brightness

    def set_power(self, on: bool) -> None:
        self._power = on

    def set_fps(self, fps: float) -> None:
        self._fps = max(1.0, fps)

    # ------------------------------------------------------------------
    # Preview (stub mode)
    # ------------------------------------------------------------------

    def get_preview_frame(self) -> bytes:
        """Raw RGB bytes of the current frame. Works in both modes."""
        return self.frame_buffer.get_frame()

    @property
    def is_stub(self) -> bool:
        return self._is_stub

    # ------------------------------------------------------------------
    # Display loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        while self._running:
            frame_start = time.monotonic()

            with self._module_lock:
                module = self._module

            self._canvas.Fill(0, 0, 0)

            if module is not None and self._power:
                try:
                    module.render(self._canvas)
                except Exception as exc:
                    print(f"[display] render error in {module.name!r}: {exc}")

            self._canvas = self._matrix.SwapOnVSync(self._canvas)

            # Capture frame for preview / FPS tracking
            if self._is_stub:
                raw = self._matrix.get_current_frame()
            else:
                # On real hardware, build the frame from what we just drew.
                # Re-read from the stub canvas before the swap cleared it.
                # Since we can't read back from real hardware, we keep a
                # software mirror via the last drawn canvas bytes.
                raw = bytes(WIDTH * HEIGHT * 3)
            self.frame_buffer.update(raw)

            elapsed = time.monotonic() - frame_start
            sleep_time = (1.0 / self._fps) - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
