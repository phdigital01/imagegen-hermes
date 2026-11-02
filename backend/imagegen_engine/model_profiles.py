"""Model capability profiles and stable generation intent helpers."""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Dict, Iterable, List, Mapping

_DEFAULT_CAPABILITIES: Dict[str, Any] = {
    "maxReferences": 0,
    "edit": False,
    "inpaint": False,
    "outpaint": False,
    "bg": False,
    "upscale": False,
    "animate": False,
    "negativeMode": "unsupported",
    "strengthTags": [],
    "resolutions": [],
}

# Family prompt dialects — used by optimize/refine callers as system addenda.
_FAMILY_PROFILES: List[Dict[str, Any]] = [
    {
        "id": "gpt-image",
        "match": ["gpt-image", "openai", "dall-e", "chatgpt"],
        "prompt_style": "natural",
        "negative_mode": "omit",
        "prefer_camera_exif": False,
        "prefer_short": True,
        "system_addendum": (
            "Write one plain English paragraph. Prefer concrete materials and lighting. "
            "Avoid quality-tag stacks and Midjourney parameters."
        ),
    },
    {
        "id": "grok",
        "match": ["grok", "xai", "imagine"],
        "prompt_style": "natural",
        "negative_mode": "inline",
        "prefer_camera_exif": False,
        "prefer_short": False,
        "system_addendum": (
            "Natural cinematic prose. Strong instruction following. "
            "Do not invent brand logos or UI chrome unless requested."
        ),
    },
    {
        "id": "flux",
        "match": ["flux", "fal-ai/flux"],
        "prompt_style": "mixed",
        "negative_mode": "separate",
        "prefer_camera_exif": True,
        "prefer_short": False,
        "system_addendum": (
            "Detailed photographic prompt. Named lighting and lens cues help. "
            "Keep product geometry explicit when references exist."
        ),
    },
    {
        "id": "seedream",
        "match": ["seedream"],
        "prompt_style": "natural",
        "negative_mode": "separate",
        "prefer_camera_exif": False,
        "prefer_short": False,
        "system_addendum": "Clear subject and scene structure. Multi-ref fidelity first.",
    },
    {
        "id": "ideogram",
        "match": ["ideogram"],
        "prompt_style": "natural",
        "negative_mode": "separate",
        "prefer_camera_exif": False,
        "prefer_short": True,
        "system_addendum": "Prioritize legible text layout when the user wants lettering.",
    },
    {
        "id": "imagen",
        "match": ["imagen", "gemini", "nano-banana", "mai-image"],
        "prompt_style": "natural",
        "negative_mode": "omit",
        "prefer_camera_exif": False,
        "prefer_short": False,
        "system_addendum": "Natural language scene description. Preserve referenced subjects.",
    },
    {
        "id": "qwen",
        "match": ["qwen", "alibaba"],
        "prompt_style": "natural",
        "negative_mode": "separate",
        "prefer_camera_exif": True,
        "prefer_short": False,
        "system_addendum": (
            "Detailed natural-language scene description. This model reads long prompts "
            "well and renders text accurately; keep lettering in quotation marks."
        ),
    },
    {
        "id": "recraft",
        "match": ["recraft"],
        "prompt_style": "mixed",
        "negative_mode": "separate",
        "prefer_camera_exif": False,
        "prefer_short": True,
        "system_addendum": (
            "Design-oriented description: composition, color palette, style and vector-clean "
            "geometry. Avoid photographic camera jargon for graphic assets."
        ),
    },
    {
        "id": "krea",
        "match": ["krea"],
        "prompt_style": "natural",
        "negative_mode": "inline",
        "prefer_camera_exif": True,
        "prefer_short": False,
        "system_addendum": (
            "Name the look directly: medium, texture and finish (film grain, motion blur, "
            "brush strokes). Krea rewards a clear aesthetic over a list of quality tags."
        ),
    },
    {
        "id": "kling",
        "match": ["kling"],
        "prompt_style": "natural",
        "negative_mode": "separate",
        "prefer_camera_exif": True,
        "prefer_short": False,
        "system_addendum": (
            "Realistic scene description with explicit subject, setting, lighting and lens. "
            "Spell out fine surface detail; the model renders it at native 2K."
        ),
    },
    {
        "id": "muse",
        "match": ["muse", "meta/"],
        "prompt_style": "natural",
        "negative_mode": "omit",
        "prefer_camera_exif": False,
        "prefer_short": True,
        "system_addendum": (
            "Short plain-English description of a realistic scene. Put any lettering in "
            "quotation marks and say where it sits."
        ),
    },
    {
        "id": "z-image",
        "match": ["z-image"],
        "prompt_style": "mixed",
        "negative_mode": "omit",
        "prefer_camera_exif": True,
        "prefer_short": True,
        "system_addendum": (
            "Compact English prompt: subject first, then setting, light and camera. "
            "A fast distilled model, so keep it under about 60 words."
        ),
    },
    {
        "id": "default",
        "match": [],
        "prompt_style": "natural",
        "negative_mode": "inline",
        "prefer_camera_exif": False,
        "prefer_short": False,
        "system_addendum": "One production-ready English paragraph. Be specific and concrete.",
    },
]


