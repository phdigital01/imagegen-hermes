"""Single source of truth for (provider, model) capability resolution.

Every surface that answers "does this model accept reference images / does it
edit?" goes through :func:`resolve_capabilities`, so the provider catalog, the
generation pipeline and the frontend never disagree about what a model can do.

Resolution order (per provider family):
- ``magnific``   → per-model direct API contracts from magnific_catalog.
- ``local``      → text only: the local server route sends a prompt and a size.
- ``fal`` and Nous Portal catalog models → the host ``FAL_MODELS`` entry
  (``edit_endpoint`` ⇒ edit; ``max_reference_images`` ⇒ maxReferences).
- Registered providers (openai, openai-codex, xai, krea, openrouter,
  deepinfra, ...) → per-model ``list_models`` entry check first, then
  ``provider_obj.capabilities()``; ``"image"`` in ``modalities`` ⇒ refs with
  ``max_reference_images`` (default 1).
- Unknown → the safe default derived from ``model_meta``.

``referenceImages`` is ALWAYS derived as ``maxReferences > 0``; an input
``referenceImages`` that contradicts the resolved count is ignored. The
function NEVER raises — any failure falls back to the safe default and is
logged at debug level.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Mapping, Optional

from imagegen_engine.model_profiles import capabilities_for_model

logger = logging.getLogger(__name__)

CAPABILITY_KEYS = (
    "referenceImages", "maxReferences", "edit", "inpaint", "outpaint",
    "bg", "upscale", "animate", "negativeMode", "strengthTags", "resolutions",
)

# FAL catalog fields that map onto the stable capability shape.
_FAL_META_KEYS = ("edit_endpoint", "max_reference_images", "upscale")

def get_fal_model_meta(model: str) -> Dict[str, Any]:
    """Central FAL catalog accessor — delegates to providers_catalog."""
    try:
        from imagegen_engine.providers_catalog import get_fal_model_meta as _central

        return _central(model)
    except Exception as exc:  # noqa: BLE001
        logger.debug("get_fal_model_meta delegate failed: %s", exc)
        return {}


# Back-compat alias — capabilities._fal_catalog_meta was the previous entry.
def _fal_catalog_meta(model: str) -> Dict[str, Any]:
    return get_fal_model_meta(model)


def _fal_catalog_knows(model: str) -> bool:
    """True when FAL's cached public catalog lists ``model``."""
    try:
        from imagegen_engine import fal_catalog

        return fal_catalog.knows(model)
    except Exception as exc:  # noqa: BLE001
        logger.debug("fal_catalog unavailable: %s", exc)
        return False


def _per_model_ref_cap(provider_obj: Any, model: str) -> Optional[int]:
    """Per-model maxReferences from list_models() entry, if any.

    Returns the entry's cap (0 when text-only), or None when the model is
    not listed or carries no explicit ref cap.
    """
    if not model:
        return None
    try:
        entries = provider_obj.list_models() or []
    except Exception as exc:  # noqa: BLE001
        logger.debug("list_models failed for %s: %s", getattr(provider_obj, "name", "?"), exc)
        return None
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        mid = entry.get("id") or entry.get("model") or ""
        if mid != model:
            continue
        caps_field = entry.get("capabilities")
        if isinstance(caps_field, dict):
            mods = caps_field.get("modalities")
            if mods is not None and "image" not in (mods or []):
                return 0
            for key in ("maxReferences", "max_reference_images"):
                if key in caps_field:
                    try:
                        val = caps_field[key]
                        if val is None:
                            continue
                        return max(0, int(val))
                    except (TypeError, ValueError):
                        return 1
            if mods is not None and "image" in (mods or []):
                return 1
        for key in ("max_reference_images", "maxReferences"):
            if key in entry:
                try:
                    return max(0, int(entry[key] or 0))
                except (TypeError, ValueError):
                    return 1
        mods = entry.get("modalities")
        if mods is not None:
            return 1 if "image" in (mods or []) else 0
        return None
    return None


