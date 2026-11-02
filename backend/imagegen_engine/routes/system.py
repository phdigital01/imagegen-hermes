"""System routes: health, provider catalog/status/configure/test, settings."""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import Body, HTTPException, Query

from imagegen_engine import gen_service, store
from imagegen_engine.api_core import _imagegen_error_http, _to_thread, coerce_body, make_router
from imagegen_engine.errors import ImageGenError
from imagegen_engine.providers_catalog import _list_providers

router = make_router()


@router.get("/health")
async def health() -> Dict[str, Any]:
    providers = _list_providers()
    return {
        "ok": True,
        "plugin": "imagegen",
        "providers": providers,
    }


@router.get("/providers")
async def providers() -> Dict[str, Any]:
    return {"providers": _list_providers()}


@router.get("/providers/fal/model")
async def fal_model(id: str = Query("", max_length=200)) -> Dict[str, Any]:
    """Exact controls of one model from FAL's catalog, read from its input schema."""
    from imagegen_engine import fal_catalog

    if not gen_service._MODEL_ID_RE.match(id) or not fal_catalog.knows(id):
        raise HTTPException(status_code=404, detail="unknown FAL catalog model")
    try:
        details = await _to_thread(fal_catalog.details, id)
    except ImageGenError as exc:
        raise _imagegen_error_http(exc) from exc
    max_refs = int(details.get("maxReferences") or 0)
    return {"id": id, **details, "capabilities": {"maxReferences": max_refs, "referenceImages": max_refs > 0,
                                                  "edit": max_refs > 0}}


@router.get("/providers/status")
async def providers_status() -> Dict[str, Any]:
    """Report which providers are configured/available, without exposing secrets."""
    out: List[Dict[str, Any]] = []
    for p in _list_providers():
        name = p.get("name")
        configured: bool = False
        if name == "fal":
            configured = bool(gen_service._fal_key()) or bool(p.get("available", False))
        elif name == "magnific":
            configured = bool(gen_service._magnific_available())
        else:
            configured = bool(p.get("available", False))
        out.append({
            "name": name,
            "display_name": p.get("display_name", name),
            "configured": configured,
            "available": bool(p.get("available", False)),
        })
    return {"providers": out}


@router.post("/providers/test")
async def providers_test(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    """Lightweight connectivity check for a provider (never returns the key)."""
    provider = str(body.get("provider", "")).strip()
    if provider == "fal" and gen_service._fal_key():
        return {"ok": True, "provider": provider}
    if provider in ("fal", "nous"):
        # Without a direct key, both run through the providers Hermes registered.
        registered = next((p for p in _list_providers() if p.get("name") == provider), None)
        if registered and registered.get("available"):
            return {"ok": True, "provider": provider, "via": "hermes"}
        return {"ok": False, "error": "not_configured"}
    raise HTTPException(status_code=400, detail="unsupported provider")


@router.get("/settings/output-folder")
async def output_folder_get() -> Dict[str, Any]:
    """Return the optional folder used to export generated images."""
    return store.output_dir_status()


@router.post("/settings/output-folder")
async def output_folder_set(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    """Set or clear the optional generated-image export folder."""
    folder = body.get("path", "")
    if folder is None:
        folder = ""
    try:
        store.set_output_dir(str(folder))
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return store.output_dir_status()


@router.get("/settings/budget")
async def budget_get() -> Dict[str, Any]:
    """Return the monthly spend limit and the amount spent this month."""
    return store.budget_status()


@router.post("/settings/budget")
async def budget_set(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    """Set or clear the monthly budget limit (``None`` clears it)."""
    body = coerce_body(body)
    try:
        store.set_budget(body.get("monthlyLimit"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return store.budget_status()


@router.post("/settings/clear-data")
async def clear_data(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    if body.get("confirm") != "CLEAR":
        raise HTTPException(status_code=400, detail="Invalid confirmation")
    return {"ok": True, "deleted": store.clear_plugin_data(
        gallery=bool(body.get("gallery")),
        handoffs=bool(body.get("handoffs")),
        subjects=bool(body.get("subjects")),
    )}
