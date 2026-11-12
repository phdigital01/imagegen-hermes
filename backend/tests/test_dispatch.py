"""Dispatch tests for the text-to-image provider registry (gen_service).

Covers the three acceptance points of the registry refactor:
(a) every backend in ``_PROVIDER_BACKENDS`` accepts the shared keyword-only
    signature;
(b) a provider that is not in the registry falls back to the registered /
    FAL path;
(c) every backend returns the mandatory contract keys
    (images, provider, model, modality, references_used, cost_estimate),
    with the transport stubbed via monkeypatch (no network, no CLI).
"""

from __future__ import annotations

import inspect
import subprocess
import sys
import types
from pathlib import Path
from typing import Any, Dict

import pytest

from imagegen_engine import gen_service

# The full keyword set the dispatcher passes to a registry backend.
_COMMON_KWARGS: Dict[str, Any] = {
    "provider": "magnific",
    "model": "fal-ai/magnific/image-to-image",
    "prompt": "a red bicycle",
    "aspect_ratio": "4:5",
    "seed": None,
    "negative_prompt": None,
    "num_images": 1,
    "resolution": "1K",
    "reference_images": None,
    "cancel": None,
}

_CONTRACT_KEYS = {
    "images",
    "provider",
    "model",
    "modality",
    "references_used",
    "cost_estimate",
}


# ---------------------------------------------------------------------------
# (a) Shared keyword-only signature
# ---------------------------------------------------------------------------


def test_registry_backends_share_the_common_signature() -> None:
    """Every registered backend binds the dispatcher's full kwarg set."""
    backends = list(gen_service._PROVIDER_BACKENDS.values())
    assert backends, "the provider registry must not be empty"

    signatures = [inspect.signature(b) for b in backends]
    expected = [p.name for p in signatures[0].parameters.values()]
    for backend, sig in zip(backends, signatures):
        names = list(sig.parameters.values())
        assert [p.name for p in names] == expected, (
            f"{backend.__name__} diverges from the shared signature"
        )
        # keyword-only contract: no positional parameters after the `*`
        assert all(p.kind is inspect.Parameter.KEYWORD_ONLY for p in names)
        # the dispatcher's call must bind without error
        sig.bind(**_COMMON_KWARGS)


def test_registry_contains_exactly_the_direct_providers() -> None:
    assert set(gen_service._PROVIDER_BACKENDS) == {"magnific", "vertex", "local"}


# ---------------------------------------------------------------------------
# (b) Unknown providers fall back to the registered / FAL path
# ---------------------------------------------------------------------------


def test_unknown_provider_routes_to_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []

    def fake_fallback(**kwargs):
        calls.append(kwargs)
        return {"images": ["https://cdn.example/out.png"], "provider": "ghost", "model": "m"}

    monkeypatch.setattr(gen_service, "_generate_via_registered_or_fal", fake_fallback)

    result = gen_service.generate_text_to_image(
        provider="totally-unknown",
        model="m",
        prompt="a red bicycle",
    )

    assert calls, "an unregistered provider must reach the fallback path"
    assert calls[0]["provider"] == "totally-unknown"
    assert result["provider"] == "ghost"
    assert result["images"] == ["https://cdn.example/out.png"]
    # the dispatcher normalizes the fallback result to the contract shape
    assert result["modality"] == "text"
    assert result["references_used"] == 0
    assert result["cost_estimate"] is None


def test_fal_provider_routes_to_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []

    def fake_fallback(**kwargs):
        calls.append(kwargs)
        return {"images": ["https://cdn.example/fal.png"], "provider": "fal", "model": "m"}

    monkeypatch.setattr(gen_service, "_generate_via_registered_or_fal", fake_fallback)

    result = gen_service.generate_text_to_image(
        provider="fal",
        model="fal-ai/flux-2-pro",
        prompt="a red bicycle",
    )

    assert calls and calls[0]["provider"] == "fal"
    assert result["provider"] == "fal"


