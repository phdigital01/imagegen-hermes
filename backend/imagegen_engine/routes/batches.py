"""A profile's latest prompt list, backed by ordinary generation jobs."""
from copy import deepcopy
from uuid import UUID

from fastapi import Body, HTTPException

from imagegen_engine import jobs, store
from imagegen_engine.api_core import make_router
from imagegen_engine.errors import ImageGenError
from imagegen_engine.operations import build_operation
from imagegen_engine.routes.jobs import retry_failed_job

router = make_router()
ACTIVE = {"queued", "running", "recovering"}
SETTINGS = ("provider", "model", "aspectRatio", "resolution", "negativePrompt", "seed", "referenceImages", "config")


def _file():
    return store.data_dir() / "latest-batch.json"


def _snapshot(batch):
    if not batch:
        return None
    records = {r.get("clientRequestId"): r for r in store.load_job_records()}
    items = []
    for entry in batch["entries"]:
        record = records.get(entry["key"])
        row = {"prompt": entry["prompt"], "status": "unsent", "error": entry.get("error", "")}
        if record:
            job = jobs.Job.from_record(record)
            row.update(job.to_dict())
            row["image"] = next(iter((job.result or {}).get("images") or []), None)
        elif entry.get("accepted"):
            # An old job may have aged out of history. Never resubmit it implicitly.
            row["status"] = "expired"
        items.append(row)
    return {"id": batch["id"], "model": batch["settings"].get("model"), "items": items}


def _enqueue(batch, index):
    entry = batch["entries"][index]
    payload = {**batch["settings"], "prompt": entry["prompt"], "clientRequestId": entry["key"],
               "kind": "generate", "numImages": 1, "saveToGallery": True}
    payload["config"] = {**(payload.get("config") or {}), "description": entry["prompt"],
                         "compositionIntent": None, "numImages": 1, "saveToGallery": True}
    try:
        jobs.manager.submit("generate", build_operation("generate", payload), payload=payload)
        entry["accepted"] = True
        entry.pop("error", None)
    except (HTTPException, ImageGenError) as exc:
        entry["error"] = str(exc.detail if isinstance(exc, HTTPException) else exc)
    store._write_json(_file(), batch)


@router.get("/batches/latest")
def latest_batch():
    return {"batch": _snapshot(store._read_json(_file(), None))}


@router.post("/batches")
def start_batch(body: dict = Body(...)):
    prompts = body.get("prompts")
    if not isinstance(prompts, list) or not 1 <= len(prompts) <= jobs.MAX_JOBS or not all(
        isinstance(s, str) and s.strip() and len(s) <= 16000 for s in prompts
    ):
        raise HTTPException(400, "Enter 1 to 32 prompts, up to 16000 characters each")
    try:
        batch_id = str(UUID(str(body.get("id"))))
    except ValueError as exc:
        raise HTTPException(400, "Invalid batch ID") from exc
    common = body.get("settings")
    if not isinstance(common, dict) or not common.get("provider") or not common.get("model"):
        raise HTTPException(400, "Select a provider and model")
    settings = {k: deepcopy(common[k]) for k in SETTINGS if k in common}
    if not isinstance(settings.get("config", {}), dict):
        raise HTTPException(400, "Invalid generation config")
    prompts = [s.strip() for s in prompts]
    path = _file()
    with store._file_lock(path):
        previous = store._read_json(path, None)
        if previous and previous["id"] == batch_id:
            if settings != previous["settings"] or prompts != [e["prompt"] for e in previous["entries"]]:
                raise HTTPException(409, "Batch ID already used for a different request")
            return {"batch": _snapshot(previous)}
        if previous and (previous["id"] != body.get("previousId") or
                         any(i["status"] in ACTIVE for i in _snapshot(previous)["items"])):
            raise HTTPException(409, "Review the current batch before starting another")
        batch = {"id": batch_id, "settings": settings, "entries": [
            {"prompt": p, "key": f"batch-{batch_id}-{i}"} for i, p in enumerate(prompts)
        ]}
        store._write_json(path, batch)
        for i in range(len(prompts)):
            _enqueue(batch, i)
        return {"batch": _snapshot(batch)}


@router.post("/batches/{batch_id}/items/{index}/retry")
def retry_item(batch_id: str, index: int, body: dict = Body(...)):
    path = _file()
    with store._file_lock(path):
        batch = store._read_json(path, None)
        if not batch or batch_id != batch["id"] or not 0 <= index < len(batch["entries"]):
            raise HTTPException(404, "Batch item not found")
        row = _snapshot(batch)["items"][index]
        if row.get("id") == body.get("jobId"):
            if row["status"] == "unsent":
                _enqueue(batch, index)
            elif row.get("retryable"):
                retry_failed_job(row["id"])
                batch["entries"][index].update(key=f"retry-{row['id']}", accepted=True)
                store._write_json(path, batch)
            else:
                raise HTTPException(409, "This item cannot be retried")
        return {"batch": _snapshot(batch)}