def capabilities_for_model(metadata: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Normalize provider metadata into the frontend's stable capability shape."""
    meta = metadata or {}
    caps = deepcopy(_DEFAULT_CAPABILITIES)
    raw_caps = meta.get("capabilities")
    if isinstance(raw_caps, Mapping):
        caps.update({key: value for key, value in raw_caps.items() if key in caps})
    max_refs = meta.get("maxReferences", meta.get("max_reference_images", caps["maxReferences"]))
    try:
        caps["maxReferences"] = max(0, int(max_refs or 0))
    except (TypeError, ValueError):
        caps["maxReferences"] = 0
    if not caps["maxReferences"] and meta.get("edit_endpoint"):
        caps["maxReferences"] = max(caps["maxReferences"], 1)
    if meta.get("referenceImages") and not caps["maxReferences"]:
        caps["maxReferences"] = 1
    caps["edit"] = bool(meta.get("edit", meta.get("edit_endpoint", caps["edit"])))
    caps["inpaint"] = bool(meta.get("inpaint", meta.get("supports_inpaint", caps["inpaint"])))
    caps["outpaint"] = bool(meta.get("outpaint", meta.get("supports_outpaint", caps["outpaint"])))
    caps["bg"] = bool(meta.get("bg", meta.get("supports_background_removal", caps["bg"])))
    caps["upscale"] = bool(meta.get("upscale", meta.get("supports_upscale", caps["upscale"])))
    caps["animate"] = bool(meta.get("animate", meta.get("supports_animation", caps["animate"])))
    caps["negativeMode"] = str(meta.get("negativeMode", meta.get("negative_mode", caps["negativeMode"])))
    strengths = meta.get("strengthTags", meta.get("strength_tags", caps["strengthTags"]))
    caps["strengthTags"] = list(strengths) if isinstance(strengths, Iterable) and not isinstance(strengths, (str, bytes)) else []
    resolutions = meta.get("resolutions", meta.get("resolutionOptions", caps["resolutions"]))
    caps["resolutions"] = list(resolutions) if isinstance(resolutions, Iterable) and not isinstance(resolutions, (str, bytes)) else []
    return caps


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")


def _token_contains(value: str, token: str) -> bool:
    """True when ``token`` appears as a unit inside an id (e.g. ``flux``
    matches ``fal-ai/flux-2-pro`` but not ``gpt-image-1``; the point is to
    require a token boundary for short tokens)."""
    if token.startswith("fal-ai/"):
        return token in value
    return re.search(rf"(^|[^A-Za-z0-9]){re.escape(token)}([^A-Za-z0-9]|$)", value) is not None


def resolve_family(provider: str = "", model: str = "") -> Dict[str, Any]:
    """Resolve the prompt family by model tokens (more specific) and then by
    provider tokens — never by a loose substring (``openai`` + ``flux`` must
    not fall into the gpt-image family)."""
    model_s = str(model or "").lower()
    provider_s = str(provider or "").lower()
    families = [f for f in _FAMILY_PROFILES if f["id"] != "default"]
    for family in families:
        if any(_token_contains(model_s, token) for token in family["match"]):
            return family
    for family in families:
        if any(_token_contains(provider_s, token) for token in family["match"]):
            return family
    return _FAMILY_PROFILES[-1]


def profile_for_model(provider: str = "", model: str = "", metadata: Mapping[str, Any] | None = None) -> Dict[str, Any]:
    """Return a serializable model profile without exposing provider secrets."""
    family = resolve_family(provider, model)
    return {
        "provider": provider,
        "id": model,
        "family": family["id"],
        "promptStyle": family["prompt_style"],
        "systemAddendum": family["system_addendum"],
        "capabilities": capabilities_for_model(metadata),
    }


def prompt_system_addendum(provider: str = "", model: str = "") -> str:
    return str(resolve_family(provider, model).get("system_addendum") or "")


INTENT_SCHEMA = "imagegen.intent.v2"

def build_intent(config: Mapping[str, Any]) -> Dict[str, Any]:
    """Build the stable, provider-neutral intent persisted with a generation.

    V2 stores the full shape: structured fields, global direction, references
    with fidelity, geometry/material/spatial, clean zones, and composition
    status. Refs are canonical as referencesV4 (not referenceImages).
    """
    refs = config.get("referencesV4") or config.get("referenceImages") or []
    if not isinstance(refs, list):
        refs = []
    ci = config.get("compositionIntent") or {}
    gd = config.get("globalDirection") or {}
    cz = config.get("cleanZones") or {}
    description = str(ci.get("userIntent") or config.get("description") or config.get("prompt") or "").strip()
    return {
        "schema": INTENT_SCHEMA,
        "userIntent": description,
        "subjectType": config.get("subjectType", ""),
        "subjectIds": list(config.get("subjectIds") or []),
        "aspectRatio": config.get("aspectRatio", "1:1"),
        "resolution": config.get("resolution", "1K"),
        "model": {"provider": config.get("provider", ""), "id": config.get("model", config.get("selectedModel", ""))},
        "referenceCount": len(refs),
        "references": [
            {
                "id": r.get("id"),
                "label": r.get("label", ""),
                "semanticRole": r.get("semanticRole", ""),
                "authority": "authoritative" if r.get("semanticRole") == "object_primary" else "contextual",
                "fidelity": int(r.get("fidelity", 70)) if str(r.get("fidelity", "")).isdigit() or isinstance(r.get("fidelity"), int) else 70,
                "fixedProduct": bool(r.get("fixedProduct")),
                "keep": list(r.get("keep") or []),
                "vary": list(r.get("vary") or []),
                "granularWeights": dict(r.get("granularWeights") or {}),
                "userNotes": str(r.get("userNotes") or r.get("instructions") or ""),
                "hasImage": bool(r.get("hasImage") or r.get("imageDataUrl") or r.get("localPath") or r.get("url")),
            }
            for r in refs if isinstance(r, dict)
        ],
        "colorAccents": list(config.get("colorAccents") or []),
        "qualityLevel": config.get("qualityLevel") or config.get("qualityTier") or "padrao",
        "qualityTier": config.get("qualityTier") or config.get("qualityLevel") or "",
        "family": resolve_family(str(config.get("provider") or ""), str(config.get("model") or config.get("selectedModel") or ""))["id"],
        "genre": config.get("genre") or "",
        "structuredFields": dict(config.get("structuredFields") or {}),
        "globalDirection": {k: gd.get(k) for k in ("style", "lighting", "angle", "lens", "aperture", "useReferenceAngle", "fidelityMode") if gd.get(k) is not None},
        "subjectDistance": config.get("subjectDistance", ""),
        "mood": config.get("mood", ""),
        "negativePrompt": str(config.get("negativePrompt") or "").strip(),
        "cleanZones": {"enabled": bool(cz.get("enabled")), "zones": list(cz.get("zones") or []), "intensity": cz.get("intensity", ""), "tone": cz.get("tone", "")},
        "preserveElements": list(ci.get("preserveElements") or []),
        "modifyElements": list(ci.get("modifyElements") or []),
        "geometry": dict(ci.get("objectGeometry") or {}),
        "material": dict(ci.get("materialTransition") or {}),
        "spatial": dict(ci.get("spatialAnchoring") or {}),
        "sceneComplexity": ci.get("sceneComplexity", ""),
        "composition": {"status": ci.get("status", ""), "suggestedPrompt": ci.get("suggestedPrompt", ""), "confidence": ci.get("confidence", ""), "compositionSummary": ci.get("compositionSummary", "")},
    }
