"""LLM/prompt routes: handoffs, refine-from-feedback, presets, /prompt, /llm/*."""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

from fastapi import Body, HTTPException

from imagegen_engine import llm_service, store
from imagegen_engine.api_core import coerce_body, _imagegen_error_http, _to_thread, make_router
from imagegen_engine.errors import ImageGenError
from imagegen_engine.prompt_builder import build_prompt, format_for_tool

logger = logging.getLogger(__name__)

router = make_router()


@router.get("/handoff/last")
async def handoff_last() -> Dict[str, Any]:
    record = store.get_last_handoff()
    if record is None:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return record


@router.get("/handoff/{handoff_id}")
async def handoff_get(handoff_id: str) -> Dict[str, Any]:
    try:
        record = store.get_handoff(handoff_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Handoff not found")
    return record


@router.post("/handoff/feedback")
async def handoff_feedback(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    handoff_id = str(body.get("handoffId") or body.get("generationId") or "").strip()
    if not handoff_id or not body.get("feedback"):
        raise HTTPException(status_code=400, detail="handoffId and feedback are required")
    try:
        return store.save_handoff_feedback(handoff_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Handoff not found") from exc


def _parse_refinement(raw: Any, original_prompt: str, feedback: str) -> Dict[str, str]:
    if isinstance(raw, dict):
        diagnosis = str(raw.get("diagnosis") or raw.get("analysis") or "").strip()
        new_prompt = str(raw.get("newPrompt") or raw.get("prompt") or "").strip()
    else:
        text = str(raw or "").strip()
        try:
            parsed = json.loads(text)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict):
            return _parse_refinement(parsed, original_prompt, feedback)
        diagnosis = text
        new_prompt = f"{original_prompt}. Address this feedback: {feedback}".strip()
    return {
        "diagnosis": diagnosis or "The feedback calls for a targeted prompt adjustment.",
        "newPrompt": new_prompt or f"{original_prompt}. Address this feedback: {feedback}".strip(),
    }


@router.post("/refine-from-feedback")
async def refine_from_feedback(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    """Diagnose feedback and propose a prompt; never starts a generation job."""
    prompt = str(body.get("prompt") or body.get("originalPrompt") or "").strip()
    feedback = str(body.get("feedback") or "").strip()
    if not prompt or not feedback:
        raise HTTPException(status_code=400, detail="prompt and feedback are required")
    structured_change = (
        "Return ONLY valid JSON with keys diagnosis and newPrompt "
        "(no markdown). diagnosis = one short sentence about what is wrong. "
        "newPrompt = full improved English image prompt applying the feedback. "
        f"Feedback: {feedback}"
    )
    try:
        raw = await _to_thread(
            llm_service.llm_refine_prompt,
            base_prompt=prompt,
            user_change=structured_change,
            tool_target=body.get("model") or body.get("provider") or "generic",
        )
        parsed = _parse_refinement(raw, prompt, feedback)
    except Exception as exc:  # noqa: BLE001
        logger.warning("refine-from-feedback fallback: %s", exc)
        parsed = _parse_refinement("", prompt, feedback)
    return {"autoGenerate": False, **parsed}


@router.get("/presets")
async def presets() -> Dict[str, Any]:
    from imagegen_engine import presets as P

    return {
        "subject_types": P.SUBJECT_TYPES,
        "styles": P.VISUAL_STYLES,
        "style_descriptions": P.STYLE_DESCRIPTIONS,
        "lighting": P.LIGHTING_OPTIONS,
        "angles": P.ANGLE_OPTIONS,
        "distances": P.SUBJECT_DISTANCES,
        "aspect_ratios": P.V4_ASPECT_RATIOS,
        "platform_presets": P.PLATFORM_PRESETS,
        "moods": P.MOOD_OPTIONS,
        "lenses": P.LENSES,
        "apertures": P.APERTURES,
        "semantic_roles": P.SEMANTIC_ROLES,
        "reference_purposes": P.REFERENCE_PURPOSES,
        "keep_vary": P.KEEP_VARY_OPTIONS,
        "structured_fields": P.STRUCTURED_FIELDS,
        "default_negatives": P.DEFAULT_NEGATIVES,
        "generic_negative": P.GENERIC_NEGATIVE,
    }


@router.post("/prompt/build")
async def prompt_build(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    config = body.get("config", {})
    try:
        # build_prompt now emits {prompt, negative_prompt} per family
        built = build_prompt(config)
        if isinstance(built, dict):
            prompt = built.get("prompt", "")
            negative_prompt = built.get("negative_prompt", "")
        else:
            prompt = str(built)
            negative_prompt = ""
        # format_for_tool is family-aware; provider from config
        formatted = format_for_tool(
            built if isinstance(built, dict) else prompt,
            config.get("selectedModel", ""),
            config,
            provider=config.get("provider") or config.get("selectedProvider") or "",
        )
        # Normalize formatted to dict/string for response
        if isinstance(formatted, dict):
            return {"prompt": prompt, "negative_prompt": negative_prompt, "formatted": formatted}
        return {"prompt": prompt, "negative_prompt": negative_prompt, "formatted": formatted}
    except Exception as exc:  # noqa: BLE001
        logger.exception("prompt build failed")
        raise HTTPException(status_code=500, detail="Failed to build the prompt") from exc


@router.post("/llm/optimize")
async def llm_optimize(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    if "directionOptions" in body and not (
        isinstance(body["directionOptions"], dict) and isinstance(body.get("manual", {}), dict)
        and isinstance(body.get("description"), str) and body["description"].strip()
    ):
        raise HTTPException(400, "A description and direction controls are required")
    try:
        if "directionOptions" in body:
            return await _to_thread(llm_service.suggest_direction, body.get("description", ""), body.get("prompt", ""),
                                    body.get("toolTarget", ""), body["directionOptions"], body.get("manual", {}),
                                    body.get("english") is True)
        result = await _to_thread(
            llm_service.llm_optimize_prompt,
            prompt=body.get("prompt", ""),
            tool_target=body.get("toolTarget", "generic"),
            subject_type=body.get("subjectType", "general"),
            aspect_ratio=body.get("aspectRatio", "1:1"),
            references=body.get("references"),
            composition_summary=body.get("compositionSummary", ""),
            user_intent=body.get("description", ""),
        )
        return {"result": result}
    except ImageGenError as exc:
        logger.error("llm optimize failed (%s): %s", exc.code, exc.message)
        raise _imagegen_error_http(exc, status_code=500) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("llm optimize failed")
        raise HTTPException(status_code=500, detail="Prompt optimization failed") from exc


@router.post("/llm/composition-analyze")
async def llm_composition_analyze(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    """Analyze reference images + request (real vision) and return brief + optimized prompt."""
    try:
        result = await _to_thread(
            llm_service.llm_composition_analyze,
            scene=body.get("scene", ""),
            images=body.get("images", []),
            subject_type=body.get("subjectType", "general"),
            aspect_ratio=body.get("aspectRatio", "1:1"),
            refs_meta=body.get("refsMeta"),
            genre=body.get("genre", ""),
            deep=bool(body.get("deep", False)),
        )
        return {"brief": result["brief"], "prompt": result["prompt"], "genre": result["genre"]}
    except ImageGenError as exc:
        logger.error("llm composition-analyze failed (%s): %s", exc.code, exc.message)
        raise _imagegen_error_http(exc, status_code=500) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("llm composition-analyze failed")
        raise HTTPException(status_code=500, detail="Composition analysis failed") from exc


@router.get("/genres")
async def genres() -> Dict[str, Any]:
    from imagegen_engine.presets import GENRES

    return {"genres": GENRES}


@router.post("/llm/refine")
async def llm_refine(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    try:
        result = await _to_thread(
            llm_service.llm_refine_prompt,
            base_prompt=body.get("basePrompt", ""),
            user_change=body.get("userChangeRequest", ""),
            tool_target=body.get("toolTarget", "generic"),
        )
        return {"result": result}
    except ImageGenError as exc:
        logger.error("llm refine failed (%s): %s", exc.code, exc.message)
        raise _imagegen_error_http(exc, status_code=500) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("llm refine failed")
        raise HTTPException(status_code=500, detail="Prompt refinement failed") from exc


@router.post("/llm/translate")
async def llm_translate(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    try:
        result = await _to_thread(
            llm_service.llm_translate_prompt,
            text=body.get("text", ""),
            target_lang=body.get("targetLang", "pt-BR"),
        )
        return {"result": result}
    except ImageGenError as exc:
        logger.error("llm translate failed (%s): %s", exc.code, exc.message)
        raise _imagegen_error_http(exc, status_code=500) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("llm translate failed")
        raise HTTPException(status_code=500, detail="Prompt translation failed") from exc


@router.post("/llm/product-passport")
async def llm_product_passport(body: Any = Body(None)) -> Dict[str, Any]:
    body = coerce_body(body)
    """DF1 — Technical product passport (vision): describes shape, materials, details."""
    body = coerce_body(body)
    try:
        passport = await _to_thread(llm_service.llm_product_passport, images=body.get("images", []))
        return {"passport": passport}
    except ImageGenError as exc:
        logger.error("product-passport failed (%s): %s", exc.code, exc.message)
        raise _imagegen_error_http(exc, status_code=500) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("product-passport failed")
        raise HTTPException(status_code=500, detail="Failed to generate the product passport") from exc
