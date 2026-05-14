"""Thread-safe frame buffer for preview capture and FPS tracking."""
from __future__ import annotations

import threading
import time


class FrameBuffer:
    """Stores the most-recently rendered frame as raw RGB bytes.

    The display thread writes via update(); the Flask preview thread reads
    via get_frame().  Dimensions must match the display (WIDTH × HEIGHT × 3).
    """

    def __init__(self, width: int, height: int) -> None:
        self._width = width
        self._height = height
        self._lock = threading.Lock()
        self._frame: bytes = bytes(width * height * 3)
        self._frame_time: float = 0.0
        self._fps: float = 0.0
        self._last_fps_time: float = time.monotonic()
        self._frame_count: int = 0

    def update(self, raw_rgb: bytes) -> None:
        """Called by display thread after each SwapOnVSync."""
        now = time.monotonic()
        with self._lock:
            self._frame = raw_rgb
            self._frame_time = now
            self._frame_count += 1
            elapsed = now - self._last_fps_time
            if elapsed >= 1.0:
                self._fps = self._frame_count / elapsed
                self._frame_count = 0
                self._last_fps_time = now

    def get_frame(self) -> bytes:
        with self._lock:
            return self._frame

    @property
    def fps(self) -> float:
        with self._lock:
            return self._fps

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height
