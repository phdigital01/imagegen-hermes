"""Job routes: async generation pipeline lifecycle (list/status/result/cancel/
retry/resume/submit)."""
from __future__ import annotations

import json
from copy import deepcopy
import logging
from typing import Any, Dict

from fastapi import Body, HTTPException, Request

from imagegen_engine import gen_service
from imagegen_engine.api_core import _abs_images, _imagegen_error_http, _to_thread, make_router
from imagegen_engine.errors import ImageGenError
from imagegen_engine.generation_artifacts import (
    parse_num_images,
    save_generation_artifacts,
)

logger = logging.getLogger(__name__)

router = make_router()


@router.get("/jobs")
async def jobs_list() -> Dict[str, Any]:
    from imagegen_engine import jobs

    return {"jobs": jobs.manager.list()}


@router.get("/jobs/{job_id}")
async def jobs_status(job_id: str) -> Dict[str, Any]:
    from imagegen_engine import jobs

    job = jobs.manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.to_dict()


@router.get("/jobs/{job_id}/result")
async def jobs_result(request: Request, job_id: str) -> Dict[str, Any]:
    from imagegen_engine import jobs

    job = jobs.manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    if job.result is None:
        raise HTTPException(status_code=409, detail=f"job {job.status}")
    response = deepcopy(job.to_dict(include_result=True))
    result = response["result"]
    result["images"] = _abs_images(request, result.get("images") or [])
    for key in ("matrix", "variations"):
        for item in result.get(key) or []:
            if isinstance(item, dict) and item.get("images"):
                item["images"] = _abs_images(request, item["images"])
    return response

@router.post("/jobs/{job_id}/cancel")
async def jobs_cancel(job_id: str) -> Dict[str, Any]:
    from imagegen_engine import jobs

    job = jobs.manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    ok = jobs.manager.cancel(job_id)
    return {"ok": ok}


@router.post("/jobs/{job_id}/retry")
async def jobs_retry(job_id: str) -> Dict[str, Any]:
    from imagegen_engine import jobs

    previous = jobs.manager.get(job_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="job not found")
    from imagegen_engine.operations import build_operation
    if not previous.to_dict().get("retryable"):
        raise HTTPException(409, "Recover pending provider results before starting another request")
    payload = deepcopy(previous.payload)
    payload["clientRequestId"] = f"retry-{job_id}"
    if previous.kind in ("generate", "magnific", "vary") and not payload.get("image"):
        done = len((previous.result or {}).get("images") or [])
        remaining = parse_num_images(payload) - done
        if remaining <= 0:
            raise HTTPException(409, "All requested images are already available")
        payload["numImages"] = remaining
        if payload.get("seed") is not None:
            payload["seed"] = (int(payload["seed"]) + done) % (2 ** 32)
    retried = jobs.manager.submit(previous.kind, build_operation(previous.kind, payload), payload=payload)
    return retried.to_dict()


@router.post("/jobs/{job_id}/resume")
async def jobs_resume(job_id: str) -> Dict[str, Any]:
    """Retrieve accepted requests only; never submit generation during recovery."""
    from imagegen_engine import jobs, magnific_api

    if jobs.manager.get(job_id) is None:
        raise HTTPException(404, {"code": "job.not_found", "message": "Job not found"})
    record = jobs.manager.resume(job_id)
    if record is None:
        raise HTTPException(409, "No recoverable provider request was found")
    job = jobs.manager.get(job_id)
    payload = record.get("payload") or {}
    combined = deepcopy(record.get("result") or {"images": [], "gallery_ids": []})
    try:
        for index, remote in enumerate(job.remotes):
            if remote.get("saved"):
                continue
            provider = remote.get("provider", "fal")
            model = remote.get("endpoint") or remote.get("model", "")
            if provider == "magnific":
                result = await _to_thread(magnific_api.fetch_result, remote["requestId"], model)
            elif provider == "fal":
                result = await _to_thread(gen_service.fal_fetch_result, model, remote["requestId"], remote.get("responseUrl", ""))
            else:
                raise HTTPException(409, "This provider does not support recovery")
            result["images"] = gen_service._extract_images(result)
            if not result["images"]:
                raise HTTPException(502, "The remote result contains no image")
            result.update({"provider": provider, "model": model})
            artifact = remote.get("artifactBody") or {**payload, "generationId": f"{job.id}-{index}"}
            saved = await _to_thread(save_generation_artifacts, artifact, result)
            if remote.get("cell"):
                combined.setdefault("matrix", []).append({**remote["cell"], "images": saved["images"]})
                combined["scenes"] = [item.get("title", "") for item in payload.get("scenes", [])]
                combined["zones"] = [item.get("label", "") for item in payload.get("zones", [])]
            for key in ("images", "gallery_ids", "warnings", "output_paths"):
                combined.setdefault(key, []).extend(saved.get(key) or [])
            for key in ("provider", "model", "handoff_id"):
                if key in saved:
                    combined[key] = saved[key]
            remote["saved"] = True
            try:
                job.save_partial(combined)
            except Exception:
                remote["saved"] = False
                raise
        requested = int(payload.get("numImages") or 1)
        if job.kind == "matrix":
            requested = len(payload.get("scenes", [])) * len(payload.get("zones", []))
            if len(combined.get("matrix", [])) < requested:
                combined.setdefault("warnings", []).append("Only submitted campaign cells were recovered. Start a new campaign for the remaining cells.")
        if len(combined.get("images") or []) < requested and job.kind in ("generate", "magnific", "vary"):
            # Preserve partial output; the next action is an explicit paid retry.
            job.status = "failed"
            job.error = "Recovered available images; remaining images were not submitted"
            jobs.manager._persist(job)
        else:
            jobs.manager.mark_completed(job_id, combined)
        return {"ok": True, "result": combined}
    except ImageGenError as exc:
        jobs.manager.recovery_failed(job_id)
        raise _imagegen_error_http(exc) from exc
    except Exception:
        jobs.manager.recovery_failed(job_id)
        raise

@router.post("/jobs/submit")
async def jobs_submit(request: Request, body: Any = Body(None)) -> Dict[str, Any]:
    """Submit a generation as an async job (recommended for long generations).

    Accepts a dict or a JSON string (the desktop frontend serializes the body
    to avoid DataCloneError in the Electron bridge).
    """
    from imagegen_engine import jobs

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="invalid body (JSON expected)")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid body")

    from imagegen_engine.operations import build_operation
    kind = body.get("kind", "generate")
    job = jobs.manager.submit(kind, build_operation(kind, body), payload=body)
    return job.to_dict()
