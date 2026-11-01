"""Direct Magnific API transport for image generation and editing.

API contract: https://docs.magnific.com/api-reference/mystic/post-mystic
Credentials stay in the backend; no Hermes MCP connection is involved.
"""
from __future__ import annotations

import base64
import io
import json
import time
from typing import Any, Callable, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen, build_opener

from dashboard.errors import ImageGenError, MODEL_INVALID, MODEL_NO_IMAGE, PROVIDER_FAILED, PROVIDER_UNAVAILABLE
from dashboard.magnific_catalog import EXPAND_MODELS, MODELS, OPERATIONS, TASK_PATHS, get_model

API_URL = "https://api.magnific.com/v1/ai/"
MODEL_ID = "mystic"
ENDPOINTS = {model: API_URL + (spec["path"] or f"text-to-image/{model}") for model, spec in MODELS.items()}
ENDPOINTS.update({spec["edit_endpoint"]: API_URL + f"text-to-image/{spec['edit_endpoint']}"
                  for spec in MODELS.values() if spec["edit_endpoint"]})
ENDPOINTS.update({name: API_URL + path for name, path in OPERATIONS.items()})
BASE_URL = ENDPOINTS[MODEL_ID]
ASPECT_RATIOS = {
    "1:1": "square_1_1", "4:3": "classic_4_3", "3:4": "traditional_3_4",
    "16:9": "widescreen_16_9", "9:16": "social_story_9_16",
    "20:9": "smartphone_horizontal_20_9", "9:20": "smartphone_vertical_9_20",
    "3:2": "standard_3_2", "2:3": "portrait_2_3", "2:1": "horizontal_2_1",
    "1:2": "vertical_1_2", "5:4": "social_5_4", "4:5": "social_post_4_5",
    "21:9": "cinematic_21_9",
}
# GPT Image names two ratios differently from the other named-ratio endpoints.
GPT_ASPECT_RATIOS = {**ASPECT_RATIOS, "21:9": "film_horizontal_21_9", "3:1": "banner_3_1"}
SKIN_MODES = ("creative", "faithful", "flexible")
SKIN_TARGETS = ("enhance_skin", "improve_lighting", "enhance_everything", "transform_to_real", "no_make_up")
UPSCALE_FLAVORS = ("sublime", "photo", "photo_denoiser")
EMPTY_RESULT_POLLS = 15


def api_key() -> str:
    from dashboard import credentials

    return credentials.magnific_key()


