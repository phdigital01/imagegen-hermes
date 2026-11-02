"""Storage contract tests for the ImageGen backend."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from imagegen_engine import store
from imagegen_engine.gen_service import retry_transient

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _png(tag: bytes) -> bytes:
    """Minimal payload that passes the gallery's image-signature check."""
    return _PNG_MAGIC + tag


@pytest.fixture
def isolated_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path


def test_history_is_capped(isolated_store: Path) -> None:
    for index in range(store.HISTORY_CAP + 5):
        store.add_history({"prompt": f"prompt-{index}"})

    entries = store.get_history(store.HISTORY_CAP + 10)
    assert len(entries) == store.HISTORY_CAP
    assert entries[0]["prompt"] == f"prompt-{store.HISTORY_CAP + 4}"


def test_gallery_prunes_old_files_and_metadata(isolated_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(store, "GALLERY_CAP", 2)
    for index in range(3):
        entry = store.save_gallery_entry(_png(f"image-{index}".encode()), {"ts": index, "prompt": str(index)})
        assert (store.gallery_dir() / entry["file"]).exists()

    records = list((store.gallery_dir() / ".meta").glob("*.json"))
    images = [path for path in store.gallery_dir().glob("*.png") if path.is_file()]
    assert len(records) == 2
    assert len(images) == 2
    prompts = {json.loads(path.read_text(encoding="utf-8"))["prompt"] for path in records}
    assert prompts == {"1", "2"}


def test_retry_transient_retries_only_transient_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    sleeps: list[float] = []

    def flaky_operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise OSError("temporary network failure")
        return "ok"

    monkeypatch.setattr("imagegen_engine.gen_service.time.sleep", sleeps.append)
    assert retry_transient(flaky_operation, label="test", base_delay=0.01) == "ok"
    assert calls == 3
    assert sleeps == [0.01, 0.02]

    calls = 0

    def invalid_operation() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("invalid payload")

    with pytest.raises(ValueError):
        retry_transient(invalid_operation, label="test")
    assert calls == 1


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("image.png", "image/png"),
        ("image.jpg", "image/jpeg"),
        ("image.webp", "image/webp"),
    ],
)
def test_image_media_type_matches_extension(filename: str, expected: str) -> None:
    assert store.image_media_type(filename) == expected


@pytest.mark.parametrize(
    "entry_id",
    ["../settings.json", "..", ".", "a/b", "a\\b", "a..b/../x", ""],
)
def test_safe_entry_id_rejects_traversal(isolated_store: Path, entry_id: str) -> None:
    with pytest.raises(ValueError):
        store._safe_entry_id(entry_id)


