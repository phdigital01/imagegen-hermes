"""Request contracts for the Magnific catalog and FAL's public catalog, without network."""
from __future__ import annotations

import base64
import io
import time

import pytest

from dashboard import fal_catalog, magnific_api, providers_catalog
from dashboard.errors import ImageGenError


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch):
    """Capture Magnific submissions instead of sending them."""
    calls = []

    def submit(model, payload, **kwargs):
        calls.append((model, payload, kwargs.get("text", False)))
        return {"text": "words"} if kwargs.get("text") else {"images": ["https://x/y.png"]}

    monkeypatch.setattr(magnific_api, "_submit_and_poll", submit)
    monkeypatch.setattr(magnific_api, "_base64_image", lambda source, seedream=False: f"b64:{source}")
    monkeypatch.setattr(magnific_api, "_public_image_url", lambda source, **kwargs: f"https://pub/{source}")
    return calls


def _run(fn, *args, **kwargs):
    return fn(*args, check_cancel=lambda: None, sleep=lambda seconds: None, **kwargs)


def test_gpt_image_uses_named_ratio_lowercase_resolution_and_edit_endpoint(sent):
    _run(magnific_api.generate, "gpt-image-2", "a poster", aspect_ratio="21:9", resolution="2K",
         reference_images=["a.png", "b.png"])
    model, payload, _ = sent[0]
    assert model == "gpt-image-2-edit"
    assert payload["aspect_ratio"] == "film_horizontal_21_9"
    assert payload["resolution"] == "2k"
    assert payload["reference_images"] == ["b64:a.png", "b64:b.png"]
    assert "seed" not in payload


def test_nano_banana_2_1_wraps_references_and_keeps_raw_ratio(sent):
    _run(magnific_api.generate, "nano-banana-2-1", "a cat", aspect_ratio="8:1", reference_images=["r.png"])
    model, payload, _ = sent[0]
    assert model == "nano-banana-2-1"
    assert payload["aspect_ratio"] == "8:1"
    assert payload["resolution"] == "1K"
    assert payload["reference_images"] == [{"image": "b64:r.png"}]


def test_ideogram_seed_range_and_kontext_max_requires_reference(sent):
    _run(magnific_api.generate, "ideogram-4", "logo", aspect_ratio="16:10", seed=7)
    assert sent[0][1] == {"prompt": "logo", "seed": 7, "aspect_ratio": "16:10"}
    with pytest.raises(ImageGenError):
        _run(magnific_api.generate, "ideogram-4", "logo", seed=2**31)
    with pytest.raises(ImageGenError):
        _run(magnific_api.generate, "flux-kontext-max", "edit it")
    _run(magnific_api.generate, "flux-kontext-max", "edit it", reference_images=["p.png"])
    assert sent[-1][1]["input_image"] == "https://pub/p.png"


def test_magnific_one_sends_public_reference_urls(sent):
    _run(magnific_api.generate, "magnific-one", "studio photo", aspect_ratio="3:1", resolution="4K",
         reference_images=["p.png"])
    model, payload, _ = sent[0]
    assert model == "magnific-one"
    assert payload == {"prompt": "studio photo", "aspect_ratio": "3:1", "resolution": "4k",
                       "reference_images": ["https://pub/p.png"]}


def test_camera_skin_and_expand_operations(sent):
    _run(magnific_api.edit_operation, "camera", {"image": "i.png", "horizontalAngle": 90, "verticalAngle": -10, "zoom": 3})
    assert sent[-1][:2] == ("image-change-camera", {"image": "https://pub/i.png", "horizontal_angle": 90,
                                                    "vertical_angle": -10, "zoom": 3})
    _run(magnific_api.edit_operation, "skin", {"image": "i.png", "skinMode": "flexible", "optimizedFor": "enhance_skin"})
    assert sent[-1][0] == "skin-enhancer-flexible"
    assert sent[-1][1]["optimized_for"] == "enhance_skin" and "skin_detail" not in sent[-1][1]
    _run(magnific_api.edit_operation, "outpaint", {"image": "i.png", "direction": "left", "expandPx": 300,
                                                   "expandModel": "ideogram"})
    model, payload, _ = sent[-1]
    assert model == "image-expand-ideogram"
    assert payload == {"image": "b64:i.png", "left": 300, "right": 0, "top": 0, "bottom": 0}


