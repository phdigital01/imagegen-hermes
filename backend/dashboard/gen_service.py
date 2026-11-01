"""Image generation service — reuses the Hermes infra (FAL) and the registry.

Owns everything that produces pixels and everything that can cost money:

- generate_text: text-to-image via provider (direct FAL or image_gen_registry)
- inpaint / edit / outpaint: FAL edit/fill endpoints
- upscale / bg-remove / magnific: auxiliary image operations
- reference publishing, cost estimation, and the spend guard (`check_budget`)

Prompt writing and vision analysis live in ``dashboard/llm_service.py``; this
module never calls an LLM.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import random
import threading
import time
import math
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from dashboard import billing, image_input, store
from dashboard.errors import (
    BUDGET_EXCEEDED,
    ImageGenError,
    MODEL_INVALID,
    MODEL_NO_IMAGE,
    PROVIDER_FAILED,
    PROVIDER_NOT_REGISTERED,
    PROVIDER_UNAVAILABLE,
    REFS_MODEL_UNSUPPORTED,
    REFS_PROVIDER_UNSUPPORTED,
    REFS_TOO_MANY,
    REFS_UNRESOLVED,
    REFS_UPLOAD_FAILED,
)

logger = logging.getLogger(__name__)

MAX_GENERATIONS = 8


class JobCancelledError(RuntimeError):
    """Raised when a job's cancel event fires mid-generation."""


def _check_cancel(cancel: Any = None) -> None:
    """Aborts generation when the job has been cancelled (cooperative poll)."""
    if cancel is None:
        return
    try:
        if hasattr(cancel, "is_set") and cancel.is_set():
            raise JobCancelledError("job cancelled by the user")
    except JobCancelledError:
        raise
    except Exception:
        pass
    try:
        if callable(cancel) and cancel():
            raise JobCancelledError("job cancelled by the user")
    except JobCancelledError:
        raise
    except Exception:
        pass

def _is_cancelled(cancel: Any) -> bool:
    if cancel is None:
        return False
    try:
        if hasattr(cancel, "is_set") and cancel.is_set():
            return True
    except Exception:
        pass
    try:
        if callable(cancel) and cancel():
            return True
    except Exception:
        return False
    return False

def _cancellable_sleep(cancel: Any, delay: float) -> None:
    """Sleep *delay* seconds with jitter, wake early if cancelled via Event.wait."""
    jittered = delay * (0.85 + random.random() * 0.3)
    if cancel is not None and hasattr(cancel, "wait"):
        try:
            if cancel.wait(timeout=jittered):
                _check_cancel(cancel)
            return
        except Exception:
            pass
    end = time.monotonic() + jittered
    while time.monotonic() < end:
        _check_cancel(cancel)
        remain = end - time.monotonic()
        if remain <= 0:
            break
        time.sleep(min(0.2, remain))

def _validate_seed(seed: Optional[int]) -> Optional[int]:
    """Validate seed is an int in [0, 4294967295]; raises ImageGenError on bad input."""
    if seed is None:
        return None
    try:
        if isinstance(seed, str) and seed.strip() == "":
            return None
        v = int(seed)
    except (TypeError, ValueError):
        raise ImageGenError(MODEL_INVALID, f"Invalid seed: {seed!r}", model=str(seed))
    if not (0 <= v <= 4294967295):
        raise ImageGenError(MODEL_INVALID, f"Seed out of range [0, 4294967295]: {v}", model=str(v))
    return v


def _short_ref(value: str, limit: int = 80) -> str:
    """Truncate a reference for error params (data URLs are huge)."""
    value = str(value or "")
    return value if len(value) <= limit else value[: limit - 3] + "..."


_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _safe_model_id(model: str) -> str:
    """Validate a model id before using it in a FAL URL (anti path/query)."""
    value = str(model or "").strip()
    if not _MODEL_ID_RE.match(value) or ".." in value:
        raise ImageGenError(MODEL_INVALID, f"Invalid model id: {model!r}", model=value or str(model))
    return value


def _is_transient_error(exc: BaseException) -> bool:
    """Return true only for failures that are safe to retry."""
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status in (408, 425, 429) or (isinstance(status, int) and status >= 500):
        return True
    if isinstance(status, int):
        return False
    return isinstance(exc, (TimeoutError, ConnectionError, OSError))


def _http_detail(exc: BaseException) -> str:
    """The provider's own reason for an HTTP error ("Exhausted balance"), not only "403 Forbidden"."""
    cached = getattr(exc, "_imagegen_detail", None)
    if cached:
        return cached  # the body can be read only once
    text = str(exc)
    response = getattr(exc, "response", None)  # httpx carries the body on its response
    read = getattr(response, "read", None) or getattr(exc, "read", None)
    if callable(read):
        try:
            body = json.loads(read() or b"{}")
        except Exception:  # noqa: BLE001 — a body that is not JSON keeps the status line
            body = {}
        reason = body.get("detail") if isinstance(body, dict) else None
        if isinstance(reason, list):
            reason = "; ".join(str(item.get("msg", item)) if isinstance(item, dict) else str(item) for item in reason)
        if reason:
            text = f"{text}: {str(reason)[:300]}"
    try:
        exc._imagegen_detail = text  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001
        pass
    return text


def retry_transient(operation, *, label: str, attempts: int = 3, base_delay: float = 0.75):
    """Run an operation with bounded exponential backoff for transient errors."""
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            if attempt >= attempts or not _is_transient_error(exc):
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("Transient %s failure (%s/%s): %s; retrying in %.2fs", label, attempt, attempts, exc, delay)
            time.sleep(delay)
    raise RuntimeError(f"{label} failed after {attempts} attempts")

# ---------------------------------------------------------------------------
# FAL helpers (reuse the Hermes tools.fal_common when available)
# ---------------------------------------------------------------------------

def _fal_key() -> Optional[str]:
    from dashboard import credentials

    return credentials.fal_key() or None


def _managed_gateway_active() -> bool:
    """True when the Nous Tool Gateway (managed fal-queue) resolves.

    A paid Nous Portal subscription routes FAL calls through the managed
    gateway, so FAL-backed plugin paths work without a FAL_KEY.
    """
    try:
        from tools.managed_tool_gateway import resolve_managed_tool_gateway

        return resolve_managed_tool_gateway("fal-queue") is not None
    except Exception:  # noqa: BLE001 — host modules absent in tests
        return False


def _fal_sync_client():
    """Synchronous FAL client — uses the Hermes one (fal_client) when installed."""
    key = _fal_key()
    if not key:
        from tools.managed_tool_gateway import resolve_managed_tool_gateway
        from tools.image_generation_tool import _get_managed_fal_client

        gateway = resolve_managed_tool_gateway("fal-queue")
        if gateway is None:
            return None
        return _get_managed_fal_client(gateway)
    try:
        import fal_client

        # Pass the key explicitly: the Hermes secret scope, not os.environ, owns it.
        return fal_client.SyncClient(key=key)
    except Exception as exc:  # noqa: BLE001
        logger.error("fal_client not installed: %s", exc)
        return None


