"""Contract tests for ImageGen as a Hermes ``image_gen`` provider."""

from __future__ import annotations

import pytest

pytest.importorskip("agent.image_gen_provider")

from dashboard import chat_provider, generation_artifacts, providers_catalog  # noqa: E402

_PROVIDERS = [
    {"name": "fal", "display_name": "FAL.ai", "available": True, "recommended": True,
     "default_model": "fal-ai/flux-2-pro", "models": [{"id": "fal-ai/flux-2-pro", "display": "FLUX 2 Pro"},
                                                      {"id": "fal-ai/nano-banana-2", "display": "Nano Banana 2"}]},
    {"name": "openai", "display_name": "OpenAI", "available": False, "models": [{"id": "gpt-image-2"}]},
]


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list:
    seen: list = []
    monkeypatch.setattr(providers_catalog, "_list_providers", lambda: [dict(p) for p in _PROVIDERS])

    def fake_job(body):
        seen.append(body)
        return lambda job: {"images": ["/tmp/out.png"], "gallery_ids": [f"{job.id}-0"]}

    monkeypatch.setattr(generation_artifacts, "build_generation_job", fake_job)
    monkeypatch.setattr(providers_catalog, "_hermes_image_setting", lambda key: "")
    return seen


def test_generate_uses_the_start_provider_and_reports_the_gallery_entry(calls: list) -> None:
    result = chat_provider.ImageGenChatProvider().generate("a red cup", "portrait")
    assert result["success"] is True
    assert result["provider"] == "imagegen" and result["via"] == "fal"
    assert calls[0]["model"] == "fal-ai/flux-2-pro" and calls[0]["aspectRatio"] == "9:16"
    assert result["gallery_id"].startswith("chat")
    assert result["imagegen_card"] == f'::imagegen-image{{id="{result["gallery_id"]}"}}'


def test_generate_follows_the_model_picked_for_imagegen(calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(providers_catalog, "_hermes_image_setting",
                        lambda key: "fal-ai/nano-banana-2" if key == "model" else "imagegen")
    chat_provider.ImageGenChatProvider().generate("a red cup")
    assert calls[0]["model"] == "fal-ai/nano-banana-2"


def test_models_list_only_usable_providers(calls: list) -> None:
    ids = [m["id"] for m in chat_provider.ImageGenChatProvider().list_models()]
    assert ids == ["fal-ai/flux-2-pro", "fal-ai/nano-banana-2"]


def test_without_a_usable_provider_the_agent_gets_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(providers_catalog, "_list_providers", lambda: [])
    monkeypatch.setattr(providers_catalog, "_hermes_image_setting", lambda key: "")
    provider = chat_provider.ImageGenChatProvider()
    assert provider.is_available() is False
    result = provider.generate("a red cup")
    assert result["success"] is False and result["error_type"] == "not_configured"
