"""ImageGen as a Hermes ``image_gen`` provider.

When the user picks "ImageGen" under Tools -> Image Generation, the agent's
``image_generate`` calls land here. ImageGen does not generate by itself: it
forwards each call to the provider the user can use (the same choice its own
screen starts on, or the model picked for ImageGen in that menu) and keeps the
result in its gallery, history and monthly budget.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO, ImageGenProvider, error_response, resolve_aspect_ratio, success_response,
)

logger = logging.getLogger(__name__)

# Hermes passes orientation words; ImageGen speaks ratios.
_RATIOS = {"landscape": "16:9", "square": "1:1", "portrait": "9:16"}


def _catalog():
    # Imported on use, so registering the provider stays light.
    from dashboard import providers_catalog

    return providers_catalog


class ImageGenChatProvider(ImageGenProvider):
    """Routes the agent's images through ImageGen's providers, gallery and budget."""

    @property
    def name(self) -> str:
        from dashboard.providers_catalog import SELF_PROVIDER

        return SELF_PROVIDER

    @property
    def display_name(self) -> str:
        return "ImageGen"

    def is_available(self) -> bool:
        try:
            return _catalog().resolve_target() is not None
        except Exception:  # noqa: BLE001 — never break the Tools picker
            return False

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "ImageGen",
            "badge": "plugin",
            "tag": "Uses the image provider you already have and keeps every image in the ImageGen gallery and budget",
            "env_vars": [],
        }

    def list_models(self) -> List[Dict[str, Any]]:
        try:
            providers = _catalog().available_providers()
        except Exception:  # noqa: BLE001
            return []
        models: List[Dict[str, Any]] = []
        seen = set()
        for provider in providers:
            for model in provider["models"]:
                model_id = model.get("id") or model.get("model") or ""
                if not model_id or model_id in seen:
                    continue
                seen.add(model_id)
                label = model.get("display") or model_id
                models.append({**{k: model[k] for k in ("speed", "price", "strengths") if model.get(k)},
                               "id": model_id, "display": f"{label} · {provider.get('display_name') or provider['name']}"})
        return models

    def default_model(self) -> Optional[str]:
        target = _catalog().resolve_target()
        return target[1] if target else None

    def capabilities(self) -> Dict[str, Any]:
        return {"modalities": ["text", "image"], "max_reference_images": 4}

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        from dashboard import image_input
        from dashboard.errors import ImageGenError
        from dashboard.generation_artifacts import InlineJob, build_generation_job
        from dashboard.providers_catalog import _hermes_image_setting, resolve_target

        aspect = resolve_aspect_ratio(aspect_ratio)
        prompt = (prompt or "").strip()
        if not prompt:
            return error_response(error="A prompt is required", error_type="invalid_request", provider="imagegen",
                                  aspect_ratio=aspect)
        # Hermes passes the model picked for ImageGen under Tools as ``model``.
        target = resolve_target(str(kwargs.get("model") or "") or _hermes_image_setting("model"))
        if target is None:
            return error_response(error="ImageGen has no image provider it can use. Add one in ImageGen -> Providers.",
                                  error_type="not_configured", provider="imagegen", prompt=prompt, aspect_ratio=aspect)
        provider, model = target
        refs = [u for u in [image_url, *(reference_image_urls or [])] if u]
        body = {"prompt": prompt, "provider": provider, "model": model, "aspectRatio": _RATIOS.get(aspect, "1:1"),
                "referenceImages": refs, "config": {"source": "chat"}}
        try:
            result = build_generation_job(body)(InlineJob())
        except ImageGenError as exc:
            return error_response(error=exc.message, error_type=exc.code, provider="imagegen", model=model,
                                  prompt=prompt, aspect_ratio=aspect)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ImageGen chat generation failed")
            return error_response(error=str(exc) or "Image generation failed", provider="imagegen", model=model,
                                  prompt=prompt, aspect_ratio=aspect)
        images = result.get("images") or []
        if not images:
            return error_response(error="The provider returned no image", error_type="empty_response",
                                  provider="imagegen", model=model, prompt=prompt, aspect_ratio=aspect)
        image = image_input.resolve_served_image(images[0])
        gallery_id = (result.get("gallery_ids") or [""])[0]
        _announce_gallery()
        return success_response(
            image=image, model=model, prompt=prompt, aspect_ratio=aspect, provider="imagegen",
            modality="image" if refs else "text",
            extra={"via": provider, "gallery_id": gallery_id, "warnings": result.get("warnings") or [],
                   **_card_hint(gallery_id)},
        )


def _card_hint(gallery_id: str) -> Dict[str, str]:
    """Tell the model how to add ImageGen's action strip (Edit, Open in gallery) under the image."""
    if not image_input_safe(gallery_id):
        return {}
    card = f'::imagegen-image{{id="{gallery_id}"}}'
    return {"imagegen_card": card,
            "imagegen_card_note": f"To give the user ImageGen actions for this image, put {card} alone "
                                  "as its own paragraph in your reply."}


def image_input_safe(value: str) -> bool:
    from dashboard import image_input

    return bool(value) and image_input.is_safe_id(value)


def _announce_gallery() -> None:
    from dashboard.events import announce

    announce("gallery.changed", {})
