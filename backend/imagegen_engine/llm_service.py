"""Auxiliary LLM and vision calls for the ImageGen plugin.

This is the text side of the plugin: turning what the user typed into a
production-ready image prompt, and reading reference images with a vision
model. It never generates an image and never touches a paid image provider —
`gen_service` owns that. The two modules share nothing but the error type.

Both transports go through the host-owned ``ctx.llm`` facade
(:mod:`imagegen_engine.host_llm`), so calls use the user's active model and
credentials under the plugin's trust policy:

- :func:`_llm_call`  — text-only system + user prompt.
- :func:`_vision_call` — multimodal messages with image blocks, on the plugin's
  ``imagegen_vision`` slot, which follows the user's vision model.

Both use the plugin's own auxiliary slots (:data:`imagegen_engine.host_llm.TASKS`).
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from imagegen_engine.errors import (
    ImageGenError,
    LLM_EMPTY_RESPONSE,
    LLM_NO_VISION,
    LLM_TIMEOUT,
    LLM_UNAVAILABLE,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Transport helpers — retry for transient vision failures (V1)
# ---------------------------------------------------------------------------

def _is_transient(exc: BaseException) -> bool:
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, int) and (status in (408, 425, 429) or status >= 500):
        return True
    # string codes like "429"
    try:
        si = int(str(status))
        if si in (408, 425, 429) or si >= 500:
            return True
    except Exception:
        pass
    msg = str(exc).lower()
    if "429" in msg or "rate limit" in msg or "timeout" in msg or "timed out" in msg:
        return True
    return isinstance(exc, (TimeoutError, ConnectionError, OSError))


def _retry_transient(operation, *, label: str, attempts: int = 3, base_delay: float = 0.75):
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except ImageGenError:
            raise
        except Exception as exc:  # noqa: BLE001
            if attempt >= attempts or not _is_transient(exc):
                raise
            delay = base_delay * (2 ** (attempt - 1))
            logger.warning("Transient %s failure (%s/%s): %s; retrying in %.2fs", label, attempt, attempts, exc, delay)
            time.sleep(delay)
    raise RuntimeError(f"{label} failed after {attempts} attempts")


def _host_llm() -> Any:
    from imagegen_engine import host_llm

    llm = host_llm.get()
    if llm is None:
        raise ImageGenError(LLM_UNAVAILABLE, "The Hermes LLM is unavailable to this plugin")
    return llm


def _complete(messages: List[Dict[str, Any]], *, task: str, purpose: str, max_tokens: int, temperature: float) -> str:
    from imagegen_engine import host_llm

    try:
        llm = _host_llm()
        result = llm.complete(
            messages, max_tokens=max_tokens, temperature=temperature, timeout=180, purpose=purpose,
            task=host_llm.task(task),
        )
    except ImageGenError:
        raise
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "timeout" in msg or "timed out" in msg:
            raise ImageGenError(LLM_TIMEOUT, f"{purpose} request timed out: {exc}", detail=str(exc)) from exc
        raise
    out = (getattr(result, "text", "") or "").strip()
    if not out:
        raise ImageGenError(LLM_EMPTY_RESPONSE, f"{purpose} returned an empty response",
                            detail=f"{purpose} returned an empty response")
    return out


def _llm_call(system: str, user: str) -> str:
    """Text completion on the user's active Hermes model."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    try:
        return _retry_transient(
            lambda: _complete(messages, task="imagegen_prompt", purpose="imagegen prompt", max_tokens=1200, temperature=0.4),
            label="llm", attempts=3, base_delay=0.75,
        )
    except ImageGenError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ImageGenError(LLM_UNAVAILABLE, f"LLM request failed: {exc}", detail=str(exc)) from exc


# Provider wording for a model that rejects image input (task names such as
# "imagegen_vision" appear in other errors, so match phrases, not words).
_NO_VISION_HINTS = ("does not support image", "doesn't support image", "image input",
                    "not support vision", "no vision", "not multimodal", "image_url is not supported")


