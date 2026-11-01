"""Tests for the spend ledger, the monthly budget, and the /settings/budget routes."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from dashboard import gen_service, plugin_api, store
from dashboard.errors import BUDGET_EXCEEDED, ImageGenError


@pytest.fixture
def isolated_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the spend ledger and settings file at a temp directory."""
    monkeypatch.setattr(store, "SPEND_FILE", tmp_path / "spend.json")
    monkeypatch.setattr(store, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setenv("FAL_KEY", "test-key")
    return tmp_path


def _fake_fal_queue(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Answer FAL queue submissions synchronously, without any network call."""
    import io
    import json
    import urllib.request

    calls: list[str] = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return io.BytesIO(json.dumps({"images": [{"url": "https://cdn.example/x.png"}]}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return calls


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

def test_record_spend_accumulates_and_ignores_null_cost(isolated_budget: Path) -> None:
    store.record_spend("fal", "flux-2-pro", 2, 0.06)
    store.record_spend("fal", "flux-2-pro", 1, None)
    store.record_spend("krea", "krea-v1", 1, 0.0)
    store.record_spend("xai", "grok-imagine", 4, 0.24, job_id="job-7")

    ledger = store._read_json(store.SPEND_FILE, [])
    assert len(ledger) == 2
    assert {entry["provider"] for entry in ledger} == {"fal", "xai"}
    assert sum(entry["cost"] for entry in ledger) == pytest.approx(0.3)
    assert ledger[1]["jobId"] == "job-7"
    assert ledger[1]["numImages"] == 4
    assert store.spend_since(0) == pytest.approx(0.3)


def test_spend_since_filters_by_timestamp(isolated_budget: Path) -> None:
    now = time.time()
    store.record_spend("fal", "m", 1, 1.0)
    store._write_json(store.SPEND_FILE, store._read_json(store.SPEND_FILE, []) + [
        {"ts": now - 100, "provider": "fal", "model": "m", "numImages": 1, "cost": 2.0, "jobId": ""},
    ])
    assert store.spend_since(now - 50) == pytest.approx(1.0)


def test_spend_this_month_ignores_previous_months(isolated_budget: Path) -> None:
    now = time.time()
    month_start = store._month_start_utc(now)
    store._write_json(store.SPEND_FILE, [
        # One second before the current UTC month → must be excluded.
        {"ts": month_start - 1, "provider": "fal", "model": "old", "numImages": 1, "cost": 9.5, "jobId": "old"},
        {"ts": now, "provider": "fal", "model": "now", "numImages": 1, "cost": 0.5, "jobId": "now"},
    ])
    assert store.spend_this_month() == pytest.approx(0.5)


def test_spend_ledger_cap_prunes_only_previous_months(isolated_budget: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "SPEND_CAP", 3)
    old = store._month_start_utc(time.time()) - 100
    store._write_json(store.SPEND_FILE, [
        {"ts": old - 5 + index, "provider": "fal", "model": "m", "numImages": 1, "cost": 1.0, "jobId": f"old{index}"}
        for index in range(5)
    ])
    for index in range(2):
        store.record_spend("fal", "m", 1, 1.0, job_id=f"j{index}")
    ledger = store._read_json(store.SPEND_FILE, [])
    assert [entry["jobId"] for entry in ledger] == ["old4", "j0", "j1"]

    # This month's accounting is never pruned, even past the cap.
    for index in range(2, 5):
        store.record_spend("fal", "m", 1, 1.0, job_id=f"j{index}")
    ledger = store._read_json(store.SPEND_FILE, [])
    assert [entry["jobId"] for entry in ledger] == ["j0", "j1", "j2", "j3", "j4"]


# ---------------------------------------------------------------------------
# Budget settings
# ---------------------------------------------------------------------------

def test_set_budget_rejects_negative_and_non_numeric(isolated_budget: Path) -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        store.set_budget(-1)
    with pytest.raises(ValueError, match="must be a number"):
        store.set_budget("abc")
    assert store.get_budget() == {"monthlyLimit": None}


def test_set_budget_accepts_value_and_none(isolated_budget: Path) -> None:
    assert store.set_budget(25.5) == {"monthlyLimit": 25.5}
    assert store.get_budget() == {"monthlyLimit": 25.5}

    status = store.budget_status()
    assert status["monthlyLimit"] == 25.5
    assert status["spentThisMonth"] == 0.0
    assert status["currency"] == "USD"

    assert store.set_budget(None) == {"monthlyLimit": None}
    assert store.get_budget() == {"monthlyLimit": None}


def test_budget_status_reflects_ledger(isolated_budget: Path) -> None:
    store.set_budget(10)
    store.record_spend("fal", "m", 2, 3.25)
    status = store.budget_status()
    assert status["monthlyLimit"] == 10
    assert status["spentThisMonth"] == pytest.approx(3.25)
    assert status["currency"] == "USD"


# ---------------------------------------------------------------------------
# check_budget enforcement
# ---------------------------------------------------------------------------

def test_check_budget_raises_when_limit_would_be_crossed(isolated_budget: Path) -> None:
    store.set_budget(10)
    store.record_spend("fal", "m", 1, 4.0)
    # 4 + 5 = 9 <= 10 → allowed.
    gen_service.check_budget(5.0)
    # 4 + 7 = 11 > 10 → blocked with the exact params.
    with pytest.raises(ImageGenError) as exc_info:
        gen_service.check_budget(7.0)
    assert exc_info.value.code == BUDGET_EXCEEDED
    assert exc_info.value.params == {"spent": 4.0, "limit": 10.0, "estimate": 7.0}
    assert "10.00" in str(exc_info.value)


def test_check_budget_noop_without_limit_or_estimate(isolated_budget: Path) -> None:
    store.record_spend("fal", "m", 1, 500.0)
    # No limit configured → no-op.
    gen_service.check_budget(100.0)
    # Limit configured but no/zero estimate → no-op.
    store.set_budget(1)
    gen_service.check_budget(None)
    gen_service.check_budget(0)
    store.record_spend("fal", "m", 1, 0.0)


def test_generate_fal_blocks_before_submission_when_budget_exceeded(
    isolated_budget: Path, monkeypatch: pytest.MonkeyPatch, host_catalog: None,
) -> None:
    store.set_budget(0.05)
    calls = _fake_fal_queue(monkeypatch)
    # 2 × $0.03/MP = 0.06 > 0.05 → blocked before any paid submission.
    with pytest.raises(ImageGenError) as exc_info:
        gen_service.generate_text_to_image("fal", "fal-ai/flux-2-pro", "a red bicycle", num_images=2)
    assert exc_info.value.code == BUDGET_EXCEEDED
    assert calls == []


def test_generate_fal_records_spend_after_success(
    isolated_budget: Path, monkeypatch: pytest.MonkeyPatch, host_catalog: None,
) -> None:
    calls = _fake_fal_queue(monkeypatch)
    result = gen_service.generate_text_to_image("fal", "fal-ai/flux-2-pro", "a red bicycle", num_images=2)

    assert len(calls) == 2
    assert result["cost_estimate"] == pytest.approx(0.06)
    # One reservation per submitted image, settled once the queue accepted it.
    ledger = store._read_json(store.SPEND_FILE, [])
    assert [(entry["provider"], entry["model"], entry["status"]) for entry in ledger] == [
        ("fal", "fal-ai/flux-2-pro", "submitted"),
        ("fal", "fal-ai/flux-2-pro", "submitted"),
    ]
    assert [entry["cost"] for entry in ledger] == [pytest.approx(0.03), pytest.approx(0.03)]
    assert store.spend_this_month() == pytest.approx(0.06)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@pytest.fixture
def budget_client(isolated_budget: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(plugin_api.router)
    return TestClient(app)


def test_budget_route_get_post_clear(budget_client) -> None:
    resp = budget_client.get("/settings/budget")
    assert resp.status_code == 200
    assert resp.json() == {
        "monthlyLimit": None,
        "spentThisMonth": 0.0,
        "currency": "USD",
        "estimated": True,
        "unknownCostCount": 0,
        "pendingCount": 0,
    }

    resp = budget_client.post("/settings/budget", json={"monthlyLimit": 50})
    assert resp.status_code == 200
    assert resp.json()["monthlyLimit"] == 50

    store.record_spend("fal", "flux-2-pro", 2, 1.25)
    resp = budget_client.get("/settings/budget")
    assert resp.status_code == 200
    assert resp.json()["monthlyLimit"] == 50
    assert resp.json()["spentThisMonth"] == pytest.approx(1.25)

    resp = budget_client.post("/settings/budget", json={"monthlyLimit": None})
    assert resp.status_code == 200
    assert resp.json()["monthlyLimit"] is None


def test_budget_route_rejects_negative_and_invalid(budget_client) -> None:
    resp = budget_client.post("/settings/budget", json={"monthlyLimit": -5})
    assert resp.status_code == 400
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "bad_request"
    assert "cannot be negative" in body["error"]["message"]

    resp = budget_client.post("/settings/budget", json={"monthlyLimit": "abc"})
    assert resp.status_code == 400
    assert "must be a number" in resp.json()["error"]["message"]

    # Failed writes never change the stored limit.
    assert store.get_budget() == {"monthlyLimit": None}
