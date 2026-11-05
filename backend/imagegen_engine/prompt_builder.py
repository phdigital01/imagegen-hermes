"""Prompt builder.

3 paths:
1. Confirmed composition (suggestedPrompt) → reinforcements (preserve/modify/interaction/anchoring).
2. Intent as a description fallback.
3. Layered advanced builder.

Unification: family resolution via model_profiles.resolve_family drives
negative handling (omit/inline/separate) and prompt_style stripping.
Builders emit {prompt, negative_prompt}; format_for_tool serializes per
family negative_mode.
"""
from __future__ import annotations

import re as _re
from typing import Any, Dict, List, Optional

from .presets import (
    APERTURES,
    DEFAULT_NEGATIVES,
    GENERIC_NEGATIVE,
    LENSES,
    PHOTOGRAPHIC_STYLES,
    QUALITY_TAGS,
    STRUCTURED_FIELDS,
    SUBJECT_DEFAULTS,
    SUBJECT_DISTANCES,
    SUBJECT_TYPES,
)

# Kept for reference — param injections only; family is authoritative.
PARAM_BASED_TOOLS = {"midjourney", "flux-pro", "sdxl", "stability-ultra", "krea-ai", "runwayml"}
NATURAL_LANG_TOOLS = {
    "dalle-3", "adobe-firefly", "chatgpt", "grok", "gemini-web", "copilot",
    "bing-creator", "canva-ai", "freepik-ai", "playground", "ideogram",
    "leonardo-ai", "recraft", "imagen-3",
}
NATURAL_LANG_MODELS = {
    "nanobanana-pro", "gemini-flash-image", "seedream-4.5", "google-imagen-4",
    "google-imagen-4-ultra", "ideogram-v3", "kling-v3", "imagen-3",
}

# ---------------------------------------------------------------------------
# Helpers: family + negative extraction
# ---------------------------------------------------------------------------

def _family_for_config(config: Dict[str, Any] | None, model_id: str = "", provider: str = "") -> Dict[str, Any]:
    from imagegen_engine.model_profiles import resolve_family

    cfg = config or {}
    prov = str(provider or cfg.get("provider") or cfg.get("selectedProvider") or "").strip()
    mod = str(model_id or cfg.get("model") or cfg.get("selectedModel") or cfg.get("toolTarget") or "").strip()
    return resolve_family(prov, mod)


def _split_raw_prompt(raw: str) -> tuple[str, str]:
    """Extract (prompt_body, negative) from a raw string that may contain --no."""
    if not raw:
        return "", ""
    # Prefer the canonical "\n\n--no " separator, fallback to any "--no "
    m = _re.search(r"\n\n--no\s+(.+)$", raw, flags=_re.MULTILINE | _re.DOTALL)
    if m:
        neg = m.group(1).strip()
        body = raw[: m.start()].rstrip()
        return body, neg
    m = _re.search(r"--no\s+(.+)$", raw, flags=_re.MULTILINE)
    if m:
        neg = m.group(1).strip()
        body = _re.sub(r"\s*--no\s+[^\n]*", "", raw).rstrip()
        return body, neg
    return raw, ""


def _serialize_by_family(prompt_body: str, negative: str, family: Dict[str, Any]) -> Dict[str, str]:
    mode = str(family.get("negative_mode") or "separate")
    prompt_style = str(family.get("prompt_style") or "natural")
    if mode == "omit":
        # Drop negatives entirely
        return {"prompt": prompt_body.strip(), "negative_prompt": ""}
    if mode == "inline":
        if negative:
            body = prompt_body.rstrip(" ,;:-")
            # avoid double Avoid injection
            if "avoid:" not in body.lower():
                body = f"{body}. Avoid: {negative}"
            return {"prompt": body.strip(), "negative_prompt": ""}
        return {"prompt": prompt_body.strip(), "negative_prompt": ""}
    # separate — keep negative as distinct field; prompt stays clean
    # For natural prompt_style, strip Midjourney flags from prompt body
    if prompt_style == "natural":
        prompt_body = _re.sub(r"\s*--(?:ar|s|iw|guidance)\s+[^\n]*", "", prompt_body)
        prompt_body = _re.sub(r"\s+", " ", prompt_body).strip().rstrip(" ,;:-")
    return {"prompt": prompt_body.strip(), "negative_prompt": negative.strip()}


# ---------------------------------------------------------------------------
# Public: build_prompt now emits {prompt, negative_prompt}
# ---------------------------------------------------------------------------

