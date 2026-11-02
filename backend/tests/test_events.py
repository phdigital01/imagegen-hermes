"""Live Desktop events must never end the job that sends them."""
from __future__ import annotations

import sys
import types

import pytest

from imagegen_engine import events


def test_announce_is_a_noop_outside_the_gateway(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "tui_gateway.server", raising=False)
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_events", None)  # any import would raise
    events.announce("job.changed", {"id": "x"})


def test_announce_swallows_a_host_relaunch(monkeypatch: pytest.MonkeyPatch) -> None:
    def relaunch(*_args, **_kwargs):
        raise SystemExit(1)  # hermes_bootstrap.RelaunchExit is a SystemExit

    monkeypatch.setitem(sys.modules, "tui_gateway.server", types.ModuleType("tui_gateway.server"))
    monkeypatch.setitem(sys.modules, "hermes_cli.plugin_events",
                        types.SimpleNamespace(broadcast_plugin_event=relaunch))
    events.announce("job.changed", {"id": "x"})
