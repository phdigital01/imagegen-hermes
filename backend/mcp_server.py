"""ImageGen MCP server — exposes the plugin engine as MCP tools for the Hermes agent.

Runs over stdio. Registered in the host ``config.yaml`` under ``mcp_servers``
(see docs/runbooks/development.md). Reuses ``gen_service``/``store`` in-process — the
same engine as the plugin UI — so the agent generates with the plugin's
provider catalog (capabilities resolved by
``dashboard.capabilities.resolve_capabilities``), its subject library and its
reference pipeline instead of the host's generic image tool.
"""
from __future__ import annotations

import functools
import json
import logging
import os
import sys

# Ensure the plugin's dashboard import works.
_PLUGIN_HOME = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_HOME not in sys.path:
    sys.path.insert(0, _PLUGIN_HOME)

try:
    from mcp.server.fastmcp import FastMCP  # noqa: E402  # mcp<2.0
except ModuleNotFoundError:
    from mcp.server.mcpserver import MCPServer as FastMCP  # noqa: E402  # mcp>=2.0

from dashboard import gen_service, llm_service, store  # noqa: E402
from dashboard.errors import ImageGenError  # noqa: E402

logger = logging.getLogger(__name__)

mcp = FastMCP("imagegen")


def _error_text(exc: BaseException) -> str:
    """Render an engine failure as a stable, LLM-readable error string."""
    if isinstance(exc, ImageGenError):
        payload = exc.to_dict()
        params = f" params={json.dumps(payload['params'])}" if payload.get("params") else ""
        return f"ERROR [{payload['code']}]: {payload['message']}{params}"
    return f"ERROR [internal]: {exc}"


def _guarded(fn):
    """Convert engine failures into error strings instead of MCP tracebacks.

    ``ImageGenError`` keeps its stable dotted code and message so the agent can
    act on it; any other failure is reported without a traceback.
    """
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 — surface a message, not a traceback
            logger.warning("tool %s failed: %s", fn.__name__, exc)
            return _error_text(exc)
    return wrapper


@mcp.tool()
@_guarded
def imagegen_providers() -> str:
    """List every image provider/model available to the plugin, with capabilities.

    Use this FIRST to pick a valid (provider, model) pair for
    ``imagegen_generate``: a model must appear in this list for that provider.
    Each model line shows the price and capability flags, where ``refs=N``
    means the model accepts up to N reference images (N > 0 is required for
    ``imagegen_generate``'s ``reference_images`` to work). The capabilities
    come from the same resolver the plugin UI and the generation pipeline use
    (``dashboard.capabilities.resolve_capabilities``), so this list is the
    single source of truth for "does this model accept references".
    """
    from dashboard.providers_catalog import _list_providers

    out = []
    for prov in _list_providers():
        name = prov.get("name", "")
        available = "available" if prov.get("available") else "unavailable"
        models = []
        for model_entry in prov.get("models", []):
            mid = model_entry.get("id") or model_entry.get("model") or ""
            if not mid:
                continue
            caps = model_entry.get("capabilities") or {}
            max_refs = int(caps.get("maxReferences") or 0)
            flags = []
            if max_refs:
                flags.append(f"refs={max_refs}")
            if caps.get("edit"):
                flags.append("edit")
            if caps.get("upscale"):
                flags.append("upscale")
            price = str(model_entry.get("price") or "").strip()
            line = mid if not price else f"{mid} ({price})"
            if flags:
                line += " [" + ", ".join(flags) + "]"
            models.append(line)
        if models:
            out.append(f"{name} ({available}):\n  " + "\n  ".join(models))
        else:
            out.append(f"{name} ({available}): no models")
    return "\n".join(out) if out else "No providers registered"


