"""Edits that keep the image: only the area the model changed goes back over the source.

A model such as GPT Image redraws the whole picture on every edit, so repeated edits soften it.
Here the source goes out without loss, the answer is compared with it, and every pixel outside the
changed area stays exactly the source's. A later edit starts from that result, so nothing outside
its own area is ever redrawn twice.
"""
from __future__ import annotations

import io
import math
from typing import Any, Callable, Dict, List, Optional, Tuple

from dashboard import gen_service, image_input, store

# The sizes GPT Image and other Hermes providers deliver: the source is padded to the nearest one.
_CANVASES = (("2:3", 2 / 3), ("1:1", 1.0), ("3:2", 3 / 2))
_SEND_MAX_SIDE = 2048
_WORK_SIDE = 768
# Above this share the request changed the whole picture, so its answer is used whole.
_WHOLE_IMAGE_SHARE = 0.65
_WHOLE_TONE_SHIFT = 12
_MIN_DIFFERENCE = 22
_RATIO_TOLERANCE = 0.03
_REGION_CONTEXT = 0.45
_REGION_MIN_SIDE = 640
# Reaches into the source, so the new area blends with it instead of meeting it at a hard line.
_EXPAND_OVERLAP = 24

_GLOBAL_PROMPT = ("Edit this image. Change only what the instruction asks. Keep everything else identical: "
                  "composition, framing, people, objects, text, colors, light and grain.\n\nInstruction: {prompt}")
_REGION_PROMPT = ("Edit the first image. The second image is the same picture with the area to change painted in "
                  "magenta; the magenta is only a guide and never appears in the result. Change only that area and "
                  "keep everything else identical.\n\nInstruction: {prompt}")


_EXPAND_PROMPT = ("Continue this picture into the marked area, as if the camera had seen more of the same place: same "
                  "surfaces, light, perspective and style. Add no new main subject. {prompt}")
_RELIGHT_PROMPT = ("Relight this picture. Keep every object, person, position and the framing; change only the light and "
                   "what it does to color and shadows. {prompt}")
_RELIGHT_REFERENCE = "Match the light of the second image."
_STYLE_PROMPT = ("Redraw the first image in the visual style of the second image: its palette, medium, texture and mood. "
                 "Keep the composition, objects and people of the first image; take nothing else from the second. {prompt}")
_CAMERA_PROMPT = ("Show this same scene from another camera position: {view}. Keep every object, person, material and the "
                  "light. Only the point of view changes.")
_SKIN_PROMPT = ("Retouch the skin naturally: even out the tone and soften blemishes, keeping pores and real texture. Same "
                "person, same expression, same hair, clothes and light.")


def _camera_view(horizontal: int, vertical: int, zoom: int) -> str:
    side = horizontal if horizontal <= 180 else horizontal - 360
    parts = [f"moved {abs(side)} degrees to the {'right' if side > 0 else 'left'} around the subject"] if side else []
    if vertical:
        parts.append(f"{abs(vertical)} degrees {'above' if vertical > 0 else 'below'} the original height")
    if zoom != 5:
        parts.append("closer to the subject" if zoom > 5 else "farther from the subject")
    return ", ".join(parts) or "slightly different from the original"


def _load(raw: bytes):
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(raw)) as source:
        image = ImageOps.exif_transpose(source)
        has_alpha = image.mode in ("RGBA", "LA", "PA") or "transparency" in image.info
        return image.convert("RGBA" if has_alpha else "RGB")


def _encode(image) -> bytes:
    """PNG, without loss; only a file over the plugin's size limit becomes a JPEG of top quality."""
    out = io.BytesIO()
    image.save(out, "PNG")
    if out.tell() <= image_input.MAX_IMAGE_BYTES or image.mode == "RGBA":
        return out.getvalue()
    out = io.BytesIO()
    image.save(out, "JPEG", quality=98, subsampling=0)
    return out.getvalue()


def _canvas_for(ratio: float) -> Tuple[str, float]:
    return min(_CANVASES, key=lambda item: abs(math.log(ratio / item[1])))


