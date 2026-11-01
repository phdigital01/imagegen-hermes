"""Repeated edits keep the source: pixels outside each changed area never move."""
from __future__ import annotations

import random

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter

from dashboard import edit_merge

_AREAS = [(100, 100, 300, 300), (700, 150, 950, 350), (150, 800, 400, 1100), (700, 850, 950, 1100), (450, 450, 650, 650)]


def _photo() -> Image.Image:
    rng = random.Random(7)
    image = Image.effect_noise((1100, 1300), 40).convert("RGB")
    draw = ImageDraw.Draw(image)
    for _ in range(90):
        x, y = rng.randint(0, 1100), rng.randint(0, 1300)
        draw.ellipse((x, y, x + rng.randint(30, 200), y + rng.randint(30, 200)),
                     fill=tuple(rng.randint(0, 255) for _ in range(3)))
    return image.filter(ImageFilter.GaussianBlur(1))


def _redrawn(image: Image.Image, box=None) -> Image.Image:
    """What a model answers: the whole picture softer and a little brighter, with one area changed."""
    out = image.resize((768, 908), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.8))
    out = ImageEnhance.Brightness(out).enhance(1.02).resize(image.size, Image.LANCZOS)
    if box:
        ImageDraw.Draw(out).rectangle(box, fill=(255, 40, 40))
    return out


def test_five_edits_leave_every_pixel_outside_the_changes_identical() -> None:
    source = _photo()
    current = source
    for box in _AREAS:
        current, report = edit_merge.merge(current, _redrawn(current, box))
        assert report["merged"] is True
    guard = Image.new("L", source.size, 255)
    for left, top, right, bottom in _AREAS:
        ImageDraw.Draw(guard).rectangle((left - 70, top - 70, right + 70, bottom + 70), fill=0)
    outside = ImageChops.multiply(ImageChops.difference(source, current).convert("L"), guard)
    assert outside.getextrema()[1] == 0
    assert current.getpixel((200, 200))[0] > 200


def test_a_painted_area_is_the_only_one_that_changes() -> None:
    source = _photo()
    mask = Image.new("L", source.size, 0)
    ImageDraw.Draw(mask).rectangle((300, 300, 700, 700), fill=255)
    merged, report = edit_merge.merge(source, _redrawn(source, (100, 100, 300, 300)), mask)
    assert report["merged"] is True
    assert merged.crop((0, 0, 250, 250)).tobytes() == source.crop((0, 0, 250, 250)).tobytes()


def test_a_change_to_the_whole_picture_uses_the_whole_answer() -> None:
    source = _photo()
    warmer = Image.merge("RGB", [band.point(lambda v, o=o: min(255, max(0, v + o)))
                                 for band, o in zip(source.split(), (30, 8, -25))])
    merged, report = edit_merge.merge(source, warmer)
    assert report == {"merged": False, "reason": "whole-image", "changedShare": 1.0}
    assert merged.tobytes() == warmer.tobytes()


def test_the_source_is_padded_to_the_providers_shape_without_moving() -> None:
    source = _photo().crop((0, 0, 1040, 1300))
    canvas, box, aspect = edit_merge._pad_to_canvas(source)
    assert aspect == "2:3"
    assert abs(canvas.width / canvas.height - 2 / 3) < 0.01
    assert canvas.crop(box).tobytes() == source.tobytes()


def test_expanding_grows_the_canvas_and_keeps_the_source(monkeypatch, tmp_path):
    source = tmp_path / "source.png"
    photo = _photo().crop((0, 0, 1040, 1300))
    photo.save(source)
    monkeypatch.setattr(edit_merge.store, "fetch_image_bytes", lambda path: open(path, "rb").read())
    monkeypatch.setattr(edit_merge, "_store", lambda image: (image.save(tmp_path / f"{id(image)}.png"), str(tmp_path / f"{id(image)}.png"))[1])

    def answer(reference_images, **_):
        return {"images": [str(_stored_redraw(reference_images[0], tmp_path))]}

    monkeypatch.setattr(edit_merge.gen_service, "generate_text_to_image", answer)
    result = edit_merge.expand_with_provider(str(source), "", "right", 300, "any", "any")
    with Image.open(result["images"][0]) as image:
        assert image.size == (1340, 1300)
        kept = image.convert("RGB").crop((0, 0, 1000, 1300))
    assert ImageChops.difference(kept, photo.crop((0, 0, 1000, 1300))).getbbox() is None


def _stored_redraw(path, folder):
    target = folder / "answer.png"
    with Image.open(path) as image:
        _redrawn(image.convert("RGB")).save(target)
    return target


def test_an_expansion_redrawn_whole_gets_the_source_back(monkeypatch, tmp_path):
    source = tmp_path / "source.png"
    photo = _photo().crop((0, 0, 1000, 800))
    photo.save(source)
    answer = tmp_path / "answer.png"
    _redrawn(photo).resize((1300, 800)).save(answer)
    monkeypatch.setattr(edit_merge.store, "fetch_image_bytes", lambda path, **_: open(path, "rb").read())
    monkeypatch.setattr(edit_merge, "_store", lambda image: (image.save(tmp_path / "kept.png"), str(tmp_path / "kept.png"))[1])
    result = edit_merge.keep_expanded(str(source), {"images": [str(answer)]}, "right", 300)
    with Image.open(result["images"][0]) as image:
        kept = image.convert("RGB").crop((0, 0, 950, 800))
    assert ImageChops.difference(kept, photo.crop((0, 0, 950, 800))).getbbox() is None
