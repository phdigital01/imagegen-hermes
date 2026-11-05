"""ImageGen — FastAPI backend for the desktop plugin.

Runs inside the Hermes gateway. Imports code from Hermes itself
(tools.image_generation_tool, agent.image_gen_registry) to generate images
without an external backend. Provider keys come from the Hermes secret store and
are never exposed to the frontend.

Loading contract
----------------
The web server imports this file as a top-level module
(``spec_from_file_location``, no parent package), so relative imports break.
The ``sys.path`` bootstrap below MUST run before any ``imagegen_engine.*`` import;
``imagegen_engine.api_core`` repeats the same guard for modules loaded directly.

This file is now a thin aggregator — all routes live in domain routers
(``imagegen_engine/routes/*``), each built with ``make_router()`` from
``imagegen_engine.api_core`` so the structured error envelope applies everywhere.
The routers are mounted here in the order system, llm, jobs, generation,
library, media; relative route order inside each module is preserved from the
original single-file layout (static paths precede shadowing parametric ones,
e.g. ``/handoff/last`` before ``/handoff/{handoff_id}``).

Module map
----------
- ``imagegen_engine.api_core`` — error envelope, route base class, URL helpers,
  ``make_router`` factory.
- ``imagegen_engine.providers_catalog`` — provider registration/listing, profile env.
- ``imagegen_engine.generation_artifacts`` — gallery/history persistence, job builder.
- ``imagegen_engine.routes.system`` — /health, /providers*, /settings/*
- ``imagegen_engine.routes.llm`` — /handoff*, /refine-from-feedback, /presets,
  /genres, /prompt/build, /llm/*
- ``imagegen_engine.routes.jobs`` — /jobs lifecycle + /jobs/submit
- ``imagegen_engine.routes.generation`` — /generate, /vary, /upscale, /bg-remove,
  /edit, /inpaint, /outpaint, /relight, /style-transfer, /magnific, /batch/matrix
- ``imagegen_engine.routes.library`` — /objects*, /subjects*, /library*
- ``imagegen_engine.routes.media`` — /upload, /refs, /feed*, /history*, /gallery*,
  /exports, /cache

``router`` is the single exported symbol the web server mounts.
"""
from __future__ import annotations

import sys
from pathlib import Path

# The web server imports this file as a top-level module
# (spec_from_file_location, no parent package) — relative imports (``.``)
# break with "attempted relative import with no known parent package".
# We make sure the imagegen_engine/ package parent directory is on sys.path
# and use absolute ``imagegen_engine.*`` imports.
_DASH_PARENT = Path(__file__).resolve().parent.parent
if str(_DASH_PARENT) not in sys.path:
    sys.path.insert(0, str(_DASH_PARENT))

from fastapi import APIRouter

from imagegen_engine.api_core import _ImageGenRoute
from imagegen_engine.routes import batches, generation, jobs, library, llm, media, system

# Mount the domain routers in order (system, llm, jobs, generation, library,
# media). Note: FastAPI >= 0.141 wraps ``include_router`` lazily
# (``_IncludedRouter``), which would turn ``router.routes`` from the 68
# APIRoute objects into 6 wrappers — an observable change from the pre-split
# router. The aggregator needs no prefix/dependencies, so we concatenate the
# leaf routes directly to keep the exact pre-split surface.
router = APIRouter(route_class=_ImageGenRoute)
router.routes.extend(system.router.routes)
router.routes.extend(llm.router.routes)
router.routes.extend(jobs.router.routes)
router.routes.extend(batches.router.routes)
router.routes.extend(generation.router.routes)
router.routes.extend(library.router.routes)
router.routes.extend(media.router.routes)