def _pad_to_canvas(image) -> Tuple[Any, Tuple[int, int, int, int], str]:
    """The image mirrored outward to a size the provider delivers, so the answer lines up with it."""
    from PIL import Image, ImageOps

    width, height = image.size
    label, ratio = _canvas_for(width / height)
    canvas_w = max(width, round(height * ratio))
    canvas_h = max(height, round(width / ratio))
    left, top = (canvas_w - width) // 2, (canvas_h - height) // 2
    box = (left, top, left + width, top + height)
    if (canvas_w, canvas_h) == image.size:
        return image, box, label
    canvas = Image.new(image.mode, (canvas_w, canvas_h))
    flipped = ImageOps.mirror(image)
    for x in range(left % width - width, canvas_w, width):
        canvas.paste(flipped if (x - left) // width % 2 else image, (x, top))
    row = canvas.crop((0, top, canvas_w, top + height))
    flipped_row = ImageOps.flip(row)
    for y in range(top % height - height, canvas_h, height):
        canvas.paste(flipped_row if (y - top) // height % 2 else row, (0, y))
    return canvas, box, label


def _shrink(image, side: int):
    from PIL import Image

    scale = side / max(image.size)
    if scale >= 1:
        return image
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)


def _store(image) -> str:
    return str(store.save_reference(_encode(image)))


def change_mask(before, after):
    """Where the two images really differ: white on the change, without the noise of a redraw."""
    from PIL import Image, ImageChops, ImageFilter, ImageStat

    small_a = _shrink(before.convert("RGB"), _WORK_SIDE).filter(ImageFilter.GaussianBlur(1.5))
    small_b = after.convert("RGB").resize(small_a.size, Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.5))
    # A redraw often moves the whole picture's tone a little; that is not a change.
    offsets = [a - b for a, b in zip(ImageStat.Stat(small_a).median, ImageStat.Stat(small_b).median)]
    # Redraws measured up to 8 levels; more than this was asked for, such as warmer light on the whole photo.
    if max(abs(value) for value in offsets) >= _WHOLE_TONE_SHIFT:
        return Image.new("L", small_a.size, 255)
    small_b = Image.merge("RGB", [band.point(lambda v, o=o: max(0, min(255, v + o)))
                                  for band, o in zip(small_b.split(), offsets)])
    bands = ImageChops.difference(small_a, small_b).split()
    difference = ImageChops.lighter(ImageChops.lighter(bands[0], bands[1]), bands[2])
    noise = ImageStat.Stat(difference).median[0]
    limit = max(_MIN_DIFFERENCE, noise * 3)
    mask = difference.point(lambda v: 255 if v >= limit else 0)
    # Thin lines are edges the redraw moved by a pixel; only a real area survives this opening.
    mask = mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))
    return mask.filter(ImageFilter.MaxFilter(21)).filter(ImageFilter.MinFilter(9))


def _share(mask) -> float:
    from PIL import ImageStat

    return ImageStat.Stat(mask.convert("L")).mean[0] / 255


def _match_tone(base, edited, mask):
    """Align the new area's tone with the source around it, so its edge does not show."""
    from PIL import Image, ImageChops, ImageFilter, ImageStat

    small_mask = _shrink(mask, _WORK_SIDE).point(lambda v: 255 if v > 127 else 0)
    ring = ImageChops.subtract(small_mask.filter(ImageFilter.MaxFilter(15)), small_mask)
    if not ring.getbbox():
        return edited
    small_base = base.convert("RGB").resize(ring.size, Image.BOX)
    small_edited = edited.convert("RGB").resize(ring.size, Image.BOX)
    offsets = [max(-40, min(40, a - b)) for a, b in zip(ImageStat.Stat(small_base, ring).mean, ImageStat.Stat(small_edited, ring).mean)]
    bands = list(edited.split())
    bands[:3] = [band.point(lambda v, o=o: max(0, min(255, round(v + o)))) for band, o in zip(bands[:3], offsets)]
    return Image.merge(edited.mode, bands)


def merge(base, edited, mask=None) -> Tuple[Any, Dict[str, Any]]:
    """``base`` with only the changed area taken from ``edited``; the report says what happened.

    With ``mask`` (white on the area) the area is the one given. Without it the area comes from
    comparing both images. Pixels where the soft edge reaches zero are exactly the base's.
    """
    from PIL import Image, ImageFilter

    edited = edited.convert(base.mode)
    if edited.size != base.size:
        edited = edited.resize(base.size, Image.LANCZOS)
    automatic = mask is None
    mask = change_mask(base, edited) if automatic else mask.convert("L").point(lambda v: 255 if v > 127 else 0)
    share = _share(mask)
    if automatic and share > _WHOLE_IMAGE_SHARE:
        return edited, {"merged": False, "reason": "whole-image", "changedShare": round(share, 3)}
    if not share:
        return base, {"merged": True, "reason": "no-change", "changedShare": 0.0}
    mask = mask.resize(base.size, Image.BILINEAR).point(lambda v: 255 if v > 127 else 0)
    radius = max(3, max(base.size) // 256)
    soft = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(radius))
    return Image.composite(_match_tone(base, edited, mask), base, soft), {"merged": True, "changedShare": round(share, 3)}


