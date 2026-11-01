"""Nous Portal provider for the ImageGen plugin.

Routes text-to-image requests through the Hermes Tool Gateway (managed
fal-queue passthrough). A paid Nous Portal subscription replaces the FAL
API key: no ``FAL_KEY`` is required. The gateway is exposed by the Hermes
host (``tools.managed_tool_gateway``), so this module stays a thin adapter:

1. ``nous_portal_available()`` — read-only entitlement/token probe (cheap,
   no OAuth refresh, no network).
2. ``PORTAL_CATALOG`` — the pinned ImageGen model list served under the
   ``nous`` provider. Adding a model means adding one entry here (see
   docs/runbooks/adding-models.md).
3. ``submit()`` — delegates to the host's ``_submit_fal_request``, which
   picks the managed gateway when the account is entitled.
4. ``upload_reference()`` — turns local files / data URLs into
   ``nous-upload:<token>`` references via the gateway upload protocol.

The host's 4xx mapping already turns allowlist misses and billing gates
into actionable guidance (``tools.image_generation_tool._submit_fal_request``),
so plugin-level error messages stay short and let the host text through.
"""
from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

PROVIDER_NAME = "nous"
DISPLAY_NAME = "Nous Portal"

# Image models listed on the Nous Portal image-generation changelog and
# verified to exist as FAL queue endpoints. The gateway allowlist decides
# what an individual subscription can actually run; rejected models surface
# the portal's own guidance.
PORTAL_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "fal-ai/bytedance/seedream/v5/pro/text-to-image",
        "display": "Seedream 5.0 Pro",
        "speed": "~10s",
        "price": "portal credits",
        "strengths": "Flagship realism, native hi-res (2K), strong multilingual text",
        "capabilities": {
            "maxReferences": 0,
            "edit": False,
            "negativeMode": "separate",
            "resolutions": ["1K", "2K"],
        },
    },
    {
        "id": "fal-ai/bytedance/seedream/v5/lite/text-to-image",
        "display": "Seedream 5.0 Lite",
        "speed": "~5s",
        "price": "portal credits",
        "strengths": "Faster Seedream tier for drafts and iteration",
        "capabilities": {"maxReferences": 0, "edit": False, "negativeMode": "separate"},
    },
    {
        "id": "fal-ai/ideogram/v4/instant",
        "display": "Ideogram V4 Instant",
        "speed": "<1s",
        "price": "portal credits",
        "strengths": "Ultra-fast typography and poster layouts",
        "capabilities": {"maxReferences": 0, "edit": False, "negativeMode": "separate"},
    },
    {
        "id": "fal-ai/ideogram/v4/fast",
        "display": "Ideogram V4 Fast",
        "speed": "~1s",
        "price": "portal credits",
        "strengths": "Fast typography with higher fidelity than instant",
        "capabilities": {"maxReferences": 0, "edit": False, "negativeMode": "separate"},
    },
    {
        "id": "fal-ai/alibaba/qwen-image-3/text-to-image",
        "display": "Qwen Image 3",
        "speed": "~8s",
        "price": "portal credits",
        "strengths": "LLM-driven prompt understanding, legible text in 12 languages",
        "capabilities": {"maxReferences": 0, "edit": False, "negativeMode": "separate"},
    },
    {
        "id": "fal-ai/microsoft/mai-image-2.5-pro",
        "display": "MAI Image 2.5 Pro",
        "speed": "~6s",
        "price": "portal credits",
        "strengths": "Microsoft MAI — high fidelity and precise typography",
        "capabilities": {"maxReferences": 0, "edit": False, "negativeMode": "omit"},
    },
    {
        "id": "fal-ai/google/nano-banana-2-lite",
        "display": "Nano Banana 2 Lite",
        "speed": "~2s",
        "price": "portal credits",
        "strengths": "Cheap fast Gemini image tier, 14 aspect ratios",
        "capabilities": {"maxReferences": 0, "edit": False, "negativeMode": "omit"},
    },
    {
        "id": "fal-ai/recraft/v4.1/text-to-image",
        "display": "Recraft V4.1",
        "speed": "~6s",
        "price": "portal credits",
        "strengths": "Vector-clean graphic design, brand assets, icons",
        "capabilities": {"maxReferences": 0, "edit": False, "negativeMode": "separate"},
    },
]


def nous_portal_available() -> bool:
    """True when the Hermes host can reach the Nous Tool Gateway.

    Read-only probe: checks host helpers plus a cached Nous OAuth token
    (``peek_nous_access_token``). Never refreshes tokens and never performs
    network I/O, so it is safe for availability scans.
    """
    try:
        from tools.tool_backend_helpers import managed_nous_tools_enabled

        if not managed_nous_tools_enabled():
            return False
        from tools.managed_tool_gateway import peek_nous_access_token

        return bool(peek_nous_access_token())
    except Exception as exc:  # noqa: BLE001 — host modules may be absent in tests
        logger.debug("nous portal probe failed: %s", exc)
        return False


