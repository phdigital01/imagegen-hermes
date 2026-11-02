"""HTTP contract tests for the ImageGen plugin API.

Runs the real FastAPI router (``plugin_api.router``) through a TestClient.
Every store path is monkeypatched to ``tmp_path`` (mirroring
``tests/test_store.py::isolated_store``), so no test touches real user data
and no test makes a network call.

Covered contracts:

- health / provider catalog shape (capabilities regression)
- provider status never leaks API keys
- feed read model + filters + idempotent delete
- upload (real JPEG/PNG bytes) + reference serving with real media types
- structured error envelope (``{ok, error: {code, message}}``)
- path-traversal ids never escape the data directory
- jobs lifecycle surface (list / missing get / missing cancel)
- retired routes stay 404
- presets / genres / library cycle / clear-data confirmation
"""
from __future__ import annotations

import base64
import io
import json
import urllib.request
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from imagegen_engine import gen_service, plugin_api, store
from imagegen_engine.capabilities import CAPABILITY_KEYS

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 32


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the store under tmp_path; every store path derives from ``data_dir``."""
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def client(isolated_store: Path) -> TestClient:
    app = FastAPI()
    app.include_router(plugin_api.router)
    with TestClient(app) as test_client:
        yield test_client


def _seed_feed() -> None:
    store.add_history({
        "id": "h-apple",
        "kind": "generate",
        "provider": "fal",
        "model": "fal-ai/flux",
        "prompt": "red apple on a wooden table",
        "images": ["/api/plugins/imagegen/cache/a.png"],
        "gallery_ids": [],
        "ts": 3000,
    })
    store.save_gallery_entry(_PNG_BYTES, {
        "id": "g-sky",
        "ts": 1000,
        "prompt": "blue sky with clouds",
        "provider": "krea",
        "model": "krea-v1",
    })


# ---------------------------------------------------------------------------
# Health / Catalog
# ---------------------------------------------------------------------------


def test_health_returns_expected_shape(client: TestClient) -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["plugin"] == "imagegen"
    assert isinstance(body["providers"], list)
    assert len(body["providers"]) >= 1


def test_providers_models_carry_stable_derived_capabilities(client: TestClient) -> None:
    """Regression: capabilities must never come back all-false or contradictory.

    Every model must expose the full stable capability shape and
    ``referenceImages`` MUST equal ``maxReferences > 0`` (the old bug shipped
    ``referenceImages: False`` for every model regardless of the catalog).
    """
    resp = client.get("/providers")
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    names = {p["name"] for p in providers}
    # nous is listed only when Hermes registers it; ImageGen adds no Nous entry itself.
    assert {"fal", "magnific", "vertex"} <= names

    model_count = 0
    for provider in providers:
        for model in provider.get("models") or []:
            model_count += 1
            label = f"{provider['name']}/{model.get('id')}"
            caps = model.get("capabilities")
            assert caps is not None, f"{label}: missing capabilities"
            for key in CAPABILITY_KEYS:
                assert key in caps, f"{label}: missing capability {key}"
            assert isinstance(caps["maxReferences"], int) and caps["maxReferences"] >= 0
            assert isinstance(caps["referenceImages"], bool)
            assert caps["referenceImages"] == (caps["maxReferences"] > 0), (
                f"{label}: referenceImages={caps['referenceImages']} "
                f"contradicts maxReferences={caps['maxReferences']}"
            )
    assert model_count > 0, "providers catalog must expose at least one model"

    vertex = next(p for p in providers if p["name"] == "vertex")
    nano_banana = next(m for m in vertex["models"] if m.get("id") == "gemini-nano-banana-2.1")
    assert nano_banana["capabilities"]["maxReferences"] == 14
    assert nano_banana["capabilities"]["referenceImages"] is True


def test_providers_status_counts_a_linked_subscription_as_configured(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from imagegen_engine.routes import system

    monkeypatch.setattr(system, "_list_providers", lambda: [
        {"name": "openai-codex", "available": True},
        {"name": "openai", "available": False},
    ])
    status = {row["name"]: row["configured"] for row in client.get("/providers/status").json()["providers"]}
    assert status == {"openai-codex": True, "openai": False}


def test_providers_status_never_leaks_secrets(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    secret = "sk-test-imagegen-secret-1234567890"
    monkeypatch.setenv("FAL_KEY", secret)
    resp = client.get("/providers/status")
    assert resp.status_code == 200
    providers = resp.json()["providers"]
    assert isinstance(providers, list) and len(providers) >= 1

    text = json.dumps(providers)
    assert secret not in text
    assert not re.search(r"sk-[A-Za-z0-9]{12,}", text)

    for entry in providers:
        assert {"name", "display_name", "configured", "available"} <= set(entry)
        assert isinstance(entry["configured"], bool)
        assert isinstance(entry["available"], bool)
        assert not any(re.search(r"key|token|secret", str(key), re.IGNORECASE) for key in entry)


# ---------------------------------------------------------------------------
# Feed
# ---------------------------------------------------------------------------


def test_feed_returns_items_and_stats(client: TestClient) -> None:
    _seed_feed()
    resp = client.get("/feed")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["items"], list)
    assert len(body["items"]) == 2
    stats = body["stats"]
    assert {"total", "saved", "generated", "bytes"} <= set(stats)
    assert stats["total"] == 2
    assert stats["generated"] == 1
    assert stats["saved"] == 1
    sources = {item["source"] for item in body["items"]}
    assert sources == {"generated", "saved"}


def test_feed_filters_by_source(client: TestClient) -> None:
    _seed_feed()
    generated = client.get("/feed", params={"source": "generated"}).json()["items"]
    assert [item["id"] for item in generated] == ["h-apple"]
    saved = client.get("/feed", params={"source": "saved"}).json()["items"]
    assert [item["id"] for item in saved] == ["g-sky"]


def test_feed_filters_by_provider_and_query(client: TestClient) -> None:
    _seed_feed()
    by_provider = client.get("/feed", params={"provider": "krea"}).json()["items"]
    assert [item["id"] for item in by_provider] == ["g-sky"]
    by_query = client.get("/feed", params={"q": "apple"}).json()["items"]
    assert [item["id"] for item in by_query] == ["h-apple"]
    case_insensitive = client.get("/feed", params={"q": "BLUE"}).json()["items"]
    assert [item["id"] for item in case_insensitive] == ["g-sky"]
    no_match = client.get("/feed", params={"q": "no-such-prompt"}).json()["items"]
    assert no_match == []


def test_feed_delete_is_idempotent(client: TestClient) -> None:
    _seed_feed()
    first = client.delete("/feed/h-apple")
    assert first.status_code == 200
    assert first.json()["ok"] is True
    assert first.json()["removed"] == 0  # h-apple owns no gallery files

    again = client.delete("/feed/h-apple")
    assert again.status_code == 200
    assert again.json()["ok"] is True
    assert again.json()["removed"] == 0

    unknown = client.delete("/feed/never-existed")
    assert unknown.status_code == 200
    assert unknown.json()["ok"] is True
    assert unknown.json()["removed"] == 0


def test_feed_delete_rejects_traversal_id(client: TestClient) -> None:
    resp = client.delete("/feed/..%2F..%2Fetc%2Fpasswd")
    assert resp.status_code in (400, 404)
    assert resp.status_code != 200
    if resp.status_code == 400:
        body = resp.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "bad_request"


# ---------------------------------------------------------------------------
# Upload / reference serving
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data_url", "expected_ext", "expected_media"),
    [
        (
            f"data:image/jpeg;base64,{base64.b64encode(_JPEG_BYTES).decode()}",
            ".jpg",
            "image/jpeg",
        ),
        (
            f"data:image/png;base64,{base64.b64encode(_PNG_BYTES).decode()}",
            ".png",
            "image/png",
        ),
    ],
)
def test_upload_writes_real_extension_and_serves_with_media_type(
    client: TestClient, isolated_store: Path, data_url: str, expected_ext: str, expected_media: str
) -> None:
    """Regression: upload must store real bytes with the real extension and
    serve them back with the matching Content-Type (not a generic image/png)."""
    resp = client.post("/upload", json={"image": data_url})
    assert resp.status_code == 200
    body = resp.json()
    name = body["name"]
    assert name.endswith(expected_ext)
    stored = store.refs_dir() / name
    assert stored.is_file()
    assert stored.read_bytes() == (base64.b64decode(data_url.split(",", 1)[1]))

    served = client.get(f"/refs/{name}")
    assert served.status_code == 200
    assert served.headers["content-type"].startswith(expected_media)


def test_refs_traversal_never_serves_outside_content(client: TestClient, isolated_store: Path) -> None:
    data_url = f"data:image/png;base64,{base64.b64encode(_PNG_BYTES).decode()}"
    name = client.post("/upload", json={"image": data_url}).json()["name"]
    # A decoy with the SAME name as the stored ref, placed OUTSIDE the data
    # dir: if a traversal ever escaped, the route would serve this decoy.
    outside = isolated_store.parent / name
    outside.write_text("TOP-SECRET-OUTSIDE")

    # The direct path serves the real refs copy, never the outside decoy.
    direct = client.get(f"/refs/{name}")
    assert direct.status_code == 200
    assert "TOP-SECRET-OUTSIDE" not in direct.text

    # Traversal variants never resolve to the outside decoy.
    for url in (f"/refs/..%2F{name}", f"/refs/../{name}"):
        resp = client.get(url)
        assert resp.status_code in (400, 404)
        assert "TOP-SECRET-OUTSIDE" not in resp.text


@pytest.mark.parametrize(
    "url",
    [
        "/refs/..%2Fsecret.txt",
        "/refs/..%2F..%2Fetc%2Fpasswd",
        "/gallery/file/..%2Fsecret.txt",
        "/gallery/file/..%2F..%2Fetc%2Fpasswd",
    ],
)
def test_file_routes_reject_traversal(client: TestClient, isolated_store: Path, url: str) -> None:
    outside = isolated_store.parent / "secret.txt"
    outside.write_text("TOP-SECRET-OUTSIDE")
    resp = client.get(url)
    assert resp.status_code in (400, 404)
    assert "TOP-SECRET-OUTSIDE" not in resp.text


def test_gallery_image_reaches_the_ui_inline_and_nothing_else_does(client: TestClient, isolated_store: Path) -> None:
    """The Desktop guards plugin URLs, so the chat card and Edit tab read gallery images inline."""
    import base64
    from urllib.parse import urlsplit

    store.save_gallery_entry(_PNG_BYTES, {"id": "g-1", "ts": 1, "prompt": "p"})
    item = client.get("/gallery/item/g-1").json()
    assert Path(item["localPath"]).is_file()
    served = urlsplit(item["url"]).path  # the Desktop sends http://127.0.0.1:<port>/...
    data_url = client.get("/media/data-url", params={"url": served}).json()["dataUrl"]
    assert data_url.startswith("data:image/png;base64,")
    assert base64.b64decode(data_url.split(",", 1)[1]) == _PNG_BYTES

    outside = isolated_store.parent / "secret.txt"
    outside.write_text("TOP-SECRET-OUTSIDE")
    for url in (str(outside), outside.as_uri(), "/api/plugins/imagegen/gallery/file/..%2Fsecret.txt"):
        resp = client.get("/media/data-url", params={"url": url})
        assert resp.status_code in (400, 404)
        assert "TOP-SECRET-OUTSIDE" not in resp.text


# ---------------------------------------------------------------------------
# Error envelope / retired routes
# ---------------------------------------------------------------------------


def test_404_error_uses_structured_envelope(client: TestClient) -> None:
    resp = client.get("/jobs/does-not-exist-xyz")
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"
    assert isinstance(body["error"]["message"], str) and body["error"]["message"]


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("post", "/scene-variations"),
        ("post", "/generate/refined"),
        ("get", "/refs/x/preview"),
        ("post", "/gallery/x/to-ref"),
    ],
)
def test_retired_routes_still_404(client: TestClient, method: str, url: str) -> None:
    resp = client.request(method, url)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------


def test_jobs_list_returns_200_with_list(client: TestClient) -> None:
    resp = client.get("/jobs")
    assert resp.status_code == 200
    assert isinstance(resp.json()["jobs"], list)


def test_jobs_get_missing_returns_structured_404(client: TestClient) -> None:
    resp = client.get("/jobs/nope-123")
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"


def test_jobs_cancel_missing_returns_structured_404(client: TestClient) -> None:
    resp = client.post("/jobs/nope-123/cancel")
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"


def test_jobs_cancel_terminal_returns_ok_false(client: TestClient) -> None:
    """Cancel on an existing but already-terminal job is a no-op, not a 404."""
    from imagegen_engine import jobs

    job = jobs.manager.submit("generate", lambda j: {"images": []})
    job.thread.join(timeout=5)
    assert job.status == "completed"
    resp = client.post(f"/jobs/{job.id}/cancel")
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_jobs_retry_missing_returns_structured_404(client: TestClient) -> None:
    resp = client.post("/jobs/nope-123/retry")
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "not_found"


def test_jobs_resume_missing_returns_structured_404(client: TestClient) -> None:
    resp = client.post("/jobs/nope-123/resume")
    assert resp.status_code == 404
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "job.not_found"


# ---------------------------------------------------------------------------
# Presets / Genres
# ---------------------------------------------------------------------------


def test_presets_nonempty(client: TestClient) -> None:
    resp = client.get("/presets")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body.get("styles"), list) and len(body["styles"]) >= 1
    assert isinstance(body.get("aspect_ratios"), list) and len(body["aspect_ratios"]) >= 1


def test_genres_nonempty(client: TestClient) -> None:
    resp = client.get("/genres")
    assert resp.status_code == 200
    genres = resp.json()["genres"]
    assert isinstance(genres, list) and len(genres) >= 1


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------


def test_library_full_cycle(client: TestClient) -> None:
    empty = client.get("/library")
    assert empty.status_code == 200
    assert empty.json()["entries"] == []

    saved = client.post(
        "/library",
        json={"name": "Red chair", "prompt": "a red chair on white background", "genre": "ad_product"},
    )
    assert saved.status_code == 200
    item = saved.json()
    assert item["prompt"] == "a red chair on white background"
    assert item["name"] == "Red chair"
    entry_id = item["id"]

    listed = client.get("/library").json()["entries"]
    assert [e["id"] for e in listed] == [entry_id]

    removed = client.delete(f"/library/{entry_id}")
    assert removed.status_code == 200
    assert removed.json()["ok"] is True
    assert client.get("/library").json()["entries"] == []


def test_library_requires_prompt(client: TestClient) -> None:
    resp = client.post("/library", json={"name": "no prompt"})
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "bad_request"


# ---------------------------------------------------------------------------
# Clear data
# ---------------------------------------------------------------------------


def test_clear_data_requires_confirmation(client: TestClient) -> None:
    resp = client.post("/settings/clear-data", json={})
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "bad_request"


def test_clear_data_with_confirmation_deletes_gallery(client: TestClient) -> None:
    store.save_gallery_entry(_PNG_BYTES, {"id": "g-1", "ts": 1, "prompt": "p"})
    resp = client.post("/settings/clear-data", json={"confirm": "CLEAR", "gallery": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["deleted"]["gallery"] == 1
    assert store.gallery_list() == []


# ---------------------------------------------------------------------------
# Reference contract: upload → generation with references
# ---------------------------------------------------------------------------


def test_reference_upload_flows_into_generation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, host_catalog: None,
) -> None:
    """The full reference path works end to end: POST /upload persists the
    bytes, POST /generate publishes them to FAL, and the edit endpoint
    receives exactly the uploaded references (regression for 'references
    don't work when added')."""
    png_data_url = "data:image/png;base64," + base64.b64encode(_PNG_BYTES).decode()
    resp = client.post("/upload", json={"image": png_data_url, "name": "ref.png"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"], "upload must persist a local path"
    assert Path(body["path"]).is_file()

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        gen_service,
        "fal_upload_image",
        lambda ref, filename: f"https://fal.media/{filename}",
    )

    def fake_urlopen(req, timeout=None):
        calls.append((req.full_url.removeprefix("https://queue.fal.run/"), json.loads(req.data)))
        return io.BytesIO(json.dumps({"images": [{"url": "https://cdn.example/out.png"}]}).encode())

    monkeypatch.setenv("FAL_KEY", "test-key")
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    resp = client.post("/generate", json={
        "provider": "fal",
        "model": "fal-ai/flux-2-pro",
        "prompt": "a red bicycle in a studio",
        "aspectRatio": "4:5",
        "referenceImages": [body["path"]],
        "saveToGallery": False,
    })
    assert resp.status_code == 200
    result = resp.json()
    assert result["references_used"] == 1
    assert result["modality"] == "image"
    assert result["images"] == ["https://cdn.example/out.png"]

    assert calls, "the edit endpoint must receive the generation"
    endpoint, payload = calls[0]
    assert endpoint == "fal-ai/flux-2-pro/edit"
    assert payload["image_urls"] == ["https://fal.media/reference-1.png"]