def test_skin_enhancer_polls_the_shared_task_path():
    assert magnific_api.ENDPOINTS["skin-enhancer-faithful"].endswith("/v1/ai/skin-enhancer/faithful")
    base = magnific_api.API_URL + magnific_api.TASK_PATHS["skin-enhancer-faithful"]
    assert base.endswith("/v1/ai/skin-enhancer")


def test_precision_v2_upscale_and_prompt_helpers(sent, monkeypatch):
    from dashboard import store

    monkeypatch.setattr(store, "fetch_image_bytes", lambda source: b"raw")
    _run(magnific_api.upscale, "i.png", mode="precision-v2", scale=8, flavor="photo")
    assert sent[-1][:2] == ("image-upscaler-precision-v2", {"image": base64.b64encode(b"raw").decode(),
                                                            "scale_factor": 8, "flavor": "photo"})
    assert _run(magnific_api.prompt_helper, "describe", "i.png") == {"text": "words"}
    assert sent[-1] == ("image-to-prompt", {"image": "b64:i.png"}, True)
    _run(magnific_api.prompt_helper, "improve", "a cat", language="pt")
    assert sent[-1] == ("improve-prompt", {"prompt": "a cat", "type": "image", "language": "pt"}, True)


def test_inpaint_inverts_the_painted_mask(sent, monkeypatch):
    from PIL import Image

    from dashboard import store

    def png(color):
        buffer = io.BytesIO()
        Image.new("L", (4, 4), color).save(buffer, format="PNG")
        return buffer.getvalue()

    monkeypatch.setattr(store, "fetch_image_bytes", lambda source: png(255 if source == "mask.png" else 90))
    _run(magnific_api.edit_operation, "inpaint", {"image": "i.png", "maskImage": "mask.png", "prompt": "a hat"})
    model, payload, _ = sent[-1]
    assert model == "ideogram-image-edit" and payload["prompt"] == "a hat"
    with Image.open(io.BytesIO(base64.b64decode(payload["mask"]))) as mask:
        assert mask.getpixel((0, 0)) == 0  # Painted white becomes the black area Ideogram edits.


# --- FAL public catalog -------------------------------------------------------

def _field(types=("string",), enum=(), max_items=None, default=False):
    return {"types": list(types), "enum": list(enum), "maxItems": max_items, "hasDefault": default}


@pytest.fixture
def catalog(monkeypatch: pytest.MonkeyPatch):
    def row(endpoint, group, label=""):
        return {"id": endpoint, "display": endpoint, "strengths": "", "group": group, "label": label}

    data = {"at": time.time(),
            "text-to-image": [row("fal-ai/flux-2-pro", "flux2"), row("acme/poster", "poster"), row("acme/solo", "")],
            "image-to-image": [row("acme/poster/remix", "poster", "Remix"), row("acme/poster/edit", "poster", "Edit")]}
    schemas = {
        "acme/poster": {"properties": {"prompt": _field(), "aspect_ratio": _field(enum=["1:1", "16:9", "auto"]),
                                       "resolution": _field(enum=["1k", "2k"]), "seed": _field(("integer",))},
                        "required": ["prompt"]},
        "acme/poster/edit": {"properties": {"prompt": _field(), "image_urls": _field(("array",), max_items=3),
                                            "image_size": _field(("object",))},
                             "required": ["prompt", "image_urls"]},
        "acme/solo": {"properties": {"prompt": _field(), "image_size": _field(enum=["square_hd", "landscape_16_9"]),
                                     "style": _field()},
                      "required": ["prompt", "style"]},
    }
    monkeypatch.setattr(fal_catalog, "_memory", {"catalog": data, "schemas": {
        key: {"at": time.time(), "input": value} for key, value in schemas.items()}})
    return data


def test_fal_catalog_lookup_details_and_edit_sibling(catalog):
    assert fal_catalog.knows("acme/poster") and not fal_catalog.knows("acme/missing")
    assert fal_catalog.edit_sibling("acme/poster") == "acme/poster/edit"
    assert fal_catalog.edit_sibling("acme/solo") == ""
    assert fal_catalog.details("acme/poster", fetch=False) == {
        "supportsSeed": True, "aspectRatios": ["1:1", "16:9"], "resolutionOptions": ["1K", "2K"],
        "maxReferences": 3, "editEndpoint": "acme/poster/edit"}
    assert fal_catalog.details("acme/solo", fetch=False)["aspectRatios"] == ["1:1", "16:9"]
    assert fal_catalog.details("acme/unknown", fetch=False) == {}