def wait_for_handle(handle, cancel=None):
    """Keep cancellation responsive while the SDK waits on an accepted task."""
    import threading

    ready = threading.Event()
    value = []
    failure = []

    def wait():
        try:
            value.append(handle.get())
        except Exception as exc:
            failure.append(exc)
        finally:
            ready.set()

    threading.Thread(target=wait, daemon=True, name="imagegen-result").start()
    deadline = time.monotonic() + 300
    while not ready.wait(0.5):
        _check_cancel(cancel)
        if time.monotonic() >= deadline:
            raise TimeoutError("The accepted task is still pending; recover its result later")
    if failure:
        raise failure[0]
    result = value[0]
    return result if isinstance(result, dict) else {"result": result}


def fal_submit_sync(model: str, arguments: Dict[str, Any], *, cancel: Any = None,
                    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Submit a job to FAL synchronously (uses the Hermes infra)."""
    _safe_model_id(model)
    key = _fal_key()
    if not key and not _managed_gateway_active():
        raise ImageGenError(
            PROVIDER_UNAVAILABLE,
            "The FAL provider is unavailable: no FAL_KEY configured and the "
            "Nous Portal Tool Gateway is not active",
            provider="fal",
        )
    client = _fal_sync_client()
    if client is None:
        raise ImageGenError(PROVIDER_UNAVAILABLE, "The FAL client is unavailable", provider="fal")
    try:
        _check_cancel(cancel)
        handle = billing.run("fal" if key else "nous", model, _fal_cost(model, arguments) if key else None,
            lambda: client.submit(model, arguments=arguments, headers={"x-idempotency-key": str(uuid.uuid4())}))
        if isinstance(handle, dict):
            return handle
        rid = getattr(handle, "request_id", "")
        if on_submit and rid:
            on_submit({
                "provider": "fal" if key else "nous", "model": model, "endpoint": model,
                "requestId": str(rid), "responseUrl": str(getattr(handle, "response_url", "")),
                "statusUrl": str(getattr(handle, "status_url", "")),
            })
        # Waiting may fail after acceptance. Never fall back to another submit.
        result = wait_for_handle(handle, cancel)
        _check_cancel(cancel)
        return result if isinstance(result, dict) else {"result": result}
    except (ImageGenError, JobCancelledError):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("FAL submit failed: %s", exc)
        raise ImageGenError(
            PROVIDER_FAILED, f"FAL submit failed: {exc}", provider="fal", detail=str(exc)
        ) from exc


def fal_upload_image(image_b64_or_path: str, filename: str = "image.png") -> str:
    """Upload an image (data URL, public URL, or allowed local path).

    Local paths are only accepted inside the plugin roots (anti-exfiltration);
    the payload is validated by size and magic bytes before the upload.
    """
    key = _fal_key()
    if not key:
        if _managed_gateway_active():
            from dashboard import nous_portal

            return nous_portal.upload_reference(image_b64_or_path)
        raise ImageGenError(
            PROVIDER_UNAVAILABLE,
            "The FAL provider is unavailable: no FAL_KEY configured",
            provider="fal",
        )

    kind, data = image_input.resolve_image_source(image_b64_or_path)
    if kind == "url":
        return image_b64_or_path  # public URL is already usable
    assert data is not None

    def _do_upload():
        # FAL storage hands out a signed upload URL; the official client does that dance.
        import fal_client

        return fal_client.SyncClient(key=key).upload(data, image_input.detect_mime(data), filename)
    try:
        return retry_transient(_do_upload, label="FAL upload")
    except Exception as exc:  # noqa: BLE001
        logger.error("FAL upload failed: %s", exc)
        raise ImageGenError(
            PROVIDER_FAILED, f"FAL upload failed: {_http_detail(exc)}", provider="fal", detail=str(exc)
        ) from exc


# Historical alias of the FAL path with references (was a NameError at runtime).
fal_upload_file = fal_upload_image


def reference_mode_for(provider: str) -> str:
    """How the provider consumes reference images: ``"url"`` or ``"local"``.

    ``"url"`` providers (fal, krea) receive the refs as public URLs — local
    paths/data URLs must be published before the call. ``"local"`` providers
    (openai, openai-codex, xai, openrouter, nous) read the bytes themselves
    and keep the local path.
    """
    if str(provider or "").strip().lower() in ("fal", "krea"):
        return "url"
    return "local"


def prepare_reference_sources(
    provider: str,
    model: str,
    refs: Optional[List[str]],
    *,
    max_refs: int,
) -> List[str]:
    """Normalize references to exactly what ``provider`` accepts.

    - ``"url"`` mode (fal, krea): local paths/data URLs are published via the
      FAL uploader (or the managed ``nous-upload`` gateway when there is no
      FAL_KEY); https URLs pass through.
    - ``"local"`` mode (openai, openai-codex, xai, openrouter, nous): paths
      are validated (they exist and are inside the plugin roots) and kept —
      these SDKs read the bytes; http(s)/data URLs pass through.

    Never drops a reference silently: raises ImageGenError with an actionable
    code and message when a ref cannot be resolved or when the count exceeds
    the cap.
    """
    refs = [image_input.resolve_served_image(v) for v in (refs or []) if str(v).strip()]
    if not refs:
        return []
    max_refs = max(0, int(max_refs or 0))
    if max_refs <= 0:
        raise ImageGenError(
            REFS_MODEL_UNSUPPORTED,
            f"The model '{model}' does not accept reference images",
            model=model,
            provider=provider,
        )
    if len(refs) > max_refs:
        raise ImageGenError(
            REFS_TOO_MANY,
            f"The model '{model}' accepts at most {max_refs} reference image(s); "
            f"you provided {len(refs)}.",
            model=model,
            max=max_refs,
            provided=len(refs),
        )
    if reference_mode_for(provider) == "url":
        sources: List[str] = []
        for idx, ref in enumerate(refs):
            if ref.startswith("https://"):
                sources.append(ref)
                continue
            try:
                sources.append(fal_upload_image(ref, f"reference-{idx + 1}.png"))
            except ImageGenError as exc:
                if exc.code == REFS_UPLOAD_FAILED:
                    raise
                raise ImageGenError(
                    REFS_UPLOAD_FAILED,
                    f"Failed to upload the reference image: {exc}",
                    ref=_short_ref(ref),
                    detail=str(exc),
                ) from exc
            except Exception as exc:  # noqa: BLE001
                raise ImageGenError(
                    REFS_UPLOAD_FAILED,
                    f"Failed to upload the reference image: {exc}",
                    ref=_short_ref(ref),
                    detail=str(exc),
                ) from exc
        return sources
    # "local" mode — validate (size, magic bytes, roots) and keep the ref.
    sources = []
    for ref in refs:
        try:
            image_input.resolve_image_source(ref)
        except ValueError as exc:
            raise ImageGenError(
                REFS_UNRESOLVED,
                f"Could not resolve the reference image '{ref}': {exc}",
                ref=_short_ref(ref),
                detail=str(exc),
            ) from exc
        sources.append(ref)
    return sources


def fal_queue_poll(model: str, payload: Dict[str, Any], timeout_s: float = 300.0,
                   cancel: Optional[Callable[[], bool]] = None,
                   on_submit: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Submit to the FAL queue and poll until COMPLETED/FAILED.

    ``cancel`` is checked between polls to abort cancelled jobs early.
    ``on_submit`` fires with the provider ``request_id`` right after the queue
    accepts the paid request — the checkpoint hook for job persistence.
    """
    _safe_model_id(model)
    key = _fal_key()
    if not key:
        if _managed_gateway_active():
            # Nous Portal subscription routes the queue through the managed
            # gateway — the host client submits and polls for us.
            return fal_submit_sync(model, payload, cancel=cancel, on_submit=on_submit)
        raise ImageGenError(
            PROVIDER_UNAVAILABLE,
            "The FAL provider is unavailable: no FAL_KEY configured",
            provider="fal",
        )
    import urllib.request

    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"https://queue.fal.run/{model}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Key {key}",
            "Content-Type": "application/json",
            "x-idempotency-key": str(uuid.uuid4()),
        },
    )
    def _do_submit():
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode())
    try:
        _check_cancel(cancel)
        queued = billing.run("fal", model, _fal_cost(model, payload), _do_submit)
    except (ImageGenError, JobCancelledError):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("FAL queue submit failed: %s", exc)
        raise ImageGenError(
            PROVIDER_FAILED, f"FAL queue submit failed: {_http_detail(exc)}", provider="fal", detail=_http_detail(exc)
        ) from exc

    request_id = queued.get("request_id") or queued.get("requestId")
    if not request_id:
        # Synchronous (model answers directly)
        return queued
    app_id = "/".join(model.split("/")[:2])
    response_url = _fal_queue_url(queued.get("response_url") or f"https://queue.fal.run/{app_id}/requests/{request_id}")
    status_url = _fal_queue_url(queued.get("status_url") or response_url + "/status")
    if on_submit is not None:
        on_submit({"provider": "fal", "model": model, "endpoint": model,
                   "requestId": str(request_id), "responseUrl": response_url, "statusUrl": status_url})

    start = time.monotonic()
    poll_delay = 2.5
    while time.monotonic() - start < timeout_s:
        _check_cancel(cancel)
        _cancellable_sleep(cancel, poll_delay)
        _check_cancel(cancel)
        def _do_status():
            status_request = urllib.request.Request(status_url, headers={"Authorization": f"Key {key}"})
            with urllib.request.urlopen(status_request, timeout=60) as resp:
                return json.loads(resp.read().decode())
        try:
            status = retry_transient(_do_status, label="FAL status poll", attempts=2, base_delay=0.5)
        except Exception as exc:  # noqa: BLE001
            if not _is_transient_error(exc):
                raise ImageGenError(PROVIDER_FAILED, "FAL status request failed", provider="fal", detail=_http_detail(exc), requestId=request_id) from exc
            logger.debug("FAL status poll error: %s", exc)
            poll_delay = min(poll_delay * 2, 10.0)
            continue
        poll_delay = 2.5
        st = status.get("status", "")
        if st == "COMPLETED":
            def _do_result():
                result_request = urllib.request.Request(response_url, headers={"Authorization": f"Key {key}"})
                with urllib.request.urlopen(result_request, timeout=90) as resp:
                    return json.loads(resp.read().decode())
            try:
                return retry_transient(_do_result, label="FAL result fetch")
            except Exception as exc:  # noqa: BLE001
                logger.error("FAL result fetch failed: %s", exc)
                raise ImageGenError(
                    PROVIDER_FAILED, f"FAL result fetch failed: {_http_detail(exc)}", provider="fal", detail=_http_detail(exc)
                ) from exc
        if st in ("FAILED", "ERROR"):
            raise ImageGenError(
                PROVIDER_FAILED,
                f"FAL job failed: {status.get('error', st)}",
                provider="fal",
                detail=str(status.get("error") or st),
            )
    raise ImageGenError(
        PROVIDER_FAILED,
        "FAL generation timed out after 5 minutes",
        provider="fal",
        detail="generation timed out after 5 minutes",
    )