def build_prompt(config: Dict[str, Any]) -> Dict[str, str]:
    """Build the prompt as {prompt, negative_prompt} per family negative_mode.

    The underlying builders still produce a Midjourney-style raw string with
    ``--no``; we split it and re-emit according to ``resolve_family``.
    Backward compat: callers that expect a string should use
    ``build_prompt(config)[\"prompt\"]`` or the ``format_for_tool`` wrapper.
    """
    config = dict(config)
    tier = config.get("qualityTier") or config.get("qualityLevel")
    config["qualityLevel"] = {"draft": "padrao", "standard": "alta", "max": "maxima"}.get(tier, tier or "padrao")
    composed = _build_from_composition_intent(config)
    if composed:
        raw = composed
    else:
        effective = dict(config)
        intent = config.get("compositionIntent") or {}
        if not effective.get("description", "").strip() and (intent.get("userIntent") or "").strip():
            effective["description"] = intent["userIntent"].strip()
        raw = _append_reference_annotation(_build_advanced_prompt(effective), effective)

    colors = [str(value) for value in (config.get("colorAccents") or []) if isinstance(value, str)]
    if colors and config.get("colorAccentsEnabled") is not False:
        raw = f"Accent color palette: {', '.join(colors)}. {raw}"
    prompt_body, negative = _split_raw_prompt(raw)
    family = _family_for_config(config)
    return _serialize_by_family(prompt_body, negative, family)


# Backward-compatible string wrapper for callers that still expect str.
def build_prompt_string(config: Dict[str, Any]) -> str:
    """Legacy string form — joins negative inline when family is separate via --no."""
    out = build_prompt(config)
    if out["negative_prompt"]:
        return out["prompt"] + f"\n\n--no {out['negative_prompt']}"
    return out["prompt"]

