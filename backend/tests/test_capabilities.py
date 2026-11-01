"""Contract tests for capability resolution and the reference pipeline.

Covers: per-(provider, model) capability resolution with fake providers, the
FAL / Nous Portal catalog lookup, the reference count clamp/error, and the
url vs local reference modes.
"""

from __future__ import annotations

import asyncio
import base64
import sys
import types
from pathlib import Path

import pytest

from dashboard import providers_catalog, store
from dashboard.routes import media as media_routes

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + b"\x00" * 32


class _FakeProvider:
    """Minimal registered-provider stand-in (ImageGenProvider ABC shape)."""

    def __init__(self, name: str, modalities, max_refs: int = 0):
        self.name = name
        self._modalities = list(modalities)
        self._max_refs = max_refs
        self.models: list = []

    def capabilities(self) -> dict:
        return {
            "modalities": self._modalities,
            "max_reference_images": self._max_refs,
        }

    def list_models(self) -> list:
        return list(self.models)


def _install_fake_tools(monkeypatch: pytest.MonkeyPatch, catalog: dict) -> None:
    """Put a fake ``tools.image_generation_tool`` on sys.modules so the real
    ``_fal_catalog_meta`` lookup runs against a hermetic FAL_MODELS."""
    fake_module = types.ModuleType("tools.image_generation_tool")
    fake_module.FAL_MODELS = catalog
    fake_pkg = types.ModuleType("tools")
    monkeypatch.setitem(sys.modules, "tools", fake_pkg)
    monkeypatch.setitem(sys.modules, "tools.image_generation_tool", fake_module)


# ---------------------------------------------------------------------------
# resolve_capabilities
# ---------------------------------------------------------------------------


def test_registered_provider_capabilities_from_fakes() -> None:
    from dashboard.capabilities import resolve_capabilities

    cases = [
        ("openai", "gpt-image-2", ["text", "image"], 16),
        ("openai-codex", "gpt-image-2", ["text", "image"], 16),
        ("xai", "grok-imagine-2", ["text", "image"], 3),
        ("krea", "krea-2.1-pro", ["text", "image"], 10),
        ("openrouter", "openai/gpt-image-1", ["text", "image"], 4),
        ("deepinfra", "black-forest-labs/flux-1.1-pro", ["text"], 0),
    ]
    for provider, model, modalities, max_refs in cases:
        caps = resolve_capabilities(
            provider, model,
            provider_obj=_FakeProvider(provider, modalities, max_refs),
        )
        assert caps["maxReferences"] == max_refs, provider
        assert caps["referenceImages"] == (max_refs > 0), provider


def test_text_only_provider_reports_no_references() -> None:
    from dashboard.capabilities import resolve_capabilities

    caps = resolve_capabilities("openai", "gpt-image-2", provider_obj=_FakeProvider("openai", ["text"]))
    assert caps["maxReferences"] == 0
    assert caps["referenceImages"] is False


def test_image_modality_defaults_to_one_reference() -> None:
    from dashboard.capabilities import resolve_capabilities

    # modalities include "image" but no explicit cap → 1, never 0.
    caps = resolve_capabilities("openai", "gpt-image-2", provider_obj=_FakeProvider("openai", ["text", "image"], 0))
    assert caps["maxReferences"] == 1
    assert caps["referenceImages"] is True


