"""Contract tests for ImageGen plan slices 0-4 and reliability backend seams."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest

from imagegen_engine import gen_service, llm_service, model_profiles, store
from imagegen_engine.generation_artifacts import parse_num_images
from imagegen_engine.routes import llm as llm_routes


@pytest.fixture
def isolated_handoffs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "handoffs_dir", lambda: tmp_path / "handoffs")
    monkeypatch.setattr(store, "handoff_last_file", lambda: tmp_path / "handoffs" / "last.json")
    return tmp_path / "handoffs"


def test_handoff_store_writes_last_and_id_files(isolated_handoffs: Path) -> None:
    record = store.save_handoff({
        "generationId": "gen-123",
        "prompt": "a red bicycle",
        "provider": "fal",
        "model": "flux",
        "paths": ["C:/images/a.png"],
    })

    assert record["id"] == "gen-123"
    assert json.loads((isolated_handoffs / "gen-123.json").read_text()) == record
    assert json.loads((isolated_handoffs / "last.json").read_text()) == record
    assert store.get_handoff("gen-123")["prompt"] == "a red bicycle"
    assert store.get_last_handoff()["generationId"] == "gen-123"


def test_handoff_feedback_is_persisted(isolated_handoffs: Path) -> None:
    store.save_handoff({"generationId": "gen-feedback", "prompt": "old prompt"})
    updated = store.save_handoff_feedback("gen-feedback", {"feedback": "make it warmer"})

    assert updated["feedback"] == "make it warmer"
    assert store.get_handoff("gen-feedback")["feedback"] == "make it warmer"


def test_model_capabilities_have_stable_contract() -> None:
    caps = model_profiles.capabilities_for_model({
        "max_reference_images": 3,
        "edit_endpoint": True,
        "supports_inpaint": True,
        "supports_outpaint": False,
        "supports_background_removal": True,
        "supports_upscale": True,
        "supports_animation": False,
        "negative_mode": "separate",
        "strength_tags": ["photorealistic"],
        "resolutions": ["1K", "2K"],
    })

    assert caps == {
        "maxReferences": 3,
        "edit": True,
        "inpaint": True,
        "outpaint": False,
        "bg": True,
        "upscale": True,
        "animate": False,
        "negativeMode": "separate",
        "strengthTags": ["photorealistic"],
        "resolutions": ["1K", "2K"],
    }


def test_build_intent_includes_model_and_generation_context() -> None:
    intent = model_profiles.build_intent({
        "description": "a red bicycle",
        "subjectType": "vehicle",
        "aspectRatio": "4:5",
        "provider": "fal",
        "model": "flux",
        "referenceImages": ["a.png"],
        "colorAccents": ["#ff0000"],
        "subjectIds": ["subject-1"],
    })

    assert intent["userIntent"] == "a red bicycle"
    assert intent["model"] == {"provider": "fal", "id": "flux"}
    assert intent["aspectRatio"] == "4:5"
    assert intent["referenceCount"] == 1
    assert intent["colorAccents"] == ["#ff0000"]
    assert intent["subjectIds"] == ["subject-1"]


def test_disabled_accent_palette_is_kept_out_of_the_prompt_and_intent() -> None:
    from imagegen_engine.prompt_builder import build_prompt

    config = {"description": "Yellow umbrella", "colorAccents": ["#765432"]}
    assert "#765432" in build_prompt(config)["prompt"]
    config["colorAccentsEnabled"] = False
    assert "#765432" not in build_prompt(config)["prompt"]
    assert model_profiles.build_intent(config)["colorAccents"] == []
    assert config["colorAccents"] == ["#765432"]


def test_refine_from_feedback_returns_prompt_without_generating(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_refine(**kwargs):
        calls.append(kwargs)
        return json.dumps({"diagnosis": "lighting is too cold", "newPrompt": "a red bicycle in warm light"})

    monkeypatch.setattr(llm_routes.llm_service, "llm_refine_prompt", fake_refine)
    result = asyncio.run(llm_routes.refine_from_feedback({
        "prompt": "a red bicycle",
        "feedback": "make the lighting warmer",
        "provider": "fal",
        "model": "flux",
    }))

    assert result == {
        "autoGenerate": False,
        "diagnosis": "lighting is too cold",
        "newPrompt": "a red bicycle in warm light",
    }
    assert len(calls) == 1


def test_refine_from_feedback_does_not_accept_auto_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_routes.llm_service, "llm_refine_prompt", lambda **_: "Use warmer lighting")
    result = asyncio.run(llm_routes.refine_from_feedback({
        "prompt": "a red bicycle",
        "feedback": "warmer",
        "autoGenerate": True,
    }))
    assert result["autoGenerate"] is False
    assert set(result) == {"autoGenerate", "diagnosis", "newPrompt"}


def test_export_gallery_pack_contains_image_and_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gallery = tmp_path / "gallery"
    meta = gallery / ".meta"
    exports = tmp_path / "exports"
    gallery.mkdir()
    meta.mkdir()
    monkeypatch.setattr(store, "gallery_dir", lambda: gallery)
    monkeypatch.setattr(store, "export_dir", lambda: exports)
    (gallery / "img-one.png").write_bytes(b"png")
    (meta / "one.json").write_text(json.dumps({"id": "one", "file": "img-one.png", "prompt": "test"}))

    archive = store.export_gallery_pack("one")

    assert archive is not None
    import zipfile
    with zipfile.ZipFile(archive) as value:
        assert set(value.namelist()) == {"image.png", "meta.json"}
        assert json.loads(value.read("meta.json"))["prompt"] == "test"


def test_clear_plugin_data_requires_scoped_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handoffs = tmp_path / "handoffs"
    objects = tmp_path / "objects"
    index = tmp_path / "objects.json"
    handoffs.mkdir()
    objects.mkdir()
    (handoffs / "last.json").write_text("{}")
    (objects / "one.png").write_bytes(b"x")
    index.write_text(json.dumps([{ "id": "one", "file": "one.png" }]))
    monkeypatch.setattr(store, "handoffs_dir", lambda: handoffs)
    monkeypatch.setattr(store, "objects_dir", lambda: objects)
    monkeypatch.setattr(store, "objects_index", lambda: index)

    deleted = store.clear_plugin_data(handoffs=True, subjects=True)

    assert deleted["handoffs"] == 1
    assert deleted["subjects"] == 1
    assert not list(handoffs.glob("*.json"))
    assert json.loads(index.read_text()) == []


def test_subject_open_kind_and_multi_angle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    objects = tmp_path / "objects"
    index = tmp_path / "objects.json"
    objects.mkdir()
    monkeypatch.setattr(store, "objects_dir", lambda: objects)
    monkeypatch.setattr(store, "objects_index", lambda: index)
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)

    primary = store.object_add("a.png", b"primary-bytes", name="Box", kind="packaging_box")
    assert primary["kind"] == "packaging-box" or primary["kind"] == "packaging_box" or "packaging" in primary["kind"]
    updated = store.subject_add_angle(primary["id"], "b.png", b"angle-bytes", label="side")
    assert updated is not None
    assert len(updated.get("angles") or []) >= 2

    # Dedupe same bytes
    again = store.object_add("c.png", b"primary-bytes", name="Dup", kind="product")
    assert again.get("deduped") is True

    refs = store.subject_as_refs(primary["id"], max_refs=4)
    assert len(refs) >= 2
    assert refs[0]["fixedProduct"] is True

    kinds = store.subjects_kinds()
    assert "product" in kinds["presets"]
    assert any("packaging" in k for k in kinds["all"])


def test_model_family_addendum() -> None:
    assert "paragraph" in model_profiles.prompt_system_addendum(model="gpt-image-2").lower() or "plain" in model_profiles.prompt_system_addendum(model="gpt-image-2").lower()
    family = model_profiles.resolve_family(provider="xai", model="grok-imagine")
    assert family["id"] == "grok"


def test_nous_family_profiles_resolve() -> None:
    assert model_profiles.resolve_family(provider="nous", model="fal-ai/alibaba/qwen-image-3/text-to-image")["id"] == "qwen"
    assert model_profiles.resolve_family(provider="nous", model="fal-ai/recraft/v4.1/text-to-image")["id"] == "recraft"
    assert model_profiles.resolve_family(provider="nous", model="fal-ai/bytedance/seedream/v5/pro/text-to-image")["id"] == "seedream"


def test_resolve_family_uses_model_tokens_over_provider() -> None:
    # Regression: substring matching on "openai" + "flux" resolved to gpt-image.
    assert model_profiles.resolve_family(provider="openai", model="flux")["id"] == "flux"
    assert model_profiles.resolve_family(provider="fal", model="fal-ai/flux-2-pro")["id"] == "flux"
    assert model_profiles.resolve_family(provider="openai", model="gpt-image-1")["id"] == "gpt-image"
    assert model_profiles.resolve_family(provider="xai", model="grok-imagine-2")["id"] == "grok"
    assert model_profiles.resolve_family(provider="unknown", model="some-model")["id"] == "default"


def test_to_natural_language_preserves_prompt_with_negatives() -> None:
    from imagegen_engine.prompt_builder import _to_natural_language

    # Regression: a --no flag without --ar wiped the whole prompt.
    out = _to_natural_language("product shot, --no text", {"aspectRatio": "4:5"})
    assert out.startswith("product shot")
    assert "Avoid: text" in out
    assert "Aspect ratio: 4:5" in out

    out2 = _to_natural_language("product shot of a bottle, studio lighting --ar 4:5 --no text, watermark", {"aspectRatio": "4:5"})
    assert out2.startswith("product shot of a bottle, studio lighting")
    assert "Avoid: text, watermark" in out2
    assert "--ar" not in out2 and "--no" not in out2

    out3 = _to_natural_language("clean scene --s 250 --ar 1:1", {})
    assert out3 == "clean scene"


def test_composition_intent_with_short_interpretations_does_not_crash() -> None:
    from imagegen_engine.prompt_builder import _build_from_composition_intent

    config = {
        "compositionIntent": {
            "status": "confirmed",
            "suggestedPrompt": "a red bicycle on a terrace",
            "interpretations": [{"role": "object_primary"}],  # fewer than refs
        },
        "referencesV4": [
            {"imageDataUrl": "data:image/png;base64,x", "semanticRole": "object_primary"},
            {"imageDataUrl": "data:image/png;base64,y", "semanticRole": "context_application"},
        ],
        "outputGoal": "prompt",
        "globalDirection": {},
        "aspectRatio": "4:5",
        "qualityLevel": "padrao",
    }
    result = _build_from_composition_intent(config)
    assert result and "Reference mapping" in result


def test_parse_num_images_caps_at_max_generations() -> None:
    assert parse_num_images({"numImages": 4}) == 4
    with pytest.raises(Exception):
        parse_num_images({"numImages": gen_service.MAX_GENERATIONS + 1})
    with pytest.raises(Exception):
        parse_num_images({"numImages": 0})
    with pytest.raises(Exception):
        parse_num_images({"numImages": "many"})


def test_safe_model_id_rejects_url_tokens() -> None:
    from imagegen_engine.gen_service import _safe_model_id

    assert _safe_model_id("fal-ai/flux-2-pro/edit") == "fal-ai/flux-2-pro/edit"
    for bad in ("../x", "a?b", "a#b", "a b", "..", "x:y"):
        with pytest.raises(RuntimeError):
            _safe_model_id(bad)


def test_job_cancel_aborts_running_generation() -> None:
    from imagegen_engine import gen_service, jobs

    progress = []

    def slow_job(job: jobs.Job) -> dict:
        for i in range(10):
            gen_service._check_cancel(job.check_cancelled)
            progress.append(i)
            import time
            time.sleep(0.02)
        return {"images": ["done"]}

    job = jobs.manager.submit("test-cancel", slow_job)
    import time
    time.sleep(0.06)
    assert jobs.manager.cancel(job.id) is True
    job.thread.join(timeout=3)
    assert job.status == "cancelled"
    assert len(progress) < 10


# ---------------------------------------------------------------------------
# Module seam: image generation and auxiliary LLM stay independent
# ---------------------------------------------------------------------------

def _imported_dashboard_modules(module: object) -> set[str]:
    """Every sibling ``imagegen_engine`` module this one imports, deferred ones included."""
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            parent = node.module or ""
            if parent == "imagegen_engine":
                found.update(alias.name for alias in node.names)
            elif parent.startswith("imagegen_engine."):
                found.add(parent.split(".")[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("imagegen_engine."):
                    found.add(alias.name.split(".")[1])
    return found


def test_generation_and_llm_services_do_not_import_each_other() -> None:
    """The split only pays off while the seam holds.

    `gen_service` spends money on pixels, `llm_service` writes text. Routes may
    depend on both; neither may depend on the other. A single import here would
    quietly merge them back into one module wearing two filenames.
    """
    assert "llm_service" not in _imported_dashboard_modules(gen_service)
    assert "gen_service" not in _imported_dashboard_modules(llm_service)
