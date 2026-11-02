"""Shared plumbing for the ImageGen dashboard routers.

The Hermes web server imports ``dashboard/plugin_api.py`` as a top-level
module (``spec_from_file_location``, no parent package), so relative imports
break. This module keeps the ``sys.path`` bootstrap first — before any
``imagegen_engine.*`` import — and every router in ``imagegen_engine/routes/*`` is built
through :func:`make_router` so the structured error envelope
(``{ok: False, error: {code, message}}``) applies to every route.

Ownership map:

- ``api_core`` — error envelope, route base class, URL helpers, thread
  offloader, ``make_router`` factory.
- ``providers_catalog`` — provider registration/listing and profile env.
- ``generation_artifacts`` — gallery/history persistence + job builders.
- ``routes/*`` — one router per domain; ``plugin_api`` aggregates them.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

# The web server imports the plugin file as a top-level module
# (spec_from_file_location, no parent package) — relative imports (``.``)
# break with "attempted relative import with no known parent package".
# We make sure the imagegen_engine/ package parent directory is on sys.path
# and use absolute ``imagegen_engine.*`` imports.
_DASH_PARENT = Path(__file__).resolve().parent.parent
if str(_DASH_PARENT) not in sys.path:
    sys.path.insert(0, str(_DASH_PARENT))

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from imagegen_engine import store
from imagegen_engine.errors import ImageGenError

logger = logging.getLogger(__name__)


def _http_error_code(status_code: int, detail: Any) -> str:
    """Map route failures to a stable frontend error code."""
    if isinstance(detail, dict) and detail.get("code"):
        return str(detail["code"])
    if status_code == 400:
        return "bad_request"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "job_not_ready"
    if status_code in (408, 429, 502, 503, 504):
        return "provider_unavailable"
    if status_code in (401, 403):
        return "not_authorized"
    return "internal_error"


async def _imagegen_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    message = detail.get("message", "Request failed") if isinstance(detail, dict) else str(detail)
    error: Dict[str, Any] = {
        "code": _http_error_code(exc.status_code, detail),
        "message": message,
    }
    if isinstance(detail, dict) and detail.get("params"):
        error["params"] = detail["params"]
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "error": error,
        },
    )


class _ImageGenRoute(APIRoute):
    """Convert route-level failures to the ImageGen error shape."""

    def get_route_handler(self):
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request):
            try:
                return await original_route_handler(request)
            except HTTPException as exc:
                return await _imagegen_http_exception(request, exc)
            except ImageGenError as exc:
                # Routes that do not wrap gen_service calls still surface the
                # stable error code instead of a generic 500.
                logger.error("ImageGen route failed (%s): %s", exc.code, exc)
                return JSONResponse(
                    status_code=502,
                    content={"ok": False, "error": exc.to_dict()},
                )

        return custom_route_handler


def make_router() -> APIRouter:
    """Create an APIRouter with the ImageGen structured-error route class."""
    return APIRouter(route_class=_ImageGenRoute)


def _imagegen_error_http(exc: ImageGenError, status_code: int = 502) -> HTTPException:
    """Wrap an ImageGenError as an HTTPException carrying the structured code."""
    return HTTPException(status_code=status_code, detail=exc.to_dict())


def coerce_body(body: Any) -> Dict[str, Any]:
    """Normalize a POST body that may arrive as a JSON string via the desktop bridge.

    The desktop's ctx.rest serializes through structuredClone, and some legacy
    paths send the body as a JSON string. FastAPI with ``Body(None)`` keeps a
    string as-is, so we parse it here and validate the shape.
    """
    import json

    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="invalid body")
    return body


def _absolute(request: Request, url: str) -> str:
    """Convert a plugin-relative URL into an absolute URL (for the desktop,
    which runs the frontend from file:// and does not resolve relative paths)."""
    if not url or url.startswith(("http://", "https://", "data:", "blob:")):
        return url
    if url.startswith("/"):
        base = str(request.base_url).rstrip("/")
        return f"{base}{url}"
    return url


def _abs_images(request: Request, images):
    """Apply _absolute to a list of image URLs."""
    if isinstance(images, list):
        return [_absolute(request, img) for img in images]
    return images


def _abs_subject(request: Request, item: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(item)
    if out.get("url"):
        out["url"] = _absolute(request, out["url"])
    if out.get("thumb"):
        out["thumb"] = _absolute(request, out["thumb"])
    angles = []
    for angle in out.get("angles") or []:
        ang = dict(angle)
        if ang.get("url"):
            ang["url"] = _absolute(request, ang["url"])
        if ang.get("thumb"):
            ang["thumb"] = _absolute(request, ang["thumb"])
        angles.append(ang)
    out["angles"] = angles
    return out


async def _to_thread(fn, *args, **kwargs):
    """Run the sync engine outside the gateway event loop (does not block
    other plugins' routes during long generations)."""
    import anyio

    return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