def _fal_queue_url(value: str) -> str:
    from urllib.parse import urlsplit

    parsed = urlsplit(str(value))
    if parsed.scheme != "https" or parsed.netloc != "queue.fal.run" or parsed.fragment or parsed.username:
        raise ImageGenError(PROVIDER_FAILED, "Invalid FAL queue URL", provider="fal", detail="Unexpected queue host")
    return str(value)


def _fal_wait_completed(status_url: str, key: str, request_id: str, timeout_s: float = 240.0) -> None:
    import urllib.request

    request = urllib.request.Request(status_url, headers={"Authorization": f"Key {key}"})
    def _do_status():
        with urllib.request.urlopen(request, timeout=60) as resp:
            return json.loads(resp.read().decode())
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            status = str(retry_transient(_do_status, label="FAL status poll").get("status", ""))
        except Exception as exc:  # noqa: BLE001
            raise ImageGenError(PROVIDER_FAILED, f"FAL status request failed: {_http_detail(exc)}", provider="fal",
                                detail=_http_detail(exc), requestId=request_id) from exc
        if status not in ("IN_QUEUE", "IN_PROGRESS"):
            return  # COMPLETED, or a failure the result request reports in detail
        if time.monotonic() >= deadline:
            raise ImageGenError(PROVIDER_FAILED, "FAL is still generating this image", provider="fal",
                                detail="still running at FAL; try again in a minute", requestId=request_id)
        time.sleep(2.5)


def fal_fetch_result(model: str, request_id: str, response_url: str = "") -> Dict[str, Any]:
    """Fetch a completed FAL queue result by request id (resume path).

    Used by POST /jobs/{id}/resume to recover a result after the process died
    mid-generation. Requires FAL_KEY (the direct queue endpoint); errors
    surface as ImageGenError(PROVIDER_FAILED, ...) with the stable code.
    """
    _safe_model_id(model)
    rid = str(request_id or "").strip()
    if not rid or not _MODEL_ID_RE.match(rid) or ".." in rid:
        raise ImageGenError(
            MODEL_INVALID,
            f"Invalid FAL request id: {request_id!r}",
            model=rid or str(request_id),
        )
    key = _fal_key()
    if not key:
        raise ImageGenError(
            PROVIDER_UNAVAILABLE,
            "The FAL provider is unavailable: no FAL_KEY configured",
            provider="fal",
        )
    import urllib.request

    app_id = "/".join(model.split("/")[:2])
    url = _fal_queue_url(response_url or f"https://queue.fal.run/{app_id}/requests/{rid}")
    # A process that died right after submitting leaves the request still running:
    # its result answers 400 until FAL completes it, so wait for the status first.
    _fal_wait_completed(url + "/status", key, rid)
    req = urllib.request.Request(url, method="GET", headers={"Authorization": f"Key {key}"})
    def _do_fetch():
        with urllib.request.urlopen(req, timeout=90) as resp:
            return json.loads(resp.read().decode())
    try:
        return retry_transient(_do_fetch, label="FAL result fetch")
    except Exception as exc:  # noqa: BLE001
        logger.error("FAL result fetch failed for %s: %s", rid, exc)
        raise ImageGenError(
            PROVIDER_FAILED, f"FAL result fetch failed: {_http_detail(exc)}", provider="fal", detail=_http_detail(exc)
        ) from exc


