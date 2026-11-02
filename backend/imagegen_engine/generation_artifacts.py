"""Persist generated images and run recoverable text-to-image jobs."""
from __future__ import annotations

import logging
import uuid
from copy import deepcopy
from typing import Any, Dict, List

from fastapi import HTTPException

from imagegen_engine import gen_service, image_input, store
from imagegen_engine.model_profiles import build_intent

logger = logging.getLogger(__name__)
resolve_served_image = image_input.resolve_served_image


def save_generation_artifacts(body: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """Save durable image URLs, actual provider metadata, history, and handoff.

    Stable generation IDs make recovery writes idempotent. Storage failures
    remain visible in the result instead of hiding a lost gallery image.
    """
    generation_id = str(body.get("generationId") or result.get("generationId") or uuid.uuid4().hex)
    if not image_input.is_safe_id(generation_id):
        raise ValueError("Invalid generation ID")
    provider = result.get("provider") or body.get("provider", "fal")
    model = result.get("model") or body.get("model", "")
    prompt = str(body.get("prompt") or "")
    config = deepcopy(body.get("config") or {})
    config.update({"provider": provider, "selectedModel": model})
    if provider == "magnific":
        from imagegen_engine.magnific_catalog import generation_model
        config["selectedModel"] = generation_model(model)
    for field in ("aspectRatio", "seed", "negativePrompt", "resolution"):
        if field in body:
            config[field] = body[field]
    images = list(result.get("images") or [])
    gallery_ids: List[str] = []
    entries: List[Dict[str, Any]] = []
    warnings = list(result.get("warnings") or [])
    if body.get("saveToGallery", True):
        for index, image in enumerate(images):
            try:
                entry = store.save_gallery_entry(store.fetch_image_bytes(image, max_bytes=image_input.MAX_RESULT_BYTES), {
                    "id": f"{generation_id}-{index}", "generationId": generation_id,
                    "provider": provider, "model": model, "prompt": prompt,
                    "aspect_ratio": config.get("aspectRatio", "1:1"),
                    "seed": config.get("seed"), "negative_prompt": config.get("negativePrompt"),
                    "config": config, "kind": body.get("kind", "generate"), "index": index,
                })
                images[index] = entry["url"]
                gallery_ids.append(entry["id"])
                entries.append({key: entry.get(key, "") for key in ("id", "localPath", "outputPath")})
                if entry.get("outputPath"):
                    result.setdefault("output_paths", []).append(entry["outputPath"])
            except Exception:
                logger.exception("Could not persist image %s/%s", generation_id, index)
                warnings.append(f"Image {index + 1} could not be saved to the gallery. Download it before its provider URL expires.")
    result.update({"images": images, "gallery_ids": gallery_ids, "generationId": generation_id})
    try:
        store.add_history({
            "id": generation_id, "kind": body.get("kind", "generate"),
            "provider": provider, "model": model, "prompt": prompt, "images": images,
            "gallery_ids": gallery_ids, "gallery_entries": entries, "config": config,
        })
    except Exception:
        logger.exception("Could not persist generation history %s", generation_id)
        warnings.append("Generation history could not be saved.")
    try:
        handoff = store.save_handoff({
            "id": generation_id, "generationId": generation_id,
            "paths": [entry["localPath"] for entry in entries if entry.get("localPath")],
            "images": images, "prompt": prompt, "provider": provider, "model": model,
            "intent": body.get("intent") or build_intent({**config, "prompt": prompt}),
            "references": body.get("referenceImages") or config.get("referencesV4") or [],
            "parentId": body.get("parentId"), "galleryIds": gallery_ids,
        })
        result["handoff_id"] = handoff["id"]
    except Exception:
        logger.exception("Could not persist generation handoff %s", generation_id)
        warnings.append("The agent handoff could not be saved.")
    if warnings:
        result["warnings"] = warnings
    return result


def parse_num_images(body: Dict[str, Any]) -> int:
    raw = body.get("numImages", 1)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid numImages") from None
    if isinstance(raw, bool) or str(value) != str(raw).strip() or not 1 <= value <= gen_service.MAX_GENERATIONS:
        raise HTTPException(status_code=400, detail=f"numImages must be an integer between 1 and {gen_service.MAX_GENERATIONS}")
    return value


def build_generation_job(body: Dict[str, Any]):
    """Persist each image before starting the next paid request in a batch."""
    body = deepcopy(body)
    count = parse_num_images(body)
    if not isinstance(body.get("prompt"), str) or not body["prompt"].strip():
        raise HTTPException(status_code=400, detail="A non-empty prompt is required")
    if not isinstance(body.get("model"), str) or not body["model"].strip():
        raise HTTPException(status_code=400, detail="A model is required")

    def run(job):
        combined: Dict[str, Any] = {"images": [], "gallery_ids": [], "warnings": []}
        for index in range(count):
            gen_service._check_cancel(job.check_cancelled)
            job.progress = index / count
            job.message = f"{body.get('provider', 'fal')} · {index + 1}/{count}"
            seed = gen_service._validate_seed(body.get("seed"))
            seed = (seed + index) % (2 ** 32) if seed is not None else None
            artifact = {**body, "seed": seed, "generationId": f"{job.id}-{index}"}
            result = gen_service.generate_text_to_image(
                provider=body.get("provider", "fal"), model=body["model"], prompt=body["prompt"],
                aspect_ratio=body.get("aspectRatio", "1:1"), seed=seed,
                negative_prompt=body.get("negativePrompt"), num_images=1,
                resolution=body.get("resolution", "1K"), reference_images=body.get("referenceImages") or [],
                cancel=job.check_cancelled, on_submit=lambda remote: job.checkpoint({**remote, "artifactBody": artifact}),
            )
            result = save_generation_artifacts(artifact, result)
            for key in ("images", "gallery_ids", "warnings", "output_paths"):
                combined.setdefault(key, [])
                combined[key].extend(result.get(key) or [])
            for key in ("provider", "model", "modality", "references_used", "handoff_id"):
                if key in result:
                    combined[key] = result[key]
            job.progress = (index + 1) / count
            job.save_partial(combined, completed_request=True)
        return combined

    return run


class InlineJob:
    """The slice of ``jobs.Job`` that ``build_generation_job`` touches, for a call made outside the job queue."""

    def __init__(self, source: str = "chat") -> None:
        # Unique per call: gallery writes are idempotent per generation id.
        self.id = f"{source}{uuid.uuid4().hex[:16]}"
        self.progress = 0.0
        self.message = ""

    def check_cancelled(self) -> bool:
        return False

    def checkpoint(self, remote: Dict[str, Any]) -> None:
        pass

    def save_partial(self, result: Dict[str, Any], *, completed_request: bool = False) -> None:
        pass
