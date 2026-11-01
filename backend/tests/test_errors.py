"""Tests for the structured error contract (stable codes + params + i18n keys).

Covers the ImageGenError wire shape, the reference-path codes, the job
serialization of errorCode/errorParams, and the contract that every backend
code has a localized key in all four frontend bundles.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

from dashboard import gen_service, jobs
from dashboard.errors import (
    ImageGenError,
    PROVIDER_FAILED,
    REFS_MODEL_UNSUPPORTED,
    REFS_TOO_MANY,
    REFS_UNRESOLVED,
)


def test_imagegen_error_to_dict_roundtrip() -> None:
    err = ImageGenError(
        "refs.too_many",
        "The model 'x' accepts at most 2 reference image(s); you provided 3.",
        model="x",
        max=2,
        provided=3,
    )
    assert err.code == "refs.too_many"
    assert err.params == {"model": "x", "max": 2, "provided": 3}
    assert err.to_dict() == {
        "code": "refs.too_many",
        "message": "The model 'x' accepts at most 2 reference image(s); you provided 3.",
        "params": {"model": "x", "max": 2, "provided": 3},
    }


def test_imagegen_error_str_is_english_fallback() -> None:
    err = ImageGenError(
        "provider.failed", "The provider 'fal' failed: boom", provider="fal", detail="boom"
    )
    assert str(err) == "The provider 'fal' failed: boom"
    # Subclassing RuntimeError keeps existing `except RuntimeError` handlers working.
    assert isinstance(err, RuntimeError)
    assert issubclass(ImageGenError, RuntimeError)


def test_prepare_reference_sources_too_many_carries_counts() -> None:
    with pytest.raises(ImageGenError) as exc_info:
        gen_service.prepare_reference_sources(
            "openai", "gpt-image-2", ["a.png", "b.png", "c.png"], max_refs=2
        )
    assert exc_info.value.code == REFS_TOO_MANY
    assert exc_info.value.params == {"model": "gpt-image-2", "max": 2, "provided": 3}
    assert "3" in str(exc_info.value)
    assert "2" in str(exc_info.value)


def test_prepare_reference_sources_model_unsupported_names_the_model() -> None:
    with pytest.raises(ImageGenError) as exc_info:
        gen_service.prepare_reference_sources("openai", "gpt-image-2", ["a.png"], max_refs=0)
    assert exc_info.value.code == REFS_MODEL_UNSUPPORTED
    assert exc_info.value.params == {"model": "gpt-image-2", "provider": "openai"}
    assert "gpt-image-2" in str(exc_info.value)


def test_prepare_reference_sources_unresolved_names_the_ref(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    from dashboard import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    outside = tmp_path.parent / "outside.png"
    outside.write_bytes(b"x")
    with pytest.raises(ImageGenError) as exc_info:
        gen_service.prepare_reference_sources(
            "openai", "gpt-image-2", [str(outside)], max_refs=16
        )
    assert exc_info.value.code == REFS_UNRESOLVED
    assert str(outside) in exc_info.value.params["ref"]


def test_job_serializes_error_code_and_params() -> None:
    job = jobs.Job("generate")
    job.status = "failed"
    job.error = "boom"
    job.error_code = PROVIDER_FAILED
    job.error_params = {"provider": "fal", "detail": "boom"}
    d = job.to_dict()
    assert d["error"] == "boom"
    assert d["errorCode"] == PROVIDER_FAILED
    assert d["errorParams"] == {"provider": "fal", "detail": "boom"}


def test_job_omits_error_fields_when_absent() -> None:
    d = jobs.Job("generate").to_dict()
    assert "error" not in d
    assert "errorCode" not in d
    assert "errorParams" not in d


def test_generate_route_propagates_structured_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /generate must not mask the real ImageGenError code and message."""
    import asyncio

    from fastapi import HTTPException

    from dashboard.routes import generation as generation_routes

    class _Req:
        base_url = "http://test/"

    def fake_generate(**kwargs):
        raise ImageGenError("refs.too_many", "too many", model="m", max=2, provided=3)

    monkeypatch.setattr(generation_routes.gen_service, "generate_text_to_image", fake_generate)
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(generation_routes.generate(_Req(), {
            "provider": "fal", "model": "m", "prompt": "a red bicycle", "numImages": 1,
        }))
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == {
        "code": "refs.too_many",
        "message": "too many",
        "params": {"model": "m", "max": 2, "provided": 3},
    }


def test_job_manager_captures_imagegen_error() -> None:
    def boom(job):
        raise ImageGenError(
            "refs.too_many", "too many", model="x", max=2, provided=3
        )

    job = jobs.manager.submit("generate", boom)
    deadline = time.time() + 10
    while job.status not in ("completed", "failed", "cancelled") and time.time() < deadline:
        time.sleep(0.02)
    assert job.status == "failed"
    assert job.error_code == "refs.too_many"
    assert job.error_params == {"model": "x", "max": 2, "provided": 3}
    d = job.to_dict()
    assert d["errorCode"] == "refs.too_many"
    assert d["errorParams"] == {"model": "x", "max": 2, "provided": 3}


def _bundle(text: str, lang: str) -> str:
    start = text.index(f"const {lang}: Messages = {{") + len(f"const {lang}: Messages = {{")
    end = text.index("\n}", start)
    return text[start:end]


def test_every_error_code_has_localized_key_in_all_languages() -> None:
    """Contract: backend codes ↔ frontend i18n keys, same placeholders everywhere."""
    from dashboard import errors

    i18n_path = Path(__file__).resolve().parents[2] / "frontend" / "i18n.ts"
    text = i18n_path.read_text(encoding="utf-8")
    codes = sorted(
        value
        for name, value in vars(errors).items()
        if name.isupper() and isinstance(value, str) and "." in value
    )
    assert codes, "no error codes found in dashboard.errors"

    for lang in ("en", "pt", "es", "zh"):
        bundle = _bundle(text, lang)
        for code in codes:
            key_re = re.compile(rf"^\s*['\"]{re.escape(code)}['\"]\s*:", re.M)
            assert key_re.search(bundle), f"code {code!r} missing in the {lang} bundle"