def list_models() -> List[Dict[str, Any]]:
    """Return a deep copy of the pinned portal catalog."""
    return [deepcopy(entry) for entry in PORTAL_CATALOG]


def get_model(model_id: str) -> Dict[str, Any]:
    """Return catalog metadata for one model id (empty dict when unknown)."""
    for entry in PORTAL_CATALOG:
        if entry["id"] == model_id:
            return deepcopy(entry)
    return {}


def managed_client():
    """Resolve the requested gateway explicitly, regardless of direct FAL keys."""
    from tools.managed_tool_gateway import resolve_managed_tool_gateway
    from tools.image_generation_tool import _get_managed_fal_client
    from dashboard.errors import ImageGenError, PROVIDER_UNAVAILABLE

    gateway = resolve_managed_tool_gateway("fal-queue")
    if gateway is None:
        raise ImageGenError(PROVIDER_UNAVAILABLE, "Nous Portal is not connected", provider="nous")
    return _get_managed_fal_client(gateway)


def submit(model: str, arguments: Dict[str, Any], *, on_submit=None, cancel=None) -> Dict[str, Any]:
    import uuid
    from dashboard import billing, gen_service

    client = managed_client()
    gen_service._check_cancel(cancel)
    handle = billing.run("nous", model, None, lambda: client.submit(
        model, arguments=arguments, headers={"x-idempotency-key": str(uuid.uuid4())},
    ))
    if isinstance(handle, dict):
        return handle
    if on_submit and getattr(handle, "request_id", None):
        on_submit({"provider": "nous", "model": model, "endpoint": model,
                   "requestId": handle.request_id, "responseUrl": handle.response_url})
    return gen_service.wait_for_handle(handle, cancel)


def fetch_result(model: str, request_id: str, response_url: str = "") -> Dict[str, Any]:
    from urllib.parse import urlsplit
    from dashboard import gen_service

    gen_service._safe_model_id(model)
    gen_service._safe_model_id(request_id)
    client = managed_client()
    base = client._queue_url_format
    url = response_url or f"{base}{'/'.join(model.split('/')[:2])}/requests/{request_id}"
    # Never attach gateway credentials to a persisted foreign URL.
    if urlsplit(url).netloc != urlsplit(base).netloc or not url.startswith(base) or urlsplit(url).fragment:
        raise ValueError("Result URL does not belong to the current managed gateway")
    response = client._http_client.get(url, timeout=90, follow_redirects=False)
    response.raise_for_status()
    return response.json()

def upload_reference(value: str) -> str:
    """Turn a local image reference into something the gateway accepts.

    http(s) URLs pass through unchanged. Local paths (only inside the plugin
    data roots) and data URLs are validated by size/magic bytes, uploaded
    through the gateway presign protocol and returned as
    ``nous-upload:<token>`` references. Raises with actionable guidance when
    the host exposes no uploader.
    """
    from dashboard import image_input
    from dashboard.errors import ImageGenError, PROVIDER_UNAVAILABLE, PROVIDER_FAILED

    value = str(value or "").strip()
    if not value:
        raise RuntimeError("empty reference image")

    kind, data = image_input.resolve_image_source(value)
    if kind == "url":
        return value
    assert data is not None
    mime = image_input.detect_mime(data)

    uploader = _resolve_uploader()
    if uploader is None:
        raise ImageGenError(
            PROVIDER_UNAVAILABLE,
            "Nous Portal is not connected — run `hermes setup` and sign in to the "
            "Nous Portal, or set FAL_KEY to use FAL.ai directly.",
            provider=PROVIDER_NAME,
        )
    try:
        return _run_uploader(uploader, data, mime)
    except ImageGenError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError(
            PROVIDER_FAILED,
            f"Nous Portal upload failed: {exc}",
            provider=PROVIDER_NAME,
            detail=str(exc),
        ) from exc


def _run_uploader(uploader, data: bytes, mime: str) -> str:
    """Run the async uploader from sync code, even inside a running loop.

    Plugin routes are async FastAPI handlers that call the sync generation
    layer inline, so ``asyncio.run`` would raise there. Fall back to a
    dedicated thread when a loop is already running.
    """
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(uploader(data, mime))
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, uploader(data, mime)).result()


def _resolve_uploader():
    """Build the managed media uploader for the gateway, or None."""
    try:
        from tools.managed_tool_gateway import (
            build_managed_media_uploader,
            managed_vendor_endpoints,
        )

        endpoints = managed_vendor_endpoints("fal-queue")
        if not endpoints:
            return None
        return build_managed_media_uploader(endpoints["base_url"], endpoints["upload_path"])
    except Exception as exc:  # noqa: BLE001
        logger.debug("nous uploader unavailable: %s", exc)
        return None