@mcp.tool()
@_guarded
def imagegen_subjects_list(kind: str = "", q: str = "") -> str:
    """Search the user's ImageGen subject library (photographed fixed subjects).

    The subject library is the plugin's differentiator: products/objects the
    user photographed once and wants to appear faithfully in every generation.
    Each entry shows the subject id (use it in ``imagegen_subject_refs``), its
    name, kind, number of angles and a snippet of its technical passport.

    Args:
        kind: filter by subject kind slug (e.g. "object", "packaging_box",
            "pessoa", "food") — omit for all.
        q: free-text filter over name, kind, tags and passport.
    """
    items = store.subjects_list(kind=kind, q=q)
    if not items:
        where = []
        if kind:
            where.append(f"kind={kind!r}")
        if q:
            where.append(f"q={q!r}")
        return "No subjects found" + (f" ({', '.join(where)})" if where else "")
    lines = []
    for item in items:
        tags = ", ".join(item.get("tags") or [])
        passport = str(item.get("passport") or "").replace("\n", " ").strip()[:160]
        line = (
            f"- {item.get('id')} | {item.get('name')} | "
            f"kind={item.get('kind')} | angles={len(item.get('angles') or [])}"
        )
        if tags:
            line += f" | tags: {tags}"
        if passport:
            line += f" | passport: {passport}"
        lines.append(line)
    return "\n".join(lines)