def _request(key: str, *, payload: Optional[Dict[str, Any]] = None, task_id: str = "", model: str = MODEL_ID) -> Dict[str, Any]:
    if model not in ENDPOINTS:
        raise ImageGenError(MODEL_INVALID, "Unsupported Magnific operation", model=model)
    base = API_URL + TASK_PATHS[model] if task_id and model in TASK_PATHS else ENDPOINTS[model]
    url = base + ("/" + quote(task_id, safe="") if task_id else "")
    form = model == "remove-background" and payload is not None
    request = Request(
        url,
        data=(urlencode(payload) if form else json.dumps(payload)).encode("utf-8") if payload is not None else None,
        headers={"x-magnific-api-key": key, "Content-Type": "application/x-www-form-urlencoded" if form else "application/json"},
        method="POST" if payload is not None else "GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        # Do not echo response bodies or credentials into logs/UI.
        detail = f"Magnific API returned HTTP {exc.code}"
        raise ImageGenError(PROVIDER_FAILED, detail, provider="magnific", detail=detail) from exc
    except (URLError, OSError, ValueError) as exc:
        detail = "Magnific API request failed; submission was not retried"
        raise ImageGenError(PROVIDER_FAILED, detail, provider="magnific", detail=detail) from exc
    # Style Transfer also documents an unwrapped task/task_status response.
    data = result.get("data", result) if isinstance(result, dict) else None
    if not isinstance(data, dict):
        raise ImageGenError(PROVIDER_FAILED, "Invalid Magnific API response", provider="magnific", detail="Missing task data")
    if "task_status" in data and "status" not in data:
        data["status"] = data["task_status"]
    return data


def generate(
    model: str, prompt: str, *, aspect_ratio: str = "1:1", resolution: str = "1K",
    seed: Optional[int] = None, reference_images=None,
    check_cancel: Callable[[], None], sleep: Callable[[float], None],
    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Submit once and poll the same task; never retry a paid submission.

    Cancellation stops local polling. The remote API task may still complete.
    """
    spec = get_model(model)
    if not spec:
        raise ImageGenError(MODEL_INVALID, "Unknown Magnific image model", model=model)
    minimum = 2 if spec["family"] == "google" else 1
    if not isinstance(prompt, str) or len(prompt.strip()) < minimum or (spec["promptMax"] and len(prompt) > spec["promptMax"]):
        raise ImageGenError(MODEL_INVALID, f"Prompt must contain {minimum}–{spec['promptMax'] or 'unlimited'} characters", model=model)
    if aspect_ratio not in spec["aspectRatios"]:
        raise ImageGenError(MODEL_INVALID, f"Supported aspect ratios: {', '.join(spec['aspectRatios'])}", model=model)
    resolutions = spec["resolutionOptions"]
    if resolutions and str(resolution).upper() not in resolutions:
        raise ImageGenError(MODEL_INVALID, f"Supported resolutions: {', '.join(resolutions)}", model=model)
    refs = list(reference_images or [])
    if len(refs) > spec["maxReferences"]:
        raise ImageGenError(MODEL_INVALID, f"This model accepts at most {spec['maxReferences']} references", model=model)
    if (model.endswith("-edit") or spec["requiresReference"]) and not refs:
        raise ImageGenError(MODEL_INVALID, "This model edits a reference image; add at least one", model=model)
    payload = {"prompt": prompt}
    if seed is not None:
        minimum_seed, maximum_seed = spec["seedRange"]
        if not spec["supportsSeed"] or isinstance(seed, bool) or not isinstance(seed, int) or not minimum_seed <= seed <= maximum_seed:
            raise ImageGenError(MODEL_INVALID, "Unsupported seed for this model", model=model)
        payload["seed"] = seed
    family = spec["family"]
    if family in ("flux-pro", "flux-turbo"):
        w, h = (int(part) for part in aspect_ratio.split(":"))
        minimum_side, maximum_side = (256, spec["maxSide"] or 1440) if family == "flux-pro" else (512, 2048)
        side = int(str(resolution).upper().replace("K", "")) * 1024
        factor = max(side / max(w, h), minimum_side / min(w, h))
        if max(w, h) * factor > maximum_side:
            raise ImageGenError(MODEL_INVALID, "The selected size exceeds this model's dimensions", model=model)
        size = {"width": round(w * factor), "height": round(h * factor)}
        payload.update(size if family == "flux-pro" else {"image_size": size})
    elif family == "google":
        payload.update({"aspect_ratio": aspect_ratio, "resolution": str(resolution).upper()})
    elif family == "runway":
        payload["ratio"] = {"1:1": "1024:1024", "16:9": "1920:1080", "9:16": "1080:1920",
                            "4:3": "1440:1080", "3:4": "1080:1440", "21:9": "1680:720"}[aspect_ratio]
    elif family == "z-image":
        payload["image_size"] = {"1:1": "square_hd", "16:9": "landscape_16_9", "9:16": "portrait_9_16",
                                 "4:3": "landscape_4_3", "3:4": "portrait_3_4"}[aspect_ratio]
    elif family == "raw":
        payload["aspect_ratio"] = aspect_ratio
    else:
        payload["aspect_ratio"] = (GPT_ASPECT_RATIOS if model.startswith("gpt-image") else ASPECT_RATIOS)[aspect_ratio]
    if spec["resolutionCase"] == "lower":
        payload["resolution"] = str(resolution).lower()
    if refs:
        if spec["referenceInput"] == "public-url":
            encoded = [_public_image_url(ref, check_cancel=check_cancel) for ref in refs]
        else:
            encoded = [_base64_image(ref, seedream=model.startswith("seedream")) for ref in refs]
        field = spec["refField"] or ("reference_objects" if family == "google" else
                                     "reference_images" if model.startswith("seedream") else "input_image")
        if field == "reference_objects":
            payload["reference_images"] = [{"image": value} for value in encoded]
        elif field == "input_image":
            payload.update({"input_image" if index == 0 else f"input_image_{index + 1}": value for index, value in enumerate(encoded)})
        else:
            payload[field] = encoded
        model = spec["edit_endpoint"] or model
    return _submit_and_poll(model, payload, check_cancel=check_cancel, sleep=sleep, on_submit=on_submit)


def _public_image_url(source, *, check_cancel=lambda: None, background=False):
    """Upload local bytes through Magnific; signed URLs are never persisted."""
    from dashboard import image_input, store

    value = image_input.resolve_served_image(source)
    if value.startswith("https://") and not background:
        image_input._reject_non_public_host(value)
        return value
    key = api_key()
    if not key:
        raise ImageGenError(PROVIDER_UNAVAILABLE, "Add the Magnific API key in Hermes Settings > Plugins > ImageGen", provider="magnific")
    data = store.fetch_image_bytes(value)
    mime = image_input.detect_mime(data)
    if mime not in ("image/png", "image/jpeg", "image/webp"):
        raise ImageGenError(MODEL_INVALID, "Use a PNG, JPEG or WebP image", model="magnific")
    if background and (mime not in ("image/png", "image/jpeg") or len(data) > 20 * 1024 * 1024):
        raise ImageGenError(MODEL_INVALID, "Background removal accepts PNG/JPEG images up to 20 MB", model="remove-background")
    if value.startswith("https://"):
        return value
    check_cancel()
    response = _request(key, payload={"files": [{"content_type": mime}]}, model="upload-request")
    files = response.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise ImageGenError(PROVIDER_FAILED, "Invalid Magnific upload response", provider="magnific")
    upload = files[0]
    try:
        for name in ("upload_url", "asset_url"):
            parsed = urlparse(upload[name])
            if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
                raise ValueError("Invalid upload URL")
            image_input._reject_non_public_host(upload[name])
        headers = upload.get("headers")
        if not isinstance(headers, dict) or any(str(name).lower() in ("authorization", "x-magnific-api-key", "cookie", "host") for name in headers):
            raise ValueError("Invalid upload headers")
        check_cancel()
        # The pre-signed storage request must never contain the API key.
        request = Request(upload["upload_url"], data=data, headers=headers, method="PUT")
        with build_opener(image_input._NoRedirect()).open(request, timeout=60):
            pass
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise ImageGenError(PROVIDER_FAILED, "Magnific reference upload failed; generation was not submitted", provider="magnific") from exc
    check_cancel()
    return upload["asset_url"]


def _base64_image(source, *, seedream=False):
    from PIL import Image
    from dashboard import store, image_input

    data = store.fetch_image_bytes(source)
    mime = image_input.detect_mime(data)
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        raise ImageGenError(MODEL_INVALID, "Use a PNG, JPEG or WebP image", model="magnific")
    if seedream:
        if len(data) > 10 * 1024 * 1024 or mime not in ("image/jpeg", "image/png"):
            raise ImageGenError(MODEL_INVALID, "Seedream references must be PNG/JPEG up to 10 MB", model="magnific")
        with Image.open(io.BytesIO(data)) as image:
            if min(image.size) < 256:
                raise ImageGenError(MODEL_INVALID, "Seedream references must be at least 256 × 256 pixels", model="magnific")
    return base64.b64encode(data).decode("ascii")


def _submit_and_poll(model, payload, *, check_cancel, sleep, on_submit=None, text=False):
    """Submit once and poll; ``text`` tasks (prompt helpers) return words, not image URLs."""
    from dashboard import billing

    key = api_key()
    if not key:
        raise ImageGenError(PROVIDER_UNAVAILABLE, "Add the Magnific API key in Hermes Settings > Plugins > ImageGen", provider="magnific")
    check_cancel()
    data = billing.run("magnific", model, None, lambda: _request(key, payload=payload, model=model))
    task_id = data.get("task_id")
    if on_submit and isinstance(task_id, str) and task_id:
        on_submit({"provider": "magnific", "model": model, "endpoint": model, "requestId": task_id})
    deadline = time.monotonic() + 300
    empty_polls = 0
    while True:
        check_cancel()
        status = str(data.get("status", "")).upper()
        if status == "COMPLETED":
            generated = data.get("generated")
            if text:
                words = next((item for item in generated if isinstance(item, str) and item.strip()), "") if isinstance(generated, list) else ""
                if not words:
                    raise ImageGenError(PROVIDER_FAILED, "Magnific returned no text", provider="magnific", model=model)
                return {"text": words.strip(), "provider": "magnific", "model": model, "task_id": task_id}
            images =[url for url in generated if isinstance(url, str) and url.startswith("https://")] if isinstance(generated, list) else []
            if not images:
                # A finished task can list its images a moment after it reports COMPLETED.
                if empty_polls < EMPTY_RESULT_POLLS:
                    empty_polls += 1
                    sleep(2)
                    check_cancel()
                    data = _request(key, task_id=task_id, model=model)
                    continue
                raise ImageGenError(MODEL_NO_IMAGE, "Magnific returned no images", model=model, provider="magnific")
            return {"images": images, "provider": "magnific", "model": model, "task_id": task_id}
        if status in ("FAILED", "ERROR", "CANCELLED", "CANCELED"):
            reason = data.get("error")
            detail = f"Magnific task {task_id} ended with status {status}" + (f": {reason}" if reason else "")
            raise ImageGenError(PROVIDER_FAILED, detail, provider="magnific", detail=detail)
        if not isinstance(task_id, str) or not task_id or status not in ("CREATED", "IN_PROGRESS", "PENDING", "QUEUED"):
            raise ImageGenError(PROVIDER_FAILED, "Invalid Magnific task response", provider="magnific", detail="Missing task ID or unknown status")
        if time.monotonic() >= deadline:
            detail = f"Magnific task {task_id} is still pending; check the provider before submitting again"
            raise ImageGenError(PROVIDER_FAILED, detail, provider="magnific", detail=detail)
        sleep(2)
        check_cancel()
        data = _request(key, task_id=task_id, model=model)


def fetch_result(task_id: str, model: str = MODEL_ID) -> Dict[str, Any]:
    """Retrieve an existing task without submitting a new paid request."""
    key = api_key()
    if not key:
        raise ImageGenError(PROVIDER_UNAVAILABLE, "Add the Magnific API key in Hermes Settings > Plugins > ImageGen", provider="magnific")
    data = _request(key, task_id=task_id, model=model)
    if str(data.get("status", "")).upper() != "COMPLETED":
        raise ImageGenError(PROVIDER_FAILED, "Magnific task is not completed; recover it again later", provider="magnific", detail=str(data.get("status")))
    return {"images": data.get("generated") or [], "provider": "magnific", "model": model}


def upscale(image: str, *, mode="classic", scale=2, creativity=0.4, prompt="", flavor="", check_cancel, sleep, on_submit=None):
    import base64
    import io
    from PIL import Image
    from dashboard import store

    data = store.fetch_image_bytes(image)
    payload = {"image": base64.b64encode(data).decode("ascii")}
    model = "image-upscaler-precision"
    if mode == "precision-v2":
        model = "image-upscaler-precision-v2"
        payload["scale_factor"] = scale
        if flavor:
            payload["flavor"] = flavor
    elif mode == "creative":
        with Image.open(io.BytesIO(data)) as source:
            if source.width * source.height * scale * scale > 25_300_000:
                raise ImageGenError(MODEL_INVALID, "Magnific output must not exceed 25.3 megapixels", model="image-upscaler")
        model = "image-upscaler"
        payload.update({"scale_factor": f"{scale}x", "prompt": prompt, "creativity": round(creativity * 20 - 10)})
    return _submit_and_poll(model, payload, check_cancel=check_cancel, sleep=sleep, on_submit=on_submit)


def edit_operation(kind, body, *, check_cancel, sleep, on_submit=None):
    """Operation-specific payloads; all asynchronous edits share job recovery."""
    common = {"check_cancel": check_cancel, "sleep": sleep, "on_submit": on_submit}
    if kind == "bg-remove":
        from dashboard import billing
        key = api_key()
        if not key:
            raise ImageGenError(PROVIDER_UNAVAILABLE, "Add the Magnific API key in Hermes Settings > Plugins > ImageGen", provider="magnific")
        value = _public_image_url(body["image"], check_cancel=check_cancel, background=True)
        check_cancel()
        data = billing.run("magnific", "remove-background", None,
                           lambda: _request(key, payload={"image_url": value}, model="remove-background"))
        url = data.get("high_resolution") or data.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ImageGenError(MODEL_NO_IMAGE, "Magnific returned no image", model="remove-background")
        return {"images": [url], "provider": "magnific", "model": "remove-background"}
    if kind == "camera":
        payload = {"image": _public_image_url(body["image"], check_cancel=check_cancel),
                   "horizontal_angle": int(body.get("horizontalAngle", 0)),
                   "vertical_angle": int(body.get("verticalAngle", 0)), "zoom": int(body.get("zoom", 5))}
        return _submit_and_poll("image-change-camera", payload, **common)
    if kind == "skin":
        mode = body.get("skinMode", "faithful")
        payload = {"image": _base64_image(body["image"]), "sharpen": int(body.get("sharpen", 0)),
                   "smart_grain": int(body.get("smartGrain", 2))}
        if mode == "faithful":
            payload["skin_detail"] = int(body.get("skinDetail", 80))
        elif mode == "flexible":
            payload["optimized_for"] = body.get("optimizedFor", "enhance_skin")
        return _submit_and_poll(f"skin-enhancer-{mode}", payload, **common)
    payload = {"image": _base64_image(body["image"]), "prompt": body.get("prompt", "")}
    if kind == "inpaint":
        image, mask = _inverted_mask(body["image"], body["maskImage"])
        return _submit_and_poll("ideogram-image-edit", {"image": image, "mask": mask, "prompt": body["prompt"]}, **common)
    if kind == "outpaint":
        direction, amount = body.get("direction", "all"), int(body.get("expandPx", 256))
        payload.update({side: amount if direction in ("all", side) else 0 for side in ("left", "right", "top", "bottom")})
        if not payload["prompt"] and body.get("expandModel", "flux-pro") != "flux-pro":
            del payload["prompt"]  # Ideogram and Seedream write their own prompt from the image.
        return _submit_and_poll(EXPAND_MODELS[body.get("expandModel", "flux-pro")], payload, **common)
    if kind == "relight":
        payload.update({"light_transfer_strength": int(body.get("strength", 100)),
                        "change_background": bool(body.get("changeBackground", False)), "preserve_details": True})
        if body.get("referenceImage"):
            payload["transfer_light_from_reference_image"] = _base64_image(body["referenceImage"])
        return _submit_and_poll("image-relight", payload, **common)
    if kind == "style-transfer":
        payload.update({"reference_image": _base64_image(body["referenceImage"]),
                        "style_strength": int(body.get("strength", 100)),
                        "structure_strength": int(body.get("structureStrength", 50))})
        return _submit_and_poll("image-style-transfer", payload, **common)
    raise ImageGenError(MODEL_INVALID, "Unsupported Magnific image operation", model=kind)


def _inverted_mask(image, mask):
    """Ideogram edits the black part of its mask; the ImageGen brush paints the area white."""
    from PIL import Image, ImageOps
    from dashboard import store

    with Image.open(io.BytesIO(store.fetch_image_bytes(image))) as source:
        scene = ImageOps.exif_transpose(source)
        size = scene.size
    with Image.open(io.BytesIO(store.fetch_image_bytes(mask))) as source:
        painted = ImageOps.exif_transpose(source).convert("L")
    if painted.size != size:
        raise ImageGenError(MODEL_INVALID, "Mask dimensions must match the original image", model="ideogram-image-edit")
    buffer = io.BytesIO()
    ImageOps.invert(painted).save(buffer, format="PNG")
    return _base64_image(image), base64.b64encode(buffer.getvalue()).decode("ascii")


def prompt_helper(kind, value, *, check_cancel, sleep, language="en"):
    """Describe an image as a prompt, or improve a written prompt; returns ``{"text": ...}``."""
    if kind == "describe":
        return _submit_and_poll("image-to-prompt", {"image": _base64_image(value)},
                                check_cancel=check_cancel, sleep=sleep, text=True)
    if not isinstance(value, str) or len(value) > 2500:
        raise ImageGenError(MODEL_INVALID, "Prompts to improve must have up to 2,500 characters", model="improve-prompt")
    return _submit_and_poll("improve-prompt", {"prompt": value, "type": "image", "language": language or "en"},
                            check_cancel=check_cancel, sleep=sleep, text=True)
