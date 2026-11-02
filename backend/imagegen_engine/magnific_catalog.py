"""Pinned Magnific image contracts, shared by dispatch and UI discovery.

Source links and coverage are recorded in docs/references/magnific.md. Values describe
the adapter's supported controls, not every parameter offered by the service.
"""
from copy import deepcopy

COMMON_RATIOS = ["1:1", "16:9", "9:16", "2:3", "3:4", "3:2", "4:3"]
FLUX_RATIOS = COMMON_RATIOS + ["1:2", "2:1", "4:5"]
GOOGLE_RATIOS = COMMON_RATIOS + ["5:4", "4:5", "21:9"]
GPT_RATIOS = COMMON_RATIOS + ["21:9", "2:1", "3:1"]
RECRAFT_RATIOS = FLUX_RATIOS + ["5:4"]
IDEOGRAM_RATIOS = FLUX_RATIOS + ["5:4", "1:3", "3:1"]


def _model(name, family, *, refs=0, ratios=None, resolutions=None, seed=True,
           ref_input="base64", edit_endpoint=None, prompt_max=None, path=None,
           ref_field=None, resolution_case=None, max_side=None, seed_range=None,
           requires_reference=False, strengths=None):
    return {"display": name, "family": family, "maxReferences": refs,
            "aspectRatios": list(ratios or COMMON_RATIOS),
            "resolutionOptions": list(resolutions or []), "supportsSeed": seed,
            "referenceInput": ref_input, "edit_endpoint": edit_endpoint,
            "promptMax": prompt_max, "path": path, "refField": ref_field,
            "resolutionCase": resolution_case, "maxSide": max_side,
            "seedRange": list(seed_range or (0, 4294967295)),
            "requiresReference": requires_reference, "note": strengths}


_INT32 = (0, 2147483647)

MODELS = {
    "mystic": _model("Mystic", "mystic", resolutions=["1K", "2K", "4K"], seed=False,
                     ratios=FLUX_RATIOS + ["5:4", "20:9", "9:20"], path="mystic", resolution_case="lower"),
    "magnific-one": _model("Magnific One", "raw", refs=10, ratios=GPT_RATIOS, resolutions=["1K", "2K", "4K"],
                           seed=False, ref_input="public-url", prompt_max=2000, path="magnific-one",
                           ref_field="reference_images", resolution_case="lower",
                           strengths="Magnific's own photoreal model, with references"),
    "gpt-image-2": _model("GPT Image 2", "named", refs=16, ratios=GPT_RATIOS, resolutions=["1K", "2K", "4K"],
                          seed=False, edit_endpoint="gpt-image-2-edit", prompt_max=32000,
                          ref_field="reference_images", resolution_case="lower",
                          strengths="Legible text inside the image and close prompt following"),
    "gpt-image-2-5": _model("GPT Image 2.5", "named", refs=16, ratios=GPT_RATIOS, resolutions=["1K", "2K", "4K"],
                            seed=False, edit_endpoint="gpt-image-2-5-edit", prompt_max=32000,
                            ref_field="reference_images", resolution_case="lower",
                            strengths="Newer GPT Image tier: legible text and editing with references"),
    "flux-2-pro": _model("FLUX.2 Pro", "flux-pro", refs=4, ratios=GOOGLE_RATIOS, resolutions=["1K"], max_side=1440),
    "flux-2-flex": _model("FLUX.2 Flex", "flux-pro", refs=4, ratios=GOOGLE_RATIOS, resolutions=["1K"], max_side=1920),
    "flux-2-turbo": _model("FLUX.2 Turbo", "flux-turbo", ratios=GOOGLE_RATIOS, resolutions=["1K", "2K"]),
    "flux-2-klein": _model("FLUX.2 Klein", "named", refs=4, ratios=FLUX_RATIOS, resolutions=["1K", "2K"],
                           resolution_case="lower"),
    "flux-kontext-pro": _model("FLUX Kontext Pro", "named", refs=1, ratios=FLUX_RATIOS, ref_input="public-url"),
    "flux-kontext-max": _model("FLUX Kontext Max", "named", refs=4, ratios=FLUX_RATIOS, ref_input="public-url",
                               requires_reference=True, strengths="Edits a reference image from a prompt"),
    "flux-pro-v1-1": _model("FLUX 1.1 Pro", "named", ratios=FLUX_RATIOS),
    "flux-dev": _model("FLUX Dev", "named", ratios=FLUX_RATIOS, seed_range=(1, 4294967295)),
    "hyperflux": _model("Hyperflux", "named", ratios=FLUX_RATIOS, seed_range=(1, 4294967295),
                        strengths="Fast FLUX drafts"),
    "seedream-v4": _model("Seedream 4", "named", refs=5, edit_endpoint="seedream-v4-edit", seed_range=_INT32),
    "seedream-v4-5": _model("Seedream 4.5", "named", refs=5, ratios=COMMON_RATIOS + ["21:9"],
                           edit_endpoint="seedream-v4-5-edit", prompt_max=4096),
    "seedream-v5-lite": _model("Seedream 5 Lite", "named", refs=5, ratios=COMMON_RATIOS + ["21:9"],
                              edit_endpoint="seedream-v5-lite-edit", prompt_max=4096),
    "seedream-v5-pro": _model("Seedream 5 Pro", "named", refs=10, ratios=COMMON_RATIOS + ["21:9"],
                             resolutions=["1.5K", "2K"], edit_endpoint="seedream-v5-pro-edit", prompt_max=4096,
                             resolution_case="lower"),
    "nano-banana-pro": _model("Nano Banana Pro", "google", refs=3, ratios=GOOGLE_RATIOS,
                              resolutions=["1K", "2K", "4K"], seed=False, ref_input="public-url", prompt_max=3000),
    "nano-banana-pro-flash": _model("Nano Banana Pro Flash", "google", refs=3, ratios=GOOGLE_RATIOS,
                                    resolutions=["1K", "2K", "4K"], seed=False, ref_input="public-url", prompt_max=3000),
    "nano-banana-2-1": _model("Nano Banana 2.1", "google", refs=14,
                              ratios=GOOGLE_RATIOS + ["1:4", "4:1", "1:8", "8:1"], resolutions=["1K", "2K", "4K"],
                              seed=False, prompt_max=12000),
    "ideogram-4": _model("Ideogram 4", "raw", ratios=IDEOGRAM_RATIOS + ["16:10", "10:16"], prompt_max=10000,
                         seed_range=_INT32, strengths="Typography and graphic design"),
    "ideogram-4-5": _model("Ideogram 4.5", "raw", refs=5, ratios=IDEOGRAM_RATIOS, prompt_max=10000,
                           ref_field="images", seed_range=_INT32,
                           strengths="Typography and design; the first reference is the image to edit"),
    "recraft-v4": _model("Recraft V4", "named", ratios=RECRAFT_RATIOS, seed=False, prompt_max=10000),
    "recraft-v4-1": _model("Recraft V4.1", "named", ratios=RECRAFT_RATIOS, seed=False, prompt_max=10000),
    "recraft-v4-pro": _model("Recraft V4 Pro", "named", ratios=RECRAFT_RATIOS, seed=False, prompt_max=10000),
    "runway": _model("Runway", "runway", ratios=["1:1", "16:9", "9:16", "4:3", "3:4", "21:9"], prompt_max=1000),
    "z-image": _model("Z-Image Turbo", "z-image", ratios=["1:1", "16:9", "9:16", "4:3", "3:4"], resolutions=["1K"], prompt_max=4096),
}

