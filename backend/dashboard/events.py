"""Live events for connected Desktop windows (``plugin.imagegen.*``)."""
from __future__ import annotations

import logging
import sys
from typing import Any, Dict

logger = logging.getLogger(__name__)


def announce(event: str, payload: Dict[str, Any]) -> None:
    """Tell connected Desktop windows something changed, so they refetch instead of polling.

    Only the gateway process holds Desktop connections, and it has already loaded
    ``tui_gateway.server``. Anywhere else (CLI, MCP server, tests) this is a no-op:
    importing the gateway there can relaunch the host and kill the job thread.
    """
    if "tui_gateway.server" not in sys.modules:
        return
    try:
        from hermes_cli.plugin_events import broadcast_plugin_event

        broadcast_plugin_event("imagegen", event, payload)
    except (Exception, SystemExit) as exc:  # noqa: BLE001 — an event must never end a job
        logger.debug("%s event not sent: %s", event, exc)
