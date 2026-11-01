"""Persistence contract tests for the async job manager.

Covers the data/jobs.json store (upsert, orphan conversion, cap/pruning),
job checkpointing (``Job.set_remote``), restart hydration (the jobs module
import), and the resume lifecycle. Every store path is redirected to
``tmp_path`` so no test touches real user data or the network.
"""
from __future__ import annotations

import importlib
import threading
from pathlib import Path

import pytest

from dashboard import jobs, store
from dashboard.errors import JOB_INTERRUPTED

_RECORD_KEYS = {
    "id", "kind", "status", "created", "started", "finished", "message",
    "error", "errorCode", "errorParams", "payload", "remote", "remotes",
    "result", "progress", "ownerPid", "clientRequestId", "cancelRequested",
}


@pytest.fixture
def isolated_job_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the store at tmp_path and make the job file deterministic."""
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "JOBS_FILE", tmp_path / "jobs.json")
    store._ensure()
    return tmp_path


def _reload_jobs():
    """Re-import the jobs module so import-time hydration sees current state."""
    return importlib.reload(jobs)


# ---------------------------------------------------------------------------
# Persistence on transitions
# ---------------------------------------------------------------------------


def test_submit_persists_record(isolated_job_store: Path) -> None:
    module = _reload_jobs()
    gate = threading.Event()

    def run(job: jobs.Job) -> dict:
        gate.wait(5)
        return {"images": ["https://x/1.png"]}

    job = module.manager.submit("generate", run)
    try:
        # Intermediate transitions are persisted, not just the final state.
        record = next(r for r in store.load_job_records() if r["id"] == job.id)
        assert record["status"] in ("queued", "running")
    finally:
        gate.set()
    job.thread.join(timeout=10)

    record = next(r for r in store.load_job_records() if r["id"] == job.id)
    assert record["status"] == "completed"
    assert record["kind"] == "generate"
    assert record["created"] == job.created
    assert record["finished"] == job.finished
    assert record["remote"] is None
    assert _RECORD_KEYS <= set(record)


def test_failed_job_is_persisted(isolated_job_store: Path) -> None:
    module = _reload_jobs()

    def boom(job: jobs.Job) -> dict:
        raise RuntimeError("kaboom")

    job = module.manager.submit("generate", boom)
    job.thread.join(timeout=10)
    record = next(r for r in store.load_job_records() if r["id"] == job.id)
    assert record["status"] == "failed"
    assert record["error"] == "kaboom"


def test_set_remote_persists_checkpoint(isolated_job_store: Path) -> None:
    module = _reload_jobs()
    job = module.Job("upscale")
    job.set_remote("fal", "fal-ai/magnific", "req-abc123", "fal-ai/magnific")

    entry = store.get_job_record(job.id)
    assert entry is not None
    assert entry["remote"] == {
        "provider": "fal",
        "model": "fal-ai/magnific",
        "requestId": "req-abc123",
        "endpoint": "fal-ai/magnific",
    }
    assert entry["status"] == "queued"
    # The wire shape exposes the checkpoint too.
    assert job.to_dict()["remote"]["requestId"] == "req-abc123"


def test_job_to_record_matches_contract_shape() -> None:
    job = jobs.Job("generate")
    assert set(job.to_record()) == _RECORD_KEYS
    assert job.to_record()["remote"] is None
    assert job.to_record()["payload"] is None


# ---------------------------------------------------------------------------
# Orphan conversion (import-time)
# ---------------------------------------------------------------------------


def test_mark_orphan_converts_running_and_preserves_remote(isolated_job_store: Path) -> None:
    store.save_job_record({
        "id": "orphan-a", "kind": "upscale", "status": "running",
        "created": 1.0, "started": 1.0, "message": "Upscaling (FAL magnific)…",
        "remote": {"provider": "fal", "model": "fal-ai/magnific",
                   "requestId": "req-9", "endpoint": "fal-ai/magnific"},
    })
    store.save_job_record({"id": "orphan-b", "kind": "generate", "status": "queued", "created": 2.0})

    converted = store.mark_orphan_jobs_interrupted()
    assert {r["id"] for r in converted} == {"orphan-a", "orphan-b"}
    # Idempotent: a second call converts nothing.
    assert store.mark_orphan_jobs_interrupted() == []

    records = {r["id"]: r for r in store.load_job_records()}
    assert records["orphan-a"]["status"] == "interrupted"
    assert records["orphan-a"]["errorCode"] == JOB_INTERRUPTED
    assert records["orphan-a"]["remote"]["requestId"] == "req-9"
    assert records["orphan-b"]["status"] == "interrupted"


def test_terminal_records_are_not_converted(isolated_job_store: Path) -> None:
    for status in ("completed", "failed", "cancelled"):
        store.save_job_record({
            "id": f"job-{status}", "kind": "generate", "status": status,
            "created": 1.0, "finished": 2.0,
        })

    assert store.mark_orphan_jobs_interrupted() == []
    records = {r["id"]: r for r in store.load_job_records()}
    assert {r["status"] for r in records.values()} == {"completed", "failed", "cancelled"}


def test_restart_hydration_surfaces_interrupted_jobs(isolated_job_store: Path) -> None:
    store.save_job_record({
        "id": "orphan-1", "kind": "upscale", "status": "running",
        "created": 100.0, "message": "Upscaling (FAL magnific)…",
        "payload": {"image": "x", "kind": "upscale"},
        "remote": {"provider": "fal", "model": "fal-ai/magnific",
                   "requestId": "req-77", "endpoint": "fal-ai/magnific"},
    })
    store.save_job_record({
        "id": "orphan-2", "kind": "generate", "status": "completed",
        "created": 99.0, "finished": 101.0,
    })

    module = _reload_jobs()
    listed = {j["id"]: j for j in module.manager.list()}
    assert "orphan-1" in listed
    assert listed["orphan-1"]["status"] == "interrupted"
    assert listed["orphan-1"]["errorCode"] == JOB_INTERRUPTED
    assert listed["orphan-1"]["remote"]["requestId"] == "req-77"
    # Terminal records stay listed as recent history, never converted.
    assert listed["orphan-2"]["status"] == "completed"

    # resume() hands the route the checkpoint record; everything else is None.
    record = module.manager.resume("orphan-1")
    assert record is not None
    assert record["remote"]["requestId"] == "req-77"
    assert record["payload"] == {"image": "x", "kind": "upscale"}
    assert module.manager.resume("orphan-2") is None
    assert module.manager.resume("missing") is None


def test_resume_then_mark_completed(isolated_job_store: Path) -> None:
    store.save_job_record({
        "id": "orphan-1", "kind": "upscale", "status": "running", "created": 100.0,
        "remote": {"provider": "fal", "model": "m", "requestId": "req-77", "endpoint": "m"},
    })
    module = _reload_jobs()

    assert module.manager.mark_completed("orphan-1", {"images": ["https://x/1.png"]}) is True
    record = store.get_job_record("orphan-1")
    assert record["status"] == "completed"
    assert record["errorCode"] is None
    assert record["error"] is None
    assert module.manager.resume("orphan-1") is None
    assert module.manager.get("orphan-1").to_dict()["status"] == "completed"


# ---------------------------------------------------------------------------
# Cap / pruning
# ---------------------------------------------------------------------------


def test_jobs_file_cap_prunes_oldest_terminal_records(isolated_job_store: Path) -> None:
    assert store.JOBS_CAP == 64
    for index in range(70):
        store.save_job_record({
            "id": f"job-{index:02d}", "kind": "generate", "status": "completed",
            "created": float(index), "finished": float(index) + 1.0,
        })

    records = store.load_job_records()
    assert len(records) == store.JOBS_CAP
    assert sorted(r["id"] for r in records) == [f"job-{index:02d}" for index in range(6, 70)]


def test_jobs_file_cap_never_prunes_active_records(isolated_job_store: Path) -> None:
    for index in range(70):
        store.save_job_record({
            "id": f"terminal-{index:02d}", "kind": "generate", "status": "completed",
            "created": float(index), "finished": float(index) + 1.0,
        })
    for index in range(3):
        store.save_job_record({
            "id": f"active-{index}", "kind": "generate", "status": "running",
            "created": 1000.0 + index,
        })

    records = store.load_job_records()
    assert len(records) == store.JOBS_CAP
    assert {r["id"] for r in records if r["status"] == "running"} == {"active-0", "active-1", "active-2"}


# ---------------------------------------------------------------------------
# Missing / corrupt jobs.json
# ---------------------------------------------------------------------------


def test_missing_jobs_file_does_not_break_import(isolated_job_store: Path) -> None:
    assert not store.JOBS_FILE.exists()
    module = _reload_jobs()
    assert module.manager.list() == []
    assert store.load_job_records() == []


def test_corrupt_jobs_file_does_not_break_import(isolated_job_store: Path) -> None:
    store.JOBS_FILE.write_text("{this is not valid json !!!", encoding="utf-8")
    module = _reload_jobs()
    assert module.manager.list() == []
    # _read_json quarantined the broken file instead of returning it.
    assert not store.JOBS_FILE.exists()
    assert store.load_job_records() == []


def test_hydration_skips_malformed_record_without_breaking_import(isolated_job_store: Path) -> None:
    store.save_job_record({
        "id": "orphan-ok", "kind": "generate", "status": "running", "created": 5.0,
        "remote": {"provider": "fal", "model": "m", "requestId": "req-1", "endpoint": "m"},
    })
    # A hand-edited record with garbage timestamps must not kill the import.
    store.save_job_record({"id": "orphan-bad", "status": "running", "created": "not-a-number"})

    module = _reload_jobs()
    listed = {j["id"]: j for j in module.manager.list()}
    assert "orphan-ok" in listed
    assert "orphan-bad" not in listed


def test_fal_resume_waits_for_a_request_still_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """A job killed right after submit resumes while FAL is still generating (its result answers 400)."""
    import io
    import json as _json
    from urllib.error import HTTPError

    from dashboard import gen_service

    statuses = ["IN_QUEUE", "IN_PROGRESS", "COMPLETED"]
    seen: list[str] = []

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        seen.append(url.rsplit("/", 1)[-1])
        if url.endswith("/status"):
            return io.BytesIO(_json.dumps({"status": statuses.pop(0)}).encode())
        if statuses:  # FAL answers 400 for the result until the request completes
            raise HTTPError(url, 400, "Request is still in progress", {}, None)
        return io.BytesIO(_json.dumps({"images": [{"url": "https://v3.fal.media/x.png"}]}).encode())

    monkeypatch.setenv("FAL_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(gen_service.time, "sleep", lambda _s: None)

    result = gen_service.fal_fetch_result("fal-ai/flux-2-pro", "req-1")
    assert result["images"][0]["url"].endswith("x.png")
    assert seen == ["status", "status", "status", "req-1"]


def test_fal_errors_carry_the_provider_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    """A locked FAL account must say why ("Exhausted balance"), not only "403 Forbidden"."""
    import io
    from urllib.error import HTTPError

    from dashboard import gen_service
    from dashboard.errors import ImageGenError

    def locked(request, timeout=None):
        body = io.BytesIO(b'{"detail":"User is locked. Reason: Exhausted balance."}')
        raise HTTPError(request.full_url, 403, "Forbidden", {}, body)

    monkeypatch.setenv("FAL_KEY", "test-key")
    monkeypatch.setattr("urllib.request.urlopen", locked)
    with pytest.raises(ImageGenError) as caught:
        gen_service.fal_fetch_result("fal-ai/flux-2-pro", "req-1")
    assert "Exhausted balance" in str(caught.value)
    assert "Exhausted balance" in caught.value.params["detail"]