def _provider_ref_cap(provider_obj: Any, model: str = "") -> int:
    """maxReferences for a (provider, model) — per-model entry first, then provider-global."""
    try:
        per = _per_model_ref_cap(provider_obj, model)
        if per is not None:
            return max(0, int(per))
    except Exception as exc:  # noqa: BLE001
        logger.debug("per-model cap failed for %s/%s: %s", getattr(provider_obj, "name", "?"), model, exc)
    try:
        caps = provider_obj.capabilities() or {}
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "capabilities() failed for %s: %s",
            getattr(provider_obj, "name", "?"), exc,
        )
        return 0
    if "image" not in (caps.get("modalities") or []):
        return 0
    try:
        return max(1, int(caps.get("max_reference_images") or 1))
    except (TypeError, ValueError):
        return 1


def resolve_capabilities(
    provider: str,
    model: str,
    *,
    provider_obj: Any = None,
    model_meta: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """What a (provider, model) pair can do.

    Returns the stable capability shape (see ``CAPABILITY_KEYS``) with
    ``referenceImages`` derived from ``maxReferences``. Never raises: failures
    log at debug level and return the safe default.
    """
    provider = str(provider or "").strip().lower()
    model = str(model or "").strip()
    meta = dict(model_meta or {})
    # referenceImages is always derived from maxReferences — never trusted
    # from input (a stale True with a 0 count would silently enable refs).
    meta.pop("referenceImages", None)
    try:
        if provider == "magnific":
            from imagegen_engine.magnific_catalog import get_model
            entry = get_model(model)
            max_refs = entry.get("maxReferences", 0)
            extra: Dict[str, Any] = {"edit": bool(max_refs), "negativeMode": "unsupported",
                                     "resolutions": entry.get("resolutionOptions", [])}
        elif provider == "vertex":
            from imagegen_engine import vertex_api
            spec = vertex_api.MODELS.get(model, {})
            max_refs = spec.get("maxReferences", 0)
            extra = {"edit": bool(max_refs), "negativeMode": "unsupported", "resolutions": list(spec.get("resolutions", ()))}
        elif provider == "local":
            # The OpenAI images API takes a prompt and a size; references wait for the A1111 API.
            from imagegen_engine import local_api
            max_refs = 0
            extra = {"edit": False, "negativeMode": "unsupported", "resolutions": list(local_api.RESOLUTIONS)}
        elif provider in ("fal", "nous"):
            fal_meta = get_fal_model_meta(model)
            if fal_meta:
                edit = bool(fal_meta.get("edit_endpoint"))
                max_refs = int(fal_meta.get("max_reference_images") or (1 if edit else 0))
                extra = {"edit": edit}
                meta.update({key: fal_meta[key] for key in _FAL_META_KEYS if key in fal_meta})
            elif provider == "fal" and _fal_catalog_knows(model):
                # FAL's own catalog: cached schemas only, so listing never waits on the
                # network. Without a cached schema an edit sibling allows one reference;
                # the UI then asks /providers/fal/model for the exact limit.
                from imagegen_engine import fal_catalog

                found = fal_catalog.details(model, fetch=False)
                sibling = fal_catalog.edit_sibling(model)
                max_refs = found.get("maxReferences", 1 if sibling else 0)
                extra = {"edit": bool(max_refs)}
            elif provider_obj is not None:
                max_refs = _provider_ref_cap(provider_obj, model)
                extra = {}
            else:
                max_refs = 0
                extra = {}
        elif provider_obj is not None:
            max_refs = _provider_ref_cap(provider_obj, model)
            extra = {}
        else:
            max_refs = 0
            extra = {}

        merged = dict(meta)
        merged["maxReferences"] = max(0, int(max_refs or 0))
        merged.update(extra)
        caps = capabilities_for_model(merged)
        caps["referenceImages"] = caps["maxReferences"] > 0
        return {key: caps[key] for key in CAPABILITY_KEYS}
    except Exception as exc:  # noqa: BLE001
        logger.debug("resolve_capabilities(%s, %s) failed: %s", provider, model, exc)
        caps = capabilities_for_model(meta)
        caps["referenceImages"] = caps["maxReferences"] > 0
        return {key: caps[key] for key in CAPABILITY_KEYS}
