"""Direct Vertex AI transport for Gemini image generation (Nano Banana).

API contract: https://cloud.google.com/vertex-ai/generative-ai/docs/model-reference/inference
Credentials stay in the backend and travel only in the ``x-goog-api-key`` header.
"""
from __future__ import annotations

import base64
import json
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from dashboard.errors import ImageGenError, MODEL_INVALID, MODEL_NO_IMAGE, PROVIDER_FAILED, PROVIDER_UNAVAILABLE

PROVIDER = "vertex"
API_ROOT = "https://aiplatform.googleapis.com/v1"
_GEMINI_3_RATIOS = ("1:1", "3:2", "2:3", "3:4", "1:4", "4:1", "4:3", "4:5", "5:4", "1:8", "8:1", "9:16", "16:9", "21:9")
# Gemini image models on Vertex AI (docs.cloud.google.com, read 2026-10-27; the Imagen models were retired
# in June 2026). ``usd`` is a budget estimate per output image from Google's published token prices, never
# shown as a price; the Google Cloud bill is the real cost.
MODELS = {
    "gemini-nano-banana-2.1": {"display": "Nano Banana 2.1", "maxReferences": 14, "aspectRatios": _GEMINI_3_RATIOS,
                               "resolutions": ("1K", "2K", "4K"), "usd": {"1K": 0.0336, "2K": 0.0504, "4K": 0.113}},
    "gemini-3.1-flash-image": {"display": "Nano Banana 2", "maxReferences": 14, "aspectRatios": _GEMINI_3_RATIOS,
                               "resolutions": ("1K", "2K", "4K"), "usd": {"1K": 0.067, "2K": 0.101, "4K": 0.151}},
    "gemini-3-pro-image": {"display": "Nano Banana Pro", "maxReferences": 14, "aspectRatios": _GEMINI_3_RATIOS,
                           "resolutions": ("1K", "2K", "4K"), "usd": {"1K": 0.134, "2K": 0.134, "4K": 0.24}},
    "gemini-3.1-flash-lite-image": {"display": "Nano Banana 2 Lite", "maxReferences": 14,
                                    "aspectRatios": _GEMINI_3_RATIOS, "resolutions": ("1K",), "usd": {"1K": 0.0336}},
}
DEFAULT_MODEL = "gemini-nano-banana-2.1"
# Input tokens are cheap next to the image; a flat share covers the prompt and a few references.
_PROMPT_USD = 0.002


def credentials() -> tuple[str, str]:
    """(api key, project id); the project is optional for express-mode keys."""
    from dashboard import credentials as creds

    return creds.vertex_key(), creds.vertex_project()


def available() -> bool:
    return bool(credentials()[0])


def estimate(model: str, resolution: str) -> float:
    prices = MODELS[model]["usd"]
    return prices.get(resolution, max(prices.values())) + _PROMPT_USD


def endpoint(model: str, project: str) -> str:
    path = f"/projects/{quote(project, safe='')}/locations/global" if project else ""
    return f"{API_ROOT}{path}/publishers/google/models/{quote(model, safe='')}:generateContent"


def build_body(model: str, prompt: str, aspect_ratio: str, resolution: str,
               references: List[tuple[str, bytes]]) -> Dict[str, Any]:
    parts: List[Dict[str, Any]] = [
        {"inlineData": {"mimeType": mime, "data": base64.b64encode(data).decode()}} for mime, data in references
    ]
    parts.append({"text": prompt})
    spec = MODELS[model]
    image_config: Dict[str, Any] = {
        "imageSize": resolution if resolution in spec["resolutions"] else spec["resolutions"][0]}
    if aspect_ratio in spec["aspectRatios"]:
        image_config["aspectRatio"] = aspect_ratio
    return {"contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": image_config}}


def generate(model: str, prompt: str, *, aspect_ratio: str = "1:1", resolution: str = "1K",
             references: Optional[List[tuple[str, bytes]]] = None) -> Dict[str, Any]:
    """One image from Vertex AI; returns ``{"images": [data URL], "model": model}``."""
    if model not in MODELS:
        raise ImageGenError(MODEL_INVALID, f"Unsupported Vertex AI model: {model}", model=model)
    key, project = credentials()
    if not key:
        raise ImageGenError(PROVIDER_UNAVAILABLE, "Vertex AI needs an API key in the plugin settings", provider=PROVIDER)
    body = build_body(model, prompt, aspect_ratio, resolution, references or [])
    request = Request(endpoint(model, project), data=json.dumps(body).encode("utf-8"),
                      headers={"x-goog-api-key": key, "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=300) as response:
            result = json.load(response)
    except HTTPError as exc:
        # Google's error message names the problem (quota, permission, safety) and never the key.
        try:
            message = str(json.load(exc).get("error", {}).get("message", ""))[:200]
        except (ValueError, AttributeError, OSError):
            message = ""
        detail = f"Vertex AI returned HTTP {exc.code}" + (f": {message}" if message else "")
        raise ImageGenError(PROVIDER_FAILED, detail, provider=PROVIDER, detail=detail) from exc
    except (URLError, OSError, ValueError) as exc:
        detail = "Vertex AI request failed; submission was not retried"
        raise ImageGenError(PROVIDER_FAILED, detail, provider=PROVIDER, detail=detail) from exc
    result = result if isinstance(result, dict) else {}
    candidates = result.get("candidates") or []
    for candidate in candidates:
        for part in (candidate.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or {}
            if inline.get("data"):
                mime = inline.get("mimeType") or "image/png"
                return {"images": [f"data:{mime};base64,{inline['data']}"], "model": model}
    reason = str((candidates[0].get("finishReason") if candidates else None)
                 or (result.get("promptFeedback") or {}).get("blockReason") or "no image in the response")
    raise ImageGenError(MODEL_NO_IMAGE, f"Vertex AI returned no image ({reason})", model=model, provider=PROVIDER)