def _ratio_matches(image, width: int, height: int) -> bool:
    return abs(math.log((image.width / image.height) / (width / height))) <= _RATIO_TOLERANCE


def _kept(base, answer_raw: bytes, mask) -> Tuple[Any, Dict[str, Any]]:
    answer = _load(answer_raw)
    if not _ratio_matches(answer, *base.size):
        return answer, {"merged": False, "reason": "different-shape", "changedShare": None}
    return merge(base, answer, mask)


def keep_source(base_image: str, result: Dict[str, Any], mask_image: Optional[str] = None) -> Dict[str, Any]:
    """Apply the merge to the answer of a provider that received the source by its own route."""
    base = _load(store.fetch_image_bytes(base_image))
    mask = _load(store.fetch_image_bytes(mask_image)).convert("L") if mask_image else None
    images: List[str] = []
    report: Dict[str, Any] = {}
    for image in result.get("images") or []:
        merged, report = _kept(base, store.fetch_image_bytes(image, max_bytes=image_input.MAX_RESULT_BYTES), mask)
        images.append(_store(merged))
    return {**result, "images": images, "merge": report}


def _region_box(mask, size: Tuple[int, int]) -> Tuple[int, int, int, int]:
    """The area around the painted mask, with context: the model then draws it at its full size."""
    left, top, right, bottom = mask.getbbox() or (0, 0, *size)
    margin = max(right - left, bottom - top) * _REGION_CONTEXT
    want = max(_REGION_MIN_SIDE, max(right - left, bottom - top) + 2 * margin)
    half_w, half_h = max(want, right - left) / 2, max(want, bottom - top) / 2
    middle_x, middle_y = (left + right) / 2, (top + bottom) / 2
    x0, y0 = max(0, round(middle_x - half_w)), max(0, round(middle_y - half_h))
    x1, y1 = min(size[0], round(middle_x + half_w)), min(size[1], round(middle_y + half_h))
    return x0, y0, x1, y1


def _marked(image, mask):
    from PIL import Image

    guide = Image.new("RGB", image.size, (255, 0, 255))
    return Image.composite(guide, image.convert("RGB"), mask.point(lambda v: 170 if v > 127 else 0))