def test_fal_text_only_model_has_zero_references(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.capabilities import resolve_capabilities

    _install_fake_tools(monkeypatch, {"fal-ai/flux-2-pro": {"display": "FLUX 2 Pro"}})
    caps = resolve_capabilities("fal", "fal-ai/flux-2-pro")
    assert caps["maxReferences"] == 0
    assert caps["referenceImages"] is False
    assert caps["edit"] is False


def test_fal_edit_model_reports_catalog_max_refs(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.capabilities import resolve_capabilities

    _install_fake_tools(monkeypatch, {
        "fal-ai/nano-banana-2": {
            "display": "Nano Banana 2",
            "edit_endpoint": "fal-ai/nano-banana-2/edit",
            "max_reference_images": 14,
        },
    })
    caps = resolve_capabilities("fal", "fal-ai/nano-banana-2")
    assert caps["maxReferences"] == 14
    assert caps["referenceImages"] is True
    assert caps["edit"] is True


def test_fal_edit_endpoint_without_cap_defaults_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.capabilities import resolve_capabilities

    _install_fake_tools(monkeypatch, {"fal-ai/flux-2-pro": {"edit_endpoint": "fal-ai/flux-2-pro/edit"}})
    caps = resolve_capabilities("fal", "fal-ai/flux-2-pro")
    assert caps["maxReferences"] == 1
    assert caps["referenceImages"] is True


def test_fal_nano_banana_2_accepts_14_refs_real_catalog() -> None:
    pytest.importorskip("tools.image_generation_tool")
    from dashboard.capabilities import resolve_capabilities

    caps = resolve_capabilities("fal", "fal-ai/nano-banana-2")
    assert caps["maxReferences"] == 14
    assert caps["referenceImages"] is True


def test_nous_portal_catalog_model_refuses_references(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.capabilities import resolve_capabilities

    # The managed Portal path is text-only, even when FAL lists an edit endpoint.
    _install_fake_tools(monkeypatch, {
        "bytedance/seedream/v5/pro/text-to-image": {
            "edit_endpoint": "bytedance/seedream/v5/pro/edit",
            "max_reference_images": 10,
        },
    })
    caps = resolve_capabilities("nous", "fal-ai/bytedance/seedream/v5/pro/text-to-image")
    assert caps["maxReferences"] == 0
    assert caps["referenceImages"] is False


def test_nous_model_outside_portal_resolves_via_fal_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard import nous_portal
    from dashboard.capabilities import resolve_capabilities

    # Ids outside the Portal catalog carry the fal-ai/ prefix while the FAL key does not.
    monkeypatch.setattr(nous_portal, "get_model", lambda model: {})
    _install_fake_tools(monkeypatch, {
        "bytedance/seedream/v5/pro/text-to-image": {
            "edit_endpoint": "bytedance/seedream/v5/pro/edit",
            "max_reference_images": 10,
        },
    })
    caps = resolve_capabilities("nous", "fal-ai/bytedance/seedream/v5/pro/text-to-image")
    assert caps["maxReferences"] == 10
    assert caps["referenceImages"] is True


def test_unknown_nous_model_falls_back_to_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard.capabilities import resolve_capabilities

    _install_fake_tools(monkeypatch, {})
    caps = resolve_capabilities("nous", "openai/gpt-image-1", provider_obj=_FakeProvider("nous", ["text", "image"], 4))
    assert caps["maxReferences"] == 4


def test_magnific_never_accepts_references() -> None:
    from dashboard.capabilities import resolve_capabilities

    caps = resolve_capabilities("magnific", "upscale")
    assert caps["maxReferences"] == 0
    assert caps["referenceImages"] is False


def test_reference_images_flag_is_always_derived() -> None:
    from dashboard.capabilities import resolve_capabilities

    # Contradictory input: stale referenceImages=True with a text-only source.
    caps = resolve_capabilities(
        "openai", "gpt-image-2",
        provider_obj=_FakeProvider("openai", ["text"]),
        model_meta={"referenceImages": True, "maxReferences": 5},
    )
    assert caps["maxReferences"] == 0
    assert caps["referenceImages"] is False


def test_resolve_capabilities_never_raises() -> None:
    from dashboard.capabilities import resolve_capabilities

    class _Boom:
        name = "boom"

        def capabilities(self):
            raise RuntimeError("boom")

    caps = resolve_capabilities("boom", "m", provider_obj=_Boom())
    assert caps["maxReferences"] == 0
    assert caps["referenceImages"] is False
    assert set(caps) == {
        "referenceImages", "maxReferences", "edit", "inpaint", "outpaint",
        "bg", "upscale", "animate", "negativeMode", "strengthTags", "resolutions",
    }


# ---------------------------------------------------------------------------
# reference_mode_for / prepare_reference_sources
# ---------------------------------------------------------------------------


def test_reference_mode_for() -> None:
    from dashboard.gen_service import reference_mode_for

    assert reference_mode_for("fal") == "url"
    assert reference_mode_for("krea") == "url"
    for provider in ("openai", "openai-codex", "xai", "openrouter", "nous"):
        assert reference_mode_for(provider) == "local"
    assert reference_mode_for("unknown-provider") == "local"


def test_prepare_reference_sources_url_mode_publishes_locals(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from dashboard import gen_service

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    ref = tmp_path / "ref.png"
    ref.write_bytes(_PNG_BYTES)
    published = []

    def fake_upload(value: str, filename: str = "image.png") -> str:
        published.append((value, filename))
        return f"https://published.example/{filename}"

    monkeypatch.setattr(gen_service, "fal_upload_image", fake_upload)
    sources = gen_service.prepare_reference_sources(
        "krea", "krea-2.1-pro",
        [str(ref), "https://already.example/a.png"],
        max_refs=10,
    )
    assert sources == ["https://published.example/reference-1.png", "https://already.example/a.png"]
    assert published == [(str(ref), "reference-1.png")]


def test_prepare_reference_sources_local_mode_keeps_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from dashboard import gen_service

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    ref = tmp_path / "ref.png"
    ref.write_bytes(_PNG_BYTES)
    sources = gen_service.prepare_reference_sources(
        "openai", "gpt-image-2",
        [str(ref), "https://already.example/a.png"],
        max_refs=16,
    )
    assert sources == [str(ref), "https://already.example/a.png"]


def test_prepare_reference_sources_rejects_path_outside_roots(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from dashboard import gen_service

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(_PNG_BYTES)
    with pytest.raises(RuntimeError) as exc_info:
        gen_service.prepare_reference_sources("openai", "gpt-image-2", [str(outside)], max_refs=16)
    assert exc_info.value.code == "refs.unresolved"
    assert str(outside) in exc_info.value.params["ref"]


def test_prepare_reference_sources_raises_when_over_cap() -> None:
    from dashboard.gen_service import prepare_reference_sources

    with pytest.raises(RuntimeError) as exc_info:
        prepare_reference_sources("openai", "gpt-image-2", ["a.png", "b.png", "c.png"], max_refs=2)
    assert exc_info.value.code == "refs.too_many"
    assert exc_info.value.params == {"model": "gpt-image-2", "max": 2, "provided": 3}
    with pytest.raises(RuntimeError) as exc_info:
        prepare_reference_sources("openai", "gpt-image-2", ["a.png"], max_refs=0)
    assert exc_info.value.code == "refs.model_unsupported"
    assert exc_info.value.params == {"model": "gpt-image-2", "provider": "openai"}
    assert prepare_reference_sources(
        "openai", "gpt-image-2",
        ["https://a.example/1.png", "https://b.example/2.png"],
        max_refs=2,
    ) == ["https://a.example/1.png", "https://b.example/2.png"]


def test_generate_krea_publishes_https_refs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Regression: Krea must receive https URLs, never raw local paths."""
    import sys
    import types

    from dashboard import gen_service

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    local_ref = tmp_path / "ref.png"
    local_ref.write_bytes(_PNG_BYTES)

    captured = {}

    class _FakeKrea:
        name = "krea"

        def is_available(self) -> bool:
            return True

        def capabilities(self) -> dict:
            return {"modalities": ["text", "image"], "max_reference_images": 10}

        def list_models(self) -> list:
            return [{"id": "krea-2.1-pro", "display": "Krea 2.1 Pro"}]

        def generate(self, prompt, aspect_ratio="square", *, image_url=None,
                     reference_image_urls=None, **kwargs):
            captured["image_url"] = image_url
            captured["reference_image_urls"] = reference_image_urls
            return {"success": True, "image": "https://result.example/out.png"}

    fake_pkg = types.ModuleType("agent")
    fake_reg = types.ModuleType("agent.image_gen_registry")
    fake_reg.get_provider = lambda name: _FakeKrea() if name == "krea" else None
    monkeypatch.setitem(sys.modules, "agent", fake_pkg)
    monkeypatch.setitem(sys.modules, "agent.image_gen_registry", fake_reg)

    published = []

    def fake_upload(value: str, filename: str = "image.png") -> str:
        published.append((value, filename))
        return f"https://published.example/{filename}"

    monkeypatch.setattr(gen_service, "fal_upload_image", fake_upload)

    result = gen_service.generate_text_to_image(
        provider="krea",
        model="krea-2.1-pro",
        prompt="a red bicycle",
        reference_images=[str(local_ref), "https://already.example/a.png"],
    )
    assert captured["image_url"] == "https://published.example/reference-1.png"
    assert captured["reference_image_urls"] == ["https://already.example/a.png"]
    assert published[0][0] == str(local_ref)
    assert result["provider"] == "krea"
    assert result["references_used"] == 2


def test_generate_text_to_image_rejects_refs_for_text_only_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    from dashboard import gen_service

    class _FakeTextOnly:
        name = "deepinfra"

        def is_available(self) -> bool:
            return True

        def capabilities(self) -> dict:
            return {"modalities": ["text"], "max_reference_images": 0}

        def list_models(self) -> list:
            return [{"id": "flux", "display": "Flux"}]

        def generate(self, prompt, aspect_ratio="square", **kwargs):
            raise AssertionError("generate must not be called")

    fake_pkg = types.ModuleType("agent")
    fake_reg = types.ModuleType("agent.image_gen_registry")
    fake_reg.get_provider = lambda name: _FakeTextOnly() if name == "deepinfra" else None
    monkeypatch.setitem(sys.modules, "agent", fake_pkg)
    monkeypatch.setitem(sys.modules, "agent.image_gen_registry", fake_reg)

    with pytest.raises(RuntimeError) as exc_info:
        gen_service.generate_text_to_image(
            provider="deepinfra",
            model="flux",
            prompt="a red bicycle",
            reference_images=["ref.png"],
        )
    assert exc_info.value.code == "refs.model_unsupported"
    assert exc_info.value.params == {"model": "flux", "provider": "deepinfra"}


# ---------------------------------------------------------------------------
# _list_providers enrichment (single source of truth)
# ---------------------------------------------------------------------------


def test_list_providers_enriches_registered_and_special_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    class _FakeOpenAI:
        name = "openai"
        display_name = "OpenAI"

        def is_available(self) -> bool:
            return True

        def list_models(self) -> list:
            return [{"id": "gpt-image-2", "display": "GPT Image 2"}]

        def capabilities(self) -> dict:
            return {"modalities": ["text", "image"], "max_reference_images": 16}

    fake_pkg = types.ModuleType("agent")
    fake_reg = types.ModuleType("agent.image_gen_registry")
    fake_reg.list_providers = lambda: [_FakeOpenAI()]
    monkeypatch.setitem(sys.modules, "agent", fake_pkg)
    monkeypatch.setitem(sys.modules, "agent.image_gen_registry", fake_reg)
    monkeypatch.setattr(providers_catalog, "_ensure_providers_registered", lambda: None)
    monkeypatch.setattr(providers_catalog, "_magnific_provider_entry",
                        lambda: {"name": "magnific", "models": [{"id": "upscale"}]})
    monkeypatch.setattr(providers_catalog, "_merge_nous_portal_entry", lambda out: None)

    out = providers_catalog._list_providers()
    openai = next(p for p in out if p["name"] == "openai")
    assert openai["models"][0]["capabilities"]["referenceImages"] is True
    assert openai["models"][0]["capabilities"]["maxReferences"] == 16
    magnific = next(p for p in out if p["name"] == "magnific")
    assert magnific["models"][0]["capabilities"]["referenceImages"] is False


# ---------------------------------------------------------------------------
# Upload MIME
# ---------------------------------------------------------------------------


def test_upload_route_writes_real_extension_and_media_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    refs = tmp_path / "refs"
    refs.mkdir()
    monkeypatch.setattr(store, "REFS_DIR", refs)

    class _Req:
        base_url = "http://test/"

    jpeg_b64 = base64.b64encode(_JPEG_BYTES).decode()
    result = asyncio.run(media_routes.upload_image(
        _Req(), {"image": f"data:image/jpeg;base64,{jpeg_b64}"},
    ))
    assert result["name"].endswith(".jpg")
    assert store.image_media_type(result["name"]) == "image/jpeg"

    png_b64 = base64.b64encode(_PNG_BYTES).decode()
    result_png = asyncio.run(media_routes.upload_image(
        _Req(), {"image": f"data:image/png;base64,{png_b64}"},
    ))
    assert result_png["name"].endswith(".png")
    assert store.image_media_type(result_png["name"]) == "image/png"


def test_reference_file_route_uses_stored_media_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    refs = tmp_path / "refs"
    refs.mkdir()
    monkeypatch.setattr(store, "REFS_DIR", refs)
    (refs / "ref-jpeg.jpg").write_bytes(_JPEG_BYTES)
    (refs / "ref-webp.webp").write_bytes(b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 32)

    response = asyncio.run(media_routes.reference_file("ref-jpeg.jpg"))
    assert response.media_type == "image/jpeg"
    response_webp = asyncio.run(media_routes.reference_file("ref-webp.webp"))
    assert response_webp.media_type == "image/webp"
