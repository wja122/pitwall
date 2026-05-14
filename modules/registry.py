"""Module auto-discovery and registry.

Modules register themselves with the @register decorator.
discover() walks the modules/ package and imports every subpackage,
triggering those decorators.
"""
from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Type

from modules.base import BaseModule

_registry: dict[str, Type[BaseModule]] = {}

_SKIP = frozenset({'base', 'registry'})


def register(cls: Type[BaseModule]) -> Type[BaseModule]:
    """Class decorator — registers a module so the system can find it."""
    _registry[cls.name] = cls
    return cls


def discover() -> None:
    """Import every subpackage under modules/ to trigger @register calls."""
    modules_path = Path(__file__).parent
    for _finder, name, _is_pkg in pkgutil.iter_modules([str(modules_path)]):
        if name not in _SKIP:
            importlib.import_module(f'modules.{name}')


def get(name: str) -> Type[BaseModule] | None:
    return _registry.get(name)


def all_modules() -> dict[str, Type[BaseModule]]:
    return dict(_registry)
