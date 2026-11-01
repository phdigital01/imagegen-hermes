"""Library routes: subject/object entries (photos + passports) and the
generation-recipe library."""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Body, HTTPException, Request
from fastapi.responses import FileResponse

from dashboard import gen_service, llm_service, store
from dashboard.api_core import coerce_body, _abs_subject, make_router

router = make_router()


@router.get("/objects")
async def objects_list(request: Request) -> Dict[str, Any]:
    """List subject library entries (legacy path; same payload as /subjects)."""
    objects = [_abs_subject(request, item) for item in store.objects_list()]
    return {"objects": objects, "subjects": objects}


@router.get("/subjects")
async def subjects_list(request: Request, kind: str = "", q: str = "") -> Dict[str, Any]:
    subjects = [_abs_subject(request, item) for item in store.subjects_list(kind=kind, q=q)]
    return {"subjects": subjects, "objects": subjects}


@router.get("/subjects/kinds")
async def subjects_kinds() -> Dict[str, Any]:
    return store.subjects_kinds()


@router.get("/objects/file/{filename}")
async def objects_file(filename: str) -> Any:
    """Serve the file of a library subject/angle."""
    safe = Path(filename).name
    p = store.OBJECTS_DIR / safe
    if not p.exists():
        raise HTTPException(status_code=404, detail="Subject not found")
    return FileResponse(p, media_type=store.image_media_type(p.name))


@router.post("/objects/import")
@router.post("/subjects/import")
async def objects_import(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    """Import photos into the subject library (+ passport). Supports open kind + dedupe."""
    from dashboard import jobs

    folder = str(body.get("folder", "")).strip()
    paths = [str(p) for p in (body.get("paths") or []) if str(p).strip()]
    kind = str(body.get("kind") or "object")
    if not folder and not paths:
        raise HTTPException(status_code=400, detail="Provide a folder or a list of paths")
    img_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

    def _candidates() -> List[Path]:
        if folder:
            root = Path(folder)
            if not root.is_dir():
                raise HTTPException(status_code=400, detail=f"Folder not found: {folder}")
            return [p for p in sorted(root.iterdir()) if p.suffix.lower() in img_exts]
        return [Path(p) for p in paths if Path(p).is_file() and Path(p).suffix.lower() in img_exts]

    def _run(job: jobs.Job) -> Dict[str, Any]:
        cands = _candidates()
        if not cands:
            return {"imported": [], "total": 0, "deduped": 0, "message": "Nenhuma imagem encontrada"}
        imported = []
        deduped = 0
        total = len(cands)
        for i, p in enumerate(cands):
            gen_service._check_cancel(job.check_cancelled)
            job.progress = i / total
            job.message = f"Importing {p.name} ({i + 1}/{total})…"
            try:
                raw = p.read_bytes()
                fname = f"{int(time.time())}-{p.stem[:40]}{p.suffix.lower()}"
                fname = "".join(c for c in fname if c.isalnum() or c in ".-_")
                data_url = f"data:image/png;base64,{base64.b64encode(raw).decode()}"
                passport = ""
                try:
                    passport = llm_service.llm_product_passport(images=[data_url])
                except Exception:  # noqa: BLE001
                    passport = ""
                item = store.object_add(fname, raw, name=p.stem, passport=passport, kind=kind, dedupe=True)
                if item.get("deduped"):
                    deduped += 1
                imported.append({
                    k: item.get(k)
                    for k in ("id", "name", "file", "passport", "localPath", "kind", "contentHash", "deduped")
                })
            except Exception as exc:  # noqa: BLE001
                job.message = f"Failed on {p.name}: {exc}"
        job.progress = 100
        return {"imported": imported, "total": total, "deduped": deduped}

    job = jobs.manager.submit("objects-import", _run, payload={"folder": folder, "paths": paths, "kind": kind})
    return job.to_dict()


@router.post("/objects/{obj_id}/as-ref")
@router.post("/subjects/{obj_id}/as-ref")
async def objects_as_ref(obj_id: str, body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    """Return one or more fixed-subject refs (multi-angle when available)."""
    payload = body if isinstance(body, dict) else {}
    max_refs = int(payload.get("maxRefs") or payload.get("max_refs") or 4)
    refs = store.subject_as_refs(obj_id, max_refs=max_refs)
    if not refs:
        raise HTTPException(status_code=404, detail="Subject not found")
    # Back-compat: single-ref clients still get the primary fields at the top level.
    primary = dict(refs[0])
    primary["refs"] = refs
    return primary


@router.post("/subjects/{obj_id}/as-refs")
async def subjects_as_refs(obj_id: str, body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    payload = body if isinstance(body, dict) else {}
    max_refs = int(payload.get("maxRefs") or payload.get("max_refs") or 4)
    refs = store.subject_as_refs(obj_id, max_refs=max_refs)
    if not refs:
        raise HTTPException(status_code=404, detail="Subject not found")
    return {"refs": refs}


@router.patch("/subjects/{obj_id}")
async def subjects_patch(obj_id: str, body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    payload = body if isinstance(body, dict) else {}
    updated = store.subject_update(obj_id, payload)
    if not updated:
        raise HTTPException(status_code=404, detail="Subject not found")
    return updated


@router.post("/subjects/{obj_id}/angles")
async def subjects_add_angle(obj_id: str, body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    payload = body if isinstance(body, dict) else {}
    image = str(payload.get("image") or payload.get("imageDataUrl") or "")
    if not image:
        raise HTTPException(status_code=400, detail="image is required")
    raw = store.fetch_image_bytes(image)
    label = str(payload.get("label") or "angle")
    fname = f"{int(time.time())}-{label[:24]}.png"
    fname = "".join(c for c in fname if c.isalnum() or c in ".-_")
    updated = store.subject_add_angle(obj_id, fname, raw, label=label)
    if not updated:
        raise HTTPException(status_code=404, detail="Subject not found")
    return updated


@router.delete("/objects/{obj_id}")
@router.delete("/subjects/{obj_id}")
async def objects_delete(obj_id: str) -> Dict[str, Any]:
    removed = store.object_remove(obj_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Subject not found")
    return {"ok": True}


@router.get("/library")
async def library() -> Dict[str, Any]:
    return {"entries": store.library_list()}


@router.post("/library")
async def library_save(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    """Save/update a generation recipe (prompt + full config + refs)."""
    body = coerce_body(body)
    prompt = (body.get("prompt") or "").strip()
    name = (body.get("name") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    item = store.library_save(
        name=name,
        prompt=prompt,
        config=body.get("config", {}),
        refs=body.get("refs"),
        genre=body.get("genre", ""),
        negative_prompt=body.get("negativePrompt", ""),
        entry_id=body.get("id"),
    )
    return item


@router.delete("/library/{entry_id}")
async def library_delete(entry_id: str) -> Dict[str, Any]:
    store.library_remove(entry_id)
    return {"ok": True}
