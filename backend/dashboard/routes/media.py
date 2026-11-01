"""Media routes: upload, refs/exports/cache file serving, feed, history,
gallery."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any, Dict

from fastapi import Body, HTTPException, Request
from fastapi.responses import FileResponse

from dashboard import image_input, store
from dashboard.api_core import _abs_images, _absolute, _to_thread, coerce_body, make_router

router = make_router()


@router.post("/upload")
async def upload_image(request: Request, body: Any = Body(None)) -> Dict[str, Any]:
    """Accept a base64 image → save to data/gallery/refs/ → return the local path."""
    body = coerce_body(body)
    data_url = body.get("image", "")
    if not data_url:
        raise HTTPException(status_code=400, detail="image is required")
    if not isinstance(data_url, str) or len(data_url) > ((image_input.MAX_IMAGE_BYTES + 2) // 3) * 4 + 256:
        raise HTTPException(status_code=400, detail="Image exceeds the upload limit")
    raw = data_url.split(",", 1)[-1] if data_url.startswith("data:") else data_url
    try:
        binary = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="invalid base64") from exc
    try:
        path = store.save_reference(binary)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    url = _absolute(request, f"/api/plugins/imagegen/refs/{path.name}")
    return {"path": str(path), "name": path.name, "url": url}


@router.get("/refs/{filename}")
async def reference_file(filename: str) -> FileResponse:
    """Serve a persisted reference without keeping dataURLs in localStorage."""
    safe_name = Path(filename).name
    path = (store.REFS_DIR / safe_name).resolve()
    if path.parent != store.REFS_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="reference not found")
    return FileResponse(str(path), media_type=store.image_media_type(safe_name))


@router.get("/feed")
async def feed(request: Request, source: str = "all", provider: str = "", q: str = "", limit: int = 200, sort: str = "newest") -> Dict[str, Any]:
    """Unified read model: history (generated) + orphan gallery (saved)."""
    items = await _to_thread(store.feed_list, source=source, provider=provider, query=q, limit=limit, sort=sort)
    for item in items:
        for img in item.get("images") or []:
            url = img.get("url")
            if url and str(url).startswith("/"):
                img["url"] = _absolute(request, str(url))
    stats = await _to_thread(store.feed_stats)
    return {"items": items, "stats": stats}


@router.get("/feed/stats")
async def feed_stats_route() -> Dict[str, Any]:
    """Distinct providers + global counters for the provider filter (no feed scan in the UI)."""
    stats = await _to_thread(store.feed_stats)
    # Distinct is already in stats.providers, but also return top-level for convenience
    return {"stats": stats, "providers": stats.get("providers") or []}


@router.post("/feed/export-zip")
async def feed_export_zip(request: Request, body: Any = Body(None)) -> Dict[str, Any]:
    data = coerce_body(body)
    ids = data.get("ids") or data.get("items") or []
    if not isinstance(ids, list) or not ids:
        raise HTTPException(status_code=400, detail="ids is required")
    try:
        archive = await _to_thread(store.export_feed_zip, ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if archive is None:
        raise HTTPException(status_code=404, detail="No images found for the selected items")
    return {
        "ok": True,
        "path": str(archive),
        "filename": archive.name,
        "url": _absolute(request, f"/api/plugins/imagegen/exports/{archive.name}"),
    }


@router.delete("/feed/{entry_id}")
async def feed_delete(entry_id: str) -> Dict[str, Any]:
    """Cascade delete: history entry + gallery files/metas (idempotent)."""
    try:
        removed = await _to_thread(store.feed_delete, entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "removed": removed}


@router.get("/history")
async def history(request: Request, limit: int = 50) -> Dict[str, Any]:
    entries = store.get_history(limit)
    for e in entries:
        if e.get("images"):
            e["images"] = _abs_images(request, e["images"])
        locations = list(e.get("gallery_entries") or [])
        known_ids = {item.get("id") for item in locations if isinstance(item, dict)}
        for gallery_id in e.get("gallery_ids") or []:
            if gallery_id in known_ids:
                continue
            meta = store.gallery_metadata(str(gallery_id))
            if not meta:
                continue
            file_path = store.gallery_file(str(meta.get("file", "")))
            if file_path is None:
                continue
            locations.append({
                "id": gallery_id,
                "localPath": str(file_path),
                "outputPath": meta.get("outputPath", ""),
            })
        e["gallery_entries"] = locations
    return {"entries": entries}


@router.delete("/history/{entry_id}")
async def history_delete(entry_id: str) -> Dict[str, Any]:
    store.remove_history(entry_id)
    return {"ok": True}


@router.get("/gallery")
async def gallery(request: Request) -> Dict[str, Any]:
    entries = store.gallery_list()
    for e in entries:
        if e.get("url"):
            e["url"] = _absolute(request, e["url"])
        if e.get("thumb"):
            e["thumb"] = _absolute(request, e["thumb"])
    return {"entries": entries}


@router.get("/gallery/item/{entry_id}")
async def gallery_item(request: Request, entry_id: str) -> Dict[str, Any]:
    """One gallery entry, for the chat card the agent shows under an image."""
    try:
        meta = store.gallery_metadata(entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not meta or not store.gallery_file(str(meta.get("file", ""))):
        raise HTTPException(status_code=404, detail="Not in the gallery")
    url = _absolute(request, f"/api/plugins/imagegen/gallery/file/{meta['file']}")
    local = str(store.gallery_file(str(meta["file"])))
    return {key: meta.get(key) for key in ("id", "provider", "model", "prompt")} | {"url": url, "localPath": local}


@router.get("/gallery/stats")
async def gallery_stats() -> Dict[str, Any]:
    return store.gallery_stats()


@router.delete("/gallery")
async def gallery_clear() -> Dict[str, Any]:
    return {"ok": True, "deleted": store.clear_gallery()}


@router.delete("/gallery/{entry_id}")
async def gallery_delete(entry_id: str) -> Dict[str, Any]:
    try:
        store.delete_gallery_entry(entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/gallery/{entry_id}/export-pack")
async def gallery_export_pack(request: Request, entry_id: str) -> Dict[str, Any]:
    try:
        archive = store.export_gallery_pack(entry_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if archive is None:
        raise HTTPException(status_code=404, detail="Gallery entry not found")
    # Prefer JSON for the desktop bridge; FileResponse is awkward through ctx.rest.
    return {
        "ok": True,
        "path": str(archive),
        "filename": archive.name,
        "url": _absolute(request, f"/api/plugins/imagegen/exports/{archive.name}"),
    }


@router.get("/exports/{filename}")
async def export_file(filename: str) -> FileResponse:
    safe = Path(filename).name
    path = store.EXPORT_DIR / safe
    if not path.exists():
        raise HTTPException(status_code=404, detail="Export not found")
    return FileResponse(str(path), media_type="application/zip", filename=safe)


def _served_file(url: str) -> Path:
    try:
        local = image_input.resolve_served_image(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = Path(local)
    if local == url or not path.is_file() or not image_input.is_allowed_local_path(path):
        raise HTTPException(status_code=404, detail="Not a local ImageGen image")
    return path


@router.get("/media/local-path")
async def media_local_path(url: str = "") -> Dict[str, str]:
    """Map one of our served image URLs to its file on disk, so the agent can open it."""
    return {"path": str(_served_file(url))}


@router.get("/media/data-url")
async def media_data_url(url: str = "") -> Dict[str, str]:
    """One of our served images inline. The Desktop guards plugin URLs, and <img>/fetch send no credentials."""
    path = _served_file(url)
    if path.stat().st_size > image_input.MAX_RESULT_BYTES:
        raise HTTPException(status_code=413, detail="Image too large")
    data = await _to_thread(path.read_bytes)
    return {"dataUrl": f"data:{image_input.detect_mime(data)};base64,{base64.b64encode(data).decode()}"}


@router.get("/gallery/file/{filename}")
async def gallery_file(filename: str) -> FileResponse:
    p = store.gallery_file(filename)
    if not p:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(p), media_type=store.image_media_type(p.name))


@router.get("/cache/{name}")
async def cache_file(name: str, p: str = "") -> FileResponse:
    """Serve local files generated by b64 providers (OpenAI/Krea/etc.).

    `p` is the absolute path (comes from _local_to_served). Validation: only
    image files inside known directories (the Hermes image caches and the
    plugin data directory).
    """
    if not p:
        raise HTTPException(status_code=400, detail="p is required")
    target = Path(p).resolve()
    if not any(target.is_relative_to(root) for root in image_input.allowed_image_roots()):
        raise HTTPException(status_code=403, detail="access denied")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="not found")
    with target.open("rb") as source:
        header = source.read(32)
    try:
        image_input.validate_image_bytes(header)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Only image files can be served") from exc
    return FileResponse(str(target), media_type=image_input.detect_mime(header))
