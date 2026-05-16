"""Widget auto-discovery and registry — mirrors modules/registry.py."""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Type

from widgets.base import BaseWidget

_registry: dict[str, Type[BaseWidget]] = {}

_SKIP = frozenset({'base', 'registry'})


def register_widget(cls: Type[BaseWidget]) -> Type[BaseWidget]:
    """Class decorator — registers a widget so HomeModule can find it."""
    _registry[cls.name] = cls
    return cls


def discover() -> None:
    """Import every subpackage under widgets/ to trigger @register_widget calls."""
    widgets_path = Path(__file__).parent
    for _finder, name, _is_pkg in pkgutil.iter_modules([str(widgets_path)]):
        if name not in _SKIP:
            importlib.import_module(f'widgets.{name}')


def get_widget(name: str) -> Type[BaseWidget] | None:
    return _registry.get(name)


def all_widgets() -> dict[str, Type[BaseWidget]]:
    return dict(_registry)