def _extract_images(result: Dict[str, Any]) -> List[str]:
    """Extract image URLs from a FAL result (common formats)."""
    out: List[str] = []
    images = result.get("images")
    if isinstance(images, list):
        for img in images:
            if isinstance(img, str):
                out.append(img)
            elif isinstance(img, dict) and img.get("url"):
                out.append(img["url"])
    elif isinstance(images, dict) and images.get("url"):
        out.append(images["url"])
    if not out and result.get("image"):
        out.append(result["image"]["url"] if isinstance(result["image"], dict) else result["image"])
    if not out and result.get("url"):
        out.append(result["url"])
    if not out and result.get("output"):
        o = result["output"]
        if isinstance(o, str):
            out.append(o)
        elif isinstance(o, dict) and o.get("url"):
            out.append(o["url"])
    return out


def _resolution_to_pixels(resolution: str, aspect_ratio: str) -> Dict[str, int]:
    """Convert an editorial resolution into exact dimensions, multiples of 8."""
    max_edge = {"1K": 1024, "2K": 2048, "4K": 4096}.get(str(resolution).upper(), 1024)
    try:
        rw, rh = (max(1, int(v)) for v in str(aspect_ratio).split(":", 1))
    except (TypeError, ValueError):
        rw, rh = 1, 1
    if rw >= rh:
        width = max_edge
        height = round((max_edge * rh / rw) / 8) * 8
    else:
        height = max_edge
        width = round((max_edge * rw / rh) / 8) * 8
    return {"width": max(256, width), "height": max(256, height)}


# ---------------------------------------------------------------------------
# Text-to-image generation
# ---------------------------------------------------------------------------

def _reference_model_hint(provider: str, provider_obj: Any) -> str:
    """List up to 4 sibling models that accept references (error hint)."""
    try:
        from dashboard.capabilities import resolve_capabilities

        picks = []
        for entry in (provider_obj.list_models() or []):
            mid = entry.get("id") or entry.get("model") or ""
            if not mid:
                continue
            sibling = resolve_capabilities(provider, mid, provider_obj=provider_obj)
            if int(sibling.get("maxReferences") or 0) > 0:
                picks.append(mid)
            if len(picks) >= 4:
                break
        if picks:
            return " Models that accept references: " + ", ".join(picks) + "."
    except Exception:  # noqa: BLE001
        pass
    return ""


def _normalize_generation_result(result: Dict[str, Any], *, refs: List[str]) -> Dict[str, Any]:
    """Guarantee the text-to-image contract keys on any backend result.

    Contract: ``images``, ``provider``, ``model``, ``modality``,
    ``references_used``, ``cost_estimate``. Backends return what they know and
    the dispatcher fills the rest, so every caller sees one shape regardless
    of the provider that served the request.
    """
    out = dict(result)
    out.setdefault("modality", "image" if refs else "text")
    out.setdefault("references_used", len(refs))
    out.setdefault("cost_estimate", None)
    return out


# Provider dispatch: see the ``_PROVIDER_BACKENDS`` registry docstring below
# (defined with the backend wrappers) for how to add a new direct provider.

