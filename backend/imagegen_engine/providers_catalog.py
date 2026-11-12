"""Provider catalog: registration and listing.

Split out of ``plugin_api.py``; consumed by the system routes and by
``backend/mcp_server.py`` (``_list_providers``). ``gen_service.py`` also
calls ``_ensure_providers_registered`` lazily from its fallback generation
path, which is why the helpers live here rather than in a router module.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

from imagegen_engine import gen_service
from imagegen_engine.model_profiles import capabilities_for_model

logger = logging.getLogger(__name__)

_DISCOVERY_DONE = False
_DISCOVERY_LOCK = threading.Lock()


def get_fal_model_meta(model: str) -> Dict[str, Any]:
    """Central FAL catalog accessor: prefix-aware lookup for a single model.

    Wraps ``FAL_MODELS`` so every caller (``capabilities``, ``gen_service``,
    ``_list_providers``) shares the ``fal-ai/`` prefix-strip fallback. Returns
    ``{}`` when the catalog is absent or the id is unknown — never raises.
    """
    if not model:
        return {}
    try:
        from tools.image_generation_tool import FAL_MODELS
    except Exception as exc:  # noqa: BLE001 — host modules absent in tests
        logger.debug("FAL_MODELS unavailable: %s", exc)
        return {}
    meta = FAL_MODELS.get(model)
    if meta is not None:
        return dict(meta)
    if model.startswith("fal-ai/"):
        meta = FAL_MODELS.get(model[len("fal-ai/"):])
        if meta is not None:
            return dict(meta)
    for entry in FAL_MODELS.values():
        if entry.get("edit_endpoint") == model:
            return dict(entry)
    return {}


def _ensure_providers_registered() -> None:
    """Make sure Hermes has loaded its image providers in this process.

    ImageGen never loads Hermes's bundled plugins itself: it asks the host's
    idempotent public loader once and then only reads the registry. A process
    that already discovered plugins (the agent, the gateway) returns at once.
    """
    global _DISCOVERY_DONE
    if _DISCOVERY_DONE:
        return
    with _DISCOVERY_LOCK:
        if _DISCOVERY_DONE:
            return
        try:
            from hermes_cli.plugins import discover_plugins

            discover_plugins()
            _DISCOVERY_DONE = True
        except Exception as exc:  # noqa: BLE001 - outside Hermes there is no registry
            logger.warning("imagegen: Hermes plugin discovery failed: %s", exc)


def _list_providers() -> List[Dict[str, Any]]:
    """List image_gen providers registered in Hermes and direct API backends."""
    from imagegen_engine.capabilities import resolve_capabilities

    _ensure_providers_registered()
    out: List[Dict[str, Any]] = []
    registry_by_name: Dict[str, Any] = {}
    try:
        from agent.image_gen_registry import list_providers as _registry_list

        for p in _registry_list():
            if p.name == SELF_PROVIDER:
                continue  # ImageGen's own chat provider delegates to the others listed here.
            registry_by_name[p.name] = p
            models: List[Dict[str, Any]] = []
            try:
                models = p.list_models() or []
            except Exception as exc:  # noqa: BLE001
                logger.warning("list_models failed for %s: %s", p.name, exc)
            available = True
            try:
                available = bool(p.is_available())
            except Exception:  # noqa: BLE001
                available = False
            out.append({
                "name": p.name,
                "display_name": getattr(p, "display_name", p.name.title()),
                "available": available,
                "models": models,
            })
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_gen_registry unavailable: %s", exc)

    # Direct FAL (Hermes catalog) — fallback when not registered
    if "fal" not in registry_by_name:
        fal_models: List[Dict[str, Any]] = []
        try:
            from tools.image_generation_tool import FAL_MODELS

            for mid, meta in FAL_MODELS.items():
                fal_models.append({
                    "id": mid,
                    "display": meta.get("display", mid),
                    "speed": meta.get("speed", ""),
                    "price": meta.get("price", ""),
                    "strengths": meta.get("strengths", ""),
                })
        except Exception as exc:  # noqa: BLE001
            logger.warning("FAL catalog unavailable: %s", exc)
        out.insert(0, {
            "name": "fal",
            "display_name": "FAL.ai",
            "available": bool(gen_service._fal_key()),
            "models": fal_models,
        })
    _merge_fal_catalog(out)
    out.append(_magnific_provider_entry())
    out.append(_vertex_provider_entry())
    out.append(_local_provider_entry())
    # Single source of truth: capabilities per (provider, model) resolved by
    # the capabilities module — covers even the Hermes-registered providers
    # (openai/xai/krea/openrouter/openai-codex/deepinfra) whose plugins do NOT
    # expose capabilities in list_models() (the ABC exposes only the active
    # global model via p.capabilities()).
    for provider_entry in out:
        provider_name = provider_entry.get("name", "")
        provider_obj = registry_by_name.get(provider_name)
        for model_entry in provider_entry.get("models", []):
            model_id = model_entry.get("id") or model_entry.get("model") or ""
            model_entry["capabilities"] = resolve_capabilities(
                provider_name,
                model_id,
                provider_obj=provider_obj,
                model_meta=model_entry.get("capabilities") or {},
            )
    _mark_recommended(out, registry_by_name)
    return out


# Used when Hermes names no image provider: subscriptions the user already
# pays for come before pay-per-image keys.
_PROVIDER_PREFERENCE = ("openai-codex", "nous", "fal", "openai", "xai", "openrouter", "krea", "deepinfra", "meta-ai")
_FAL_DEFAULT_MODEL = "fal-ai/flux-2-pro"
SELF_PROVIDER = "imagegen"


def _hermes_image_setting(key: str) -> str:
    """Read ``image_gen.<key>`` from the Hermes config; empty when unset or unreadable."""
    try:
        from hermes_cli.config import load_config_readonly

        block = (load_config_readonly() or {}).get("image_gen")
        value = block.get(key) if isinstance(block, dict) else None
        return value.strip() if isinstance(value, str) else ""
    except Exception as exc:  # noqa: BLE001 — host modules absent in tests
        logger.debug("image_gen.%s unreadable: %s", key, exc)
        return ""


def _mark_recommended(out: List[Dict[str, Any]], registry_by_name: Dict[str, Any]) -> None:
    """Set ``default_model`` on each provider and ``recommended`` on the one a new user starts with.

    The provider Hermes uses for chat images wins; otherwise the first available
    one in ``_PROVIDER_PREFERENCE``. The model follows ``image_gen.model`` when
    that provider serves it, then the provider's own default.
    """
    hermes_provider = _hermes_image_setting("provider")
    hermes_model = _hermes_image_setting("model")
    if hermes_provider == SELF_PROVIDER:
        # Chat images already go through ImageGen; its model id names the real provider.
        hermes_provider = next((e["name"] for e in out if e.get("available") and any(
            (m.get("id") or m.get("model")) == hermes_model for m in e.get("models") or [])), "")
    for entry in out:
        ids = [m.get("id") or m.get("model") or "" for m in entry.get("models") or []]
        own_default = _FAL_DEFAULT_MODEL if entry.get("name") == "fal" else getattr(
            registry_by_name.get(entry.get("name")), "default_model_id", "")
        # Hermes reads image_gen.model for FAL even when no provider is named.
        uses_hermes_model = entry.get("name") == (hermes_provider or "fal")
        candidates = [hermes_model if uses_hermes_model else "", own_default, ids[0] if ids else ""]
        entry["default_model"] = next((mid for mid in candidates if mid and mid in ids), "")
    available = {e["name"]: e for e in out if e.get("available") and e.get("default_model")}
    order = [hermes_provider, *_PROVIDER_PREFERENCE, *available]
    chosen = next((name for name in order if name in available), None)
    if chosen:
        available[chosen]["recommended"] = True


def _merge_fal_catalog(out: List[Dict[str, Any]]) -> None:
    """Add every active model from FAL's public catalog to the FAL entry.

    Hermes' own FAL models stay first and keep their ids; catalog models with the
    same endpoint are skipped. Image-to-image endpoints go to ``edit_models`` for
    the Edit tab. Details come from cached schemas only, so listing stays offline.
    """
    from imagegen_engine import fal_catalog

    entry = next((p for p in out if p.get("name") == "fal"), None)
    if entry is None:
        return
    models = entry.setdefault("models", [])
    known = {str(m.get("id") or "") for m in models}
    known |= {"fal-ai/" + mid for mid in known}
    for item in fal_catalog.models("text-to-image"):
        if item["id"] in known:
            continue
        details = fal_catalog.details(item["id"], fetch=False)
        models.append({"id": item["id"], "display": item["display"], "strengths": item["strengths"],
                       "catalog": True, **{key: details[key] for key in
                                           ("aspectRatios", "resolutionOptions", "supportsSeed") if key in details}})
    entry["edit_models"] = [{"id": item["id"], "display": item["display"], "strengths": item["strengths"]}
                            for item in fal_catalog.models("image-to-image")]


def _vertex_provider_entry() -> Dict[str, Any]:
    """Gemini image models on Google Cloud Vertex AI, billed to the key's project."""
    from imagegen_engine import vertex_api

    return {
        "name": vertex_api.PROVIDER,
        "display_name": "Vertex AI (Gemini)",
        "available": vertex_api.available(),
        "models": [
            {"id": model, "display": spec["display"], "strengths": f"Gemini on Vertex AI, {spec['maxReferences']} references",
             "aspectRatios": list(spec["aspectRatios"]), "resolutionOptions": list(spec["resolutions"]),
             "supportsSeed": False, "capabilities": {"max_reference_images": spec["maxReferences"]}}
            for model, spec in vertex_api.MODELS.items()
        ],
    }


