"""Desktop batch contract: persisted receipts, per-line prompts and safe retries."""
import time
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from imagegen_engine import operations, store
from imagegen_engine.routes import batches


def test_batch_reopens_and_retries_only_the_failed_item(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    calls = []

    def build(kind, body):
        def generate(job):
            calls.append(body.copy())
            if body["prompt"] == "Umbrella" and not body["clientRequestId"].startswith("retry-"):
                raise RuntimeError("fixture unavailable")
            return {"images": [f"/api/plugins/imagegen/gallery/file/{job.id}.png"]}
        return generate

    monkeypatch.setattr(batches, "build_operation", build)
    monkeypatch.setattr(operations, "build_operation", build)
    app = FastAPI()
    app.include_router(batches.router)
    client = TestClient(app)
    batch_id = str(uuid4())
    body = {"id": batch_id, "prompts": ["Red scooter", "Umbrella"], "settings": {
        "provider": "test", "model": "fixture", "referenceImages": ["ref.png"],
        "config": {"description": "Old description", "compositionIntent": {"userIntent": "Old intent"}},
    }}

    def finished():
        for _ in range(150):
            rows = client.get("/batches/latest").json()["batch"]["items"]
            if all(row["status"] not in batches.ACTIVE for row in rows):
                return rows
            time.sleep(0.02)
        raise AssertionError("batch did not finish")

    assert client.post("/batches", json={**body, "prompts": ["test"] * 33}).status_code == 400
    assert client.post("/batches", json=body).status_code == 200
    first, failed = finished()
    assert first["image"] and failed["retryable"]
    assert client.post("/batches", json=body).status_code == 200
    assert client.post("/batches", json={**body, "prompts": ["Wrong"]}).status_code == 409
    assert len(calls) == 2
    url = f"/batches/{batch_id}/items/1/retry"
    for _ in range(2):
        assert client.post(url, json={"jobId": failed["id"]}).status_code == 200
    final = finished()
    assert [row["status"] for row in final] == ["completed", "completed"]
    assert final[0]["id"] == first["id"] and final[1]["id"] != failed["id"]
    assert sorted(call["prompt"] for call in calls) == ["Red scooter", "Umbrella", "Umbrella"]
    assert all(call["config"]["description"] == call["prompt"] and call["config"]["compositionIntent"] is None
               and call["numImages"] == 1 and call["saveToGallery"] and call["referenceImages"] == ["ref.png"] for call in calls)
