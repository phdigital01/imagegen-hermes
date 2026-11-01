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

from dashboard import gen_service
from dashboard.model_profiles import capabilities_for_model

logger = logging.getLogger(__name__)

_REGISTERED_PROVIDERS = False
_REGISTRATION_LOCK = threading.RLock()


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
    with _REGISTRATION_LOCK:
        _register_providers_locked()


def _register_providers_locked() -> None:
    """Register the Hermes image providers (plugins/image_gen/*) in the registry.

    The web_server does not load these plugins automatically; we replicate the
    agent boot: import each bundled backend and call its ``register(ctx)``
    with a ctx stub that delegates to the global registry.
    """
    global _REGISTERED_PROVIDERS
    if _REGISTERED_PROVIDERS:
        return

    try:
        from hermes_cli.plugins import get_bundled_plugins_dir
        from hermes_cli.plugins import PluginContext  # noqa: F401

        bundled = get_bundled_plugins_dir()
        import importlib.util
        import sys

        from agent.image_gen_registry import get_provider, register_provider

        class _CtxStub:
            def register_image_gen_provider(self, provider) -> None:
                register_provider(provider)

        image_gen_dir = bundled / "image_gen"
        if not image_gen_dir.is_dir():
            logger.warning("plugins/image_gen not found in %s", bundled)
            return

        failed = False
        for child in sorted(image_gen_dir.iterdir()):
            init_file = child / "__init__.py"
            if not child.is_dir() or not init_file.exists():
                continue
            # Dedupe: if the agent boot already registered this provider in the
            # registry, do not register it again (avoids double loading).
            try:
                if get_provider(child.name) is not None:
                    logger.info("imagegen: provider %s already registered", child.name)
                    continue
            except Exception:  # noqa: BLE001
                pass
            try:
                spec = importlib.util.spec_from_file_location(
                    f"imagegen_bundled_{child.name}", init_file
                )
                mod = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = mod
                spec.loader.exec_module(mod)
                if hasattr(mod, "register"):
                    mod.register(_CtxStub())
                    logger.info("imagegen: provider registered: %s", child.name)
            except Exception as exc:  # noqa: BLE001
                failed = True
                logger.warning("imagegen: failed to register provider %s: %s", child.name, exc)
        _REGISTERED_PROVIDERS = not failed
    except Exception as exc:  # noqa: BLE001
        logger.warning("imagegen: _ensure_providers_registered failed: %s", exc)


def _list_providers() -> List[Dict[str, Any]]:
    """List image_gen providers registered in Hermes and direct API backends."""
    from dashboard.capabilities import resolve_capabilities

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
            "available": bool(gen_service._fal_key()) or gen_service._managed_gateway_active(),
            "models": fal_models,
        })
    _merge_fal_catalog(out)
    out.append(_magnific_provider_entry())
    out.append(_vertex_provider_entry())
    _merge_nous_portal_entry(out)
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
    from dashboard import fal_catalog

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


def _merge_nous_portal_entry(out: List[Dict[str, Any]]) -> None:
    """Expose Nous Portal models without duplicating the provider entry.

    Hermes may already register a ``nous`` provider (the OpenRouter-backed
    reference-grounded path with Nous Portal auth). When present, merge the
    pinned Tool Gateway catalog into that entry; otherwise add a fresh one.
    Availability is the union of the registered provider and the gateway.
    """
    from dashboard import nous_portal

    portal_models = nous_portal.list_models()
    existing = next((p for p in out if p.get("name") == nous_portal.PROVIDER_NAME), None)
    if existing is None:
        out.append(_nous_portal_provider_entry())
        return
    existing_ids = {m.get("id") for m in existing.get("models") or []}
    for model_entry in portal_models:
        if model_entry["id"] not in existing_ids:
            existing.setdefault("models", []).append(model_entry)
    existing["available"] = bool(existing.get("available")) or nous_portal.nous_portal_available()


def _nous_portal_provider_entry() -> Dict[str, Any]:
    """Nous Portal provider — managed Tool Gateway (subscription, no FAL_KEY)."""
    from dashboard import nous_portal

    return {
        "name": nous_portal.PROVIDER_NAME,
        "display_name": nous_portal.DISPLAY_NAME,
        "available": nous_portal.nous_portal_available(),
        "models": nous_portal.list_models(),
    }


def _vertex_provider_entry() -> Dict[str, Any]:
    """Gemini image models on Google Cloud Vertex AI, billed to the key's project."""
    from dashboard import vertex_api

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


def _magnific_provider_entry() -> Dict[str, Any]:
    from dashboard.magnific_catalog import list_models

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