def test_fal_build_payload_maps_fields_and_refuses_unknown_inputs(catalog):
    assert fal_catalog.build_payload("acme/poster", prompt="p", aspect_ratio="3:2", resolution="2K", seed=5) == {
        "prompt": "p", "aspect_ratio": "16:9", "resolution": "2k", "seed": 5}
    edit = fal_catalog.build_payload("acme/poster/edit", prompt="p", aspect_ratio="1:1", image_urls=["u1", "u2"])
    assert edit["image_urls"] == ["u1", "u2"] and set(edit["image_size"]) == {"width", "height"}
    with pytest.raises(ImageGenError):
        fal_catalog.build_payload("acme/poster/edit", prompt="p", image_urls=["u"] * 4)
    with pytest.raises(ImageGenError):
        fal_catalog.build_payload("acme/poster", prompt="p", image_urls=["u"])
    with pytest.raises(ImageGenError, match="style"):
        fal_catalog.build_payload("acme/solo", prompt="p", aspect_ratio="16:9")


def test_provider_list_adds_catalog_models_once_and_edit_models(catalog):
    out = [{"name": "fal", "models": [{"id": "fal-ai/flux-2-pro"}]}]
    providers_catalog._merge_fal_catalog(out)
    ids = [model["id"] for model in out[0]["models"]]
    assert ids == ["fal-ai/flux-2-pro", "acme/poster", "acme/solo"]
    assert out[0]["models"][1]["aspectRatios"] == ["1:1", "16:9"]
    assert [model["id"] for model in out[0]["edit_models"]] == ["acme/poster/remix", "acme/poster/edit"]


def test_fal_catalog_capabilities_use_cached_schema(catalog):
    from dashboard.capabilities import resolve_capabilities

    assert resolve_capabilities("fal", "acme/poster")["maxReferences"] == 3
    assert resolve_capabilities("fal", "acme/solo")["maxReferences"] == 0


def test_a_finished_task_may_list_its_images_a_moment_later(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = [{"task_id": "t", "status": "CREATED", "generated": []},
               {"task_id": "t", "status": "COMPLETED", "generated": []},
               {"task_id": "t", "status": "COMPLETED", "generated": ["https://x/y.png"]}]
    monkeypatch.setattr(magnific_api, "api_key", lambda: "k")
    monkeypatch.setattr(magnific_api, "_request", lambda *_, **__: answers.pop(0))
    result = magnific_api._submit_and_poll("image-upscaler-precision", {}, check_cancel=lambda: None, sleep=lambda _: None)
    assert result["images"] == ["https://x/y.png"]


def test_a_failed_task_says_the_providers_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(magnific_api, "api_key", lambda: "k")
    monkeypatch.setattr(magnific_api, "_request", lambda *_, **__: {"task_id": "t", "status": "FAILED", "error": "mask too small"})
    with pytest.raises(ImageGenError, match="mask too small"):
        magnific_api._submit_and_poll("ideogram-image-edit", {}, check_cancel=lambda: None, sleep=lambda _: None)


def test_a_result_served_as_generic_binary_is_accepted_when_its_bytes_are_an_image(monkeypatch: pytest.MonkeyPatch) -> None:
    from dashboard import image_input

    class Response(io.BytesIO):
        headers = {"Content-Type": "application/octet-stream"}

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

    class Opener:
        def __init__(self, data):
            self.data = data

        def open(self, *_, **__):
            return Response(self.data)

    monkeypatch.setattr(image_input, "_reject_non_public_host", lambda _: None)
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 64
    monkeypatch.setattr(image_input.urllib.request, "build_opener", lambda *_: Opener(png))
    assert image_input.fetch_remote_image("https://x/y.png") == png
    monkeypatch.setattr(image_input.urllib.request, "build_opener", lambda *_: Opener(b"<html>not an image</html>"))
    with pytest.raises(ValueError):
        image_input.fetch_remote_image("https://x/y.png")
