"""Test-session isolation for the persistent job store.

``imagegen_engine.jobs`` hydrates persisted records at module import time (and every
job state transition writes data/jobs.json), so the very first import must not
read or write the developer's real ``backend/data/jobs.json``. Point the store
at a scratch file before any test module imports ``imagegen_engine.jobs``; per-test
fixtures (e.g. ``test_routes.isolated_store``) re-derive it under tmp_path.
"""
from __future__ import annotations

import atexit
import shutil
import sys
import tempfile
import types
from pathlib import Path

import pytest

from imagegen_engine import store

_JOBS_DIR = tempfile.mkdtemp(prefix="imagegen-test-jobs-")
atexit.register(shutil.rmtree, _JOBS_DIR, ignore_errors=True)
store.jobs_file = lambda: Path(_JOBS_DIR) / "jobs.json"


@pytest.fixture
def host_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Expose a minimal host FAL catalog when the Hermes checkout is absent.

    ``gen_service`` falls back to a manual payload when
    ``tools.image_generation_tool`` cannot be imported, which drops the price
    metadata and silently breaks the cost-estimation assertions. This fixture
    makes the import succeed so the real catalog path is exercised.
    """
    fake = types.ModuleType("tools.image_generation_tool")
    fake.FAL_MODELS = {
        "fal-ai/flux-2-pro": {
            "display": "FLUX 2 Pro",
            "price": "$0.03/MP",
            "edit_endpoint": "fal-ai/flux-2-pro/edit",
            "max_reference_images": 9,
        },
    }
    # A 1 MP size makes the "$0.03/MP" price above resolve to $0.03 per image.
    fake._build_fal_payload = lambda model_id, prompt, aspect_ratio="square", seed=None: {
        "prompt": prompt,
        "image_size": {"width": 1000, "height": 1000},
    }
    fake._build_fal_edit_payload = lambda model_id, prompt, image_urls=None, aspect_ratio="square", seed=None: {"prompt": prompt, "image_urls": image_urls or []}
    monkeypatch.setitem(sys.modules, "tools.image_generation_tool", fake)


@pytest.fixture(autouse=True)
def offline_fal_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep FAL's public catalog offline: an empty, fresh cache and no HTTP."""
    import time

    from imagegen_engine import fal_catalog

    def refuse(params):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(fal_catalog, "_get", refuse)
    monkeypatch.setattr(fal_catalog, "_write_json", lambda name, data: None)
    monkeypatch.setattr(fal_catalog, "_memory", {"catalog": {"at": time.time()}, "schemas": {}})
