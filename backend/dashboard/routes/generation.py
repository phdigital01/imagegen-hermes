"""Generation routes: text-to-image, vary, upscale, bg-remove, edit, inpaint,
outpaint, camera, skin, magnific, prompt helpers, and the D-MASS batch matrix."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from fastapi import Body, HTTPException, Request

from dashboard import gen_service, llm_service
from dashboard.api_core import _abs_images, _imagegen_error_http, _to_thread, coerce_body, make_router
from dashboard.errors import ImageGenError
from dashboard.generation_artifacts import (
    parse_num_images,
    save_generation_artifacts,
)

logger = logging.getLogger(__name__)

router = make_router()


@router.post("/generate")
async def generate(request: Request, body: Any = Body(None)) -> Dict[str, Any]:
    """Route A — generation by provider. Supports save_to_gallery."""
    body = coerce_body(body)
    provider = body.get("provider", "fal")
    model = body.get("model", "")
    prompt = body.get("prompt", "")
    aspect_ratio = body.get("aspectRatio", "1:1")
    seed = body.get("seed")
    negative_prompt = body.get("negativePrompt")
    num_images = parse_num_images(body)
    save = bool(body.get("saveToGallery", True))
    if not isinstance(prompt, str) or not prompt.strip():
        raise HTTPException(status_code=400, detail="Empty prompt")

    try:
        result = await _to_thread(
            gen_service.generate_text_to_image,
            provider=provider,
            model=model,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            seed=seed,
            negative_prompt=negative_prompt,
            num_images=num_images,
            resolution=body.get("resolution", "1K"),
            reference_images=body.get("referenceImages") or [],
        )
    except ImageGenError as exc:
        logger.error("generate failed (%s): %s", exc.code, exc.message)
        raise _imagegen_error_http(exc) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("generate failed")
        raise HTTPException(status_code=502, detail="Image generation failed") from exc

    if save:
        result = save_generation_artifacts(body, result)
    result["images"] = _abs_images(request, result.get("images"))
    return result


def _submit_operation(kind: str, body: Any) -> Dict[str, Any]:
    from dashboard import jobs
    from dashboard.operations import build_operation

    payload = {**coerce_body(body), "kind": kind}
    return jobs.manager.submit(kind, build_operation(kind, payload), payload=payload).to_dict()


@router.post("/vary")
async def vary_image(body: Any = Body(None)) -> Dict[str, Any]:
    return _submit_operation("vary", body)


@router.post("/upscale")
async def upscale_image(body: Any = Body(None)) -> Dict[str, Any]:
    return _submit_operation("upscale", body)


@router.post("/bg-remove")
async def bg_remove(body: Any = Body(None)) -> Dict[str, Any]:
    return _submit_operation("bg-remove", body)


@router.post("/edit")
async def edit_image(body: Any = Body(None)) -> Dict[str, Any]:
    return _submit_operation("edit", body)


@router.post("/relight")
async def relight_image(body: Any = Body(None)) -> Dict[str, Any]:
    return _submit_operation("relight", body)


@router.post("/style-transfer")
async def style_transfer_image(body: Any = Body(None)) -> Dict[str, Any]:
    return _submit_operation("style-transfer", body)


@router.post("/camera")
async def change_camera(body: Any = Body(None)) -> Dict[str, Any]:
    return _submit_operation("camera", body)


@router.post("/skin")
async def enhance_skin(body: Any = Body(None)) -> Dict[str, Any]:
    return _submit_operation("skin", body)


@router.post("/prompt-helper")
async def prompt_helper(body: Any = Body(None)) -> Dict[str, Any]:
    """Magnific prompt helpers: describe an image, or improve a written prompt."""
    from dashboard import magnific_api

    payload = coerce_body(body)
    kind = payload.get("action")
    value = payload.get("image") if kind == "describe" else payload.get("prompt")
    if kind not in ("describe", "improve") or not isinstance(value, str) or not value.strip():
        raise HTTPException(400, "Send an image to describe or a prompt to improve")
    try:
        result = await _to_thread(magnific_api.prompt_helper, kind, value, language=str(payload.get("language") or "en"),
                                  check_cancel=lambda: None, sleep=time.sleep)
    except ImageGenError as exc:
        raise _imagegen_error_http(exc) from exc
    except (RuntimeError, ValueError) as exc:  # Unreadable or oversized image.
        raise HTTPException(400, str(exc)) from exc
    return {"text": result["text"]}


@router.post("/inpaint")
async def inpaint_image(body: Any = Body(None)) -> Dict[str, Any]:
    return _submit_operation("inpaint", body)


@router.post("/outpaint")
async def outpaint_image(body: Any = Body(None)) -> Dict[str, Any]:
    return _submit_operation("outpaint", body)


@router.post("/magnific")
async def magnific_call(body: Any = Body(None)) -> Dict[str, Any]:
    payload = coerce_body(body)
    if payload.get("tool"):
        raise HTTPException(400, "Select a Magnific API model; MCP tool names are not supported")
    if payload.get("image") and not payload.get("referenceImages"):
        payload["referenceImages"] = [payload["image"]]
    return _submit_operation("magnific", payload)

@router.post("/batch/matrix")
async def batch_matrix(body: Any = Body(None)) -> Dict[str, Any]:
    """D-MASS — Creative matrix: fixed object × environments × text zones → grid."""
    body = coerce_body(body)
    from dashboard import jobs

    image = body.get("image", "")
    scenes = body.get("scenes", [])
    zones = body.get("zones", [{"id": "none", "label": "No zone", "prompt": ""}])
    if not image or not scenes:
        raise HTTPException(status_code=400, detail="image and scenes are required")
    if not isinstance(scenes, list) or not isinstance(zones, list) or not zones or any(not isinstance(item, dict) for item in scenes + zones):
        raise HTTPException(400, "Scenes and zones must be non-empty lists of objects")
    if len(scenes) > 6 or len(zones) > 6:
        raise HTTPException(status_code=400, detail="Maximum of 6 environments × 6 zones")

    def _run(job: jobs.Job) -> Dict[str, Any]:
        total = len(scenes) * len(zones)
        cells: list[Dict[str, Any]] = []
        def snapshot():
            return {"matrix": cells, "images": [url for cell in cells for url in cell.get("images", [])],
                    "scenes": [scene.get("title", "") for scene in scenes], "zones": [zone.get("label", "") for zone in zones]}
        # V3: memoize composition per scene (vision is 2 calls per scene, not per zone)
        comp_cache: Dict[str, Dict[str, Any]] = {}
        subject_type = body.get("subjectType", "objeto_produto")
        aspect_ratio = body.get("aspectRatio", "4:5")
        genre_val = body.get("genre", "ad_product")
        fidelity_val = int(body.get("fidelity", 90))
        keep_val = body.get("keep", ["Composição", "Textura", "Estilo"])
        vary_val = body.get("vary", [])

        def _get_comp(sc: Dict[str, Any]) -> Dict[str, Any]:
            scene_text = sc.get("sceneText", "") or sc.get("title", "")
            # cache key: scene text + subject/genre/fidelity — covers all vision-varying inputs
            key = f"{scene_text}\x1f{subject_type}\x1f{aspect_ratio}\x1f{genre_val}\x1f{fidelity_val}"
            if key not in comp_cache:
                comp_cache[key] = llm_service.llm_composition_analyze(
                    scene=scene_text,
                    images=[image],
                    subject_type=subject_type,
                    aspect_ratio=aspect_ratio,
                    refs_meta=[{
                        "label": "Produto", "semanticRole": "object_primary",
                        "fixedProduct": True, "fidelity": fidelity_val,
                        "keep": keep_val,
                        "vary": vary_val,
                    }],
                    genre=genre_val,
                )
            return comp_cache[key]

        idx = 0
        for sc in scenes:
            gen_service._check_cancel(job.check_cancelled)
            # compute once per scene, outside zone loop
            try:
                comp = _get_comp(sc)
                comp_error = None
            except Exception as exc:  # noqa: BLE001
                comp = None  # type: ignore[assignment]
                comp_error = str(exc)
            for zone in zones:
                gen_service._check_cancel(job.check_cancelled)
                idx += 1
                job.progress = (idx - 1) / total
                job.message = f"{sc.get('title', 'Scene')} × {zone.get('label', 'zone')} ({idx}/{total})"
                if comp_error is not None:
                    cells.append({"scene": sc.get("title", ""), "zone": zone.get("label", ""), "error": comp_error})
                    continue
                try:
                    assert comp is not None
                    zone_prompt = zone.get("prompt", "")
                    final_prompt = comp["prompt"]
                    if zone_prompt:
                        final_prompt = f"{final_prompt}, {zone_prompt}"
                    artifact = {**body, "prompt": final_prompt, "kind": "matrix", "generationId": f"{job.id}-{idx - 1}"}
                    cell = {"scene": sc.get("title", ""), "zone": zone.get("label", ""), "prompt": final_prompt}
                    gen = gen_service.generate_text_to_image(
                        provider=body.get("provider", "fal"),
                        model=body.get("model", ""),
                        prompt=final_prompt,
                        aspect_ratio=aspect_ratio,
                        reference_images=[image],
                        seed=None,
                        num_images=1,
                        resolution=body.get("resolution", "1K"),
                        cancel=job.check_cancelled,
                        on_submit=lambda remote: job.checkpoint({**remote, "artifactBody": artifact, "cell": cell}),
                    )
                    gen = save_generation_artifacts(artifact, gen)
                    cells.append({
                        "scene": sc.get("title", ""), "zone": zone.get("label", ""),
                        "prompt": final_prompt, "images": gen.get("images", []),
                    })
                    job.save_partial(snapshot(), completed_request=True)
                except Exception as exc:  # noqa: BLE001
                    if isinstance(exc, gen_service.JobCancelledError) or any(not remote.get("saved") for remote in job.remotes):
                        raise
                    cells.append({"scene": sc.get("title", ""), "zone": zone.get("label", ""), "error": str(exc)})
                    job.save_partial(snapshot())
        job.progress = 1.0
        return snapshot()

    job = jobs.manager.submit("matrix", _run, payload={
        **body,
        "image": image,
        "scenes": scenes,
        "zones": zones,
        "provider": body.get("provider", "fal"),
        "model": body.get("model", ""),
        "aspectRatio": body.get("aspectRatio", "4:5"),
        "subjectType": body.get("subjectType", "objeto_produto"),
        "genre": body.get("genre", "ad_product"),
        "fidelity": body.get("fidelity", 90),
        "resolution": body.get("resolution", "1K"),
        "kind": "matrix",
    })
    return job.to_dict()
