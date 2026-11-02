"""FAL's public model catalog: every active image model, read at runtime and cached.

FAL lists its models at ``https://api.fal.ai/v1/models`` (category filter, cursor pages) and
returns each model's OpenAPI input schema with ``expand=openapi-3.0``. The list stays on disk
for a day and refreshes in the background, so opening the catalog never waits on FAL; schemas
stay for a week. The FAL key, when present, is sent so the account's own rate limit applies.
Requests are built from the schema: ImageGen fills prompt, size, seed and references, and
refuses a model that requires an input it cannot provide instead of guessing.
"""
from __future__ import annotations

import json
import math
import logging
import threading
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from imagegen_engine.errors import ImageGenError, MODEL_INVALID, PROVIDER_FAILED, REFS_MODEL_UNSUPPORTED

logger = logging.getLogger(__name__)

CATALOG_URL = "https://api.fal.ai/v1/models"
CATEGORIES = ("text-to-image", "image-to-image")
LIST_TTL = 24 * 3600
SCHEMA_TTL = 7 * 24 * 3600
RETRY_AFTER = 30 * 60
SIZE_PRESETS = {"square_hd": (1, 1), "portrait_4_3": (3, 4), "portrait_16_9": (9, 16),
                "landscape_4_3": (4, 3), "landscape_16_9": (16, 9)}
LIST_FIELDS = ("image_urls", "reference_image_urls", "input_image_urls", "reference_images")
SINGLE_FIELDS = ("image_url", "input_image_url", "reference_image_url")
PRESET_RATIOS = {"square_hd": "1:1", "square": "1:1", "portrait_4_3": "3:4", "portrait_16_9": "9:16",
                 "landscape_4_3": "4:3", "landscape_16_9": "16:9"}

_lock = threading.RLock()
_memory: Dict[str, Any] = {}
_refresh: Dict[str, Any] = {"thread": None, "failed_at": 0.0}


def _cache_file(name: str):
    from imagegen_engine import store

    return store.data_dir() / name


