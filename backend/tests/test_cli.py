"""The terminal entry point: references from any folder, copies that never overwrite, retries."""
from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

import imagegen_cli
from imagegen_engine import gen_service, generation_artifacts, providers_catalog, store
from imagegen_engine.errors import PROVIDER_FAILED, ImageGenError

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    monkeypatch.setattr(store, "data_dir", lambda: root)
    return root


def _fake_job(calls: list, fail_first: int = 0):
    def build(body):
        def run(job):
            calls.append(body)
            if len(calls) <= fail_first:
                raise ImageGenError(PROVIDER_FAILED, "busy", provider=body["provider"], detail="busy")
            image = store.gallery_dir() / f"img-{job.id}.png"
            image.write_bytes(_PNG)
            return {"images": [str(image)], "gallery_ids": [job.id], "provider": body["provider"],
                    "model": body["model"], "references_used": len(body["referenceImages"])}
        return run
    return build


def test_cli_stores_outside_references_and_keeps_earlier_files(
        data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    calls: list = []
    monkeypatch.setattr(generation_artifacts, "build_generation_job", _fake_job(calls))
    monkeypatch.setattr(providers_catalog, "resolve_target", lambda model="": ("openai-codex", "gpt-image-2-high"))
    ref = tmp_path / "client" / "photo.png"
    ref.parent.mkdir()
    ref.write_bytes(_PNG)
    out = tmp_path / "out"
    out.mkdir()
    (out / "hero.png").write_bytes(b"earlier")

    code = imagegen_cli.main(["--prompt", "a pool cover", "--ref", str(ref), "--aspect", "4:5",
                              "--out", str(out), "--name", "hero"])

    assert code == 0
    sent = calls[0]["referenceImages"]
    assert len(sent) == 1 and Path(sent[0]).parent == store.refs_dir()
    assert calls[0]["aspectRatio"] == "4:5" and calls[0]["config"] == {"source": "cli"}
    printed = json.loads(capsys.readouterr().out)
    assert printed["files"] == [str(out / "hero-2.png")]
    assert (out / "hero.png").read_bytes() == b"earlier"
    assert printed["references_used"] == 1


def test_cli_retries_a_provider_failure_only_when_asked(
        data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(imagegen_cli.time, "sleep", lambda seconds: None)
    args = ["--prompt", "a mug", "--provider", "openai-codex", "--model", "gpt-image-2-high", "--out", str(tmp_path)]

    calls: list = []
    monkeypatch.setattr(generation_artifacts, "build_generation_job", _fake_job(calls, fail_first=1))
    assert imagegen_cli.main(args) == 1
    assert "ERROR [provider.failed]" in capsys.readouterr().err

    calls.clear()
    assert imagegen_cli.main([*args, "--retries", "1"]) == 0
    assert len(calls) == 2


def test_batch_skips_finished_jobs_and_a_failed_job_keeps_the_rest_running(
        data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    def build(body):
        def run(job):
            if body["prompt"] == "fail":
                raise ImageGenError(PROVIDER_FAILED, "busy", provider=body["provider"], detail="busy")
            image = store.gallery_dir() / f"img-{job.id}.png"
            image.write_bytes(_PNG)
            return {"images": [str(image)], "provider": body["provider"], "model": body["model"]}
        return run
    monkeypatch.setattr(generation_artifacts, "build_generation_job", build)
    out = tmp_path / "out"
    out.mkdir()
    (out / "done.png").write_bytes(b"earlier")
    batch = tmp_path / "jobs.jsonl"
    batch.write_text("\n".join(json.dumps(job) for job in [
        {"prompt": "a", "name": "done"}, {"prompt": "fail", "name": "bad"}, {"prompt": "b", "name": "new"}]), encoding="utf-8")

    code = imagegen_cli.main(["--batch", str(batch), "--provider", "openai-codex", "--model", "gpt-image-2-high",
                              "--out", str(out), "--workers", "2"])

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert code == 1
    assert {line["name"]: line["status"] for line in lines[:-1]} == {"done": "skipped", "bad": "failed", "new": "ok"}
    assert (lines[-1]["ok"], lines[-1]["skipped"], lines[-1]["failed"]) == (1, 1, 1)
    assert (out / "done.png").read_bytes() == b"earlier" and (out / "new.png").exists()


def test_batch_refuses_a_missing_reference_before_any_generation(tmp_path: Path) -> None:
    batch = tmp_path / "jobs.jsonl"
    batch.write_text(json.dumps({"prompt": "a", "name": "x", "refs": [str(tmp_path / "gone.png")]}), encoding="utf-8")
    with pytest.raises(SystemExit, match="refs.not_found"):
        imagegen_cli.main(["--batch", str(batch), "--provider", "p", "--model", "m", "--out", str(tmp_path)])


def test_prune_survives_a_reference_removed_by_another_process(
        data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    kept = store.refs_dir() / "ref-kept.png"
    kept.write_bytes(_PNG)

    class Vanished(type(kept)):
        def is_file(self, *args, **kwargs) -> bool:
            return True

        def stat(self, *args, **kwargs):
            raise FileNotFoundError(str(self))

    class Listing:
        def exists(self) -> bool:
            return True

        def glob(self, pattern: str) -> list:
            return [Vanished(store.gallery_dir() / "ref-gone.png"), kept]

    monkeypatch.setattr(store, "refs_dir", lambda: Listing())
    store.prune_refs(cap=5)
    assert kept.exists()


def test_written_settings_are_not_repeated() -> None:
    plain = gen_service._with_written_settings("openai-codex", "a mug", "square")
    assert plain.startswith("Use gpt-image-2 at high quality.") and plain.endswith("(1024x1024).")
    own = "Use gpt-image-2 at high quality.\n\na mug\n\nVertical portrait image, 2:3 aspect ratio."
    assert gen_service._with_written_settings("openai-codex", own, "square") == own


def test_cli_lists_providers_and_uses_a_named_provider_default_model(
        data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    providers = [{"name": "nous", "display_name": "Nous Portal", "default_model": "flux-2-pro", "recommended": True,
                  "models": [{"id": "flux-2-pro", "display": "FLUX 2 Pro"}, {"id": "nano-banana-pro"}]}]
    monkeypatch.setattr(providers_catalog, "available_providers", lambda: providers)

    assert imagegen_cli.main(["--list"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"provider": "nous", "name": "Nous Portal", "default_model": "flux-2-pro", "models": 2, "recommended": True}]
    assert imagegen_cli.main(["--list", "nous"]) == 0
    assert [m["model"] for m in json.loads(capsys.readouterr().out)] == ["flux-2-pro", "nano-banana-pro"]

    calls: list = []
    monkeypatch.setattr(generation_artifacts, "build_generation_job", _fake_job(calls))
    assert imagegen_cli.main(["--prompt", "a mug", "--provider", "nous", "--out", str(tmp_path)]) == 0
    assert (calls[0]["provider"], calls[0]["model"]) == ("nous", "flux-2-pro")


def test_replace_overwrites_and_batch_label_reaches_the_ledger(
        data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    from imagegen_engine import billing

    def build(body):
        def run(job):
            billing.run(body["provider"], body["model"], 0.5, lambda: {"success": "fail" not in body["prompt"]})
            if "fail" in body["prompt"]:
                raise ImageGenError(PROVIDER_FAILED, "busy", provider=body["provider"], detail="busy")
            image = store.gallery_dir() / f"img-{body['prompt']}.png"
            image.write_bytes(_PNG)
            return {"images": [str(image)], "gallery_ids": [], "provider": body["provider"], "model": body["model"]}
        return run

    monkeypatch.setattr(generation_artifacts, "build_generation_job", build)
    monkeypatch.setattr(providers_catalog, "resolve_target", lambda model="": ("openai-codex", "gpt-image-2-high"))
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.png").write_bytes(b"earlier")
    jobs = tmp_path / "jobs.jsonl"
    jobs.write_text('\n'.join(json.dumps(job) for job in [
        {"prompt": "one", "name": "a", "label": "client-a"},
        {"prompt": "fail", "name": "b", "label": "client-a"},
        {"prompt": "two", "name": "c"},
    ]), encoding="utf-8")

    code = imagegen_cli.main(["--batch", str(jobs), "--out", str(out), "--replace", "--label", "run", "--workers", "2"])
    capsys.readouterr()

    assert code == 1
    assert (out / "a.png").read_bytes() == _PNG and not (out / "a-2.png").exists()
    assert imagegen_cli.main(["--spend"]) == 0
    report = json.loads(capsys.readouterr().out)
    groups = {group["label"]: group for group in report["labels"]}
    assert groups["client-a"]["images"] == 1 and groups["client-a"]["failed_attempts"] == 1
    assert groups["client-a"]["failed_cost"] == 0.5 and groups["client-a"]["cost"] == 1.0
    assert groups["run"]["images"] == 1 and report["total"] == 1.5


def test_long_references_are_reduced_and_keep_orientation_and_transparency(tmp_path: Path) -> None:
    from PIL import Image

    photo = tmp_path / "photo.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # stored sideways
    Image.new("RGB", (4000, 1000), "white").save(photo, "JPEG", exif=exif)
    cutout = tmp_path / "cutout.png"
    Image.new("RGBA", (3000, 3000), (0, 0, 0, 0)).save(cutout)
    small = tmp_path / "small.png"
    Image.new("RGB", (800, 800), "white").save(small)

    reduced = Image.open(io.BytesIO(imagegen_cli._reference_bytes(photo)))
    assert reduced.size == (512, 2048)
    kept = Image.open(io.BytesIO(imagegen_cli._reference_bytes(cutout)))
    assert kept.format == "PNG" and kept.mode == "RGBA" and kept.size == (2048, 2048)
    assert imagegen_cli._reference_bytes(small) == small.read_bytes()
    assert imagegen_cli._reference_bytes(photo, 0) == photo.read_bytes()