def generate_text_to_image(
    provider: str,
    model: str,
    prompt: str,
    aspect_ratio: str = "1:1",
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
    num_images: int = 1,
    resolution: str = "1K",
    reference_images: Optional[List[str]] = None,
    cancel: Any = None,
    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Generate per provider and use references when the model accepts them.

    Direct backends (magnific, nous, vertex) come from the
    ``_PROVIDER_BACKENDS`` registry; every other provider is served by the
    Hermes registered providers or the native FAL catalog (see
    ``_generate_via_registered_or_fal``). Read the registry docstring for the
    backend contract.
    """
    num_images = min(MAX_GENERATIONS, max(1, int(num_images)))
    seed = _validate_seed(seed)
    refs = [str(v).strip() for v in (reference_images or []) if str(v).strip()]

    backend = _PROVIDER_BACKENDS.get(provider)
    # A "nous" model id outside the managed Nous Portal catalog falls through
    # to the registered Nous Portal provider (OpenRouter-backed, refs-capable).
    if provider == "nous":
        from dashboard import nous_portal

        if not nous_portal.get_model(model):
            backend = None
    if backend is None:
        result = _generate_via_registered_or_fal(
            provider=provider,
            model=model,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            seed=seed,
            negative_prompt=negative_prompt,
            num_images=num_images,
            resolution=resolution,
            refs=refs,
            cancel=cancel,
            on_submit=on_submit,
        )
    else:
        result = backend(
            provider=provider,
            model=model,
            prompt=prompt,
            aspect_ratio=aspect_ratio,
            seed=seed,
            negative_prompt=negative_prompt,
            num_images=num_images,
            resolution=resolution,
            reference_images=refs,
            cancel=cancel,
            on_submit=on_submit,
        )
    return _normalize_generation_result(result, refs=refs)


def _generate_via_registered_or_fal(
    *,
    provider: str,
    model: str,
    prompt: str,
    aspect_ratio: str,
    seed: Optional[int],
    negative_prompt: Optional[str],
    num_images: int,
    resolution: str,
    refs: List[str],
    cancel: Any = None,
    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Fallback text-to-image path: registered Hermes providers, then native FAL."""
    # Provider registered in Hermes (openai, openai-codex, xai, krea, deepinfra, openrouter...)
    if provider != "fal":
        try:
            from agent.image_gen_registry import get_provider

            # Make sure the Hermes image_gen/* plugins are registered
            try:
                from dashboard.providers_catalog import _ensure_providers_registered

                _ensure_providers_registered()
            except Exception:  # noqa: BLE001
                pass

            prov = get_provider(provider)
            if prov is None:
                raise ImageGenError(
                    PROVIDER_NOT_REGISTERED,
                    f"The provider '{provider}' is not registered",
                    provider=provider,
                )
            if not prov.is_available():
                raise ImageGenError(
                    PROVIDER_UNAVAILABLE,
                    f"The provider '{provider}' is unavailable (missing credentials?)",
                    provider=provider,
                )
            from dashboard.capabilities import resolve_capabilities

            # Check BY SELECTED MODEL — the global Hermes model may accept refs
            # when the model chosen in the selector does not.
            caps = resolve_capabilities(provider, model, provider_obj=prov)
            max_refs = int(caps.get("maxReferences") or 0)
            if refs and max_refs <= 0:
                raise ImageGenError(
                    REFS_MODEL_UNSUPPORTED,
                    f"The model '{model}' does not accept reference images. "
                    "Choose a model marked as 'Accepts references'."
                    + _reference_model_hint(provider, prov),
                    model=model,
                    provider=provider,
                )
            prepared_refs = (
                prepare_reference_sources(provider, model, refs, max_refs=max_refs)
                if refs
                else []
            )
            model_meta = next((entry for entry in prov.list_models() if (entry.get("id") or entry.get("model")) == model), {})
            unit_cost = _estimate_cost(model, model_meta, 1)
            _reg_cost = unit_cost * num_images if unit_cost is not None else None
            results = []
            used_models: set[str] = set()
            delivered: set[str] = set()
            for i in range(num_images):
                _check_cancel(cancel)
                aspect_word = _aspect_ratio_word(aspect_ratio)
                kwargs: Dict[str, Any] = {
                    "prompt": _with_written_settings(provider, prompt, aspect_word),
                    "aspect_ratio": aspect_word,
                    "seed": (seed + i) if (seed is not None and num_images > 1) else seed,
                    "model": model,
                }
                if prepared_refs:
                    kwargs["image_url"] = prepared_refs[0]
                    if len(prepared_refs) > 1:
                        kwargs["reference_image_urls"] = prepared_refs[1:]
                res = billing.run(provider, model, unit_cost,
                    lambda: prov.generate(**kwargs),
                )
                if isinstance(res, dict) and not res.get("success"):
                    msg = str(res.get("error") or f"Provider {provider} failed")
                    raise ImageGenError(PROVIDER_FAILED, msg, provider=provider, detail=msg) from None
                results.append(_provider_result_to_url(res))
                used = res.get("model") if isinstance(res, dict) else None
                if isinstance(used, str) and used.strip():
                    used_models.add(used.strip())
                if isinstance(res, dict):
                    delivered.update(_delivery_misses(provider, res))
            # Some Hermes providers (OpenAI, OpenAI Codex) ignore the requested model and use the
            # one set in Hermes. Record the model that really ran and say so.
            actual = used_models.pop() if len(used_models) == 1 else model
            warnings = [] if actual == model else [
                f"{provider} used {actual}, the model set in Hermes (Tools → Image Generation), "
                f"instead of {model}."]
            warnings.extend(sorted(delivered))
            return {
                "images": results,
                "provider": provider,
                "model": actual,
                "modality": "image" if refs else "text",
                "references_used": len(refs),
                "cost_estimate": _reg_cost,
                "warnings": warnings,
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("Provider %s failed: %s", provider, exc)
            raise

    # Native FAL — Hermes catalog (central get_fal_model_meta); other FAL models
    # are built from FAL's own published schema.
    from dashboard import fal_catalog
    from dashboard.providers_catalog import get_fal_model_meta

    if not get_fal_model_meta(model) and fal_catalog.knows(model):
        model_meta = {}
        endpoint, payload = _fal_catalog_request(model, prompt, aspect_ratio, resolution, seed, negative_prompt, refs)
    else:
        model_meta, endpoint, payload = _fal_hermes_request(model, prompt, aspect_ratio, resolution, seed, negative_prompt, refs)
    return _run_fal_generation(model, model_meta, endpoint, payload, refs=refs, num_images=num_images,
                               seed=seed, negative_prompt=negative_prompt, resolution=resolution,
                               aspect_ratio=aspect_ratio, cancel=cancel, on_submit=on_submit)


def _fal_catalog_request(model, prompt, aspect_ratio, resolution, seed, negative_prompt, refs):
    """Endpoint and payload for a FAL model outside the Hermes catalog, from FAL's schema."""
    from dashboard import fal_catalog

    endpoint = model
    if refs:
        endpoint = fal_catalog.edit_sibling(model) or model
        refs = prepare_reference_sources("fal", model, refs, max_refs=fal_catalog.reference_limit(endpoint))
    payload = fal_catalog.build_payload(endpoint, prompt=prompt, aspect_ratio=aspect_ratio, resolution=resolution,
                                        seed=seed, negative_prompt=negative_prompt, image_urls=refs)
    return endpoint, payload


def _fal_hermes_request(model, prompt, aspect_ratio, resolution, seed, negative_prompt, refs):
    """Endpoint and payload from the Hermes FAL catalog, or a manual payload without it."""
    try:
        from dashboard.providers_catalog import get_fal_model_meta
        from tools.image_generation_tool import (
            _build_fal_edit_payload,
            _build_fal_payload,
        )
        from dashboard.capabilities import resolve_capabilities

        model_meta = get_fal_model_meta(model)
        # Same rule as the rest of the pipeline: caps per (provider, model).
        caps = resolve_capabilities("fal", model)
        endpoint = model
        if refs:
            edit_endpoint = model_meta.get("edit_endpoint")
            if not edit_endpoint:
                raise ImageGenError(
                    REFS_MODEL_UNSUPPORTED,
                    f"The model '{model_meta.get('display', model)}' does not accept reference images. "
                    "Choose a model marked as 'Accepts references'.",
                    model=model,
                    provider="fal",
                )
            uploaded_refs = prepare_reference_sources(
                "fal", model, refs,
                max_refs=int(caps.get("maxReferences") or 1),
            )
            payload = _build_fal_edit_payload(
                model_id=model,
                prompt=prompt,
                image_urls=uploaded_refs,
                aspect_ratio=_aspect_ratio_word(aspect_ratio),
                seed=seed,
            )
            if model_meta.get("size_style") == "aspect_ratio" and "aspect_ratio" in payload:
                payload["aspect_ratio"] = aspect_ratio
            endpoint = str(edit_endpoint)
        else:
            payload = _build_fal_payload(
                model_id=model,
                prompt=prompt,
                aspect_ratio=_aspect_ratio_word(aspect_ratio),
                seed=seed,
            )
            # The native builder works with landscape/square/portrait.
            # ImageGen exposes exact editorial ratios (4:5, 3:4, 2:3), so we
            # preserve the user's choice when the schema supports it.
            if model_meta.get("size_style") == "aspect_ratio" and "aspect_ratio" in payload:
                payload["aspect_ratio"] = aspect_ratio
            elif model_meta.get("size_style") == "image_size_preset" and "image_size" in payload:
                payload["image_size"] = _resolution_to_pixels(resolution, aspect_ratio)
    except Exception as exc:  # noqa: BLE001
        if refs:
            raise
        logger.warning("Hermes catalog unavailable (%s); manual payload", exc)
        model_meta = {}
        endpoint = model
        image_size = _fal_image_size({}, aspect_ratio)
        payload = {
            "prompt": prompt,
            "image_size": image_size,
        }
        if seed is not None:
            payload["seed"] = seed
        if negative_prompt and _model_supports_negative(model):
            payload["negative_prompt"] = negative_prompt
    return model_meta, endpoint, payload


def _run_fal_generation(model, model_meta, endpoint, payload, *, refs, num_images, seed, negative_prompt,
                        resolution, aspect_ratio, cancel, on_submit):
    """Price, budget-check and submit a prepared FAL request once per image."""
    # Budget guard: price the generation before any paid submission and refuse
    # it when the monthly limit would be crossed. The same estimate is reused
    # for the ledger and the response.
    supported = model_meta.get("edit_supports" if refs else "supports") or set()
    if negative_prompt and "negative_prompt" in supported:
        payload["negative_prompt"] = negative_prompt
    if "resolution" in supported:
        payload["resolution"] = resolution
    if "image_size" in supported and model_meta.get("size_style") == "image_size_preset":
        payload["image_size"] = _resolution_to_pixels(resolution, aspect_ratio)
    cost_estimate = _estimate_cost(model, model_meta, num_images, payload)
    # Each image reserves its own share below; refuse the whole batch up front
    # so a batch that cannot fit never pays for its first images.
    check_budget(cost_estimate)

    images: List[str] = []
    for i in range(num_images):
        _check_cancel(cancel)
        p = dict(payload)
        if num_images > 1 and seed is not None and "seed" in payload:
            p["seed"] = seed + i
        result = fal_queue_poll(endpoint, p, cancel=cancel, on_submit=on_submit)
        found = _extract_images(result)
        if not found:
            raise ImageGenError(
                MODEL_NO_IMAGE, f"FAL did not return an image for {model}", model=model, provider="fal"
            )
        images.extend(found[:1])

    return {
        "images": images,
        "provider": "fal",
        "model": model,
        "modality": "image" if refs else "text",
        "references_used": len(refs),
        "cost_estimate": cost_estimate,
    }


def _generate_nous_portal(
    *,
    provider: str = "nous",
    model: str,
    prompt: str,
    aspect_ratio: str = "1:1",
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
    num_images: int = 1,
    resolution: str = "1K",
    reference_images: Optional[List[str]] = None,
    cancel: Optional[Callable[[], bool]] = None,
    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Generate via Nous Portal (managed Tool Gateway — subscription, no FAL_KEY).

    Registry backend for the ``nous`` provider (see ``_PROVIDER_BACKENDS``).
    """
    num_images = min(MAX_GENERATIONS, max(1, int(num_images)))
    from dashboard import nous_portal

    if reference_images:
        raise ImageGenError(REFS_MODEL_UNSUPPORTED, "This Nous Portal model does not accept references", model=model, provider="nous")
    if not nous_portal.nous_portal_available():
        raise ImageGenError(
            PROVIDER_UNAVAILABLE,
            "Nous Portal is not connected — sign in to the Nous Portal (`hermes setup`) "
            "or configure FAL_KEY to use FAL.ai directly.",
            provider="nous",
        )

    meta = nous_portal.get_model(model)
    arguments: Dict[str, Any] = {"prompt": prompt, "aspect_ratio": aspect_ratio}
    if negative_prompt and _model_supports_negative(model):
        arguments["negative_prompt"] = negative_prompt
    arguments.update(meta.get("extra_args") or {})

    images: List[str] = []
    for i in range(num_images):
        _check_cancel(cancel)
        call_args = dict(arguments)
        if seed is not None:
            try:
                call_args["seed"] = int(seed) + (i if num_images > 1 else 0)
            except (TypeError, ValueError):
                pass
        result = nous_portal.submit(model, call_args, on_submit=on_submit, cancel=cancel)
        found = _extract_images(result)
        if not found:
            raise ImageGenError(
                MODEL_NO_IMAGE,
                f"Nous Portal did not return an image for {model}",
                model=model,
                provider="nous",
            )
        images.extend(found[:1])

    return {
        "images": images,
        "provider": "nous",
        "model": model,
        "modality": "text",
        "references_used": 0,
        "cost_estimate": None,
    }


def _model_supports_negative(model: str) -> bool:
    return "seedream" in model or "imagen" in model or "ideogram" in model or "kling" in model


def _fal_image_size(meta: Dict[str, Any], aspect_ratio: str) -> str:
    """Map an aspect ratio to the FAL preset (landscape/square/portrait)."""
    sizes = meta.get("sizes") if isinstance(meta, dict) else None
    if sizes:
        key = _aspect_ratio_word(aspect_ratio)
        if key in sizes:
            return sizes[key]
        return sizes.get("square", "square_hd")
    if aspect_ratio in ("16:9", "21:9", "3:2"):
        return "landscape_16_9"
    if aspect_ratio in ("9:16", "2:3", "4:5"):
        return "portrait_16_9"
    return "square_hd"


# The OpenAI Codex (ChatGPT subscription) route picks its own image size and quality and ignores
# the ones sent; it follows a shape stated in the prompt, and naming the model with high quality
# lifts its pick from low to medium, never high (2026-10-27 paid runs, NousResearch/hermes-agent#21662).
_WRITTEN_QUALITY = {"openai-codex": "Use gpt-image-2 at high quality."}
_WRITTEN_ASPECT = {
    "openai-codex": {
        "square": "Square image, 1:1 aspect ratio (1024x1024).",
        "landscape": "Horizontal landscape image, 3:2 aspect ratio, wider than tall (1536x1024).",
        "portrait": "Vertical portrait image, 2:3 aspect ratio, taller than wide (1024x1536).",
    },
}


def _with_written_settings(provider: str, prompt: str, aspect_word: str) -> str:
    # A caller that already wrote the quality line or its own shape keeps its text, written once.
    text = prompt.strip().casefold()
    quality = _WRITTEN_QUALITY.get(provider)
    if quality and quality.rstrip(".").casefold() in text:
        quality = None
    aspect = None if "aspect ratio" in text else _WRITTEN_ASPECT.get(provider, {}).get(aspect_word)
    return "\n\n".join(part for part in (quality, prompt.strip(), aspect) if part)


def _delivery_misses(provider: str, res: Dict[str, Any]) -> List[str]:
    """Warnings for a size or quality the provider reports it did not honour."""
    misses = []
    for asked_key, got_key, label in (("requested_size", "pixel_size", "size"),
                                      ("quality", "reported_quality", "quality")):
        asked, got = res.get(asked_key), res.get(got_key)
        if asked and got and asked != got:
            misses.append(f"{provider} delivered {label} {got} instead of {asked}.")
    return misses


def _aspect_ratio_word(aspect_ratio: str) -> str:
    try:
        width, height = (float(part) for part in aspect_ratio.split(":"))
        return "landscape" if width > height else "portrait" if height > width else "square"
    except (ValueError, AttributeError):
        return "square"


def _provider_result_to_url(res: Any) -> str:
    """Extract URL/path from a registry provider's result.

    b64 providers (OpenAI/Krea/etc.) save to a local file — we serve that
    file through the plugin's own /cache route so the frontend can display it.
    """
    if isinstance(res, dict):
        if res.get("image"):
            return _local_to_served(res["image"])
        if res.get("images"):
            v = res["images"]
            if isinstance(v, list) and v:
                return _local_to_served(v[0])
            return _local_to_served(v)
        for k in ("url", "image_url", "output"):
            if res.get(k):
                v = res[k]
                if isinstance(v, dict) and v.get("url"):
                    return _local_to_served(v["url"])
                return _local_to_served(v if isinstance(v, str) else str(v))
    return _local_to_served(str(res))


def _local_to_served(value: str) -> str:
    """Convert a local path into a plugin-served URL (or keep the URL)."""
    if value.startswith(("http://", "https://", "data:")):
        return value
    p = Path(value)
    if p.exists():
        from urllib.parse import urlencode, quote
        return f"/api/plugins/imagegen/cache/{quote(p.name)}?{urlencode({'p': str(p)})}"
    return value


def _estimate_cost(model: str, meta: Dict[str, Any], num_images: int, payload: Optional[Dict[str, Any]] = None) -> Optional[float]:
    try:
        price_str = str(meta.get("price", "")) if isinstance(meta, dict) else ""
        match = re.fullmatch(r"\s*\$([0-9]+(?:\.[0-9]+)?)\s*(?:/(MP|megapixel|image))?\s*", price_str, re.IGNORECASE)
        if not match:
            return None
        price = float(match.group(1))
        units = 1
        if (match.group(2) or "").lower() in ("mp", "megapixel"):
            args = payload or {}
            size = args.get("image_size")
            if not isinstance(size, dict):
                if args.get("resolution"):
                    size = _resolution_to_pixels(str(args["resolution"]), str(args.get("aspect_ratio") or "1:1"))
                else:
                    presets = {"square": (512, 512), "square_hd": (1024, 1024), "landscape_4_3": (1024, 768), "landscape_16_9": (1024, 576), "portrait_4_3": (768, 1024), "portrait_16_9": (576, 1024)}
                    dimensions = presets.get(str(size))
                    if dimensions is None:
                        return None
                    size = {"width": dimensions[0], "height": dimensions[1]}
            # Conservative estimate: billable MP units may round up.
            units = max(1, math.ceil(float(size["width"]) * float(size["height"]) / 1_000_000))
        return round(price * units * num_images, 4)
    except Exception:  # noqa: BLE001
        return None


def _fal_cost(model: str, payload: Dict[str, Any]) -> Optional[float]:
    from dashboard.providers_catalog import get_fal_model_meta
    return _estimate_cost(model, get_fal_model_meta(model), int(payload.get("num_images") or 1), payload)


def check_budget(estimate: Optional[float]) -> None:
    """Refuse a paid generation that would cross the monthly budget limit.

    Raises ``ImageGenError(BUDGET_EXCEEDED, ...)`` with ``spent``/``limit``/
    ``estimate`` params when the limit is set and ``spent + estimate`` exceeds
    it. No limit or no estimate (unpriced model) → no-op.
    """
    if not estimate:
        return
    limit = store.get_budget()["monthlyLimit"]
    if limit is None:
        return
    spent = store.spend_this_month()
    if spent + estimate > limit:
        raise ImageGenError(
            BUDGET_EXCEEDED,
            f"Monthly budget exceeded: {spent:.2f} of {limit:.2f} already spent; "
            f"this generation would add {estimate:.2f}.",
            spent=spent,
            limit=float(limit),
            estimate=float(estimate),
        )


# ---------------------------------------------------------------------------
# Edit / Inpaint / Outpaint (FAL)
# ---------------------------------------------------------------------------

def generate_edit(
    image_paths: List[str],
    prompt: str,
    model: str = "fal-ai/flux-2-pro/edit",
    aspect_ratio: str = "1:1",
    seed: Optional[int] = None,
    cancel: Any = None,
    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Natural-language editing (image-to-image) — up to 9 references.

    FLUX.2 Pro Edit keeps its pinned payload; any other FAL edit model is built
    from FAL's published schema for that endpoint.
    """
    from dashboard import fal_catalog

    seed = _validate_seed(seed)
    _check_cancel(cancel)
    if model != "fal-ai/flux-2-pro/edit":
        if not _MODEL_ID_RE.match(model) or not fal_catalog.knows(model):
            raise ImageGenError(MODEL_INVALID, "Choose an edit model from FAL's catalog", provider="fal", model=model)
        image_urls =prepare_reference_sources("fal", model, image_paths, max_refs=fal_catalog.reference_limit(model))
        payload = fal_catalog.build_payload(model, prompt=prompt, seed=seed, image_urls=image_urls)
        result = fal_queue_poll(model, payload, cancel=cancel, on_submit=on_submit)
        return {"images": _extract_images(result), "provider": "fal", "model": model}
    image_urls = [fal_upload_image(p) for p in image_paths]
    payload: Dict[str, Any] = {
        "prompt": prompt,
        "image_urls": image_urls,
    }
    if seed is not None:
        payload["seed"] = seed
    result = fal_queue_poll(model, payload, cancel=cancel, on_submit=on_submit)
    return {"images": _extract_images(result), "provider": "fal", "model": model}


def generate_inpaint(
    base_image: str,
    mask_image: str,
    prompt: str,
    aspect_ratio: str = "1:1",
    model: str = "fal-ai/flux-pro/v1/fill",
    product_image: Optional[str] = None,
    cancel: Any = None,
    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Masked inpainting (Flux Fill) — port of the creative-actions-handler."""
    import io
    from PIL import Image, ImageOps

    _check_cancel(cancel)
    if product_image:
        raise ImageGenError(MODEL_INVALID, "Flux Fill does not support a product reference", model=model)
    with Image.open(io.BytesIO(store.fetch_image_bytes(base_image))) as source:
        scene = ImageOps.exif_transpose(source).convert("RGB")
    with Image.open(io.BytesIO(store.fetch_image_bytes(mask_image))) as source:
        mask = ImageOps.exif_transpose(source).convert("L")
    if scene.size != mask.size:
        raise ImageGenError(MODEL_INVALID, "Mask dimensions must match the original image", model=model)

    def upload(value, name):
        buffer = io.BytesIO()
        value.save(buffer, format="PNG")
        return fal_upload_image("data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"), name)

    scene_url = upload(scene, "scene.png")
    mask_url = upload(mask, "mask.png")
    payload: Dict[str, Any] = {
        "image_url": scene_url,
        "mask_url": mask_url,
        "prompt": prompt,
    }
    result = fal_queue_poll(model, payload, cancel=cancel, on_submit=on_submit)
    return {"images": _extract_images(result), "provider": "fal", "model": model}


def generate_outpaint(
    image: str,
    prompt: str,
    direction: str = "all",
    expand_px: int = 256,
    model: str = "fal-ai/flux-pro/v1/fill",
    cancel: Any = None,
    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Expand the canvas and fill only its new border with the documented Fill API."""
    import io
    from PIL import Image, ImageOps

    _check_cancel(cancel)
    if direction not in ("all", "left", "right", "top", "bottom") or not 1 <= expand_px <= 2048:
        raise ImageGenError(MODEL_INVALID, "Invalid expansion direction or size", model=model)
    with Image.open(io.BytesIO(store.fetch_image_bytes(image))) as source:
        base = ImageOps.exif_transpose(source).convert("RGB")
    left = expand_px if direction in ("left", "all") else 0
    right = expand_px if direction in ("right", "all") else 0
    top = expand_px if direction in ("top", "all") else 0
    bottom = expand_px if direction in ("bottom", "all") else 0
    size = (base.width + left + right, base.height + top + bottom)
    if size[0] * size[1] > 32_000_000:
        raise ImageGenError(MODEL_INVALID, "Expanded image exceeds 32 megapixels", model=model)
    expanded = Image.new("RGB", size, "black")
    expanded.paste(base, (left, top))
    mask = Image.new("L", size, "white")
    mask.paste(0, (left, top, left + base.width, top + base.height))

    def data_url(value):
        buffer = io.BytesIO()
        value.save(buffer, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")

    return generate_inpaint(data_url(expanded), data_url(mask), prompt or "Continue the scene seamlessly", cancel=cancel, on_submit=on_submit)

# ---------------------------------------------------------------------------
# Upscale (D2) + Background removal (D6) — FAL
# ---------------------------------------------------------------------------

def generate_upscale(image: str, creativity: float = 0.4, scale: int = 2,
                     mode: str = "classic", prompt: str = "",
                     cancel: Any = None,
                     on_submit: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Magnific-style upscale: increases resolution and (in creative mode)
    invents realistic details/textures. classic = faithful; creative = enriches."""
    _check_cancel(cancel)
    img_url = fal_upload_image(image, "upscale.png")
    payload: Dict[str, Any] = {
        "image_url": img_url,
        "creativity": min(float(creativity), 0.2) if mode == "classic" else float(creativity),
        "upscale_factor": int(scale),
        "resemblance": 1.0 if mode == "classic" else 0.7,
    }
    if (prompt or "").strip():
        payload["prompt"] = prompt.strip()
    result = fal_queue_poll("fal-ai/clarity-upscaler", payload, cancel=cancel, on_submit=on_submit)
    return {"images": _extract_images(result), "provider": "fal", "model": "fal-ai/clarity-upscaler"}


def generate_bg_remove(image: str, cancel: Any = None,
                       on_submit: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Remove the image background → transparent PNG (becomes a ref for composition)."""
    _check_cancel(cancel)
    img_url = fal_upload_image(image, "bg-remove.png")
    result = fal_queue_poll("fal-ai/imageutils/rembg", {"image_url": img_url}, cancel=cancel, on_submit=on_submit)
    images = _extract_images(result)
    single = result.get("image")
    if not images and isinstance(single, str):
        images = [single]
    return {"images": images, "provider": "fal", "model": "fal-ai/imageutils/rembg"}


def _generate_vertex(
    *,
    provider: str = "vertex",
    model: str = "gemini-nano-banana-2.1",
    prompt: str,
    aspect_ratio: str = "1:1",
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
    num_images: int = 1,
    resolution: str = "1K",
    reference_images: Optional[List[str]] = None,
    cancel: Optional[Callable[[], bool]] = None,
    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Registry backend for Gemini image models on Vertex AI (see ``_PROVIDER_BACKENDS``).

    Gemini takes no seed or negative prompt; references travel inline with the request.
    """
    from dashboard import vertex_api

    spec = vertex_api.MODELS.get(model)
    if spec is None:
        raise ImageGenError(MODEL_INVALID, f"Unsupported Vertex AI model: {model}", model=model)
    refs = prepare_reference_sources("vertex", model, reference_images or [], max_refs=spec["maxReferences"])
    inline = []
    for ref in refs:
        data = store.fetch_image_bytes(ref)
        inline.append((image_input.detect_mime(data), data))
    images: List[str] = []
    for _ in range(max(1, min(int(num_images), MAX_GENERATIONS))):
        _check_cancel(cancel)
        result = billing.run("vertex", model, vertex_api.estimate(model, resolution), lambda: vertex_api.generate(
            model, prompt, aspect_ratio=aspect_ratio, resolution=resolution, references=inline))
        images.extend(result["images"])
    return _normalize_generation_result(
        {"images": images, "provider": "vertex", "model": model,
         "cost_estimate": vertex_api.estimate(model, resolution) * len(images)}, refs=refs,
    )


def _magnific_available() -> bool:
    from dashboard.magnific_api import api_key

    return bool(api_key())


def generate_magnific(
    model: str, prompt: str, aspect_ratio: str = "1:1", *,
    resolution: str = "1K", cancel: Any = None, seed: Optional[int] = None,
    reference_images: Optional[List[str]] = None,
    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Generate through the direct Magnific API."""
    from dashboard import magnific_api

    _check_cancel(cancel)
    return magnific_api.generate(
        model, prompt, aspect_ratio=aspect_ratio, resolution=resolution, seed=seed, reference_images=reference_images,
        check_cancel=lambda: _check_cancel(cancel),
        sleep=lambda delay: _cancellable_sleep(cancel, delay), on_submit=on_submit,
    )


def _generate_magnific(
    *,
    provider: str = "magnific",
    model: str,
    prompt: str,
    aspect_ratio: str = "1:1",
    seed: Optional[int] = None,
    negative_prompt: Optional[str] = None,
    num_images: int = 1,
    resolution: str = "1K",
    reference_images: Optional[List[str]] = None,
    cancel: Optional[Callable[[], bool]] = None,
    on_submit: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """Registry backend for the direct Magnific API (see ``_PROVIDER_BACKENDS``).

    Wraps :func:`generate_magnific` with the shared keyword-only signature and
    the contract return shape, including per-model reference editing.
    """
    from dashboard.magnific_catalog import get_model
    spec = get_model(model)
    refs = prepare_reference_sources("magnific", model, reference_images or [], max_refs=spec.get("maxReferences", 0))
    images: List[str] = []
    actual_model = model
    for index in range(max(1, min(int(num_images), MAX_GENERATIONS))):
        result = generate_magnific(
            model, prompt, aspect_ratio=aspect_ratio, resolution=resolution, cancel=cancel, on_submit=on_submit,
            seed=(seed + index) % (2 ** 32) if seed is not None else None, reference_images=refs,
        )
        actual_model = result.get("model", model)
        images.extend(result["images"])
    return _normalize_generation_result(
        {"images": images, "provider": "magnific", "model": actual_model}, refs=refs,
    )


# ---------------------------------------------------------------------------
# Direct text-to-image backends (registry)
#
# Providers that do NOT go through the Hermes provider registry or the FAL
# catalog are dispatched through _PROVIDER_BACKENDS. This dict is the single
# place to register a new direct backend — no if/elif chain to edit.
#
# To register a new provider:
#   1. Define a module-level function with the shared keyword-only signature
#      below (copy the parameter list of _generate_magnific).
#   2. Add it to _PROVIDER_BACKENDS under the provider id used by the API.
#
# Contract (shared by every backend):
#   Input  — the full generate_text_to_image call, all keyword-only:
#            provider, model, prompt, aspect_ratio, seed, negative_prompt,
#            num_images, resolution, reference_images, cancel. A backend may
#            ignore any parameter it does not use.
#   Output — Dict[str, Any] with the keys:
#              images          List[str]        image URLs / data URLs
#              provider        str              provider id
#              model           str              model id actually used
#              modality        "image"|"text"   whether references drove it
#              references_used int              reference count consumed
#              cost_estimate   Optional[float]  USD estimate, or None
#            Missing optional keys (modality, references_used, cost_estimate)
#            are filled by _normalize_generation_result in the dispatcher.
#   Errors — raise ImageGenError with the documented codes; the dispatcher
#            does not translate or wrap them.
# ---------------------------------------------------------------------------
ProviderBackend = Callable[..., Dict[str, Any]]

_PROVIDER_BACKENDS: Dict[str, ProviderBackend] = {
    "magnific": _generate_magnific,
    "nous": _generate_nous_portal,
    "vertex": _generate_vertex,
}
