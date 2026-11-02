"""Route registry contract for the ImageGen plugin API.

The plugin surface is split across ``imagegen_engine/routes/*`` and aggregated into
``plugin_api.router``. Two invariants must hold forever:

1. The (method, path) set mounted on ``plugin_api.router`` is EXACTLY the
   pinned list below — any route lost in a future split fails this test.
2. Static routes are registered before the parametric routes that would
   otherwise shadow them (FastAPI matches in registration order):
   ``/handoff/last`` vs ``/handoff/{handoff_id}``, ``/jobs/submit`` vs
   ``/jobs/{job_id}``, ``/subjects/kinds`` vs ``/subjects/{obj_id}``,
   ``/gallery/stats`` vs ``/gallery/{entry_id}``.
"""
from __future__ import annotations

import pytest

from imagegen_engine import plugin_api
from imagegen_engine.routes import generation, jobs, library, llm, media, system

# Ground truth captured from the pre-split single-file router. Order in this
# list is irrelevant (compared sorted); it pins the exact surface so a lost
# route fails loudly.
EXPECTED_ROUTES = [
    ("GET", "/health"),
    ("GET", "/providers"),
    ("GET", "/providers/status"),
    ("POST", "/providers/test"),
    ("GET", "/providers/fal/model"),
    ("GET", "/settings/output-folder"),
    ("POST", "/settings/output-folder"),
    ("GET", "/settings/budget"),
    ("POST", "/settings/budget"),
    ("GET", "/handoff/last"),
    ("GET", "/handoff/{handoff_id}"),
    ("POST", "/handoff/feedback"),
    ("POST", "/refine-from-feedback"),
    ("GET", "/presets"),
    ("POST", "/prompt/build"),
    ("POST", "/llm/optimize"),
    ("POST", "/llm/composition-analyze"),
    ("GET", "/genres"),
    ("POST", "/llm/refine"),
    ("POST", "/llm/translate"),
    ("GET", "/jobs"),
    ("GET", "/jobs/{job_id}"),
    ("GET", "/jobs/{job_id}/result"),
    ("POST", "/jobs/{job_id}/cancel"),
    ("POST", "/jobs/{job_id}/retry"),
    ("POST", "/jobs/{job_id}/resume"),
    ("POST", "/jobs/submit"),
    ("POST", "/generate"),
    ("POST", "/vary"),
    ("POST", "/upscale"),
    ("POST", "/bg-remove"),
    ("POST", "/llm/product-passport"),
    ("GET", "/objects"),
    ("GET", "/subjects"),
    ("GET", "/subjects/kinds"),
    ("GET", "/objects/file/{filename}"),
    ("POST", "/subjects/import"),
    ("POST", "/objects/import"),
    ("POST", "/subjects/{obj_id}/as-ref"),
    ("POST", "/objects/{obj_id}/as-ref"),
    ("POST", "/subjects/{obj_id}/as-refs"),
    ("PATCH", "/subjects/{obj_id}"),
    ("POST", "/subjects/{obj_id}/angles"),
    ("DELETE", "/subjects/{obj_id}"),
    ("DELETE", "/objects/{obj_id}"),
    ("POST", "/batch/matrix"),
    ("POST", "/edit"),
    ("POST", "/relight"),
    ("POST", "/style-transfer"),
    ("POST", "/inpaint"),
    ("POST", "/outpaint"),
    ("POST", "/camera"),
    ("POST", "/skin"),
    ("POST", "/prompt-helper"),
    ("POST", "/magnific"),
    ("POST", "/upload"),
    ("GET", "/refs/{filename}"),
    ("GET", "/feed"),
    ("GET", "/feed/stats"),
    ("POST", "/feed/export-zip"),
    ("DELETE", "/feed/{entry_id}"),
    ("GET", "/history"),
    ("DELETE", "/history/{entry_id}"),
    ("GET", "/gallery"),
    ("GET", "/gallery/stats"),
    ("DELETE", "/gallery"),
    ("DELETE", "/gallery/{entry_id}"),
    ("GET", "/gallery/{entry_id}/export-pack"),
    ("GET", "/exports/{filename}"),
    ("POST", "/settings/clear-data"),
    ("GET", "/media/local-path"),
    ("GET", "/media/data-url"),
    ("GET", "/gallery/item/{entry_id}"),
    ("GET", "/gallery/file/{filename}"),
    ("GET", "/cache/{name}"),
    ("GET", "/library"),
    ("POST", "/library"),
    ("DELETE", "/library/{entry_id}"),
]

# Static route that must resolve to its own handler, never to the parametric
# route that would shadow it if registration order regressed.
STATIC_ROUTE_HANDLERS = [
    ("GET", "/handoff/last", llm.handoff_last),
    ("POST", "/jobs/submit", jobs.jobs_submit),
    ("GET", "/subjects/kinds", library.subjects_kinds),
    ("GET", "/gallery/stats", media.gallery_stats),
]


def _actual_routes():
    return [
        (sorted(route.methods)[0], route.path)
        for route in plugin_api.router.routes
        if getattr(route, "methods", None)
    ]


def _first_match(method: str, path: str):
    """First route that FastAPI would match for (method, path)."""
    for route in plugin_api.router.routes:
        if method in (route.methods or set()) and route.path_regex.match(path):
            return route
    return None


def test_router_exposes_exactly_the_expected_route_set() -> None:
    actual = sorted(_actual_routes())
    assert len(actual) == len(EXPECTED_ROUTES)
    assert actual == sorted(EXPECTED_ROUTES)


def test_all_expected_routes_are_mounted() -> None:
    actual = set(_actual_routes())
    missing = [entry for entry in EXPECTED_ROUTES if entry not in actual]
    assert missing == [], f"routes lost in the split: {missing}"


@pytest.mark.parametrize(
    ("method", "path", "expected_endpoint"),
    STATIC_ROUTE_HANDLERS,
    ids=[f"{method} {path}" for method, path, _ in STATIC_ROUTE_HANDLERS],
)
def test_static_route_is_not_shadowed(method: str, path: str, expected_endpoint) -> None:
    route = _first_match(method, path)
    assert route is not None, f"{method} {path} is not matched by any mounted route"
    assert route.endpoint is expected_endpoint, (
        f"{method} {path} resolves to {route.endpoint.__name__} — "
        f"expected {expected_endpoint.__name__}; a parametric route shadows it"
    )


def test_every_route_module_uses_the_structured_error_router() -> None:
    """Every domain router must carry the ImageGen route class so the error
    envelope applies to all 68 routes, not only the first module's."""
    route_classes = {type(route) for route in plugin_api.router.routes}
    assert len(route_classes) == 1
    (route_class,) = route_classes
    assert route_class.__name__ == "_ImageGenRoute"
