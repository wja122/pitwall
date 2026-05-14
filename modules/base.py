"""BaseModule abstract class — every display module must subclass this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseModule(ABC):
    """Contract every Pitwall module must satisfy.

    The display thread calls render() at the module's target FPS.
    All other methods may be called from Flask threads — implementations
    must be thread-safe.
    """

    name: str
    description: str
    default_fps: int

    @abstractmethod
    def start(self) -> None:
        """Called when this module becomes active."""

    @abstractmethod
    def stop(self) -> None:
        """Called when this module is deactivated."""

    @abstractmethod
    def render(self, canvas: Any) -> None:
        """Draw one frame to canvas.  Called from the display thread."""

    @abstractmethod
    def get_config(self) -> dict[str, Any]:
        """Return the current config schema for the web UI."""

    @abstractmethod
    def set_config(self, cfg: dict[str, Any]) -> None:
        """Apply config pushed from the web UI."""

    @abstractmethod
    def get_status(self) -> dict[str, Any]:
        """Return health/status dict for the web UI dashboard."""
