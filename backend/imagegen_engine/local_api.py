"""Local image server transport: the OpenAI images API at an address the user sets.

Serves LocalAI, stable-diffusion.cpp ``sd-server``, Ollama and any other server that answers
``GET /v1/models`` and ``POST /v1/images/generations``. The address is a plugin setting; while
it is empty nothing is sent. Requests go straight to that server: no proxy, no redirect, and an
image ``url`` in the answer is fetched only from the same server. No price: the user's own machine.
"""
from __future__ import annotations

import base64
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from imagegen_engine.errors import ImageGenError, MODEL_NO_IMAGE, PROVIDER_FAILED, PROVIDER_UNAVAILABLE

logger = logging.getLogger(__name__)

PROVIDER = "local"
URL_SETTING = "local_server_url"
ASPECT_RATIOS = ("1:1", "4:3", "3:4", "3:2", "2:3", "16:9", "9:16", "4:5", "5:4", "21:9")
# Longest edge in pixels. Local models have their own native size, so the small ones are offered too.
RESOLUTIONS = {"512px": 512, "768px": 768, "1K": 1024, "2K": 2048}
LIST_TTL = 60.0
RETRY_AFTER = 15.0
LIST_TIMEOUT = 5.0
# The provider list waits this long, once, for a server that was never asked; afterwards it never waits.
FIRST_LIST_WAIT = 0.2
# A server without a GPU can take many minutes for one image.
GENERATE_TIMEOUT = 1800.0
MAX_ANSWER_BYTES = 128 * 1024 * 1024

_lock = threading.RLock()
_cache: Dict[str, Any] = {"root": "", "models": [], "at": 0.0, "failed_at": 0.0, "thread": None, "waited": False}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 — urllib signature
        return None


_opener = build_opener(ProxyHandler({}), _NoRedirect)


def base_url() -> str:
    """The server's API root, ending in ``/v1``; empty when no valid address is set."""
    from imagegen_engine import host_llm

    raw = str(host_llm.setting(URL_SETTING, "") or "").strip().rstrip("/")
    if raw and "://" not in raw:
        raw = "http://" + raw
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return ""
    return raw if raw.endswith("/v1") else raw + "/v1"


def available() -> bool:
    return bool(base_url())


def _headers() -> Dict[str, str]:
    from imagegen_engine import credentials

    key = credentials.local_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _fail(root: str, reason: str) -> ImageGenError:
    detail = f"Local server at {_origin(root)} {reason}"
    return ImageGenError(PROVIDER_FAILED, detail, provider=PROVIDER, detail=detail)


def _read(root: str, url: str, *, body: Optional[Dict[str, Any]] = None, timeout: float) -> bytes:
    """One request to the configured server; the answer's raw bytes."""
    headers = _headers()
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with _opener.open(request, timeout=timeout) as response:
            answer = response.read(MAX_ANSWER_BYTES + 1)
    except HTTPError as exc:
        try:
            parsed = json.loads(exc.read(4096))
            error = parsed.get("error") if isinstance(parsed, dict) else None
            message = str((error.get("message") if isinstance(error, dict) else error) or "")[:200]
        except (ValueError, OSError):
            message = ""
        raise _fail(root, f"returned HTTP {exc.code}" + (f": {message}" if message else "")) from exc
    except (URLError, OSError) as exc:
        cause = getattr(exc, "reason", None) or exc
        # The system's own text for these two is long on Windows and differs by language.
        reason = ("connection refused" if isinstance(cause, ConnectionRefusedError)
                  else "timed out" if isinstance(cause, TimeoutError) else str(cause)[:120])
        again = "; the request was not sent again" if body is not None else ""
        raise _fail(root, f"did not answer ({reason}){again}") from exc
    if len(answer) > MAX_ANSWER_BYTES:
        raise _fail(root, "sent an answer that is too large")
    return answer


def _json(root: str, path: str, *, body: Optional[Dict[str, Any]] = None, timeout: float) -> Any:
    answer = _read(root, root + path, body=body, timeout=timeout)
    try:
        return json.loads(answer)
    except ValueError as exc:
        raise _fail(root, "sent an answer that is not JSON") from exc


def fetch_models(root: str = "") -> List[str]:
    """Ask the server for its model ids now; raises ``ImageGenError`` when it does not answer."""
    root = root or base_url()
    if not root:
        raise ImageGenError(PROVIDER_UNAVAILABLE, "The local server needs its address in the plugin settings",
                            provider=PROVIDER)
    answer = _json(root, "/models", timeout=LIST_TIMEOUT)
    rows = answer.get("data") if isinstance(answer, dict) else answer
    ids = [str(row.get("id") or "") if isinstance(row, dict) else str(row or "")
           for row in (rows if isinstance(rows, list) else [])]
    return [model for model in dict.fromkeys(ids) if model]


