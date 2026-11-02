"""Hermes image providers as they behave at runtime (found in the 2026-10-27 paid run)."""
from __future__ import annotations

import sys
import types

import pytest

from imagegen_engine import gen_service, image_input


def test_generated_images_cache_is_an_allowed_source(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Hermes saves provider output in cache/generated/images; the gallery must accept it."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    for sub in ("generated/images", "images"):
        image = tmp_path / "cache" / sub / "out.png"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
        assert image_input.is_allowed_local_path(image)
        assert image_input.resolve_image_source(str(image))[0] == "bytes"
    assert not image_input.is_allowed_local_path(tmp_path / "cache" / "other.png")


def test_provider_that_ignores_the_requested_model_is_recorded_as_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenAI Codex uses the model set in Hermes; the result names that one and says so."""

    class _Codex:
        def is_available(self) -> bool:
            return True

        def capabilities(self) -> dict:
            return {"modalities": ["text"]}

        def list_models(self) -> list:
            return [{"id": "gpt-image-2-low"}, {"id": "gpt-image-2-high"}]

        def generate(self, prompt, aspect_ratio="square", **kwargs):
            return {"success": True, "image": "https://result.example/out.png", "model": "gpt-image-2-high"}

    registry = types.ModuleType("agent.image_gen_registry")
    registry.get_provider = lambda name: _Codex() if name == "openai-codex" else None
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.image_gen_registry", registry)

    result = gen_service.generate_text_to_image(provider="openai-codex", model="gpt-image-2-low", prompt="a mug")
    assert result["model"] == "gpt-image-2-high"
    assert "gpt-image-2-high" in result["warnings"][0] and "gpt-image-2-low" in result["warnings"][0]

    same = gen_service.generate_text_to_image(provider="openai-codex", model="gpt-image-2-high", prompt="a mug")
    assert same["model"] == "gpt-image-2-high" and same["warnings"] == []


def test_codex_gets_the_shape_in_writing_and_reports_what_it_changed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Codex route ignores the size field but follows a shape stated in the prompt."""
    sent = []

    class _Codex:
        def is_available(self) -> bool:
            return True

        def capabilities(self) -> dict:
            return {"modalities": ["text"]}

        def list_models(self) -> list:
            return [{"id": "gpt-image-2-high"}]

        def generate(self, prompt, aspect_ratio="square", **kwargs):
            sent.append((prompt, aspect_ratio))
            return {"success": True, "image": "https://result.example/out.png", "model": "gpt-image-2-high",
                    "requested_size": "1024x1536", "pixel_size": "1312x1199",
                    "quality": "high", "reported_quality": "low"}

    registry = types.ModuleType("agent.image_gen_registry")
    registry.get_provider = lambda name: _Codex()
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.image_gen_registry", registry)

    result = gen_service.generate_text_to_image(
        provider="openai-codex", model="gpt-image-2-high", prompt="a mug", aspect_ratio="2:3")
    assert sent[-1][1] == "portrait" and sent[-1][0].startswith("Use gpt-image-2 at high quality.\n\na mug\n\n") and "2:3" in sent[-1][0]
    assert any("1312x1199 instead of 1024x1536" in w for w in result["warnings"])
    assert any("quality low instead of high" in w for w in result["warnings"])

    gen_service.generate_text_to_image(provider="xai", model="gpt-image-2-high", prompt="a mug", aspect_ratio="2:3")
    assert sent[-1][0] == "a mug"