def _vision_call(messages: List[Dict[str, Any]], *, max_tokens: int = 1200, temperature: float = 0.4) -> str:
    """Multimodal completion on the user's active Hermes model.

    Wrapped with retry for transient 429/5xx/timeout (V1). A model without
    vision surfaces as ``llm.no_vision`` (V5).
    """
    try:
        return _retry_transient(
            lambda: _complete(messages, task="imagegen_vision", purpose="imagegen vision", max_tokens=max_tokens, temperature=temperature),
            label="vision", attempts=3, base_delay=0.75,
        )
    except ImageGenError:
        raise
    except Exception as exc:  # noqa: BLE001
        msg = str(exc).lower()
        if "timeout" in msg or "timed out" in msg:
            raise ImageGenError(LLM_TIMEOUT, f"Vision request failed: {exc}", detail=str(exc)) from exc
        if any(hint in msg for hint in _NO_VISION_HINTS):
            raise ImageGenError(LLM_NO_VISION, "The active Hermes model cannot read images",
                                detail=str(exc)) from exc
        raise ImageGenError(LLM_UNAVAILABLE, f"Vision request failed: {exc}", detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Context builders — turn structured reference metadata into prompt text
# ---------------------------------------------------------------------------

def _img_blocks(images: Optional[List[str]]) -> List[Dict[str, Any]]:
    import base64
    from imagegen_engine import image_input, store

    blocks: List[Dict[str, Any]] = []
    for img in (images or [])[:4]:
        if img and isinstance(img, str):
            # Vision providers cannot fetch local paths or the Desktop gateway.
            # Resolve and validate before transmitting the actual image bytes.
            data = store.fetch_image_bytes(image_input.resolve_served_image(img))
            url = f"data:{image_input.detect_mime(data)};base64,{base64.b64encode(data).decode('ascii')}"
            blocks.append({"type": "image_url", "image_url": {"url": url}})
    return blocks


def _refs_context(refs_meta: Optional[List[Dict[str, Any]]]) -> str:
    if not refs_meta:
        return ""
    lines = []
    role_map = {
        "object_primary": "PRIMARY OBJECT (authoritative — preserve shape/details)",
        "context_application": "CONTEXT/SCENE",
        "style_reference": "STYLE GUIDE",
        "lighting_reference": "LIGHTING/MOOD",
    }
    for i, r in enumerate(refs_meta, 1):
        parts = [f"Ref {i}: {r.get('label', '')} — role {role_map.get(r.get('semanticRole', ''), r.get('semanticRole', ''))}"]
        if r.get("fixedProduct"):
            parts.append("fixed product (do NOT alter)")
        else:
            parts.append(f"fidelity {r.get('fidelity', 70)}%")
        if (r.get("userNotes") or "").strip():
            parts.append(f"note: {r['userNotes'].strip()}")
        if (r.get("keep") or []):
            parts.append(f"keep: {', '.join(r['keep'])}")
        if (r.get("vary") or []):
            parts.append(f"vary: {', '.join(r['vary'])}")
        if (r.get("instructions") or "").strip():
            parts.append(f"instructions: {r['instructions'].strip()}")
        lines.append(", ".join(parts))
    return "\n\n" + "\n".join(lines)


def _genre_block(genre: str) -> str:
    """Genre template (C4) — expected structure + specific negatives."""
    from imagegen_engine.presets import GENRES

    g = next((x for x in GENRES if x["id"] == genre), None)
    if not g:
        return ""
    return (
        f"\n\nGenre: {g['label']}.\nExpected structure: {g['structure']}.\n"
        f"Negative guidance (keep these elements OUT of the scene): {g['negative']}"
    )

_COMPOSITION_FEWSHOT = [
    (
        "User: 'Colocar minha tampa de máquina em uma casa de alto padrão com piscina'",
        "Prompt final: 'Industrial machine-room access cover, exact replica of the reference product — brushed galvanized steel lid with ribbed surface, recessed pull handles and perimeter gasket — installed on the polished concrete terrace of a modern luxury home, infinity pool in the background, warm late-afternoon sunlight raking across the metal, soft reflections, 50mm f/5.6, eye level, architectural lifestyle photography, ultra detailed materials, professional color grade'",
    ),
    (
        "User: 'Garrafa de vinho em mesa de madeira, luz de fim de tarde'",
        "Prompt final: 'Premium wine bottle with deep green glass and gold foil label on a rustic oak table, warm golden-hour side light through a window, long soft shadows, dust particles in the light beam, shallow depth of field at f/2.8, 85mm lens, editorial product photography, rich amber highlights on the glass, wood grain detail, moody cozy atmosphere'",
    ),
]

# ---------------------------------------------------------------------------
# Prompt operations (text-only)
# ---------------------------------------------------------------------------

def llm_optimize_prompt(prompt: str, tool_target: str = "generic", subject_type: str = "general",
                        aspect_ratio: str = "1:1", references: Optional[List[Dict[str, Any]]] = None,
                        composition_summary: str = "", user_intent: str = "") -> str:
    """Optimize the image prompt (port of the optimize-image-prompt-v4 handler)."""
    tool_hints = {
        "midjourney": "Midjourney (add --ar, --s, --iw params)",
        "dalle-3": "DALL-E 3 (natural language only, no special syntax)",
        "flux-pro": "Flux (technical photographic terms, --guidance)",
    }
    tool_hint = tool_hints.get(tool_target, "generic AI image generation tool")

    intent_context = ""
    if user_intent and user_intent.strip():
        intent_context = f"\n\nUser intent (what they actually want to see — use this as the creative core):\n{user_intent.strip()}"

    refs_context = ""
    if references:
        lines = []
        for i, r in enumerate(references, 1):
            parts = [f"Ref {i}"]
            role_map = {
                "object_primary": "PRIMARY OBJECT (authoritative)",
                "context_application": "CONTEXT/SCENE",
                "style_reference": "STYLE GUIDE",
                "lighting_reference": "LIGHTING/MOOD",
            }
            if r.get("semanticRole"):
                parts.append(f"role: {role_map.get(r['semanticRole'], r['semanticRole'])}")
            if r.get("purposes"):
                parts.append(f"purposes: {', '.join(r['purposes'])}")
            if r.get("fixedProduct"):
                parts.append("fixed product")
            else:
                parts.append(f"fidelity: {r.get('fidelity', 70)}%")
            if (r.get("instructions") or "").strip():
                parts.append(f"instructions: {r['instructions'].strip()}")
            if (r.get("userNotes") or "").strip():
                parts.append(f"user notes: {r['userNotes'].strip()}")
            if r.get("keep"):
                parts.append(f"keep: {', '.join(r['keep'])}")
            if r.get("vary"):
                parts.append(f"vary: {', '.join(r['vary'])}")
            lines.append(", ".join(parts))
        refs_context = "\n\nVisual references:\n" + "\n".join(lines)
        if composition_summary:
            refs_context += f"\n\nComposition intent: {composition_summary}"

    system = (
        f"You are an elite prompt engineer for {tool_hint}. You will substantially IMPROVE the "
        f"given prompt — not translate it, not lightly rephrase it."
        + "\n\nRules:\n"
        "- Use the user's intent as the creative core: describe the subject, action, setting, "
          "materials, colors and atmosphere in vivid, concrete detail.\n"
        "- Add 4-8 specific technical terms (camera/lens, lighting setup, composition, DOF, "
          "texture, mood) that actually shape the image.\n"
        "- If the base prompt is generic boilerplate ('highly detailed', 'professional...'), "
          "replace it with specific, evocative language driven by the intent.\n"
        "- Keep it a single, flowing paragraph; no markdown, no explanations, no quotes.\n"
        "- Target: a prompt that would make a photorealistic renderer produce exactly what the "
          "user described."
        + (". The user has visual references — consider their purposes, keep/vary instructions, "
           "and fidelity levels when optimizing. Incorporate reference guidance naturally into "
           "the prompt." if references else "")
        + "\n\nCRITICAL: Preserve the exact aspect ratio intent (e.g. --ar 9:16, --ar 16:9) from "
          "the original prompt. Do NOT change, remove, or omit it.\n\n"
          "Return ONLY the optimized prompt in English."
    )
    try:
        from imagegen_engine.model_profiles import prompt_system_addendum

        addendum = prompt_system_addendum(model=tool_target or "")
        if addendum:
            system = system + "\n\nModel-family guidance: " + addendum
    except Exception:  # noqa: BLE001
        pass
    user = (
        f"Optimize this prompt:\n\n{prompt}\n\nSubject: {subject_type}\n"
        f"Aspect ratio: {aspect_ratio}\nTarget tool: {tool_target}{refs_context}{intent_context}"
    )
    return _llm_call(system, user)

def llm_refine_prompt(base_prompt: str, user_change: str, tool_target: str = "generic") -> str:
    """Refine a prompt with a change requested by the user (port of refine-image-prompt-v4)."""
    system = (
        "You are an expert prompt engineer. The user has an existing AI image generation "
        "prompt and wants to refine it with a specific change. Apply the requested change "
        "intelligently — do NOT just append text. Rewrite relevant parts of the prompt to "
        "incorporate the change while preserving the original intent and quality.\n\n"
        "CRITICAL: Preserve the aspect ratio parameter exactly as it appears in the base "
        "prompt (e.g. --ar 9:16). Do NOT change, remove, or omit it.\n\n"
        "Return ONLY the updated prompt in English, no explanations."
    )
    user = f"Base prompt:\n{base_prompt}\n\nRequested change:\n{user_change}\n\nTarget tool: {tool_target or 'generic'}"
    return _llm_call(system, user)

def llm_translate_prompt(text: str, target_lang: str = "pt-BR") -> str:
    """Translate the prompt (port of translate-image-prompt)."""
    system = (
        f"You are a professional translator. Translate the following AI image generation "
        f"prompt to {target_lang}. Preserve technical terms (camera settings, lighting "
        f"terms) but translate descriptive parts. Return ONLY the translation, no explanations."
    )
    return _llm_call(system, text)

# ---------------------------------------------------------------------------
# Vision operations (read the reference images) — structured system/user (V4)
# ---------------------------------------------------------------------------

def llm_product_passport(images: Optional[List[str]] = None) -> str:
    """DF1 — Product passport: technical description (shape, materials, finish,
    colors, proportions, identifying details) generated by vision. Accompanies
    the images in prompts to reinforce fidelity (and is saved in the object library)."""
    system = (
        "You are a product specification expert. Analyze the attached product image(s) "
        "and write a technical PRODUCT PASSPORT in English covering:\n"
        "SHAPE/GEOMETRY: exact form, proportions, dimensions feel.\n"
        "MATERIALS: primary and secondary materials, finish (brushed, matte, glossy, textured...).\n"
        "COLORS: exact palette of each part.\n"
        "DETAILS: textures, logos, markings, hardware, seams, edges.\n"
        "DISTINCTIVE: what makes this product unique — must be preserved in any variation.\n"
        "Be precise and concrete. No fluff, no markdown headers beyond the labels."
    )
    user_content: List[Dict[str, Any]] = [{"type": "text", "text": "Analyze the attached product image(s) and produce the PRODUCT PASSPORT."}]
    user_content.extend(_img_blocks(images))
    return _vision_call(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        max_tokens=800, temperature=0.3,
    )

def llm_composition_analyze(scene: str, images: Optional[List[str]] = None,
                            subject_type: str = "general", aspect_ratio: str = "1:1",
                            refs_meta: Optional[List[Dict[str, Any]]] = None,
                            genre: str = "", deep: bool = False) -> Dict[str, Any]:
    """Analyze the reference IMAGES + the request (real vision) and return
    {brief, prompt}: a structured production brief + the final optimized prompt.

    - C1: brief (1st call) → final prompt (2nd call).
    - C2: photography director with technical vocabulary + few-shot.
    - C3: optional self-critique (deep) — evaluates the prompt against the
      brief and refines.
    - C4: genre template.
    """
    from imagegen_engine.presets import GENRE_BY_SUBJECT

    if not genre:
        genre = GENRE_BY_SUBJECT.get(subject_type, "ad_product")

    refs_ctx = _refs_context(refs_meta)
    genre_blk = _genre_block(genre)
    user_text = f"User request:\n{scene.strip() if (scene or '').strip() else 'Compose the scene using the reference image(s).'}"

    # ---- Step 1: structured BRIEF (C1) — system/user split ----
    brief_system = (
        "You are an elite commercial composition director. Analyze the attached "
        "reference image(s) and the user request, then produce a production BRIEF "
        "as plain structured text with these labeled lines:\n"
        "SUBJECT: exact shape, materials, colors, finish of the primary object (preserve it).\n"
        "ENVIRONMENT: new setting requested by the user — concrete details, materials, colors.\n"
        "LIGHTING: named setup (golden hour, softbox, rim light, low key, practicals...).\n"
        "CAMERA: focal length, aperture/DOF, angle, height.\n"
        "COMPOSITION: framing, negative space, focal point, depth.\n"
        "PALETTE: dominant colors and contrast.\n"
        "MOOD: atmosphere and tone.\n"
        "No markdown. No preamble. Use the reference image as the creative anchor."
        + refs_ctx
        + genre_blk
        + f"\n\nAspect ratio intent: {aspect_ratio}."
    )
    brief = _vision_call(
        [
            {"role": "system", "content": brief_system},
            {"role": "user", "content": [{"type": "text", "text": user_text}] + _img_blocks(images)},
        ],
        max_tokens=900, temperature=0.3,
    )

    # ---- Step 2: final PROMPT (C1+C2) — text-only, structured ----
    fewshot = "\n\n".join(f"Example:\n{b}\n\n{a}" for a, b in _COMPOSITION_FEWSHOT)
    final_system = (
        "You are an elite photographic prompt engineer. Turn the BRIEF below into ONE "
        "production-ready prompt in English for a photorealistic image generator.\n\n"
        "Rules:\n"
        "- Single flowing paragraph, no markdown, no quotes, no explanations.\n"
        "- Be specific and vivid: materials, lighting, camera, atmosphere.\n"
        "- Preserve the primary object faithfully (shape, materials, details).\n"
        "- Technical vocabulary: lens, f-stop, DOF, lighting setup, composition.\n\n"
        f"Few-shot references:\n{fewshot}"
    )
    prompt_final = _vision_call(
        [
            {"role": "system", "content": final_system},
            {"role": "user", "content": [{"type": "text", "text": "BRIEF:\n" + brief}]},
        ],
        max_tokens=1200, temperature=0.4,
    )

    # ---- Step 3: self-critique (C3, optional via deep) — structured ----
    if deep:
        critique_system = (
            "You are a strict art director reviewing a prompt against its brief. "
            "Check: subject fidelity, environment, lighting, camera, composition, palette, mood, "
            "specificity (no generic filler). Reply with up to 3 concrete, actionable fixes, "
            "or exactly 'OK' if the prompt fully satisfies the brief."
        )
        verdict = _vision_call(
            [
                {"role": "system", "content": critique_system},
                {"role": "user", "content": [{"type": "text", "text": f"BRIEF:\n{brief}\n\nPROMPT:\n{prompt_final}"}]},
            ],
            max_tokens=400, temperature=0.2,
        )
        if verdict.strip() != "OK":
            refine_system = (
                "Rewrite the prompt applying the art director's fixes. Keep the same format: "
                "one paragraph, English, production-ready, preserving the primary object."
            )
            prompt_final = _vision_call(
                [
                    {"role": "system", "content": refine_system},
                    {"role": "user", "content": [{"type": "text", "text": f"BRIEF:\n{brief}\n\nFIXES:\n{verdict}\n\nCURRENT PROMPT:\n{prompt_final}"}]},
                ],
                max_tokens=1200, temperature=0.4,
            )

    return {"brief": brief, "prompt": prompt_final, "genre": genre}