# Image operations outside generation, each with its documented submit path. Skin
# enhancer modes submit to their own path but share one task path.
OPERATIONS = {
    "image-upscaler": "image-upscaler",
    "image-upscaler-precision": "image-upscaler-precision",
    "image-upscaler-precision-v2": "image-upscaler-precision-v2",
    "image-relight": "image-relight",
    "image-style-transfer": "image-style-transfer",
    "image-expand": "image-expand/flux-pro",
    "image-expand-ideogram": "image-expand/ideogram",
    "image-expand-seedream": "image-expand/seedream-v4-5",
    "image-change-camera": "image-change-camera",
    "ideogram-image-edit": "ideogram-image-edit",
    "skin-enhancer-creative": "skin-enhancer/creative",
    "skin-enhancer-faithful": "skin-enhancer/faithful",
    "skin-enhancer-flexible": "skin-enhancer/flexible",
    "image-to-prompt": "image-to-prompt",
    "improve-prompt": "improve-prompt",
    "upload-request": "uploads/request-url",
    "remove-background": "beta/remove-background",
}
TASK_PATHS = {name: "skin-enhancer" for name in OPERATIONS if name.startswith("skin-enhancer-")}
EXPAND_MODELS = {"flux-pro": "image-expand", "ideogram": "image-expand-ideogram", "seedream-v4-5": "image-expand-seedream"}


def get_model(model):
    if model in MODELS:
        return deepcopy(MODELS[model])
    for entry in MODELS.values():
        if entry.get("edit_endpoint") == model:
            return deepcopy(entry)
    return {}


def generation_model(model):
    """Map a concrete editing endpoint back to its selectable model family."""
    return next((key for key, value in MODELS.items() if value.get("edit_endpoint") == model), model)


def list_models():
    return [{"id": key, **{k: deepcopy(v) for k, v in value.items() if k != "note"},
             "strengths": value["note"] or ("Generation and reference editing" if value["maxReferences"] else "Text-to-image"),
             "capabilities": {"maxReferences": value["maxReferences"], "edit": bool(value["maxReferences"]),
                              "resolutions": value["resolutionOptions"], "negativeMode": "unsupported"}}
            for key, value in MODELS.items()]