@mcp.tool()
@_guarded
def imagegen_subject_refs(subject_id: str, max_refs: int = 4) -> str:
    """Resolve a subject library entry into reference image paths for generation.

    Returns the subject's local image paths (multi-angle when available) plus
    its technical passport. Pass the paths as ``reference_images`` to
    ``imagegen_generate`` — the engine validates them against the chosen
    model's capability and prepares them per provider (uploaded for fal/krea,
    read locally by openai/xai/...), so nothing is ever dropped silently.

    Args:
        subject_id: a subject id from ``imagegen_subjects_list``.
        max_refs: how many angles to return (1..4).
    """
    refs = store.subject_as_refs(subject_id, max_refs=max_refs)
    obj = next((o for o in store.objects_list() if o.get("id") == subject_id), None)
    if not obj or not refs:
        return f"ERROR: subject '{subject_id}' not found in the subject library"
    return json.dumps({
        "subject": {
            "id": obj.get("id"),
            "name": obj.get("name"),
            "kind": obj.get("kind"),
        },
        "passport": obj.get("passport", ""),
        "reference_images": [r.get("localPath") for r in refs if r.get("localPath")],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
@_guarded
def imagegen_analyze(scene: str, image_urls: list[str] | None = None,
                     subject_type: str = "general", aspect_ratio: str = "1:1",
                     genre: str = "", refs_meta: list[dict] | None = None,
                     deep: bool = False) -> str:
    """Analyze reference images + request (real vision) and return an
    optimized production prompt in English (brief → prompt, photography director).

    Run this when the user describes a scene with reference images: it inspects
    the actual images, produces a structured production BRIEF, then a single
    final PROMPT ready for ``imagegen_generate``. Genre templates (ad_product,
    editorial_fashion, architecture, ...) are applied when genre is empty.

    Args:
        scene: what the user wants in the image (e.g. 'premium product in a luxury home with pool').
        image_urls: URLs, data URLs or local paths of the reference images (product, scene, style).
        subject_type: subject kind (e.g. 'object', 'pessoa', 'food').
        aspect_ratio: '1:1', '4:5', '16:9', '9:16'.
        genre: production genre ('ad_product', 'editorial_fashion', 'architecture', ...).
        refs_meta: optional structured reference metadata (semanticRole, fidelity, keep/vary, instructions).
        deep: if true, runs art-director self-critique and refines the prompt (2 extra vision calls).
    """
    result = llm_service.llm_composition_analyze(
        scene=scene,
        images=image_urls or [],
        subject_type=subject_type,
        aspect_ratio=aspect_ratio,
        genre=genre,
        refs_meta=refs_meta,
        deep=bool(deep),
    )
    return f"BRIEF:\n{result['brief']}\n\nPROMPT:\n{result['prompt']}"


@mcp.tool()
@_guarded
def imagegen_passport(image_urls: list[str]) -> str:
    """Generate a product's technical passport (shape, materials, finish,
    details) from the images — used to preserve fidelity of a fixed subject.

    The passport is stored with subject library entries; pass image paths or
    URLs. Returns a plain-text technical description.
    """
    return llm_service.llm_product_passport(images=image_urls)


@mcp.tool()
@_guarded
def imagegen_optimize(prompt: str, subject_type: str = "general",
                      aspect_ratio: str = "1:1", tool_target: str = "generic",
                      references: list[dict] | None = None,
                      composition_summary: str = "", user_intent: str = "") -> str:
    """Optimize an image prompt (substantial improvement, not translation).

    Rewrites the prompt with photography-direction quality for a given subject
    kind and aspect ratio, targeting the model family of ``tool_target``.
    Use when the user supplies a plain prompt that would benefit from
    production-grade language before ``imagegen_generate``.
    """
    return llm_service.llm_optimize_prompt(
        prompt=prompt,
        tool_target=tool_target,
        subject_type=subject_type,
        aspect_ratio=aspect_ratio,
        references=references,
        composition_summary=composition_summary,
        user_intent=user_intent,
    )


@mcp.tool()
@_guarded
def imagegen_generate(provider: str = "fal", model: str = "", prompt: str = "",
                      aspect_ratio: str = "1:1",
                      reference_images: list[str] | None = None,
                      num_images: int = 1, seed: int | None = None,
                      negative_prompt: str | None = None,
                      resolution: str = "1K", save_to_gallery: bool = True) -> str:
    """Generate images with the plugin engine (catalog-aware, reference-capable).

    The plugin's differentiator: generation goes through the same pipeline as
    the ImageGen UI, so the model's real capabilities decide whether
    ``reference_images`` are used (an unsupported model raises a clear
    ImageGenError instead of silently dropping references) and results are
    persisted to the plugin gallery when ``save_to_gallery`` is true.

    Args:
        provider: from ``imagegen_providers`` — "fal", "nous", "magnific",
            "vertex", or a registered provider ("openai-codex", "xai", ...).
        model: a model id from ``imagegen_providers`` for that provider.
        prompt: production-ready prompt (run ``imagegen_analyze`` or
            ``imagegen_optimize`` first for best results).
        aspect_ratio: "1:1", "4:5", "16:9", "9:16", "3:4", "2:3", "3:2", "21:9".
        reference_images: local paths or URLs — from ``imagegen_subject_refs``
            for fixed subjects, or user images. Only used when the model
            accepts references (refs=N in ``imagegen_providers``).
        num_images: how many images to generate (1..8).
        seed: optional fixed seed (varied automatically when num_images > 1).
        negative_prompt: optional negative prompt (model-dependent support).
        resolution: "1K", "2K" or "4K" (fal catalog models only).
        save_to_gallery: persist into the plugin gallery/history so the result
            appears in the ImageGen UI (recommended). Images may come back as
            plugin-served URLs; the gallery entries (gallery_ids/output_paths)
            hold the actual local files.
    """
    prompt = str(prompt or "").strip()
    if not prompt:
        return "ERROR: prompt is required"
    try:
        num_images = int(num_images)
    except (TypeError, ValueError):
        return "ERROR: num_images must be an integer"
    if num_images < 1 or num_images > 8:
        return "ERROR: num_images must be between 1 and 8"
    refs = [str(v).strip() for v in (reference_images or []) if str(v).strip()]
    body = {
        "provider": provider,
        "model": model,
        "prompt": prompt,
        "aspectRatio": aspect_ratio,
        "seed": seed,
        "negativePrompt": negative_prompt,
        "numImages": num_images,
        "resolution": resolution,
        "referenceImages": refs,
        "saveToGallery": bool(save_to_gallery),
        "kind": "generate",
    }
    result = gen_service.generate_text_to_image(
        provider=provider,
        model=model,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        seed=seed,
        negative_prompt=negative_prompt,
        num_images=num_images,
        resolution=resolution,
        reference_images=refs,
    )
    if body["saveToGallery"]:
        from dashboard.generation_artifacts import save_generation_artifacts

        result = save_generation_artifacts(body, result)
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
@_guarded
def imagegen_upscale(image_url: str, creativity: float = 0.4, scale: int = 2,
                     mode: str = "classic", prompt: str = "") -> str:
    """Upscale an image through FAL Clarity with configurable creativity.

    Args:
        image_url: URL, data URL or local path of the source image.
        creativity: 0..1 — how freely details may be reimagined (classic mode keeps fidelity).
        scale: 2 or 4.
        mode: "classic" or "creative".
        prompt: optional creative direction, used with mode="creative".
    """
    result = gen_service.generate_upscale(
        image=image_url, creativity=creativity, scale=scale, mode=mode, prompt=prompt,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


@mcp.tool()
@_guarded
def imagegen_bg_remove(image_url: str) -> str:
    """Remove the image background → transparent PNG.

    The result can then be used as a reference image for composition
    (``imagegen_generate`` reference_images).

    Args:
        image_url: URL, data URL or local path of the source image.
    """
    result = gen_service.generate_bg_remove(image_url)
    return json.dumps(result, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    mcp.run(transport="stdio")
