"""BaseWidget — contract every Home module widget must satisfy."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseWidget(ABC):
    """Renders into a sub-region of the Home module canvas.

    Unlike full-screen modules, widgets receive explicit (x, y, w, h) bounds
    and must confine all drawing to that rectangle.  They manage their own
    background data threads internally.

    Class attributes
    ----------------
    name            Registry key, also used for config lookup.
    description     Shown in the web UI widget picker.
    supported_heights
        Pixel heights this widget can render at. Always a subset of the
        layout slot heights defined in HomeModule: 55 (three-tall) and/or
        111 (two-tall).
    """

    name:              str
    description:       str
    supported_heights: list[int]

    @abstractmethod
    def start(self) -> None:
        """Called when the Home module becomes active."""

    @abstractmethod
    def stop(self) -> None:
        """Called when the Home module is deactivated or the slot is reconfigured."""

    @abstractmethod
    def render(self, canvas: Any, x: int, y: int, w: int, h: int) -> None:
        """Draw one frame into the (x, y, w, h) bounding box.

        Called from the display thread — must be thread-safe and non-blocking.
        """

    @classmethod
    def setup_fields(cls) -> list[dict[str, Any]]:
        """Field descriptors for the setup wizard (same schema as BaseModule)."""
        return []