def test_handoff_id_rejects_traversal(isolated_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    handoffs = isolated_store / "handoffs"
    monkeypatch.setattr(store, "handoffs_dir", lambda: handoffs)
    monkeypatch.setattr(store, "handoff_last_file", lambda: handoffs / "last.json")
    with pytest.raises(ValueError):
        store.save_handoff({"generationId": "../../outside"})
    with pytest.raises(ValueError):
        store.get_handoff("../last")
    assert store.get_handoff("gen-ok") is None


def test_gallery_metadata_rejects_traversal(isolated_store: Path) -> None:
    with pytest.raises(ValueError):
        store.gallery_metadata("../../settings.json")


def test_handoffs_are_capped(isolated_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    handoffs = isolated_store / "handoffs"
    monkeypatch.setattr(store, "handoffs_dir", lambda: handoffs)
    monkeypatch.setattr(store, "handoff_last_file", lambda: handoffs / "last.json")
    for index in range(5):
        store.save_handoff({"generationId": f"gen-{index}", "prompt": str(index)})
    # Distinct mtimes so pruning is deterministic (same-second writes tie).
    for index in range(5):
        os.utime(handoffs / f"gen-{index}.json", ns=(0, (index + 1) * 1_000_000_000))
    store._prune_handoffs(3)
    files = [p for p in handoffs.glob("*.json") if p.name != "last.json"]
    assert len(files) == 3
    names = sorted(p.stem for p in files)
    assert names == ["gen-2", "gen-3", "gen-4"]


def test_exports_are_capped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    gallery = tmp_path / "gallery"
    meta = gallery / ".meta"
    exports = tmp_path / "exports"
    gallery.mkdir()
    meta.mkdir()
    monkeypatch.setattr(store, "gallery_dir", lambda: gallery)
    monkeypatch.setattr(store, "export_dir", lambda: exports)
    (gallery / "img.png").write_bytes(b"png")
    for index, entry_id in enumerate(("one", "two", "three")):
        (meta / f"{entry_id}.json").write_text(json.dumps({"id": entry_id, "file": "img.png"}))
        store.export_gallery_pack(entry_id)
        os.utime(exports / f"imagegen-{entry_id}.zip", ns=(0, (index + 1) * 1_000_000_000))
    store._prune_exports(2)
    zips = sorted(p.stem for p in exports.glob("*.zip"))
    assert zips == ["imagegen-three", "imagegen-two"]


def test_fetch_image_bytes_rejects_non_https(isolated_store: Path) -> None:
    with pytest.raises(RuntimeError, match="https"):
        store.fetch_image_bytes("http://example.com/image.png")


def test_fetch_image_bytes_rejects_private_host(isolated_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host, port, **_):
        return [(2, 1, 6, "", ("169.254.169.254", port))]

    import socket
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(RuntimeError, match="non-public"):
        store.fetch_image_bytes("https://metadata.internal/image.png")


def test_fetch_image_bytes_rejects_local_path_outside_roots(isolated_store: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    outside = isolated_store.parent / "secret.txt"
    outside.write_text("secret")
    with pytest.raises(RuntimeError, match="outside the allowed directories"):
        store.fetch_image_bytes(str(outside))


def test_fetch_image_bytes_accepts_data_url(isolated_store: Path) -> None:
    import base64
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    assert store.fetch_image_bytes(f"data:image/png;base64,{base64.b64encode(png).decode()}") == png


def test_fetch_image_bytes_rejects_non_image_payload(isolated_store: Path) -> None:
    import base64
    with pytest.raises(RuntimeError, match="not a valid image"):
        store.fetch_image_bytes(f"data:text/plain;base64,{base64.b64encode(b'not an image').decode()}")


def test_gallery_list_sorts_by_ts_not_filename(isolated_store: Path) -> None:
    # Entry ids are random, so ordering must come from the timestamp, never
    # from the metadata filename (which would be arbitrary).
    store.save_gallery_entry(_png(b"one"), {"id": "z-first", "ts": 1000, "prompt": "old"})
    store.save_gallery_entry(_png(b"two"), {"id": "a-second", "ts": 2000, "prompt": "new"})

    entries = store.gallery_list()
    assert [e["id"] for e in entries] == ["a-second", "z-first"]


def test_delete_gallery_entry_strips_history_references(isolated_store: Path) -> None:
    first = store.save_gallery_entry(_png(b"one"), {"id": "g-1", "ts": 1, "prompt": "one"})
    second = store.save_gallery_entry(_png(b"two"), {"id": "g-2", "ts": 2, "prompt": "two"})
    store.add_history({
        "id": "h-multi",
        "ts": 10,
        "kind": "generate",
        "provider": "fal",
        "model": "m",
        "prompt": "multi",
        "images": ["https://a/img1.png", "https://a/img2.png"],
        "gallery_ids": ["g-1", "g-2"],
        "gallery_entries": [
            {"id": "g-1", "localPath": first["localPath"]},
            {"id": "g-2", "localPath": second["localPath"]},
        ],
    })

    store.delete_gallery_entry("g-1")

    # No dangling references: the parallel arrays stay aligned by index.
    entry = store.get_history(10)[0]
    assert entry["gallery_ids"] == ["g-2"]
    assert [ge["id"] for ge in entry["gallery_entries"]] == ["g-2"]
    assert entry["images"] == ["https://a/img2.png"]
    assert not (store.gallery_dir() / first["file"]).exists()
    assert (store.gallery_dir() / second["file"]).exists()


def test_feed_delete_cascades_history_and_gallery(isolated_store: Path) -> None:
    saved = store.save_gallery_entry(_png(b"orphan"), {"id": "g-orphan", "ts": 5, "prompt": "orphan", "provider": "fal", "model": "m"})
    owned = store.save_gallery_entry(_png(b"owned"), {"id": "g-owned", "ts": 10, "prompt": "owned", "provider": "fal", "model": "m"})
    store.add_history({
        "id": "h1",
        "ts": 100,
        "kind": "generate",
        "provider": "fal",
        "model": "m",
        "prompt": "owned",
        "images": ["/api/plugins/imagegen/cache/x.png?p=C%3A%5Cx.png"],
        "gallery_ids": ["g-owned"],
        "gallery_entries": [{"id": "g-owned", "localPath": owned["localPath"]}],
    })
    store.add_history({
        "id": "h2",
        "ts": 200,
        "kind": "generate",
        "provider": "fal",
        "model": "m",
        "prompt": "no gallery",
        "images": ["https://fal.media/out.png"],
        "gallery_ids": [],
        "gallery_entries": [],
    })

    # Deleting a generated entry removes the history row and its gallery files.
    assert store.feed_delete("h1") == 1
    assert [h["id"] for h in store.get_history(50)] == ["h2"]
    assert not (store.gallery_dir() / owned["file"]).exists()
    assert not (store.gallery_dir() / ".meta" / "g-owned.json").exists()

    items = store.feed_list()
    pairs = [(item["id"], item["source"]) for item in items]
    assert ("h2", "generated") in pairs
    assert ("g-orphan", "saved") in pairs
    assert "g-owned" not in [item["id"] for item in items]
    # No orphaned gallery references: every image either has no galleryId or a
    # live one, and no localPath points at the deleted file.
    for item in items:
        for image in item["images"]:
            assert image["galleryId"] != "g-owned"
            assert str(image.get("localPath") or "") != owned["localPath"]

    # Idempotent: deleting again removes nothing.
    assert store.feed_delete("h1") == 0

    # Deleting a saved-only id cascades to its gallery files.
    assert store.feed_delete("g-orphan") == 1
    assert not (store.gallery_dir() / saved["file"]).exists()
    assert store.feed_delete("g-orphan") == 0


def test_feed_list_filters_source_provider_query(isolated_store: Path) -> None:
    store.save_gallery_entry(_png(b"a"), {"id": "g-a", "ts": 1, "prompt": "product shot", "provider": "krea", "model": "m1"})
    store.add_history({
        "id": "h-a",
        "ts": 2,
        "kind": "edit",
        "provider": "fal",
        "model": "m2",
        "prompt": "sunset edit",
        "images": ["https://fal.media/sunset.png"],
        "gallery_ids": [],
        "gallery_entries": [],
        "config": {"referencesV4": [{"id": "ref-1"}], "strength": 0.7},
    })

    assert [item["id"] for item in store.feed_list(source="generated")] == ["h-a"]
    assert [item["id"] for item in store.feed_list(source="saved")] == ["g-a"]
    assert [item["id"] for item in store.feed_list(provider="fal")] == ["h-a"]
    assert [item["id"] for item in store.feed_list(query="SUNSET")] == ["h-a"]
    assert store.feed_list(query="nothing") == []

    # Config snapshot keeps referencesV4.
    item = store.feed_list(source="generated")[0]
    assert item["config"]["referencesV4"] == [{"id": "ref-1"}]
    assert item["kind"] == "edit"

    stats = store.feed_stats()
    assert stats["total"] == 2
    assert stats["generated"] == 1
    assert stats["saved"] == 1


def test_add_history_concurrent_writes_keep_both(isolated_store: Path) -> None:
    import threading

    barrier = threading.Barrier(2)

    def worker(label: str) -> None:
        barrier.wait()
        store.add_history({"prompt": label})

    threads = [threading.Thread(target=worker, args=(f"p{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    entries = store.get_history(10)
    assert len(entries) == 2
    assert {e["prompt"] for e in entries} == {"p0", "p1"}


def test_corrupt_json_is_quarantined_not_overwritten(isolated_store: Path, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    history = store.history_file()
    history.write_text("{ definitely not json !!!", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="imagegen_engine.store"):
        entries = store.get_history(10)

    assert entries == []
    corrupt = [p for p in isolated_store.glob("history.json.corrupt-*")]
    assert len(corrupt) == 1
    assert corrupt[0].read_text(encoding="utf-8") == "{ definitely not json !!!"
    assert any("Corrupt JSON" in record.message for record in caplog.records)

    # The corrupted file is out of the way: a write afterwards creates a clean
    # file instead of overwriting the (still recoverable) broken one.
    store.add_history({"prompt": "ok"})
    assert store.get_history(10)[0]["prompt"] == "ok"
    assert corrupt[0].exists()


def test_output_folder_persists_and_exports_gallery_entry(isolated_store: Path) -> None:
    export_dir = isolated_store / "exports"
    assert store.set_output_dir(str(export_dir)) == export_dir.resolve()
    assert store.output_dir_status() == {
        "path": str(export_dir.resolve()),
        "exists": True,
        "writable": True,
    }

    entry = store.save_gallery_entry(_png(b"image"), {"id": "export-test", "prompt": "test"})
    exported = store.export_gallery_entry(entry)

    assert exported == str(export_dir.resolve() / "imagegen-export-test.png")
    assert Path(exported).read_bytes() == _png(b"image")


def test_output_folder_rejects_relative_path(isolated_store: Path) -> None:
    with pytest.raises(ValueError, match="must be an absolute path"):
        store.set_output_dir("relative/output")
