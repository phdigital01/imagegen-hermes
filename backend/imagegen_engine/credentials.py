"""Provider credentials, resolved only through the Hermes secret scope.

Keys are declared as ``config_schema`` secrets in ``plugin.yaml`` and edited in
Hermes Settings -> Plugins. The plugin never reads or writes ``.env`` itself.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

FAL_ENV = ("FAL_KEY", "FAL_API_KEY")
MAGNIFIC_ENV = ("MAGNIFIC_API_KEY",)
VERTEX_ENV = ("VERTEX_API_KEY",)
VERTEX_PROJECT_ENV = ("VERTEX_PROJECT",)
LOCAL_ENV = ("IMAGEGEN_LOCAL_SERVER_KEY",)


def _get_secret(name: str) -> Optional[str]:
    try:
        from agent.secret_scope import get_secret
    except ImportError:  # outside Hermes (unit tests): plain process environment
        return os.environ.get(name)
    try:
        return get_secret(name)
    except Exception as exc:  # noqa: BLE001 — fail closed on an unscoped read
        logger.warning("credential %s unavailable: %s", name, type(exc).__name__)
        return None


def read(names: tuple[str, ...]) -> str:
    """First non-empty secret among ``names``; empty string when none is set."""
    for name in names:
        value = (_get_secret(name) or "").strip()
        if value:
            return value
    return ""


def fal_key() -> str:
    return read(FAL_ENV)


def magnific_key() -> str:
    return read(MAGNIFIC_ENV)


def vertex_key() -> str:
    return read(VERTEX_ENV)


def vertex_project() -> str:
    return read(VERTEX_PROJECT_ENV)


def local_key() -> str:
    """Token for a local image server that asks for one; most do not."""
    return read(LOCAL_ENV)
