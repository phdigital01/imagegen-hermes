"""Validated factories shared by operation routes and explicit retries."""
from copy import deepcopy

from fastapi import HTTPException

from dashboard import edit_merge, gen_service, magnific_api
from dashboard.generation_artifacts import build_generation_job, save_generation_artifacts

RETRY_KINDS = {"generate", "vary", "edit", "inpaint", "outpaint", "upscale", "bg-remove", "magnific", "relight", "style-transfer",
               "camera", "skin"}
MAGNIFIC_ONLY = ("relight", "style-transfer", "camera", "skin")
# What a generation provider that takes references and a prompt (GPT Image, say) can do.
REFERENCE_KINDS = ("edit", "inpaint", "outpaint", *MAGNIFIC_ONLY)


def build_operation(kind, payload):
    body = deepcopy(payload)
    if kind not in RETRY_KINDS:
        raise HTTPException(409, "This operation must be started from its original screen")
    if kind == "generate" or (kind == "vary" and not body.get("image")):
        return build_generation_job(body)
    if kind == "magnific":
        return build_generation_job({**body, "provider": "magnific", "model": body.get("model") or "mystic"})
    if body.get("provider", "fal") not in ("fal", "magnific") and kind not in REFERENCE_KINDS:
        raise HTTPException(400, "Select FAL or Magnific for image operations")
    if ((kind in MAGNIFIC_ONLY and body.get("provider", "fal") == "fal") or (kind == "upscale" and body.get("mode") == "precision-v2" and body.get("provider") != "magnific")):
        raise HTTPException(400, "This operation uses Magnific")
    required = {"edit": ("images", "prompt"), "inpaint": ("baseImage", "maskImage", "prompt"),
                "style-transfer": ("image", "referenceImage")}.get(kind, ("image",))
    if any(not body.get(key) for key in required):
        raise HTTPException(400, "Required fields: " + ", ".join(required))
    if kind == "edit" and (not isinstance(body["images"], list) or not 1 <= len(body["images"]) <= 9):
        raise HTTPException(400, "Supply between 1 and 9 images")
    if kind == "inpaint" and body.get("productImage"):
        raise HTTPException(400, "Flux Fill does not accept an additional product reference")
    if kind == "relight" and not (body.get("prompt") or body.get("referenceImage")):
        raise HTTPException(400, "Describe the lighting or supply a reference image")
    try:
        expand = int(body.get("expandPx", 256))
        scale = int(body.get("scale", 2))
        creativity = float(body.get("creativity", 0.4))
        strength = int(body.get("strength", 100))
        structure_strength = int(body.get("structureStrength", 50))
        camera = [int(body.get(name, default)) for name, default in (("horizontalAngle", 0), ("verticalAngle", 0), ("zoom", 5))]
        skin = [int(body.get(name, default)) for name, default in (("sharpen", 0), ("smartGrain", 2), ("skinDetail", 80))]
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid operation parameters") from None
    if kind == "outpaint" and (not 1 <= expand <= 2048 or body.get("direction", "all") not in ("all", "left", "right", "top", "bottom")):
        raise HTTPException(400, "Choose a valid direction and expansion between 1 and 2048 pixels")
    if kind == "outpaint" and body.get("expandModel", "flux-pro") not in magnific_api.EXPAND_MODELS:
        raise HTTPException(400, "Choose Flux Pro, Ideogram or Seedream 4.5 to expand")
    upscale_mode = body.get("mode", "classic")
    if kind == "upscale" and (upscale_mode not in ("classic", "creative", "precision-v2") or not 0 <= creativity <= 1
                              or scale not in ((2, 4, 8, 16) if upscale_mode == "precision-v2" else (2, 4))
                              or body.get("flavor", "") not in ("", *magnific_api.UPSCALE_FLAVORS)):
        raise HTTPException(400, "Use scale 2 or 4 (up to 16 for Precision v2) and creativity between 0 and 1")
    if kind == "camera" and not (0 <= camera[0] <= 360 and -30 <= camera[1] <= 90 and 0 <= camera[2] <= 10):
        raise HTTPException(400, "Use a horizontal angle of 0-360, a vertical angle of -30-90 and zoom of 0-10")
    if kind == "skin" and (body.get("skinMode", "faithful") not in magnific_api.SKIN_MODES or not all(0 <= value <= 100 for value in skin)
                           or body.get("optimizedFor", "enhance_skin") not in magnific_api.SKIN_TARGETS):
        raise HTTPException(400, "Choose a skin mode and keep its settings between 0 and 100")
    if kind in ("relight", "style-transfer") and not (0 <= strength <= 100 and 0 <= structure_strength <= 100):
        raise HTTPException(400, "Strength must be between 0 and 100")

    # A one-image edit keeps every pixel the model did not change, unless the person asks for the whole answer.
    keep = body.get("keepUnchanged", True) is not False
    by_reference = kind in REFERENCE_KINDS and body.get("provider", "fal") not in ("fal", "magnific")
    if by_reference and not body.get("model"):
        raise HTTPException(400, "A model is required")

    def run(job):
        common = {"cancel": job.check_cancelled, "on_submit": job.checkpoint}
        if by_reference and kind not in ("edit", "inpaint"):
            result = edit_merge.operation_with_provider(kind, body, body["provider"], body["model"], **common)
        elif by_reference:
            images = body.get("images") or [body["baseImage"]]
            result = edit_merge.edit_with_provider(images[0], body["prompt"], body["provider"], body["model"],
                mask_image=body.get("maskImage"), references=images[1:], keep=keep, **common)
        elif kind in ("edit", "vary"):
            prompt = body.get("prompt", "")
            if kind == "vary":
                prompt = f"Create a subtle variation while preserving the subject and composition. {prompt}"
            images = body.get("images") or [body["image"]]
            if body.get("provider") == "magnific":
                result = gen_service.generate_magnific(body.get("model") or "flux-2-pro", prompt,
                    aspect_ratio=body.get("aspectRatio", "1:1"), resolution=body.get("resolution", "1K"),
                    seed=body.get("seed"), reference_images=images, **common)
            else:
                result = gen_service.generate_edit(image_paths=images, prompt=prompt,
                    model=body.get("model") or "fal-ai/flux-2-pro/edit", seed=body.get("seed"), **common)
        elif kind == "inpaint" and body.get("provider") != "magnific":
            result = gen_service.generate_inpaint(body["baseImage"], body["maskImage"], body["prompt"], **common)
        elif body.get("provider") == "magnific" and kind in ("inpaint", "outpaint", "bg-remove", *MAGNIFIC_ONLY):
            result = magnific_api.edit_operation(kind, {**body, "image": body.get("image") or body.get("baseImage")}, check_cancel=lambda: gen_service._check_cancel(job.check_cancelled),
                sleep=lambda delay: gen_service._cancellable_sleep(job.check_cancelled, delay), on_submit=job.checkpoint)
        elif kind == "outpaint":
            result = gen_service.generate_outpaint(body["image"], body.get("prompt", ""), body.get("direction", "all"), expand, **common)
        elif kind == "upscale":
            if body.get("provider") == "magnific":
                result = magnific_api.upscale(body["image"], mode=upscale_mode, scale=scale, creativity=creativity,
                    prompt=body.get("prompt", ""), flavor=body.get("flavor", ""), check_cancel=lambda: gen_service._check_cancel(job.check_cancelled),
                    sleep=lambda delay: gen_service._cancellable_sleep(job.check_cancelled, delay), on_submit=job.checkpoint)
            else:
                result = gen_service.generate_upscale(body["image"], creativity, scale, body.get("mode", "classic"), body.get("prompt", ""), **common)
        else:
            result = gen_service.generate_bg_remove(body["image"], **common)
        if not result.get("images"):
            raise HTTPException(502, "The provider returned no image")
        if keep and not by_reference and kind == "inpaint":
            result = edit_merge.keep_source(body["baseImage"], result, body["maskImage"])
        elif keep and not by_reference and kind == "edit" and len(body["images"]) == 1:
            result = edit_merge.keep_source(body["images"][0], result)
        elif keep and not by_reference and kind == "outpaint":
            result = edit_merge.keep_expanded(body["image"], result, body.get("direction", "all"), expand)
        saved = save_generation_artifacts({**body, "kind": kind, "generationId": f"{job.id}-0"}, result)
        job.save_partial(saved, completed_request=True)
        return saved

    return run