def _local_provider_entry() -> Dict[str, Any]:
    """Models of the image server at the address in the plugin settings; no key and no price.

    ``configured`` says an address is set; ``available`` says the server answered with models.
    """
    from imagegen_engine import local_api

    models = local_api.models()
    return {
        "name": local_api.PROVIDER,
        "display_name": "Local server",
        "configured": local_api.available(),
        "available": bool(models),
        "models": [
            {"id": model, "display": model, "strengths": "Runs on your own server, no API key",
             "aspectRatios": list(local_api.ASPECT_RATIOS), "resolutionOptions": list(local_api.RESOLUTIONS),
             "supportsSeed": False}
            for model in models
        ],
    }


def _magnific_provider_entry() -> Dict[str, Any]:
    from imagegen_engine.magnific_catalog import list_models

    return {
        "name": "magnific",
        "display_name": "Magnific API",
        "available": gen_service._magnific_available(),
        "models": list_models(),
    }


def available_providers() -> List[Dict[str, Any]]:
    return [p for p in _list_providers() if p.get("available") and p.get("models")]


def resolve_target(model_id: str = "") -> Optional[Tuple[str, str]]:
    """``(provider, model)`` that serves this call: the requested model, else ImageGen's own start choice."""
    providers = available_providers()
    if model_id:
        for provider in providers:
            if any((m.get("id") or m.get("model")) == model_id for m in provider["models"]):
                return provider["name"], model_id
    chosen = next((p for p in providers if p.get("recommended")), None)
    return (chosen["name"], chosen["default_model"]) if chosen else None
