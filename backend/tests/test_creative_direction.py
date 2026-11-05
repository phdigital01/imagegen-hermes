"""Prompt direction must respect manual controls and the model catalog."""
import json

import pytest

from imagegen_engine import llm_service
from imagegen_engine.errors import ImageGenError


def test_direction_filters_manual_controls_and_validates_catalog(monkeypatch):
    options = {"format": ["1:1", "16:9"], "style": ["illustration"]}
    manual = {"style": "illustration"}

    def complete(system, user):
        request = json.loads(user)
        assert request["description"] == "Landscape"
        assert request["manual"] == manual
        return json.dumps({"prompt": "A painted landscape", "direction": {"format": "16:9", "style": "illustration"}})

    monkeypatch.setattr(llm_service, "_llm_call", complete)
    assert llm_service.suggest_direction("Landscape", "Base", "model", options, manual) == {
        "result": "A painted landscape", "direction": {"format": "16:9"}}
    monkeypatch.setattr(llm_service, "_llm_call", lambda *args: '{"prompt":"x","direction":{"format":"9:16"}}')
    with pytest.raises(ImageGenError):
        llm_service.suggest_direction("Landscape", "Base", "model", options, manual)