def edit_with_provider(base_image: str, prompt: str, provider: str, model: str, mask_image: Optional[str] = None,
                       references: Optional[List[str]] = None, keep: bool = True, cancel: Any = None,
                       on_submit: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
    """Edit through a generation provider that takes references, keeping what did not change."""
    from PIL import Image

    base = _load(store.fetch_image_bytes(base_image))
    mask = None
    if mask_image:
        mask = _load(store.fetch_image_bytes(mask_image)).convert("L").point(lambda v: 255 if v > 127 else 0)
        if mask.size != base.size:
            mask = mask.resize(base.size, Image.NEAREST)
    box = _region_box(mask, base.size) if mask else (0, 0, *base.size)
    area = base.crop(box)
    area_mask = mask.crop(box) if mask else None
    canvas, inner, aspect = _pad_to_canvas(area)
    sent = _shrink(canvas, _SEND_MAX_SIDE)
    sources = [_store(sent)]
    if area_mask:
        canvas_mask = _blank_with(area_mask, canvas.size, inner)
        sources.append(_store(_marked(sent, canvas_mask.resize(sent.size))))
    text = (_REGION_PROMPT if mask else _GLOBAL_PROMPT).format(prompt=prompt.strip()) if keep or mask else prompt
    result = gen_service.generate_text_to_image(
        provider=provider, model=model, prompt=text, aspect_ratio=aspect, num_images=1,
        reference_images=[*sources, *(references or [])], cancel=cancel, on_submit=on_submit)
    images: List[str] = []
    report: Dict[str, Any] = {"merged": False, "reason": "whole-image-asked"}
    for image in result.get("images") or []:
        answer = _load(store.fetch_image_bytes(image))
        if not _ratio_matches(answer, *canvas.size):
            report = {"merged": False, "reason": "different-shape", "changedShare": None}
            images.append(_store(answer))
            continue
        # The mirrored bands were only there to reach the provider's shape; they never come back.
        scale = answer.width / canvas.width
        crop = tuple(round(value * scale) for value in inner)
        answer = answer.crop(crop).resize(area.size, Image.LANCZOS)
        if not keep and not mask:
            images.append(_store(answer))
            continue
        merged_area, report = merge(area, answer, area_mask)
        merged = base.copy()
        merged.paste(merged_area, box[:2])
        images.append(_store(merged))
    return {**result, "images": images, "merge": report}


def expand_with_provider(image: str, prompt: str, direction: str, pixels: int, provider: str, model: str,
                         **common: Any) -> Dict[str, Any]:
    """A larger canvas whose new area the provider draws; the source stays as it was."""
    from PIL import Image, ImageFilter

    base = _load(store.fetch_image_bytes(image)).convert("RGB")
    width, height = base.size
    left, right, top, bottom = ((pixels if direction in (name, "all") else 0) for name in ("left", "right", "top", "bottom"))
    size = (width + left + right, height + top + bottom)
    # A blurred stretch gives the model the colors without objects it would copy, as a mirror does.
    canvas = base.resize(size, Image.BILINEAR).filter(ImageFilter.GaussianBlur(max(size) / 30))
    canvas.paste(base, (left, top))
    mask = Image.new("L", size, 255)
    mask.paste(0, (left + _EXPAND_OVERLAP * bool(left), top + _EXPAND_OVERLAP * bool(top),
                   left + width - _EXPAND_OVERLAP * bool(right), top + height - _EXPAND_OVERLAP * bool(bottom)))
    return edit_with_provider(_store(canvas), _EXPAND_PROMPT.format(prompt=prompt.strip()), provider, model,
                              mask_image=_store(mask), **common)


def keep_expanded(image: str, result: Dict[str, Any], direction: str, pixels: int) -> Dict[str, Any]:
    """Put the source back in an expansion that a provider redrew whole, fading only where it meets the new area."""
    from PIL import Image, ImageDraw

    base = _load(store.fetch_image_bytes(image)).convert("RGB")
    width, height = base.size
    left, right, top, bottom = ((pixels if direction in (name, "all") else 0) for name in ("left", "right", "top", "bottom"))
    mask = Image.new("L", base.size, 255)
    draw = ImageDraw.Draw(mask)
    for step in range(_EXPAND_OVERLAP):
        value = round(255 * (step + 1) / (_EXPAND_OVERLAP + 1))
        if left:
            draw.line((step, 0, step, height), fill=value)
        if right:
            draw.line((width - 1 - step, 0, width - 1 - step, height), fill=value)
        if top:
            draw.line((0, step, width, step), fill=value)
        if bottom:
            draw.line((0, height - 1 - step, width, height - 1 - step), fill=value)
    images: List[str] = []
    for answer in result.get("images") or []:
        expanded = _load(store.fetch_image_bytes(answer, max_bytes=image_input.MAX_RESULT_BYTES)).convert("RGB")
        if expanded.size != (width + left + right, height + top + bottom):
            images.append(answer)  # Another size means another framing: pasting would misalign it.
            continue
        expanded.paste(base, (left, top), mask)
        images.append(_store(expanded))
    return {**result, "images": images}


def operation_with_provider(kind: str, body: Dict[str, Any], provider: str, model: str, **common: Any) -> Dict[str, Any]:
    """Expansion, light, style, camera and skin through a provider that only takes references and a prompt."""
    prompt = str(body.get("prompt") or "").strip()
    if kind == "outpaint":
        return expand_with_provider(body["image"], prompt, body.get("direction", "all"), int(body.get("expandPx", 256)),
                                    provider, model, **common)
    reference = [body["referenceImage"]] if body.get("referenceImage") else []
    text = {"relight": _RELIGHT_PROMPT.format(prompt=prompt or _RELIGHT_REFERENCE) if not reference
            else _RELIGHT_PROMPT.format(prompt=f"{_RELIGHT_REFERENCE} {prompt}"),
            "style-transfer": _STYLE_PROMPT.format(prompt=prompt),
            "skin": _SKIN_PROMPT,
            "camera": _CAMERA_PROMPT.format(view=_camera_view(int(body.get("horizontalAngle", 0)), int(body.get("verticalAngle", 0)),
                                                              int(body.get("zoom", 5))))}[kind]
    # These change every pixel, or too subtly for the comparison to see (skin), so the answer is the result.
    return edit_with_provider(body["image"], text, provider, model, references=reference, keep=False, **common)


def _blank_with(mask, size: Tuple[int, int], inner: Tuple[int, int, int, int]):
    from PIL import Image

    canvas = Image.new("L", size, 0)
    canvas.paste(mask, inner[:2])
    return canvas