def test_nous_is_served_by_the_registered_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ImageGen has no Nous backend of its own: Hermes's registered provider serves it."""
    calls: list = []

    def fake_fallback(**kwargs):
        calls.append(kwargs)
        return {"images": ["https://cdn.example/nous.png"], "provider": "nous", "model": "x"}

    monkeypatch.setattr(gen_service, "_generate_via_registered_or_fal", fake_fallback)

    result = gen_service.generate_text_to_image(
        provider="nous",
        model="any-model",
        prompt="a red bicycle",
    )

    assert calls, "nous must reach the registered provider"
    assert result["provider"] == "nous"
    assert result["images"] == ["https://cdn.example/nous.png"]


def test_fal_without_key_runs_through_hermes_fal_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a FAL key, ImageGen never builds a gateway client: Hermes's fal
    provider generates (it picks the Nous managed gateway for entitled accounts)."""
    from imagegen_engine import billing, providers_catalog

    calls: list = []

    class _HermesFal:
        name = "fal"

        def is_available(self) -> bool:
            return True

        def list_models(self) -> list:
            return []

        def generate(self, **kwargs):
            calls.append(kwargs)
            return {"success": True, "image": "https://cdn.example/fal.png", "model": "fal-ai/flux-2-pro"}

    registry = types.ModuleType("agent.image_gen_registry")
    registry.get_provider = lambda name: _HermesFal() if name == "fal" else None
    monkeypatch.setitem(sys.modules, "agent", types.ModuleType("agent"))
    monkeypatch.setitem(sys.modules, "agent.image_gen_registry", registry)
    monkeypatch.setattr(providers_catalog, "_ensure_providers_registered", lambda: None)
    monkeypatch.setattr(gen_service, "_fal_key", lambda: None)
    monkeypatch.setattr(billing, "run", lambda provider, model, estimate, operation, **_: operation())

    result = gen_service.generate_text_to_image(provider="fal", model="fal-ai/flux-2-pro", prompt="a red bicycle")

    assert calls and calls[0]["prompt"].startswith("a red bicycle")
    assert result["provider"] == "fal"
    assert result["images"] == ["https://cdn.example/fal.png"]


def test_fal_upload_without_key_names_the_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from imagegen_engine.errors import ImageGenError

    monkeypatch.setattr(gen_service, "_fal_key", lambda: None)
    with pytest.raises(ImageGenError) as exc_info:
        gen_service.fal_upload_image("data:image/png;base64,AAAA")
    assert exc_info.value.code == "provider.unavailable"
    assert "FAL key" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Dispatcher → backend wiring + normalization
# ---------------------------------------------------------------------------


def test_registry_provider_dispatches_to_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list = []

    def fake_backend(**kwargs):
        calls.append(kwargs)
        return {"images": ["https://cdn.example/x.png"], "provider": "magnific", "model": "m"}

    monkeypatch.setitem(gen_service._PROVIDER_BACKENDS, "magnific", fake_backend)

    result = gen_service.generate_text_to_image(
        provider="magnific",
        model="m",
        prompt="a red bicycle",
        reference_images=["ref-a.png", "ref-b.png"],
    )

    assert calls, "the registry backend must be invoked"
    assert calls[0]["provider"] == "magnific"
    assert calls[0]["model"] == "m"
    assert calls[0]["reference_images"] == ["ref-a.png", "ref-b.png"]
    assert calls[0]["aspect_ratio"] == "1:1"
    # dispatcher fills the contract keys the backend left out
    assert result["modality"] == "image"
    assert result["references_used"] == 2
    assert result["cost_estimate"] is None


# ---------------------------------------------------------------------------
# (c) Backend contract with stubbed transport
# ---------------------------------------------------------------------------


def test_magnific_backend_returns_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    from imagegen_engine import magnific_api

    monkeypatch.setattr(magnific_api, "generate", lambda model, prompt, **kwargs: {
        "images": ["https://cdn.example/magnific.png"],
        "provider": "magnific", "model": model,
    })

    result = gen_service._generate_magnific(
        model="mystic",
        prompt="a red bicycle",
        aspect_ratio="1:1",
    )

    assert _CONTRACT_KEYS <= set(result)
    assert result["provider"] == "magnific"
    assert result["model"] == "mystic"
    assert result["images"] == ["https://cdn.example/magnific.png"]
    assert result["modality"] == "text"
    assert result["references_used"] == 0
    assert result["cost_estimate"] is None


def test_mystic_backend_rejects_references() -> None:
    """Mystic remains text-only even though other Magnific models accept refs."""
    with pytest.raises(RuntimeError) as exc_info:
        gen_service._generate_magnific(
            model="mystic",
            prompt="a red bicycle",
            reference_images=["ref.png"],
        )
    assert exc_info.value.code == "refs.model_unsupported"
    assert exc_info.value.params == {"model": "mystic", "provider": "magnific"}


def test_vertex_backend_sends_shape_size_and_references(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import json

    from imagegen_engine import vertex_api

    monkeypatch.setattr(vertex_api, "credentials", lambda: ("test-key", "my-project"))
    monkeypatch.setattr(gen_service.store, "reserve_spend", lambda *args, **kwargs: "r1")
    monkeypatch.setattr(gen_service.store, "settle_spend", lambda *args, **kwargs: None)
    monkeypatch.setattr(gen_service, "prepare_reference_sources", lambda provider, model, refs, max_refs: refs)
    reference = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    monkeypatch.setattr(gen_service.store, "fetch_image_bytes", lambda ref: reference)
    sent: list = []

    def fake_urlopen(request, timeout):
        sent.append(request)
        reply = {"candidates": [{"content": {"parts": [{"inlineData": {"mimeType": "image/png", "data": "QUJD"}}]}}]}
        return io.BytesIO(json.dumps(reply).encode())

    monkeypatch.setattr(vertex_api, "urlopen", fake_urlopen)

    result = gen_service._generate_vertex(
        model="gemini-nano-banana-2.1", prompt="a red bicycle", aspect_ratio="4:5",
        resolution="2K", reference_images=["ref.png"],
    )

    request = sent[0]
    body = json.loads(request.data)
    assert request.full_url.endswith(
        "/projects/my-project/locations/global/publishers/google/models/gemini-nano-banana-2.1:generateContent")
    assert request.get_header("X-goog-api-key") == "test-key" and "test-key" not in request.full_url
    assert body["generationConfig"]["imageConfig"] == {"imageSize": "2K", "aspectRatio": "4:5"}
    assert body["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "image/png"
    assert body["contents"][0]["parts"][-1] == {"text": "a red bicycle"}
    assert _CONTRACT_KEYS <= set(result)
    assert result["images"] == ["data:image/png;base64,QUJD"]
    assert result["provider"] == "vertex" and result["references_used"] == 1


def test_vertex_reports_why_no_image_came_back(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import json

    from imagegen_engine import vertex_api

    monkeypatch.setattr(vertex_api, "credentials", lambda: ("test-key", ""))
    reply = {"candidates": [{"finishReason": "IMAGE_SAFETY", "content": {"parts": []}}]}
    monkeypatch.setattr(vertex_api, "urlopen", lambda request, timeout: io.BytesIO(json.dumps(reply).encode()))

    with pytest.raises(RuntimeError) as exc_info:
        vertex_api.generate("gemini-nano-banana-2.1", "a red bicycle")

    assert exc_info.value.code == "model.no_image"
    assert "IMAGE_SAFETY" in str(exc_info.value)
    assert vertex_api.endpoint("m", "") == "https://aiplatform.googleapis.com/v1/publishers/google/models/m:generateContent"


def test_vertex_models_get_only_the_settings_they_take() -> None:
    from imagegen_engine import vertex_api

    lite = vertex_api.build_body("gemini-3.1-flash-lite-image", "a mug", "1:8", "4K", [])
    assert lite["generationConfig"]["imageConfig"] == {"imageSize": "1K", "aspectRatio": "1:8"}
    assert vertex_api.estimate("gemini-3-pro-image", "4K") > vertex_api.estimate("gemini-nano-banana-2.1", "4K")