def _read_json(name: str) -> Dict[str, Any]:
    try:
        data = json.loads(_cache_file(name).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(name: str, data: Dict[str, Any]) -> None:
    path = _cache_file(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    temporary.replace(path)


def _get(params: Dict[str, Any]) -> Dict[str, Any]:
    from imagegen_engine import credentials

    headers = {"Accept": "application/json"}
    key = credentials.fal_key()
    if key:
        headers["Authorization"] = f"Key {key}"
    with urlopen(Request(f"{CATALOG_URL}?{urlencode(params)}", headers=headers), timeout=30) as response:
        return json.load(response)


def _summary(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    meta = row.get("metadata") or {}
    endpoint = row.get("endpoint_id")
    if not isinstance(endpoint, str) or not endpoint or meta.get("status", "active") != "active":
        return None
    description = " ".join(str(meta.get("description") or "").split())
    group = meta.get("group") or {}
    return {"id": endpoint, "display": str(meta.get("display_name") or endpoint),
            "strengths": description[:180], "group": str(group.get("key") or ""),
            "label": str(group.get("label") or "")}


def _fetch_all() -> Dict[str, Any]:
    catalog: Dict[str, Any] = {"at": time.time()}
    for category in CATEGORIES:
        rows: List[Dict[str, Any]] = []
        cursor = None
        for _ in range(20):  # Hard stop: 2,000 models per category.
            params = {"category": category, "status": "active", "limit": 100}
            if cursor:
                params["cursor"] = cursor
            page = _get(params)
            rows += [item for item in map(_summary, page.get("models") or []) if item]
            cursor = page.get("next_cursor")
            if not page.get("has_more") or not cursor:
                break
        catalog[category] = rows
    return catalog


def refresh() -> bool:
    """Fetch the whole catalog now; keep the last good copy when FAL refuses."""
    try:
        catalog = _fetch_all()
    except Exception as exc:  # noqa: BLE001 — offline or rate-limited: the stale list still serves
        logger.info("FAL catalog refresh failed: %s", exc)
        _refresh["failed_at"] = time.time()
        return False
    with _lock:
        _memory["catalog"] = catalog
        _write_json("fal-catalog.json", catalog)
    from imagegen_engine.events import announce

    announce("providers.changed", {"provider": "fal"})
    return True


def _catalog() -> Dict[str, Any]:
    with _lock:
        catalog = _memory.get("catalog")
        if catalog is None:
            catalog = _memory["catalog"] = _read_json("fal-catalog.json")
        stale = time.time() - float(catalog.get("at") or 0) > LIST_TTL
        thread = _refresh["thread"]
        if stale and not (thread and thread.is_alive()) and time.time() - _refresh["failed_at"] > RETRY_AFTER:
            _refresh["thread"] = threading.Thread(target=refresh, name="imagegen-fal-catalog", daemon=True)
            _refresh["thread"].start()
        return catalog


def _index() -> Dict[str, Any]:
    """Lookup tables over the cached catalog, rebuilt only when the catalog changes."""
    catalog = _catalog()
    with _lock:
        index = _memory.get("index")
        if index and index["of"] is catalog:
            return index
        groups: Dict[str, List[str]] = {}
        for item in catalog.get("image-to-image") or []:
            if item["group"]:
                groups.setdefault(item["group"], []).append(item)
        for siblings in groups.values():
            siblings.sort(key=lambda item: ("edit" not in (item["label"] + item["id"]).lower(), item["id"]))
        index = _memory["index"] = {
            "of": catalog,
            "groups": {key: [item["id"] for item in siblings] for key, siblings in groups.items()},
            "text": {item["id"]: item for item in catalog.get("text-to-image") or []},
            "ids": {item["id"] for category in CATEGORIES for item in catalog.get(category) or []}}
        return index


def models(category: str) -> List[Dict[str, Any]]:
    """Cached models of one category; an empty or stale cache starts a background refresh."""
    return [dict(item) for item in _catalog().get(category) or []]


def knows(model_id: str) -> bool:
    """True when FAL's cached catalog lists this endpoint (no network call)."""
    return model_id in _index()["ids"]


def _limit(fields: Dict[str, Any]) -> int:
    many = next((name for name in LIST_FIELDS if name in fields), "")
    if many:
        return int(fields[many]["maxItems"] or 16)
    return 1 if any(name in fields for name in SINGLE_FIELDS) else 0


def reference_limit(endpoint: str) -> int:
    """How many reference images the endpoint takes: 0 for none; 16 when FAL sets no limit."""
    return _limit(schema(endpoint)["properties"])


def edit_sibling(model_id: str) -> str:
    """The image-to-image endpoint FAL groups with a text-to-image model, if any."""
    index = _index()
    group = (index["text"].get(model_id) or {}).get("group") or ""
    siblings = index["groups"].get(group) or []
    return siblings[0] if siblings else ""


def details(model_id: str, *, fetch: bool = True) -> Dict[str, Any]:
    """The controls one catalog model supports, read from its schema.

    With ``fetch=False`` only cached schemas are read and facts not cached are left out.
    """
    own = schema(model_id, fetch=fetch)
    if own is None:
        return {}
    fields = own["properties"]
    out: Dict[str, Any] = {"supportsSeed": "seed" in fields}
    ratio, size = fields.get("aspect_ratio"), fields.get("image_size")
    if ratio and ratio["enum"]:
        out["aspectRatios"] = [value for value in ratio["enum"] if _nearest([value], "1:1")]
    elif size and "object" not in size["types"] and size["enum"]:
        out["aspectRatios"] = list(dict.fromkeys(PRESET_RATIOS[value] for value in size["enum"] if value in PRESET_RATIOS))
    if not out.get("aspectRatios"):
        out.pop("aspectRatios", None)
    resolution = fields.get("resolution")
    if resolution and resolution["enum"]:
        out["resolutionOptions"] = [str(value).upper() for value in resolution["enum"]]
    sibling = edit_sibling(model_id)
    refs = schema(sibling, fetch=fetch) if sibling else own
    if refs is not None:
        out["maxReferences"] = _limit(refs["properties"])
    if sibling:
        out["editEndpoint"] = sibling
    return out


def _resolve(spec: Dict[str, Any], node: Any) -> Any:
    seen = 0
    while isinstance(node, dict) and "$ref" in node and seen < 8:
        node = spec.get("components", {}).get("schemas", {}).get(str(node["$ref"]).rsplit("/", 1)[-1], {})
        seen += 1
    return node


def _simplify(spec: Dict[str, Any], prop: Dict[str, Any]) -> Dict[str, Any]:
    options = [_resolve(spec, item) for item in prop.get("anyOf") or prop.get("oneOf") or [prop]]
    enum = [value for item in options for value in (item.get("enum") or ([item["const"]] if "const" in item else []))]
    types = {item.get("type") for item in options} - {None, "null"}
    if any("properties" in item for item in options):
        types.add("object")
    array = next((item for item in options if item.get("type") == "array"), {})
    return {"types": sorted(types), "enum": enum, "maxItems": array.get("maxItems"),
            "hasDefault": "default" in prop}


def _parse_schema(endpoint: str, document: Dict[str, Any]) -> Dict[str, Any]:
    spec = document.get("openapi") or {}
    operation = (spec.get("paths") or {}).get("/" + endpoint, {}).get("post") or {}
    content = ((operation.get("requestBody") or {}).get("content") or {}).get("application/json") or {}
    schema = _resolve(spec, content.get("schema") or {})
    properties = schema.get("properties") or {}
    if not properties:
        raise ValueError("no input schema")
    return {"properties": {name: _simplify(spec, _resolve(spec, prop)) for name, prop in properties.items()},
            "required": list(schema.get("required") or [])}


def schema(endpoint: str, *, fetch: bool = True) -> Optional[Dict[str, Any]]:
    """The simplified input schema of one endpoint, cached for a week.

    ``fetch=False`` answers from the cache only and returns None when nothing is cached.
    """
    with _lock:
        cache = _memory.get("schemas")
        if cache is None:
            cache = _memory["schemas"] = _read_json("fal-schemas.json")
        cached = cache.get(endpoint)
        if cached and (not fetch or time.time() - float(cached.get("at") or 0) < SCHEMA_TTL):
            return cached["input"]
    if not fetch:
        return None
    try:
        rows = _get({"endpoint_id": endpoint, "expand": "openapi-3.0"}).get("models") or []
        parsed = _parse_schema(endpoint, next(row for row in rows if row.get("endpoint_id") == endpoint))
    except Exception as exc:  # noqa: BLE001
        if cached:
            return cached["input"]
        raise ImageGenError(PROVIDER_FAILED, f"Could not read the FAL model's input fields: {exc}",
                            provider="fal", model=endpoint) from exc
    with _lock:
        cache[endpoint] = {"at": time.time(), "input": parsed}
        _write_json("fal-schemas.json", cache)
    return parsed


def _ratio(value: str) -> float:
    width, height = (float(part) for part in value.split(":", 1))
    return width / height


def _nearest(options: List[str], aspect_ratio: str) -> str:
    target = _ratio(aspect_ratio)
    numeric = [option for option in options if isinstance(option, str) and option.count(":") == 1
               and all(part.replace(".", "").isdigit() for part in option.split(":"))]
    return min(numeric, key=lambda option: abs(math.log(_ratio(option) / target))) if numeric else ""


def build_payload(endpoint: str, *, prompt: str, aspect_ratio: Optional[str] = None, resolution: str = "1K",
                  seed: Optional[int] = None, negative_prompt: Optional[str] = None,
                  image_urls: Optional[List[str]] = None) -> Dict[str, Any]:
    """Map ImageGen's inputs onto one FAL model's documented fields."""
    from imagegen_engine.gen_service import _resolution_to_pixels

    input_schema = schema(endpoint)
    fields = input_schema["properties"]
    payload: Dict[str, Any] = {}
    if "prompt" in fields and prompt:
        payload["prompt"] = prompt
    if aspect_ratio:
        size = fields.get("image_size")
        ratio = fields.get("aspect_ratio")
        if ratio:
            payload["aspect_ratio"] = aspect_ratio if aspect_ratio in ratio["enum"] or not ratio["enum"] else _nearest(ratio["enum"], aspect_ratio)
            if not payload["aspect_ratio"]:
                del payload["aspect_ratio"]
        elif size and "object" in size["types"]:
            payload["image_size"] = _resolution_to_pixels(resolution, aspect_ratio)
        elif size and size["enum"]:
            target = _ratio(aspect_ratio)
            presets = [name for name in SIZE_PRESETS if name in size["enum"]]
            if presets:
                payload["image_size"] = min(presets, key=lambda name: abs(SIZE_PRESETS[name][0] / SIZE_PRESETS[name][1] - target))
    choices = (fields.get("resolution") or {}).get("enum") or []
    match = next((value for value in choices if str(value).upper() == str(resolution).upper()), None)
    if match is not None:
        payload["resolution"] = match
    if seed is not None and "seed" in fields:
        payload["seed"] = seed
    if negative_prompt and "negative_prompt" in fields:
        payload["negative_prompt"] = negative_prompt
    if "num_images" in fields:
        payload["num_images"] = 1
    refs = list(image_urls or [])
    if refs:
        many = next((name for name in LIST_FIELDS if name in fields), "")
        single = next((name for name in SINGLE_FIELDS if name in fields), "")
        limit = fields[many]["maxItems"] if many else 1 if single else 0
        if not many and not single:
            raise ImageGenError(REFS_MODEL_UNSUPPORTED, "This FAL model does not accept reference images",
                                provider="fal", model=endpoint)
        if limit and len(refs) > int(limit):
            raise ImageGenError(MODEL_INVALID, f"This FAL model accepts at most {limit} reference images",
                                provider="fal", model=endpoint)
        if many:
            payload[many] = refs
        else:
            payload[single] = refs[0]
    missing = [name for name in input_schema["required"] if name not in payload and not fields.get(name, {}).get("hasDefault")]
    if missing:
        raise ImageGenError(MODEL_INVALID, "This FAL model needs inputs ImageGen does not send: " + ", ".join(missing),
                            provider="fal", model=endpoint)
    return payload