def _store(root: str, found: List[str], failed: bool) -> None:
    """Keep the server's last answer for the provider list; a server that did not answer lists nothing."""
    with _lock:
        if _cache["root"] != root:
            return
        changed = found != _cache["models"]
        _cache.update(models=found, at=0.0 if failed else time.time(), failed_at=time.time() if failed else 0.0)
    if changed:
        from imagegen_engine.events import announce

        announce("providers.changed", {"provider": PROVIDER})


def _refresh(root: str) -> None:
    """Store what the server lists now; a server that does not answer lists nothing."""
    try:
        _store(root, fetch_models(root), False)
    except ImageGenError as exc:
        logger.info("local model list not refreshed: %s", exc)
        _store(root, [], True)


def check_connection() -> List[str]:
    """Ask the server for its models now and keep the answer, so the provider list agrees with the test."""
    root = base_url()
    try:
        found = fetch_models(root)
    except ImageGenError:
        _store(root, [], True)
        raise
    _store(root, found, False)
    return found


def models() -> List[str]:
    """Model ids the server reported last, refreshed in the background.

    A list never waits on the server, except once and briefly for an address that was never asked.
    """
    root = base_url()
    if not root:
        return []
    with _lock:
        if _cache["root"] != root:
            _cache.update(root=root, models=[], at=0.0, failed_at=0.0, thread=None, waited=False)
        now = time.time()
        thread = _cache["thread"]
        first, _cache["waited"] = not _cache["waited"], True
        stale = now - _cache["at"] > LIST_TTL and now - _cache["failed_at"] > RETRY_AFTER
        if stale and not (thread and thread.is_alive()):
            thread = _cache["thread"] = threading.Thread(
                target=_refresh, args=(root,), name="imagegen-local-models", daemon=True)
            thread.start()
    if first and thread is not None:
        thread.join(FIRST_LIST_WAIT)
    with _lock:
        return list(_cache["models"]) if _cache["root"] == root else []


def pixel_size(resolution: str, aspect_ratio: str) -> Dict[str, int]:
    """Exact dimensions for a format, in multiples of 64.

    Stable Diffusion models take only multiples of 64 and a server rounds anything else up
    (stable-diffusion.cpp turned 512x336 into 512x384), which changes the format asked for.
    """
    edge = RESOLUTIONS.get(str(resolution), RESOLUTIONS["1K"])
    try:
        rw, rh = (max(1, int(value)) for value in str(aspect_ratio).split(":", 1))
    except (TypeError, ValueError):
        rw, rh = 1, 1
    short = max(256, round(edge * min(rw, rh) / max(rw, rh) / 64) * 64)
    return {"width": edge if rw >= rh else short, "height": short if rw >= rh else edge}


def _image_data_url(data: bytes) -> str:
    from imagegen_engine.image_input import detect_mime

    return f"data:{detect_mime(data)};base64,{base64.b64encode(data).decode()}"


def generate(model: str, prompt: str, *, aspect_ratio: str = "1:1", resolution: str = "1K") -> Dict[str, Any]:
    """One image from the local server; returns ``{"images": [data URL], "model": model}``."""
    root = base_url()
    if not root:
        raise ImageGenError(PROVIDER_UNAVAILABLE, "The local server needs its address in the plugin settings",
                            provider=PROVIDER)
    size = pixel_size(resolution, aspect_ratio)
    body = {"model": model, "prompt": prompt, "n": 1, "size": f"{size['width']}x{size['height']}",
            "response_format": "b64_json"}
    answer = _json(root, "/images/generations", body=body, timeout=GENERATE_TIMEOUT)
    rows = answer.get("data") if isinstance(answer, dict) else None
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        if row.get("b64_json"):
            try:
                return {"images": [_image_data_url(base64.b64decode(str(row["b64_json"])))], "model": model}
            except ValueError as exc:
                raise _fail(root, "sent an image that could not be decoded") from exc
        if row.get("url"):
            # Some servers ignore ``response_format`` and answer with a link to their own file.
            url = urljoin(root + "/", str(row["url"]))
            if _origin(url) != _origin(root):
                raise _fail(root, "answered with an image on another address, which is not fetched")
            return {"images": [_image_data_url(_read(root, url, timeout=LIST_TIMEOUT * 6))], "model": model}
    raise ImageGenError(MODEL_NO_IMAGE, f"The local server returned no image for {model}", model=model,
                        provider=PROVIDER)
