"""Image input security: local paths, sizes, and downloads.

Every user-supplied image (references, masks, upscales) passes through here
before reaching a provider. Rules:

- ``resolve_image_source`` — local path only inside the plugin's allowed
  roots (plugin data dir and the Hermes image cache); http(s) URLs pass
  through unchanged; data URLs are decoded and validated.
- ``validate_image_bytes`` — size ceiling + real image signature (magic
  bytes), without trusting the data URL header.
- ``fetch_remote_image`` — https-only download, no redirects, with private/
  loopback IP rejection and a byte ceiling (anti-SSRF).
"""
from __future__ import annotations

import base64
import ipaddress
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

MAX_IMAGE_BYTES = 10 * 1024 * 1024
# What a provider delivers can be far larger than what it accepts: an upscaled PNG, say.
MAX_RESULT_BYTES = 128 * 1024 * 1024

# (magic, extension) — accepted raster image signatures.
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"BM", "bmp"),
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def hermes_home() -> Path:
    """The active profile's Hermes home, asked of the host on every call."""
    try:
        from hermes_constants import get_hermes_home
    except ModuleNotFoundError as exc:
        if exc.name != "hermes_constants":
            raise
    else:
        return get_hermes_home()
    # Outside Hermes (source tooling): the host's own default.
    env = os.environ.get("HERMES_HOME", "").strip()
    if env:
        return Path(env)
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        return Path(local) / "hermes" if local else Path.home() / "AppData" / "Local" / "hermes"
    return Path.home() / ".hermes"


def allowed_image_roots() -> Tuple[Path, ...]:
    """Roots where local image paths are accepted (anti-exfiltration)."""
    from imagegen_engine import store

    roots = [store.data_dir().resolve()]
    # Hermes providers save their output in cache/generated/images; older hosts used cache/images.
    roots.extend((hermes_home() / "cache" / sub).resolve() for sub in ("generated/images", "images"))
    return tuple(roots)


def is_allowed_local_path(path: Path) -> bool:
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return any(resolved.is_relative_to(root) for root in allowed_image_roots())


def resolve_served_image(value: str) -> str:
    """Resolve our relative/loopback media URLs without fetching localhost.

    Returned paths still pass the normal containment and image validation.
    A public URL with a similar path remains a public URL.
    """
    from imagegen_engine import store

    value = str(value or "").strip()
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme and (parsed.scheme not in ("http", "https") or parsed.hostname not in ("localhost", "127.0.0.1", "::1")):
        return value
    path = urllib.parse.unquote(parsed.path)
    prefix = "/api/plugins/imagegen/"
    if not path.startswith(prefix):
        return value
    tail = path[len(prefix):]
    if tail.startswith("cache/"):
        local = urllib.parse.parse_qs(parsed.query).get("p", [""])[0]
        return local or value
    for route, root in (("refs/", store.refs_dir()), ("gallery/file/", store.gallery_dir()), ("objects/file/", store.objects_dir())):
        if tail.startswith(route):
            name = tail[len(route):]
            if not is_safe_id(name):
                raise ValueError("Invalid media filename")
            return str(root / name)
    return value


def is_safe_id(value: str) -> bool:
    """True for ids used as file names (no traversal)."""
    return bool(value) and _SAFE_ID_RE.match(value) is not None and value not in (".", "..")


def detect_mime(data: bytes) -> str:
    """Detect the mime from magic bytes (never from the data URL header)."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"BM"):
        return "image/bmp"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"avif", b"avis", b"heic", b"heix", b"mif1", b"msf1"):
            return "image/avif"
    return "image/png"


def _is_image(data: bytes) -> bool:
    if not data:
        return False
    if any(data.startswith(magic) for magic, _ in _IMAGE_SIGNATURES):
        return True
    # WebP (RIFF....WEBP) and AVIF/HEIC (ISO-BMFF 'ftyp').
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return True
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        return brand in (b"avif", b"avis", b"heic", b"heix", b"mif1", b"msf1")
    return False


def validate_image_bytes(data: bytes, *, max_bytes: int = MAX_IMAGE_BYTES) -> None:
    """Validate an image's size and signature (raises ValueError)."""
    if len(data) > max_bytes:
        raise ValueError(f"Image larger than {max_bytes // (1024 * 1024)}MB")
    if not _is_image(data):
        raise ValueError("File is not a valid image (PNG/JPEG/WebP/AVIF/GIF/BMP)")


def resolve_image_source(value: str, *, max_bytes: int = MAX_IMAGE_BYTES) -> Tuple[str, Optional[bytes]]:
    """Normalize a user image reference.

    Returns ``("url", None)`` for public URLs (use as-is) or
    ``("bytes", data)`` with the validated payload. Rejects local paths
    outside the allowed roots (anti-exfiltration of arbitrary files).
    """
    value = resolve_served_image(value)
    if not value:
        raise ValueError("Empty reference image")
    if value.startswith(("http://", "https://")):
        return "url", None
    if value.startswith("data:"):
        raw = value.split(",", 1)[-1]
        if len(raw) > ((max_bytes + 2) // 3) * 4 + 4:
            raise ValueError(f"Image larger than {max_bytes // (1024 * 1024)}MB")
        try:
            data = base64.b64decode(raw, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("Invalid data URL") from exc
        validate_image_bytes(data, max_bytes=max_bytes)
        return "bytes", data
    path = Path(value)
    if not is_allowed_local_path(path):
        raise ValueError("Image path outside the allowed directories")
    if not path.is_file():
        raise ValueError(f"Image not found: {value}")
    with path.open("rb") as source:
        data = source.read(max_bytes + 1)
    validate_image_bytes(data, max_bytes=max_bytes)
    return "bytes", data


def _reject_non_public_host(url: str) -> None:
    """Resolve the host and reject non-public addresses (SSRF guard)."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname
    if not host:
        raise ValueError("Invalid URL (no host)")
    try:
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Host could not be resolved: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            raise ValueError("Host resolves to a non-public address")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect handler that blocks redirects (anti-SSRF)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: PLR0913
        return None


def fetch_remote_image(url: str, *, max_bytes: int = MAX_IMAGE_BYTES, timeout: float = 60.0) -> bytes:
    """Download a remote image with anti-SSRF: https-only, no redirect,
    no private IP, and a byte ceiling."""
    if not url.startswith("https://"):
        raise ValueError("Image URL must be https://")
    _reject_non_public_host(url)

    request = urllib.request.Request(url, headers={"Accept": "image/*, */*;q=0.5"})
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            # Magnific's storage answers some finished images as generic binary; the bytes are validated below.
            if content_type and not content_type.startswith(("image/", "application/octet-stream", "binary/octet-stream")):
                raise ValueError(f"Response is not an image (Content-Type: {content_type})")
            declared = int(resp.headers.get("Content-Length") or 0)
            if declared > max_bytes:
                raise ValueError("Remote image larger than the allowed limit")
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ValueError("Remote image larger than the allowed limit")
    except urllib.error.HTTPError as exc:
        raise ValueError(f"Failed to download image (HTTP {exc.code})") from exc
    except OSError as exc:
        raise ValueError(f"Failed to download image: {exc}") from exc
    validate_image_bytes(data, max_bytes=max_bytes)
    return data
