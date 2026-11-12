# Adding Models to the ImageGen Plugin

This document tells you exactly where to add a new image model and what
each layer does. Model data is pinned in code, with one exception: FAL's
public catalog (`backend/imagegen_engine/fal_catalog.py`) is read at runtime, so
every active FAL text-to-image and image-to-image model appears without a
code change.

## FAL's public catalog

- The list comes from `https://api.fal.ai/v1/models` (categories
  `text-to-image` and `image-to-image`, active only), is cached on disk for 24
  hours in the plugin data folder, and refreshes in a background thread. A
  failed refresh keeps the last copy and waits 30 minutes before trying again.
  When the refresh lands, the plugin announces `providers.changed` and the
  Desktop reloads its model lists.
- Hermes' own `FAL_MODELS` stay first and keep their pinned payloads; catalog
  models with the same endpoint are skipped. Image-to-image models are listed
  in the FAL entry's `edit_models` for the Edit tab.
- A model's input schema (`expand=openapi-3.0`) is cached for a week.
  `fal_catalog.build_payload` fills prompt, aspect ratio or image size,
  resolution, seed, negative prompt and references, and refuses a model that
  requires an input ImageGen does not send. With references, generation uses
  the model's edit sibling (same FAL group, label or id with "edit").
- Listing never waits on the network: capabilities come from cached schemas
  only. When a catalog model is selected, the UI asks
  `GET /providers/fal/model?id=` for its exact references, ratios and
  resolutions. The FAL key, when set, is sent so the account's own rate limit
  applies.

## How providers and models are wired

```
frontend ModelCatalogModal          GET /providers          GET /providers/status
        |                                  |                        |
        v                                  v                        v
providers_catalog._list_providers()  ->  agent.image_gen_registry   (filled by Hermes's own
        |                            + FAL_MODELS (host)        plugin discovery: openai,
        v                            + Magnific (API)           xai, krea, openrouter,
  one entry per provider:            + Vertex AI (API)          nous, fal, ...)
                                     + local server (/v1/models)
  { name, display_name,
    available, models[] }
```

Generation path:

```
POST /generate | /jobs/submit --> gen_service.generate_text_to_image(provider, model, ...)
    dispatch goes through gen_service._PROVIDER_BACKENDS (one entry per
    provider family); anything not in that registry falls back to the
    registered-provider / FAL path.
    provider == "fal" + FAL_KEY --> FAL_MODELS catalog --> fal_submit_sync / fal_queue_poll
    provider == "fal", no key   --> Hermes's registered "fal" provider (managed
                                    gateway for a Nous subscription; model set in Hermes)
    provider == other registry  --> agent.image_gen_registry.get_provider(...)
                                    (includes "nous": OpenRouter-backed, Portal auth)
    provider == "magnific"      --> direct Magnific API (magnific_catalog.py)
    provider == "vertex"        --> direct Vertex AI API (vertex_api.py)
    provider == "local"         --> the server at the address in the settings (local_api.py)
```

The plugin never loads or registers Hermes's image providers itself:
`providers_catalog._ensure_providers_registered()` runs
`hermes_cli.plugins.discover_plugins()` once and then only reads
`agent.image_gen_registry`.

## Where to add a model — by case

### Case A: new Nous subscription model

Nothing to add here. A Nous subscription reaches models in two ways, both
owned by Hermes:

- the registered `nous` provider (OpenRouter-backed, reference-grounded),
  which lists its own models;
- FAL text-to-image through Hermes's `fal` provider when no `FAL_KEY` is
  set. Hermes picks the model from its own config, routes through its
  managed gateway, and handles entitlement and billing.

Queue resume and reference uploads need a `FAL_KEY`; without one the plugin
returns a clear `PROVIDER_UNAVAILABLE` error instead of calling the managed
gateway's private client.

If a new model belongs to a new family, add a match token in
`_FAMILY_PROFILES` (`backend/imagegen_engine/model_profiles.py`) so prompt
optimization picks the right dialect. Existing matches: `seedream`,
`ideogram`, `qwen`/`alibaba`, `nano-banana`/`mai-image`, `recraft`,
`flux`, `grok`, `gpt-image`.

### Case B: new FAL direct model (BYO FAL_KEY)

FAL models come from the host catalog `tools.image_generation_tool.FAL_MODELS`
in the installed Hermes checkout — not from this repo. Options:

- Wait for the upstream Hermes release that adds it (recommended; the
  catalog entry carries payload schema, size presets, price, and edit
  endpoint metadata the plugin reuses), or
- For a quick check, submit the raw endpoint id through the existing FAL
  path: the fallback in `gen_service.generate_text_to_image` builds a
  manual payload (`prompt` + `image_size`) when the id is not in
  `FAL_MODELS`.

### Case C: new external provider (not FAL-based)

1. Add a bundled Hermes plugin under `hermes-agent/plugins/image_gen/<name>/`
   exposing `register(ctx)` + a provider object (`name`, `is_available`,
   `list_models`, `generate`). Hermes's plugin discovery registers it; the
   ImageGen plugin only reads the registry.
2. `gen_service.generate_text_to_image` already routes any provider outside
   `_PROVIDER_BACKENDS` through `agent.image_gen_registry.get_provider`.
   Add an entry to `_PROVIDER_BACKENDS` only for a provider that needs its
   own transport (see the registry docstring for the required signature).
3. If the provider needs a stored key, extend `/providers/configure` in
   `backend/imagegen_engine/routes/system.py` (currently `fal` and `magnific` persist keys).

### Case D: model on a local server

Nothing to add. The `local` provider lists what the server at the
**Local server address** setting reports in `GET /v1/models` and generates
through `POST /v1/images/generations` (`backend/imagegen_engine/local_api.py`).
The list is read in a background thread and cached, so `GET /providers` never
waits on that server. A local API with another contract (AUTOMATIC1111,
ComfyUI) gets its own transport module and `_PROVIDER_BACKENDS` entry; do not
widen `local_api.py`.

## What you must NOT change

- Do not add navigation tabs or agency surfaces (scope lock).
- Do not commit `data/`, `.env`, or generated images.
- Keep capability keys exactly as in `capabilities_for_model`
  (`backend/imagegen_engine/model_profiles.py`): `maxReferences`, `edit`,
  `inpaint`, `outpaint`, `bg`, `upscale`, `animate`, `negativeMode`,
  `strengthTags`, `resolutions`. Unknown keys are dropped silently.

## Verification after adding a model

```bash
cd <repo>
python scripts/verify_workspace.py
PYTHONPATH=backend ".venv-test/Scripts/python.exe" \
  -m pytest -q tests --basetemp .pytest-basetemp
PYTHONPATH=backend python -m compileall -q backend
```

Then restart the Desktop app and confirm the model appears in the model
catalog modal with the right provider badge.