def _refs_with_image(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return refs that have an image (hasImage/imageDataUrl/localPath/url) or text instructions.

    After frontend refsToMeta, imageDataUrl is stripped to hasImage+localPath/url.
    The builder must not require imageDataUrl.
    """
    out: List[Dict[str, Any]] = []
    for r in config.get("referencesV4", []) or []:
        if not isinstance(r, dict):
            continue
        if r.get("hasImage") or r.get("imageDataUrl") or r.get("localPath") or r.get("url") or (r.get("instructions") or "").strip():
            out.append(r)
    return out


# ===== Path 1: confirmed composition =====

def _build_from_composition_intent(config: Dict[str, Any]) -> Optional[str]:
    intent = config.get("compositionIntent") or {}
    if intent.get("status") != "confirmed" or not intent.get("suggestedPrompt"):
        return None

    composed: str = intent["suggestedPrompt"]
    refs = _refs_with_image(config)

    # 1. Reference tokens (fallback if the AI forgot them)
    if refs:
        missing = [i for i in range(1, len(refs) + 1)
                   if f"[image {i}]" not in composed.lower()]
        if missing:
            interps = intent.get("interpretations") or []

            def _interpretation_role(index: int) -> str:
                return (interps[index - 1] if index - 1 < len(interps) else {}).get("role", "")

            role_labels = {
                "object_primary": "main subject/product",
                "context_application": "environment/scene",
                "style_reference": "style guide",
                "lighting_reference": "lighting reference",
            }
            mapping = ", ".join(
                f"[Image {i}] = {role_labels.get(_interpretation_role(i), 'reference')}"
                for i in missing
            )
            composed += f". Reference mapping: {mapping}"

    # 1b. Granular fidelity (keep/vary/weights) — was lost after intent merge
    for ref in refs:
        instr = _reference_instruction(ref)
        if instr and instr not in composed:
            composed += f" {instr}"

    # 2. Preserve/modify
    preserve = intent.get("preserveElements") or []
    modify = intent.get("modifyElements") or []
    if preserve and "preserve" not in composed.lower():
        composed += f". Preserve from original scene: {', '.join(preserve)}"
    if modify and "modify" not in composed.lower():
        composed += f". Modify: {'; '.join(modify)}"

    # 3. Interaction
    interps = intent.get("interpretations") or []
    primary = next((i for i in interps if i.get("role") == "object_primary"), None)
    if primary and primary.get("interactionPoints") and "interaction" not in composed.lower():
        composed += f". Physical integration: {'; '.join(primary['interactionPoints'])}"

    # 4. Spatial anchoring
    geometry = intent.get("objectGeometry") or {}
    if geometry.get("geometryKeywords"):
        missing_kw = [k for k in geometry["geometryKeywords"]
                      if k.lower() not in composed.lower()]
        if missing_kw:
            composed += f", {', '.join(missing_kw)} form"

    # 5. Material transition
    mt = intent.get("materialTransition") or {}
    if mt.get("scenarioType") and mt["scenarioType"] != "none":
        has_terms = any(k.lower() in composed.lower() for k in (mt.get("transitionKeywords") or []))
        if not has_terms and mt.get("seamDescription"):
            composed += f". {mt['seamDescription']}"

    # 6. Contact/anchoring
    sa = intent.get("spatialAnchoring") or {}
    if sa.get("contactDescription"):
        surface = (sa.get("contactSurface") or "___never___").lower()
        if surface not in composed.lower():
            composed += f", {sa['contactDescription']}"

    # 7. Style/mood/distance
    gd = config.get("globalDirection") or {}
    if gd.get("style"):
        composed += f", {gd['style']} visual style"
    if config.get("mood"):
        composed += f", {config['mood']} mood and atmosphere"
    if config.get("subjectDistance"):
        dist = next((d for d in SUBJECT_DISTANCES if d["value"] == config["subjectDistance"]), None)
        if dist:
            composed += f", {dist['prompt_phrase']}"

    # 8. Quality
    qtags = QUALITY_TAGS.get(config.get("qualityLevel", "padrao"), "")
    if qtags:
        composed += f", {qtags}"

    # 9. Clean zones (suppressed for complex scenes/architecture)
    cz = config.get("cleanZones") or {}
    if cz.get("enabled") and cz.get("zones"):
        complex_scene = intent.get("sceneComplexity") == "complex"
        is_arch = config.get("subjectType") == "ambiente_arquitetura"
        if not (complex_scene or is_arch):
            zone_names = ", ".join(cz["zones"])
            intensity = cz.get("intensity", "Fully clean")
            tone = cz.get("tone", "Automatic")
            composed += f". Leave the {zone_names} area(s) {intensity}. Zone tone: {tone}."

    # 10. Anti-collage
    composed += ". Photorealistic integration, consistent perspective and lighting throughout, no visible compositing edges"

    # 11. Aspect ratio
    ar = config.get("aspectRatio")
    if ar and ar not in ("1:1", "auto"):
        composed += f", --ar {ar}"

    # 12. Automatic negative — always as --no for the splitter to route per family
    auto_neg = _get_auto_negative(config.get("subjectType", ""), config.get("genre", ""))
    if auto_neg:
        # Merge with user negative if present
        user_neg = (config.get("negativePrompt") or "").strip()
        final_neg = auto_neg
        if user_neg and user_neg != auto_neg:
            final_neg = f"{auto_neg}, {user_neg}"
        composed += f"\n\n--no {final_neg}"
    elif (config.get("negativePrompt") or "").strip():
        composed += f"\n\n--no {(config.get('negativePrompt') or '').strip()}"
    return composed


# ===== Path 3: advanced builder =====

def _build_advanced_prompt(config: Dict[str, Any]) -> str:
    parts: List[str] = []
    subject_type = config.get("subjectType", "")
    gd = config.get("globalDirection") or {}

    # 1. Subject context
    if subject_type and subject_type != "livre":
        st = next((s for s in SUBJECT_TYPES if s["value"] == subject_type), None)
        if st:
            parts.append(f"{st['label']} photography")

    # 2. Description
    if config.get("description", "").strip():
        parts.append(config["description"].strip())

    # 3. Structured fields
    if subject_type and subject_type != "livre":
        field_defs = STRUCTURED_FIELDS.get(subject_type, [])
        struct_parts: List[str] = []
        for fd in field_defs:
            val = config.get("structuredFields", {}).get(fd["key"])
            if not val:
                continue
            if isinstance(val, list) and val:
                struct_parts.append(f"{fd['label'].lower()}: {', '.join(val)}")
            elif isinstance(val, str) and val.strip():
                struct_parts.append(f"{fd['label'].lower()}: {val}")
        if struct_parts:
            parts.append(f"with {', '.join(struct_parts)}")

    # 4. Global direction
    if gd.get("style"):
        parts.append(f"{gd['style']} style")
    if gd.get("lens"):
        parts.append(f"shot on {gd['lens']} lens")
    if gd.get("aperture"):
        parts.append(gd["aperture"])
    if not gd.get("lens") and not gd.get("aperture") and gd.get("style") and gd["style"] in PHOTOGRAPHIC_STYLES:
        defaults = SUBJECT_DEFAULTS.get(subject_type, {"lens": "50mm", "aperture": "f/5.6"})
        if defaults.get("lens"):
            parts.append(f"shot on {defaults['lens']} lens")
        if defaults.get("aperture"):
            parts.append(defaults["aperture"])
    if gd.get("lighting"):
        parts.append(f"{', '.join(gd['lighting'])} lighting")
    if gd.get("angle"):
        parts.append(f"{gd['angle']} angle")
    if gd.get("useReferenceAngle"):
        parts.append("matching reference angle")

    # 4.5. Distance
    if config.get("subjectDistance"):
        dist = next((d for d in SUBJECT_DISTANCES if d["value"] == config["subjectDistance"]), None)
        if dist:
            parts.append(dist["prompt_phrase"])

    # 5. Fidelity
    if gd.get("fidelityMode") == "faithful":
        parts.append("exact faithful reproduction, high fidelity")
    elif gd.get("fidelityMode") == "creative":
        parts.append("creative reinterpretation, artistic freedom")

    # 5.5. Quality
    qtags = QUALITY_TAGS.get(config.get("qualityLevel", "padrao"), "")
    if qtags:
        parts.append(qtags)

    # 5.6. Mood
    if config.get("mood"):
        parts.append(f"{config['mood']} mood and atmosphere")

    # 6. References
    refs = _refs_with_image(config)
    if refs:
        parts.append(
            "[IMPORTANT: Use reference images only as guidance. Generate a new original image. "
            "Do NOT do cut-and-paste collage. Do NOT paste subjects into another scene. "
            "Avoid a composited overlay look. Keep lighting and shadows coherent.]"
        )
        for ref in refs:
            parts.append(_reference_instruction(ref))
        has_obj = any(r.get("semanticRole") == "object_primary" for r in refs)
        has_ctx = any(r.get("semanticRole") == "context_application" for r in refs)
        if has_obj and has_ctx:
            parts.append(
                "[SUBSTITUTION RULE: If the context reference contains an object similar to the "
                "primary object, IGNORE the context object and REPLACE it with the primary object. "
                "The primary object has absolute visual authority.]"
            )

    if (config.get("overflowReferenceText") or "").strip():
        parts.append(f"[Text-only references: {config['overflowReferenceText'].strip()}]")

    # 7. Clean zones
    cz = config.get("cleanZones") or {}
    if cz.get("enabled") and cz.get("zones"):
        zone_names = ", ".join(cz["zones"])
        intensity = cz.get("intensity", "Fully clean")
        tone = cz.get("tone", "Automatic")
        parts.append(f"Leave the {zone_names} area(s) {intensity}. Zone tone: {tone}.")

    base_prompt = ", ".join(parts)

    # 8. Aspect ratio
    ar = config.get("aspectRatio")
    if ar and ar not in ("1:1", "auto"):
        base_prompt += f", --ar {ar}"

    # 9. Negative — keep as --no for the splitter; family routes it
    auto_neg = _get_auto_negative(subject_type, config.get("genre", ""))
    user_neg = (config.get("negativePrompt") or "").strip()
    final_neg = auto_neg
    if user_neg and user_neg != auto_neg:
        final_neg = f"{auto_neg}, {user_neg}" if auto_neg else user_neg
    if final_neg:
        base_prompt += f"\n\n--no {final_neg}"

    return base_prompt


def _reference_instruction(ref: Dict[str, Any]) -> str:
    role = ref.get("semanticRole", "")
    label = ref.get("label", "referência")
    ref_parts: List[str] = []
    if role == "object_primary":
        ref_parts.append(f'Use Reference "{label}" as the PRIMARY OBJECT with authoritative visual fidelity.')
        ref_parts.append("Preserve its exact design, shape, material, and proportions.")
        if ref.get("userNotes"):
            ref_parts.append(f"User note: {ref['userNotes']}")
    elif role == "context_application":
        ref_parts.append(f'Use Reference "{label}" ONLY for CONTEXT: position, scale, scene integration, and environment.')
        ref_parts.append("Ignore any objects in this reference that resemble the primary subject — replace them with the primary object.")
        if ref.get("userNotes"):
            ref_parts.append(f"User note: {ref['userNotes']}")
    elif role == "style_reference":
        ref_parts.append(f'Use Reference "{label}" as STYLE guide only: visual language, color palette, rendering approach, artistic technique.')
        if ref.get("userNotes"):
            ref_parts.append(f"User note: {ref['userNotes']}")
    elif role == "lighting_reference":
        ref_parts.append(f'Use Reference "{label}" for LIGHTING and MOOD guidance only: light direction, intensity, color temperature, atmosphere.')
        if ref.get("userNotes"):
            ref_parts.append(f"User note: {ref['userNotes']}")
    else:
        if ref.get("purposes"):
            ref_parts.append(f"use for: {', '.join(ref['purposes'])}")
        if ref.get("fixedProduct"):
            ref_parts.append("fixed product (95% fidelity)")
        else:
            ref_parts.append(f"fidelity: {ref.get('fidelity', 70)}%")
        if ref.get("keep"):
            ref_parts.append(f"keep: {', '.join(ref['keep'])}")
        if ref.get("vary"):
            ref_parts.append(f"vary: {', '.join(ref['vary'])}")
        if (ref.get("instructions") or "").strip():
            ref_parts.append(f"instructions: {ref['instructions'].strip()}")
        weights = ref.get("granularWeights") or {}
        wp = []
        if weights.get("colors", 70) != 70:
            wp.append(f"colors {weights['colors']}%")
        if weights.get("lighting", 70) != 70:
            wp.append(f"lighting {weights['lighting']}%")
        if weights.get("composition", 70) != 70:
            wp.append(f"composition {weights['composition']}%")
        if weights.get("textures", 70) != 70:
            wp.append(f"textures {weights['textures']}%")
        if wp:
            ref_parts.append(f"weights: {', '.join(wp)}")
    if role in ("object_primary", "context_application", "style_reference", "lighting_reference"):
        if ref.get("keep"):
            ref_parts.append(f"Preserve within this role: {', '.join(ref['keep'])}.")
        if ref.get("vary"):
            ref_parts.append(f"Allow variation in: {', '.join(ref['vary'])}.")
        if ref.get("fidelity") is not None:
            ref_parts.append(f"Requested fidelity priority: {ref['fidelity']}/100.")
        if (ref.get("instructions") or "").strip():
            ref_parts.append(ref["instructions"].strip())
        weights = ref.get("granularWeights") or {}
        if weights:
            ref_parts.append("Visual priorities: " + ", ".join(f"{key} {value}/100" for key, value in weights.items()) + ".")
    if ref_parts:
        return f"[Reference {label}: {' '.join(ref_parts)}]"
    return ""

def _append_reference_annotation(prompt: str, config: Dict[str, Any]) -> str:
    refs = [r for r in config.get("referencesV4", []) if r.get("imageDataUrl") or (r.get("instructions") or "").strip()]
    if not refs:
        return prompt
    return prompt + " [Reference interpreted by AI visual analysis]"


def _get_auto_negative(subject_type: str, genre: str = "") -> str:
    """Automatic negative: per-subject default + genre negative (C5)."""
    base = DEFAULT_NEGATIVES.get(subject_type, GENERIC_NEGATIVE)
    if genre:
        try:
            from imagegen_engine.presets import GENRES

            g = next((x for x in GENRES if x["id"] == genre), None)
            if g and g.get("negative"):
                return ", ".join(dict.fromkeys([*(base.split(", ")), *(g["negative"].split(", "))]))
        except Exception:  # noqa: BLE001
            pass
    return base

# ===== Per-tool adapters =====

def format_for_tool(base_prompt: Any, model_id: str = "", config: Dict[str, Any] | None = None, provider: str = "") -> Any:
    """Format the prompt for the target tool/model via resolve_family.

    Accepts either a legacy string (with embedded ``--no``) or the new
    ``{prompt, negative_prompt}`` dict from :func:`build_prompt`. Output
    respects family ``negative_mode``:
      - ``omit``     → drop negatives
      - ``inline``   → ``Avoid: ...`` sentence in prompt
      - ``separate`` → ``{prompt, negative_prompt}`` dict (FAL/portal)

    ``prompt_style`` ``natural`` strips Midjourney flags (``--ar`` etc.).
    Param injections (midjourney ``--s --iw``, flux ``--guidance``) are kept
    as family extras for backward compat.
    """
    cfg = config or {}
    # Normalize base into (prompt, negative)
    if isinstance(base_prompt, dict):
        prompt = str(base_prompt.get("prompt") or "")
        negative = str(base_prompt.get("negative_prompt") or "")
        # provider/model may be in dict as well
        provider = str(provider or base_prompt.get("provider") or cfg.get("provider") or cfg.get("selectedProvider") or "")
        model_id = str(model_id or base_prompt.get("model") or cfg.get("model") or cfg.get("selectedModel") or "")
    else:
        prompt = str(base_prompt or "")
        # extract embedded --no if any (legacy path)
        m = _re.search(r"\n\n--no\s+(.+)$", prompt, flags=_re.MULTILINE | _re.DOTALL)
        if m:
            negative = m.group(1).strip()
            prompt = prompt[: m.start()].rstrip()
        else:
            m2 = _re.search(r"--no\s+(.+)$", prompt, flags=_re.MULTILINE)
            if m2:
                negative = m2.group(1).strip()
                prompt = _re.sub(r"\s*--no\s+[^\n]*", "", prompt).strip()
            else:
                negative = str(cfg.get("negativePrompt") or "").strip()

    provider_val = str(provider or cfg.get("provider") or cfg.get("selectedProvider") or "")
    model_val = str(model_id or cfg.get("model") or cfg.get("selectedModel") or cfg.get("toolTarget") or "")

    from imagegen_engine.model_profiles import resolve_family

    family = resolve_family(provider_val, model_val)
    negative_mode = str(family.get("negative_mode") or "separate")
    prompt_style = str(family.get("prompt_style") or "natural")

    # Param injections — keep midjourney/flux behavior keyed by model token
    is_midjourney = "midjourney" in model_val.lower()
    is_flux = "flux" in model_val.lower()

    if is_midjourney:
        prompt = prompt.rstrip() + "\n--s 750"
        # fidelity-derived --iw when refs exist
        refs = cfg.get("referencesV4") or []
        if refs:
            try:
                avg = sum((r.get("fidelity", 70) if isinstance(r, dict) else 70) for r in refs) / max(1, len(refs))
                prompt += f" --iw {(avg / 100 * 2):.1f}"
            except Exception:
                pass
        # Midjourney is param-based — keep --ar/--no as-is for backward compat
        if negative and negative_mode == "separate":
            return {"prompt": prompt, "negative_prompt": negative}
        if negative and negative_mode == "inline":
            prompt = prompt + f". Avoid: {negative}"
            return prompt
        if negative and negative_mode == "omit":
            return prompt
        return prompt

    if is_flux:
        gd = cfg.get("globalDirection") or {}
        flux = prompt
        if gd.get("fidelityMode") == "faithful":
            flux += "\n--guidance 7.5"
        elif gd.get("fidelityMode") == "creative":
            flux += "\n--guidance 3.5"
        # Flux negative handling per family
        if negative_mode == "omit":
            return flux
        if negative_mode == "inline":
            if negative:
                flux = flux + f". Avoid: {negative}"
            # flux inline still natural — strip flags? Keep guidance
            return flux
        # separate
        if negative:
            return {"prompt": flux, "negative_prompt": negative}
        return flux

    # Generic family path
    if prompt_style == "natural":
        # strip Midjourney-style flags
        prompt = _re.sub(r"\s*--(?:ar|s|iw|no|guidance)\s+[^\n]*", "", prompt)
        prompt = _re.sub(r"\s+", " ", prompt).strip().rstrip(" ,;:-")

    if negative_mode == "omit":
        return prompt
    if negative_mode == "inline":
        if negative:
            prompt = prompt.rstrip(" ,;:-") + f". Avoid: {negative}"
        return prompt
    # separate
    if negative:
        return {"prompt": prompt, "negative_prompt": negative}
    return prompt


def _to_natural_language(base_prompt: str, config: Dict[str, Any]) -> str:
    import re

    # Capture the negative BEFORE removing the flags (used as "Avoid:").
    neg_match = re.search(r"--no\s+(.+)$", base_prompt, flags=re.MULTILINE)
    # Remove tool flags (--ar/--s/--iw/--no/--guidance) to end of line,
    # without touching the prose that precedes them.
    prompt = re.sub(r"\s*--(?:ar|s|iw|no|guidance)\s+[^\n]*", "", base_prompt)
    prompt = re.sub(r"\s+", " ", prompt).strip()
    prompt = prompt.rstrip(" ,;:-")

    ar = config.get("aspectRatio")
    if ar and ar not in ("1:1", "auto"):
        prompt += f". Aspect ratio: {ar}"
    if neg_match:
        prompt += f". Avoid: {neg_match.group(1).strip()}"
    return prompt
