"""Domain routers for the ImageGen plugin API.

Each module exposes a single ``router = make_router()`` (see
``imagegen_engine.api_core``) and owns a slice of the plugin surface. Route order
inside each module preserves the original ``plugin_api.py`` order, because
FastAPI matches in registration order and static paths must precede the
parametric routes that would otherwise shadow them (e.g. ``/handoff/last``
before ``/handoff/{handoff_id}``).

- ``system`` — /health, /providers*, /settings/*
- ``llm`` — /handoff*, /refine-from-feedback, /presets, /genres,
  /prompt/build, /llm/*
- ``jobs`` — /jobs lifecycle + /jobs/submit
- ``generation`` — /generate, /vary, /upscale, /bg-remove, /edit, /inpaint,
  /outpaint, /magnific, /batch/matrix
- ``library`` — /objects*, /subjects*, /library*
- ``media`` — /upload, /refs/{filename}, /feed*, /history*, /gallery*,
  /exports/{filename}, /cache/{name}

``imagegen_engine.plugin_api`` aggregates these routers into a single ``router``,
which is the module the Hermes web server discovers (manifest.json).
"""
