"""Local persistence for ImageGen: history, gallery, and prompt library.

Everything lives in the active profile's plugin-data/imagegen/ directory,
resolved on every call (``data_dir``).
"""
from __future__ import annotations

import calendar
import contextvars
import json
import hashlib
import logging
import math
import mimetypes
import os
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

from imagegen_engine import image_input
from imagegen_engine.errors import JOB_INTERRUPTED, ImageGenError, BUDGET_EXCEEDED
from imagegen_engine.file_lock import ProcessRLock, process_alive



# Defaults of the ``history_cap`` and ``gallery_cap`` plugin settings (Settings -> Plugins -> ImageGen).
HISTORY_CAP = 200
GALLERY_CAP = 200


def _cap_setting(key: str, default: int) -> int:
    """A positive limit from the plugin settings of the active profile, or ``default``."""
    from imagegen_engine import host_llm

    value = host_llm.setting(key, None)
    try:
        value = int(value)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def history_cap() -> int:
    return _cap_setting("history_cap", HISTORY_CAP)


def gallery_cap() -> int:
    return _cap_setting("gallery_cap", GALLERY_CAP)
LIBRARY_CAP = 200
HANDOFFS_CAP = 50
EXPORTS_CAP = 20
REFS_CAP = 500
OBJECTS_CAP = 500
JOBS_CAP = 64
SPEND_CAP = 5000


def image_media_type(filename: str) -> str:
    """Return a safe image media type for a stored filename.

    Windows' mimetypes registry does not know .webp/.avif, so map common
    formats explicitly before falling back to mimetypes.guess_type.
    """
    extension = Path(str(filename)).suffix.lower()
    explicit = {
        ".webp": "image/webp",
        ".avif": "image/avif",
        ".svg": "image/svg+xml",
    }
    if extension in explicit:
        return explicit[extension]
    return mimetypes.guess_type(str(filename))[0] or "image/png"


def data_dir() -> Path:
    """The active profile's ImageGen data folder, resolved on every call.

    One process may serve several Hermes profiles, so no path is fixed at
    import: each call asks the host for the current profile's plugin data.
    """
    try:
        from plugins.plugin_storage import plugin_data_dir
    except ModuleNotFoundError as exc:
        if exc.name not in {"plugins", "plugins.plugin_storage"}:
            raise
        # Older hosts and source-only tooling still keep data outside the install tree.
        root = image_input.hermes_home() / "plugin-data" / "imagegen"
        root.mkdir(parents=True, exist_ok=True)
        return root
    return plugin_data_dir("imagegen")


def _folder(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def gallery_dir() -> Path:
    return _folder(data_dir() / "gallery")


def refs_dir() -> Path:
    return _folder(gallery_dir() / "refs")


def objects_dir() -> Path:
    return _folder(data_dir() / "objects")


def handoffs_dir() -> Path:
    return _folder(data_dir() / "handoffs")


def export_dir() -> Path:
    return _folder(data_dir() / "exports")


def objects_index() -> Path:
    return data_dir() / "objects.json"


def history_file() -> Path:
    return data_dir() / "history.json"


def library_file() -> Path:
    return data_dir() / "library.json"


def settings_file() -> Path:
    return data_dir() / "settings.json"


def spend_file() -> Path:
    return data_dir() / "spend.json"


def handoff_last_file() -> Path:
    return handoffs_dir() / "last.json"


def jobs_file() -> Path:
    return data_dir() / "jobs.json"




# One reentrant lock per JSON file, so concurrent read-modify-write sequences
# (add_history, library_save, object_add, ...) never lose an update. Created
# lazily under a guard; keyed by resolved path (monkeypatched paths in tests
# get their own lock).
_FILE_LOCKS: Dict[Path, ProcessRLock] = {}
_LOCKS_GUARD = threading.Lock()
# Gallery mutations touch several files (image + meta + history refs); a single
# lock keeps the whole namespace consistent. Lock order: _gallery_lock() first,
# then the history file lock — never the reverse (avoids deadlock).


def _file_lock(path: Path) -> ProcessRLock:
    resolved = path.resolve()
    with _LOCKS_GUARD:
        lock = _FILE_LOCKS.get(resolved)
        if lock is None:
            lock = ProcessRLock(resolved)
            _FILE_LOCKS[resolved] = lock
        return lock


def _gallery_lock() -> ProcessRLock:
    """The lock over the active profile's gallery namespace."""
    return _file_lock(data_dir() / ".gallery")


def _read_json(path: Path, default: Any) -> Any:
    with _file_lock(path):
        return _read_json_locked(path, default)


def _read_json_locked(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        if path.resolve() in (settings_file().resolve(), spend_file().resolve()):
            raise ValueError(f"Repair {path.name} before submitting paid operations; accounting was not reset") from exc
        # Never let corrupt JSON degrade into a silent data wipe: quarantine
        # the broken file (so the next write cannot overwrite it) and log.
        quarantine: Optional[Path] = None
        try:
            quarantine = path.with_name(f"{path.name}.corrupt-{uuid.uuid4().hex}")
            os.replace(path, quarantine)
        except OSError:
            quarantine = None
            logger.exception("Could not quarantine corrupt JSON in %s", path)
        if quarantine is not None:
            logger.error(
                "Corrupt JSON in %s; moved to %s and default used. Error: %s",
                path, quarantine, exc,
            )
        else:
            logger.error("Corrupt JSON in %s could not be quarantined. Error: %s", path, exc)
    return default


def _write_json(path: Path, data: Any) -> None:
    """Write JSON atomically (temp + rename) so a crash mid-write cannot
    corrupt the file — and concurrent readers never see half a document."""
    with _file_lock(path):
        _write_json_locked(path, data)


def _write_json_locked(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:  # Windows: an indexer or antivirus holds the file for a moment
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _unique_filename(original: str, *, prefix: str = "") -> str:
    """Generate a unique filename with ms + uuid to avoid collisions."""
    suffix = Path(str(original)).suffix.lower() or ".png"
    # Keep only safe chars from prefix/stem; limit length
    stem_raw = Path(str(original)).stem[:32] if original else ""
    safe_stem = "".join(c for c in stem_raw if c.isalnum() or c in "-_") or (prefix or "file")
    safe_stem = safe_stem[:32]
    ms = int(time.time() * 1000)
    uid = uuid.uuid4().hex[:8]
    return f"{ms}-{uid}-{safe_stem}{suffix}" if safe_stem else f"{ms}-{uid}{suffix}"


def _atomic_write_bytes(dest: Path, data: bytes) -> None:
    """Write bytes atomically via tmp + replace (robust on Windows/POSIX)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex[:6]}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, dest)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON atomically via tmp + replace (separate helper for meta files)."""
    _write_json(path, data)


def _passport_status(passport: str) -> str:
    """Derive passport status: ready if non-empty, else missing."""
    return "ready" if str(passport or "").strip() else "missing"


def _safe_entry_id(entry_id: Any) -> str:
    """Normalize an id used as a file name; rejects traversal."""
    value = str(entry_id or "").strip()
    if not image_input.is_safe_id(value):
        raise ValueError("Invalid id")
    return value


def save_handoff(record: Dict[str, Any]) -> Dict[str, Any]:
    """Persist the latest successful generation for the agent/UI handoff loop."""
    generation_id = _safe_entry_id(record.get("generationId") or record.get("id") or uuid.uuid4().hex)
    now = int(time.time() * 1000)
    normalized = {"id": generation_id, "generationId": generation_id, "ts": now, **record}
    normalized.setdefault("paths", normalized.get("outputPaths") or normalized.get("images") or [])
    path = handoffs_dir() / f"{generation_id}.json"
    with _file_lock(path):
        _write_json(path, normalized)
    with _file_lock(handoff_last_file()):
        _write_json(handoff_last_file(), normalized)
    _prune_handoffs()
    return normalized


def get_handoff(handoff_id: str) -> Optional[Dict[str, Any]]:
    safe_id = _safe_entry_id(handoff_id)
    value = _read_json(handoffs_dir() / f"{safe_id}.json", None)
    return value if isinstance(value, dict) else None


def get_last_handoff() -> Optional[Dict[str, Any]]:
    value = _read_json(handoff_last_file(), None)
    return value if isinstance(value, dict) else None


def save_handoff_feedback(handoff_id: str, feedback: Dict[str, Any]) -> Dict[str, Any]:
    safe_id = _safe_entry_id(handoff_id)
    record = get_handoff(safe_id)
    if record is None:
        raise KeyError(handoff_id)
    record["feedback"] = feedback.get("feedback", feedback)
    if "diagnosis" in feedback:
        record["diagnosis"] = feedback["diagnosis"]
    with _file_lock(handoffs_dir() / f"{safe_id}.json"):
        _write_json(handoffs_dir() / f"{safe_id}.json", record)
    with _file_lock(handoff_last_file()):
        if get_last_handoff() and get_last_handoff().get("id") == safe_id:
            _write_json(handoff_last_file(), record)
    return record


def get_output_dir() -> Optional[Path]:
    """Return the configured export folder, or ``None`` for internal-only storage."""
    raw = _read_json(settings_file(), {}).get("outputFolder", "")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return Path(raw).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def set_output_dir(folder: str) -> Optional[Path]:
    """Persist an absolute export folder and create it when needed."""
    value = (folder or "").strip()
    if not value:
        with _file_lock(settings_file()):
            settings = _read_json(settings_file(), {})
            settings.pop("outputFolder", None)
            _write_json(settings_file(), settings)
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("The output folder must be an absolute path")
    path = path.resolve()
    if path.exists() and not path.is_dir():
        raise ValueError("The output folder points at a file")
    path.mkdir(parents=True, exist_ok=True)
    with _file_lock(settings_file()):
        settings = _read_json(settings_file(), {})
        settings["outputFolder"] = str(path)
        _write_json(settings_file(), settings)
    return path


def output_dir_status() -> Dict[str, Any]:
    path = get_output_dir()
    writable = False
    if path is not None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".imagegen-write-check"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            writable = True
        except OSError:
            writable = False
    return {"path": str(path) if path else "", "exists": bool(path and path.exists()), "writable": writable}


# ---------------------------------------------------------------------------
# Spend ledger and monthly budget
# ---------------------------------------------------------------------------

# The client or project the running thread spends for; recorded in each ledger entry.
spend_label: contextvars.ContextVar[str] = contextvars.ContextVar("imagegen_spend_label", default="")


def _month_start_utc(now: float) -> float:
    """UTC epoch seconds of the first instant of the month containing ``now``."""
    utc = time.gmtime(now)
    return calendar.timegm((utc.tm_year, utc.tm_mon, 1, 0, 0, 0, 0, 0, 0))


def record_spend(provider: str, model: str, num_images: int, cost: Optional[float], job_id: str = "") -> None:
    """Append one paid generation to the spend ledger (UTC timestamps).

    A falsy/None cost is ignored — free or unknown-price generations never
    pollute the ledger. The ledger is capped at :data:`SPEND_CAP` entries,
    pruning the oldest ones.
    """
    if not cost:
        return
    entry = {
        "ts": time.time(),
        "provider": str(provider),
        "model": str(model),
        "numImages": int(num_images),
        "cost": float(cost),
        "jobId": str(job_id),
    }
    with _file_lock(spend_file()):
        ledger = _read_json(spend_file(), [])
        if not isinstance(ledger, list):
            ledger = []
        ledger.append(entry)
        ledger = _prune_spend(ledger)
        _write_json(spend_file(), ledger)


def _prune_spend(ledger: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Never prune this month's accounting, even during a large batch."""
    start = _month_start_utc(time.time())
    current = [entry for entry in ledger if float(entry.get("ts") or 0) >= start]
    older = [entry for entry in ledger if float(entry.get("ts") or 0) < start]
    return older[-max(0, SPEND_CAP - len(current)):] + current if len(current) < SPEND_CAP else current


def reserve_spend(provider: str, model: str, estimate: Optional[float], num_images: int = 1) -> str:
    """Reserve estimated USD atomically before a provider can accept a request.

    Unknown prices are recorded, never invented. A configured USD limit blocks
    unpriced requests because they cannot be checked against that limit.
    """
    if estimate is not None and (not math.isfinite(estimate) or estimate < 0):
        raise ValueError("Invalid cost estimate")
    with _file_lock(settings_file()), _file_lock(spend_file()):
        limit = get_budget()["monthlyLimit"]
        spent = spend_this_month()
        if limit is not None and estimate is None:
            raise ImageGenError("budget.unknown_cost", "This operation has no reliable USD estimate; remove the local limit or choose a priced model", provider=provider, model=model)
        # A free operation (a local server) never moves the total, so the limit does not stop it.
        if limit is not None and estimate and spent + estimate > limit:
            raise ImageGenError(BUDGET_EXCEEDED, "Monthly estimated budget exceeded", spent=spent, limit=limit, estimate=estimate)
        reservation_id = uuid.uuid4().hex
        ledger = _read_json(spend_file(), [])
        entry = {
            "id": reservation_id, "ts": time.time(), "provider": provider,
            "model": model, "numImages": num_images, "cost": estimate,
            "status": "reserved", "estimated": True,
        }
        if spend_label.get():
            entry["label"] = spend_label.get()
        ledger.append(entry)
        _write_json(spend_file(), _prune_spend(ledger))
        return reservation_id


def settle_spend(reservation_id: str, status: str) -> None:
    """Keep ambiguous submissions reserved; release only known rejections."""
    with _file_lock(spend_file()):
        ledger = _read_json(spend_file(), [])
        for entry in ledger:
            if entry.get("id") == reservation_id:
                entry["status"] = status
                if status == "rejected":
                    entry["cost"] = 0
                break
        _write_json(spend_file(), ledger)


def spend_since(ts: float) -> float:
    """Total USD recorded at or after ``ts`` (UTC epoch seconds)."""
    ledger = _read_json(spend_file(), [])
    if not isinstance(ledger, list):
        return 0.0
    total = 0.0
    for entry in ledger:
        if not isinstance(entry, dict):
            continue
        try:
            if float(entry.get("ts", 0)) >= ts:
                cost = float(entry.get("cost", 0))
                if math.isfinite(cost) and cost >= 0:
                    total += cost
        except (TypeError, ValueError):
            continue
    return round(total, 4)


def spend_report() -> Dict[str, Any]:
    """This month's ledger by label, with failed attempts apart from delivered images.

    A failed attempt keeps its cost because the provider may have billed it. Attempts still
    running count as failed until they settle; a rejected attempt costs nothing.
    """
    start = _month_start_utc(time.time())
    ledger = _read_json(spend_file(), [])
    groups: Dict[str, Dict[str, Any]] = {}
    for entry in ledger if isinstance(ledger, list) else []:
        if not isinstance(entry, dict) or float(entry.get("ts") or 0) < start:
            continue
        label = str(entry.get("label") or "")
        group = groups.setdefault(label, {"label": label, "images": 0, "cost": 0.0, "failed_attempts": 0,
                                          "failed_cost": 0.0, "rejected_attempts": 0})
        cost = float(entry.get("cost") or 0)
        status = entry.get("status", "submitted")
        group["cost"] += cost
        if status == "submitted":
            group["images"] += int(entry.get("numImages") or 0)
        elif status == "rejected":
            group["rejected_attempts"] += 1
        else:
            group["failed_attempts"] += 1
            group["failed_cost"] += cost
    labels = sorted(groups.values(), key=lambda group: group["label"])
    for group in labels:
        group["cost"], group["failed_cost"] = round(group["cost"], 4), round(group["failed_cost"], 4)
    return {"month": time.strftime("%Y-%m", time.gmtime(start)), "total": spend_this_month(), "labels": labels}


def spend_this_month() -> float:
    """Total USD recorded in the current UTC calendar month."""
    return spend_since(_month_start_utc(time.time()))


def get_budget() -> Dict[str, Any]:
    """Return the persisted monthly budget limit (``None`` = no limit)."""
    settings = _read_json(settings_file(), {})
    raw = settings.get("budget") if isinstance(settings, dict) else None
    limit = raw.get("monthlyLimit") if isinstance(raw, dict) else None
    if limit is None:
        return {"monthlyLimit": None}
    try:
        value = float(limit)
        if not math.isfinite(value) or value < 0:
            raise ValueError("Invalid persisted budget limit")
        return {"monthlyLimit": value}
    except (TypeError, ValueError):
        # A malformed configured limit must not silently disable the guard.
        return {"monthlyLimit": 0.0}


def set_budget(monthly_limit: Optional[float]) -> Dict[str, Any]:
    """Persist the monthly budget limit; ``None`` clears it.

    Raises ``ValueError`` (English message) for negative or non-numeric
    values so the API layer can map it to a structured 400.
    """
    if monthly_limit is None:
        limit: Optional[float] = None
    else:
        try:
            limit = float(monthly_limit)
        except (TypeError, ValueError):
            raise ValueError("The monthly budget limit must be a number") from None
        if not math.isfinite(limit) or limit < 0:
            raise ValueError("The monthly budget limit cannot be negative")
    with _file_lock(settings_file()):
        settings = _read_json(settings_file(), {})
        if not isinstance(settings, dict):
            settings = {}
        budget = settings.get("budget") if isinstance(settings.get("budget"), dict) else {}
        if limit is None:
            budget.pop("monthlyLimit", None)
        else:
            budget["monthlyLimit"] = limit
        if budget:
            settings["budget"] = budget
        else:
            settings.pop("budget", None)
        _write_json(settings_file(), settings)
    return {"monthlyLimit": limit}


def budget_status() -> Dict[str, Any]:
    """Combined budget read model for the UI: limit, spend, and currency."""
    start = _month_start_utc(time.time())
    ledger = [entry for entry in _read_json(spend_file(), []) if float(entry.get("ts") or 0) >= start]
    return {
        "monthlyLimit": get_budget()["monthlyLimit"],
        "spentThisMonth": spend_this_month(),
        "currency": "USD",
        "estimated": True,
        "unknownCostCount": sum(entry.get("cost") is None for entry in ledger),
        "pendingCount": sum(entry.get("status") in ("reserved", "uncertain") for entry in ledger),
    }


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def add_history(entry: Dict[str, Any]) -> Dict[str, Any]:
    with _file_lock(history_file()):
        hist = _read_json(history_file(), [])
        entry = {
            "id": entry.get("id") or str(uuid.uuid4())[:8],
            "ts": entry.get("ts") or int(time.time() * 1000),
            **entry,
        }
        hist = [item for item in hist if item.get("id") != entry["id"]]
        hist.insert(0, entry)
        _write_json(history_file(), hist[:history_cap()])
    return entry


def get_history(limit: int = 50) -> List[Dict[str, Any]]:
    hist = _read_json(history_file(), [])
    return hist[:limit]


def remove_history(entry_id: str) -> None:
    with _file_lock(history_file()):
        hist = [h for h in _read_json(history_file(), []) if h.get("id") != entry_id]
        _write_json(history_file(), hist)


# ---------------------------------------------------------------------------
# Job records (persistent job store)
# ---------------------------------------------------------------------------

_TERMINAL_STATUSES = ("completed", "failed", "cancelled")


def _record_ts(record: Dict[str, Any], field: str) -> float:
    """Coerce a record timestamp to a float for ordering; never raises.

    A hand-edited jobs.json may carry garbage values — sorting must not blow
    up the next write (that would kill live job threads).
    """
    try:
        return float(record.get(field) or 0)
    except (TypeError, ValueError):
        return 0.0


def save_job_record(record: Dict[str, Any]) -> None:
    """Upsert one job record into data/jobs.json (keyed by ``id``).

    Terminal records beyond ``JOBS_CAP`` are pruned oldest-first so the file
    cannot grow unbounded. Active records (queued/running/interrupted) are
    never pruned — they may still be resumable after a restart.
    """
    try:
        job_id = _safe_entry_id(record.get("id"))
    except ValueError:
        return
    if not job_id:
        return
    with _file_lock(jobs_file()):
        records = _read_json(jobs_file(), [])
        if not isinstance(records, list):
            records = []
        previous = next((r for r in records if isinstance(r, dict) and r.get("id") == job_id), {})
        record = {**record, "cancelRequested": bool(record.get("cancelRequested") or previous.get("cancelRequested"))}
        records = [r for r in records if not (isinstance(r, dict) and r.get("id") == job_id)]
        records.append(record)
        records.sort(key=lambda r: _record_ts(r, "created"), reverse=True)
        if len(records) > JOBS_CAP:
            terminal = [
                r for r in records
                if isinstance(r, dict) and str(r.get("status") or "") in _TERMINAL_STATUSES
            ]
            if terminal:
                terminal.sort(key=lambda r: (_record_ts(r, "finished"), _record_ts(r, "created")))
                drop = len(records) - JOBS_CAP
                doomed = {str(r.get("id")) for r in terminal[:drop]}
                records = [r for r in records if str(r.get("id") or "") not in doomed]
        _write_json(jobs_file(), records)


def load_job_records() -> List[Dict[str, Any]]:
    """Return all persisted job records (newest first)."""
    records = _read_json(jobs_file(), [])
    if not isinstance(records, list):
        return []
    return [r for r in records if isinstance(r, dict) and r.get("id")]


def get_job_record(job_id: str) -> Optional[Dict[str, Any]]:
    """Return a single persisted job record, or None when unknown."""
    try:
        safe_id = _safe_entry_id(job_id)
    except ValueError:
        return None
    for record in load_job_records():
        if record.get("id") == safe_id:
            return record
    return None


def mark_orphan_jobs_interrupted() -> List[Dict[str, Any]]:
    """Convert persisted jobs that were queued/running to ``interrupted``.

    Called once at import: such records were left behind by a previous process
    that died mid-generation. The provider request may still be running (and
    billed), so the record — including its ``remote`` checkpoint — is kept and
    returned so the caller can surface it as a resumable job. Terminal records
    are left untouched.
    """
    with _file_lock(jobs_file()):
        records = _read_json(jobs_file(), [])
        if not isinstance(records, list):
            return []
        converted: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            owner_pid = int(_record_ts(record, "ownerPid"))
            if str(record.get("status") or "") in ("queued", "running", "recovering") and not process_alive(owner_pid):
                record["status"] = "interrupted"
                record["errorCode"] = JOB_INTERRUPTED
                record.setdefault("error", "Interrupted by process restart")
                converted.append(record)
        if converted:
            _write_json(jobs_file(), records)
    return converted


# ---------------------------------------------------------------------------
# Gallery (images + metadata)
# ---------------------------------------------------------------------------

_last_gallery_ts = 0


def _export_gallery_copy(source: Path, entry_id: str, suffix: str = "") -> Optional[str]:
    """Copy a gallery image to the configured export folder (best effort)."""
    output_dir = get_output_dir()
    if output_dir is None or not source.is_file():
        return None
    output_dir.mkdir(parents=True, exist_ok=True)
    if not suffix:
        suffix = source.suffix.lower() or ".png"
    destination = output_dir / f"imagegen-{entry_id}{suffix}"
    shutil.copy2(source, destination)
    return str(destination)


def _next_gallery_ts() -> int:
    """Return a timestamp above the last one: fast saves can share a millisecond. Call under the lock."""
    global _last_gallery_ts
    _last_gallery_ts = max(int(time.time() * 1000), _last_gallery_ts + 1)
    return _last_gallery_ts


def save_gallery_entry(image_bytes: bytes, meta: Dict[str, Any]) -> Dict[str, Any]:
    """Save image + metadata transactionally; returns the entry with url.

    Image is written to a temp file, the complete metadata (including the
    optional export path) is written once via tmp->replace, and only then is
    the image renamed to its final name. A metadata failure removes the temp
    image — no orphans.
    """
    with _gallery_lock():
        image_input.validate_image_bytes(image_bytes, max_bytes=image_input.MAX_RESULT_BYTES)
        entry_id = _safe_entry_id(meta.get("id") or str(uuid.uuid4())[:8])
        suffix = {"image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif", "image/avif": ".avif", "image/bmp": ".bmp"}.get(image_input.detect_mime(image_bytes), ".png")
        filename = f"img-{entry_id}{suffix}"
        final_path = gallery_dir() / filename
        tmp = gallery_dir() / f".img-{entry_id}-{uuid.uuid4().hex[:6]}.tmp"
        tmp.write_bytes(image_bytes)
        entry = {
            **meta,
            "id": entry_id,
            "file": filename,
            "ts": _next_gallery_ts(),
            "url": f"/api/plugins/imagegen/gallery/file/{filename}",
            "thumb": f"/api/plugins/imagegen/gallery/file/{filename}",
            "localPath": str(final_path),
        }
        try:
            try:
                exported = _export_gallery_copy(tmp, entry_id, suffix=suffix)
            except OSError:
                exported = None
            if exported:
                entry["outputPath"] = exported
            meta_dir = gallery_dir() / ".meta"
            meta_dir.mkdir(parents=True, exist_ok=True)
            meta_path = meta_dir / f"{entry_id}.json"
            # Atomic meta write: tmp -> replace (crash-safe, no half JSON)
            _write_json(meta_path, entry)
            os.replace(tmp, final_path)
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass
            # Clean up partially written meta on failure
            try:
                (gallery_dir() / ".meta" / f"{entry_id}.json").unlink()
            except OSError:
                pass
            raise
        _prune_gallery()
        return entry


def export_gallery_entry(entry: Dict[str, Any]) -> Optional[str]:
    """Copy an internal gallery image to the configured export folder."""
    source = gallery_file(str(entry.get("file", "")))
    if source is None:
        return None
    return _export_gallery_copy(source, str(entry.get("id") or uuid.uuid4().hex[:8]))


def gallery_list() -> List[Dict[str, Any]]:
    """List gallery entries: metadata of each saved image.

    Ordered by timestamp descending (the metadata timestamp, not the random
    entry id), with the metadata filename as a stable tiebreaker.
    """
    records: List[tuple] = []
    meta_dir = gallery_dir() / ".meta"
    if meta_dir.exists():
        for mf in meta_dir.glob("*.json"):
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
                img_path = gallery_dir() / meta.get("file", "")
                if img_path.exists():
                    meta["url"] = f"/api/plugins/imagegen/gallery/file/{meta['file']}"
                    meta["thumb"] = meta["url"]
                    meta["localPath"] = str(img_path)
                    records.append((meta.get("ts") or 0, mf.name, meta))
            except Exception:  # noqa: BLE001
                continue
    records.sort(key=lambda record: (record[0], record[1]), reverse=True)
    return [record[2] for record in records]


def gallery_stats() -> Dict[str, Any]:
    """Return gallery count, byte size, and oldest entry timestamp."""
    entries = gallery_list()
    total_bytes = 0
    oldest_ts: Optional[int] = None
    for entry in entries:
        path = gallery_dir() / str(entry.get("file", ""))
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
        ts = entry.get("ts")
        if isinstance(ts, (int, float)):
            oldest_ts = int(ts) if oldest_ts is None else min(oldest_ts, int(ts))
    return {
        "entries": len(entries),
        "bytes": total_bytes,
        "oldest_ts": oldest_ts,
        "cap": gallery_cap(),
    }


def clear_gallery() -> int:
    """Delete all gallery images and metadata. Return the number of entries."""
    entries = gallery_list()
    for entry in entries:
        delete_gallery_entry(str(entry.get("id", "")))
    return len(entries)


def gallery_metadata(entry_id: str) -> Optional[Dict[str, Any]]:
    safe_id = _safe_entry_id(entry_id)
    meta_dir = gallery_dir() / ".meta"
    mf = meta_dir / f"{safe_id}.json"
    if mf.exists():
        try:
            return json.loads(mf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    return None


def _prune_gallery() -> None:
    """Keep the newest gallery entries and remove their files atomically enough.

    The metadata timestamp is the ordering source. A malformed metadata file is
    ignored here and remains visible to the next repair/list pass. Pruned ids
    are also stripped from history references.
    """
    with _gallery_lock():
        meta_dir = gallery_dir() / ".meta"
        if not meta_dir.exists():
            return
        records = []
        for meta_file in meta_dir.glob("*.json"):
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                records.append((int(meta.get("ts", 0)), meta_file, meta))
            except Exception:  # noqa: BLE001
                continue
        records.sort(key=lambda item: item[0], reverse=True)
        pruned_ids: List[str] = []
        for _, meta_file, meta in records[gallery_cap():]:
            try:
                image_file = gallery_dir() / str(meta.get("file", ""))
                if image_file.is_file():
                    image_file.unlink()
                meta_file.unlink()
            except OSError:
                continue
            entry_id = str(meta.get("id") or "")
            if entry_id:
                pruned_ids.append(entry_id)
        if pruned_ids:
            _strip_history_gallery_refs(pruned_ids)


def repair_gallery() -> Dict[str, int]:
    """Repair gallery inconsistencies: orphans, missing meta/image, tmp files.

    - Removes image files without matching meta.
    - Removes meta without matching image file.
    - Removes stale tmp files (.img-*.tmp, .*.tmp).
    - Ensures meta files are valid JSON with required keys.
    Returns counts: {removed_images, removed_meta, removed_tmp, repaired}.
    """
    removed_images = 0
    removed_meta = 0
    removed_tmp = 0
    with _gallery_lock():
        meta_dir = gallery_dir() / ".meta"
        meta_dir.mkdir(parents=True, exist_ok=True)
        # Index valid metas
        valid_metas: Dict[str, Path] = {}
        valid_files: set = set()
        for mf in list(meta_dir.glob("*.json")):
            try:
                meta = json.loads(mf.read_text(encoding="utf-8"))
                fid = str(meta.get("file") or "")
                gid = str(meta.get("id") or "")
                if not gid or not fid:
                    mf.unlink()
                    removed_meta += 1
                    continue
                valid_metas[fid] = mf
                valid_files.add(fid)
            except Exception:
                try:
                    mf.unlink()
                except OSError:
                    pass
                removed_meta += 1
        # Remove orphan images (no meta)
        for img in gallery_dir().glob("img-*.*"):
            if img.name not in valid_files:
                try:
                    img.unlink()
                    removed_images += 1
                except OSError:
                    pass
        # Remove meta whose image missing
        for fid, mf in list(valid_metas.items()):
            if not (gallery_dir() / fid).exists():
                try:
                    mf.unlink()
                    removed_meta += 1
                except OSError:
                    pass
        # Clean tmp files
        for tmp in list(gallery_dir().glob(".*.tmp")):
            try:
                tmp.unlink()
                removed_tmp += 1
            except OSError:
                pass
        for tmp in list(meta_dir.glob(".*.tmp")):
            try:
                tmp.unlink()
                removed_tmp += 1
            except OSError:
                pass
    return {"removed_images": removed_images, "removed_meta": removed_meta, "removed_tmp": removed_tmp, "repaired": removed_images + removed_meta}


def gallery_file(filename: str) -> Optional[Path]:
    safe_name = Path(filename).name
    p = (gallery_dir() / safe_name).resolve()
    if p.parent == gallery_dir().resolve() and p.exists() and p.is_file():
        return p
    return None


def delete_gallery_entry(entry_id: str) -> None:
    safe_id = _safe_entry_id(entry_id)
    with _gallery_lock():
        meta = gallery_metadata(safe_id)
        if meta:
            f = gallery_dir() / meta.get("file", "")
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass
            mf = gallery_dir() / ".meta" / f"{safe_id}.json"
            if mf.exists():
                try:
                    mf.unlink()
                except OSError:
                    pass
        # Drop dangling gallery references from history entries (images[],
        # gallery_ids[], gallery_entries[]) so nothing points at deleted files.
        _strip_history_gallery_refs([safe_id])


def _strip_history_gallery_refs(removed_ids: Iterable[str]) -> None:
    """Remove deleted gallery ids from history entries, keeping the parallel
    ``images``/``gallery_ids``/``gallery_entries`` arrays aligned by index."""
    removed = {str(gid) for gid in removed_ids if gid}
    if not removed:
        return
    with _file_lock(history_file()):
        hist = _read_json(history_file(), [])
        changed = False
        for entry in hist:
            ids = list(entry.get("gallery_ids") or [])
            if not ids:
                continue
            keep = [i for i, gid in enumerate(ids) if str(gid) not in removed]
            if len(keep) == len(ids):
                continue
            entries = list(entry.get("gallery_entries") or [])
            images = list(entry.get("images") or [])
            entry["gallery_ids"] = [ids[i] for i in keep]
            entry["gallery_entries"] = [entries[i] for i in keep if i < len(entries)]
            entry["images"] = [images[i] for i in keep if i < len(images)]
            changed = True
        if changed:
            _write_json(history_file(), hist)


# ---------------------------------------------------------------------------
# Export and scoped cleanup
# ---------------------------------------------------------------------------

def export_gallery_pack(entry_id: str) -> Optional[Path]:
    """Create an image plus metadata sidecar archive for one gallery entry."""
    safe_id = _safe_entry_id(entry_id)
    meta = gallery_metadata(safe_id)
    if not meta:
        return None
    image = gallery_file(str(meta.get("file", "")))
    if image is None:
        return None
    export_dir().mkdir(parents=True, exist_ok=True)
    target = export_dir() / f"imagegen-{safe_id}.zip"
    metadata = {key: value for key, value in meta.items() if key not in {"url", "thumb", "localPath"}}
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(image, f"image{image.suffix}")
        archive.writestr("meta.json", json.dumps(metadata, ensure_ascii=False, indent=2))
    _prune_exports()
    return target


def clear_plugin_data(*, gallery: bool = False, handoffs: bool = False, subjects: bool = False) -> Dict[str, int]:
    """Clear selected plugin-owned data without touching Hermes configuration."""
    deleted = {"gallery": 0, "handoffs": 0, "subjects": 0}
    if gallery:
        deleted["gallery"] = clear_gallery()
    if handoffs and handoffs_dir().exists():
        deleted["handoffs"] = len(list(handoffs_dir().glob("*.json")))
        shutil.rmtree(handoffs_dir(), ignore_errors=True)
        handoffs_dir().mkdir(parents=True, exist_ok=True)
    if subjects:
        deleted["subjects"] = len(objects_list())
        shutil.rmtree(objects_dir(), ignore_errors=True)
        objects_dir().mkdir(parents=True, exist_ok=True)
        with _file_lock(objects_index()):
            _write_json(objects_index(), [])
        subjects_root = data_dir() / "subjects"
        if subjects_root.exists():
            shutil.rmtree(subjects_root, ignore_errors=True)
            subjects_root.mkdir(parents=True, exist_ok=True)
    return deleted


# ---------------------------------------------------------------------------
# Prompt library
# ---------------------------------------------------------------------------

def library_list() -> List[Dict[str, Any]]:
    return _read_json(library_file(), [])


def library_save(name: str, prompt: str, config: Dict[str, Any], refs: Optional[List[Dict[str, Any]]] = None,
                 genre: str = "", negative_prompt: str = "", entry_id: Optional[str] = None) -> Dict[str, Any]:
    """Save a generation recipe: prompt + full config + refs + genre + negatives."""
    item = {
        "id": entry_id or str(uuid.uuid4())[:8],
        "name": name,
        "prompt": prompt,
        "config": config,
        "refs": refs or [],
        "genre": genre,
        "negativePrompt": negative_prompt,
        "ts": int(time.time() * 1000),
    }
    with _file_lock(library_file()):
        items = library_list()
        items = [i for i in items if i.get("id") != item["id"]]
        items.insert(0, item)
        _write_json(library_file(), items[:LIBRARY_CAP])
    return item


def library_remove(entry_id: str) -> None:
    with _file_lock(library_file()):
        items = [i for i in library_list() if i.get("id") != entry_id]
        _write_json(library_file(), items)


# ---------------------------------------------------------------------------
# Image download (remote URL → bytes)
# ---------------------------------------------------------------------------

def fetch_image_bytes(url_or_path: str, *, max_bytes: int = image_input.MAX_IMAGE_BYTES) -> bytes:
    """Download an image from an https URL (anti-SSRF) or read an allowed local path."""
    try:
        return _fetch_image_bytes_inner(str(url_or_path or "").strip(), max_bytes)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def _fetch_image_bytes_inner(value: str, max_bytes: int) -> bytes:
    value = image_input.resolve_served_image(value)
    kind, data = image_input.resolve_image_source(value, max_bytes=max_bytes)
    if kind == "url":
        return image_input.fetch_remote_image(value, max_bytes=max_bytes)
    assert data is not None
    return data


def _prune_handoffs(cap: int = HANDOFFS_CAP) -> None:
    """Keep only the most recent handoff records (plus last.json)."""
    if not handoffs_dir().exists():
        return
    files = sorted(
        (p for p in handoffs_dir().glob("*.json") if p.name != "last.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in files[cap:]:
        try:
            old.unlink()
        except OSError:
            pass


def _prune_exports(cap: int = EXPORTS_CAP) -> None:
    """Keep only the most recent export zips."""
    if not export_dir().exists():
        return
    files = sorted(export_dir().glob("*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[cap:]:
        try:
            old.unlink()
        except OSError:
            pass


_REF_EXTENSIONS = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif",
                   "image/avif": ".avif", "image/bmp": ".bmp"}


def save_reference(binary: bytes) -> Path:
    """Keep an uploaded reference image in ``refs_dir()``; raises ``ValueError`` for a bad image."""
    image_input.validate_image_bytes(binary)
    ext = _REF_EXTENSIONS.get(image_input.detect_mime(binary), ".png")
    path = refs_dir() / f"ref-{uuid.uuid4().hex[:10]}{ext}"
    path.write_bytes(binary)
    prune_refs()
    return path


def prune_refs(cap: int = REFS_CAP) -> None:
    """Keep only the most recent uploaded reference images."""
    if not refs_dir().exists():
        return
    # Another process pruning at the same time may remove a file between the listing and its stat.
    dated = []
    for path in refs_dir().glob("ref-*"):
        try:
            if path.is_file():
                dated.append((path.stat().st_mtime, path))
        except OSError:
            continue
    dated.sort(key=lambda item: item[0], reverse=True)
    for _, old in dated[cap:]:
        try:
            old.unlink()
        except OSError:
            pass


def objects_prune(cap: int = OBJECTS_CAP) -> int:
    """Keep only the newest ``cap`` subject library entries (LRU by updatedAt).

    Oldest entries beyond cap are removed including their image files (primary
    + angles). Returns number of pruned entries. Robust: ignores missing files,
    never raises.
    """
    with _file_lock(objects_index()):
        items = _read_json(objects_index(), []) or []
        if not isinstance(items, list) or len(items) <= cap:
            return 0
        # Sort newest first by updatedAt/createdAt/ts fallback
        def _ts(it: Dict[str, Any]) -> int:
            for k in ("updatedAt", "createdAt", "ts"):
                try:
                    v = it.get(k)
                    if v is not None:
                        return int(v)
                except (TypeError, ValueError):
                    continue
            return 0
        items_sorted = sorted(items, key=_ts, reverse=True)
        keep = items_sorted[:cap]
        drop = items_sorted[cap:]
        # Collect files to delete
        files_to_remove: set = set()
        for it in drop:
            f = str(it.get("file") or "")
            if f:
                files_to_remove.add(f)
            for ang in it.get("angles") or []:
                af = str(ang.get("file") or "")
                if af:
                    files_to_remove.add(af)
        for fname in files_to_remove:
            try:
                p = objects_dir() / fname
                if p.exists():
                    p.unlink()
            except OSError:
                pass
        # Also clean stray tmp files
        for tmp in objects_dir().glob(".*.tmp"):
            try:
                tmp.unlink()
            except OSError:
                pass
        _write_json(objects_index(), keep)
        return len(drop)


# ---------------------------------------------------------------------------
# Subject library (open kinds) — extends the objects index with angles/tags
# ---------------------------------------------------------------------------

SUBJECT_KIND_PRESETS = [
    "product", "person", "object", "animal", "vehicle", "food",
    "place", "character", "logo_mark", "material", "style", "other",
]


def _slug_kind(value: str) -> str:
    raw = (value or "").strip().lower()
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in raw)
    cleaned = "-".join(part for part in cleaned.split("-") if part)
    return (cleaned or "other")[:48]


def _file_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def objects_list() -> List[Dict[str, Any]]:
    items = _read_json(objects_index(), []) or []
    out = []
    for it in items:
        img = objects_dir() / it.get("file", "")
        if not img.exists():
            continue
        angles = []
        for angle in it.get("angles") or []:
            angle_file = str(angle.get("file") or "")
            angle_path = objects_dir() / angle_file
            if not angle_path.exists():
                continue
            angles.append({
                **angle,
                "localPath": str(angle_path),
                "thumb": f"/api/plugins/imagegen/objects/file/{angle_file}",
                "url": f"/api/plugins/imagegen/objects/file/{angle_file}",
            })
        if not angles:
            angles = [{
                "id": "primary",
                "label": "primary",
                "role": "primary",
                "file": it.get("file", ""),
                "localPath": str(img),
                "thumb": f"/api/plugins/imagegen/objects/file/{it.get('file', '')}",
                "url": f"/api/plugins/imagegen/objects/file/{it.get('file', '')}",
            }]
        passport = str(it.get("passport") or "")
        status = it.get("passportStatus") or _passport_status(passport)
        out.append({
            **it,
            "kind": it.get("kind") or "object",
            "tags": list(it.get("tags") or []),
            "passport": passport,
            "passportStatus": status,
            "angles": angles,
            "localPath": str(img),
            "thumb": f"/api/plugins/imagegen/objects/file/{it.get('file', '')}",
            "url": f"/api/plugins/imagegen/objects/file/{it.get('file', '')}",
        })
    return out


def subjects_list(*, kind: str = "", q: str = "") -> List[Dict[str, Any]]:
    kind_norm = _slug_kind(kind) if kind else ""
    needle = (q or "").strip().lower()
    out = []
    for item in objects_list():
        if kind_norm and _slug_kind(str(item.get("kind") or "")) != kind_norm:
            continue
        hay = " ".join([
            str(item.get("name") or ""),
            str(item.get("kind") or ""),
            str(item.get("passport") or ""),
            " ".join(item.get("tags") or []),
        ]).lower()
        if needle and needle not in hay:
            continue
        out.append(item)
    return out


def subjects_kinds() -> Dict[str, Any]:
    seen = {_slug_kind(str(item.get("kind") or "")) for item in objects_list()}
    custom = sorted(k for k in seen if k and k not in SUBJECT_KIND_PRESETS)
    return {"presets": SUBJECT_KIND_PRESETS, "custom": custom, "all": SUBJECT_KIND_PRESETS + custom}


def find_object_by_hash(content_hash: str) -> Optional[Dict[str, Any]]:
    if not content_hash:
        return None
    for item in _read_json(objects_index(), []) or []:
        if item.get("contentHash") == content_hash:
            return item
        for angle in item.get("angles") or []:
            if angle.get("contentHash") == content_hash:
                return item
    return None


def object_add(
    file_name: str,
    source_bytes: bytes,
    name: str = "",
    passport: str = "",
    kind: str = "object",
    tags: Optional[List[str]] = None,
    *,
    dedupe: bool = True,
) -> Dict[str, Any]:
    objects_dir().mkdir(parents=True, exist_ok=True)
    content_hash = _file_hash(source_bytes)
    if dedupe:
        existing = find_object_by_hash(content_hash)
        if existing:
            path = objects_dir() / existing.get("file", "")
            return {
                **existing,
                "localPath": str(path) if path.exists() else "",
                "deduped": True,
            }
    # Unique filename with ms+uuid (atomic tmp->replace)
    unique_name = _unique_filename(file_name)
    dest = objects_dir() / unique_name
    _atomic_write_bytes(dest, source_bytes)
    item = {
        "id": str(uuid.uuid4())[:8],
        "name": name or Path(unique_name).stem,
        "file": unique_name,
        "passport": passport,
        "passportStatus": _passport_status(passport),
        "kind": _slug_kind(kind),
        "tags": [str(t).strip() for t in (tags or []) if str(t).strip()][:24],
        "contentHash": content_hash,
        "angles": [{
            "id": "primary",
            "label": "primary",
            "role": "primary",
            "file": unique_name,
            "contentHash": content_hash,
        }],
        "createdAt": int(time.time()),
        "updatedAt": int(time.time()),
    }
    with _file_lock(objects_index()):
        items = _read_json(objects_index(), []) or []
        items = [i for i in items if i.get("file") != unique_name]
        items.append(item)
        _write_json(objects_index(), items)
        # LRU cap enforcement
        if len(items) > OBJECTS_CAP:
            # release lock ordering handled inside prune; call without holding? but we already hold file lock reentrant so ok
            try:
                objects_prune(OBJECTS_CAP)
            except Exception:
                pass
    return {**item, "localPath": str(dest), "deduped": False}


def subject_update(obj_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    with _file_lock(objects_index()):
        items = _read_json(objects_index(), []) or []
        updated = None
        for item in items:
            if item.get("id") != obj_id:
                continue
            if "name" in patch and str(patch.get("name") or "").strip():
                item["name"] = str(patch["name"]).strip()
            if "kind" in patch:
                item["kind"] = _slug_kind(str(patch.get("kind") or "other"))
            if "passport" in patch:
                val = str(patch.get("passport") or "")
                item["passport"] = val
                item["passportStatus"] = _passport_status(val)
            if "tags" in patch and isinstance(patch.get("tags"), list):
                item["tags"] = [str(t).strip() for t in patch["tags"] if str(t).strip()][:24]
            item["updatedAt"] = int(time.time())
            updated = item
            break
        if updated is None:
            return None
        _write_json(objects_index(), items)
    return next((o for o in objects_list() if o.get("id") == obj_id), updated)


def subject_add_angle(obj_id: str, file_name: str, source_bytes: bytes, label: str = "") -> Optional[Dict[str, Any]]:
    content_hash = _file_hash(source_bytes)
    # Generate unique filename early (ms+uuid) for atomic write
    unique_name = _unique_filename(file_name)
    with _file_lock(objects_index()):
        items = _read_json(objects_index(), []) or []
        for item in items:
            if item.get("id") != obj_id:
                continue
            angles = list(item.get("angles") or [])
            if any(a.get("contentHash") == content_hash for a in angles):
                return next((o for o in objects_list() if o.get("id") == obj_id), item)
            dest = objects_dir() / unique_name
            _atomic_write_bytes(dest, source_bytes)
            angles.append({
                "id": str(uuid.uuid4())[:8],
                "label": label or Path(unique_name).stem,
                "role": "variation",
                "file": unique_name,
                "contentHash": content_hash,
            })
            item["angles"] = angles
            item["updatedAt"] = int(time.time())
            _write_json(objects_index(), items)
            # Enforce cap after angle addition (count unchanged but refresh LRU)
            if len(items) > OBJECTS_CAP:
                try:
                    objects_prune(OBJECTS_CAP)
                except Exception:
                    pass
            return next((o for o in objects_list() if o.get("id") == obj_id), item)
    return None


def subject_as_refs(obj_id: str, *, max_refs: int = 4) -> List[Dict[str, Any]]:
    obj = next((o for o in objects_list() if o.get("id") == obj_id), None)
    if not obj:
        return []
    angles = list(obj.get("angles") or [])[: max(1, max_refs)]
    refs = []
    for index, angle in enumerate(angles):
        refs.append({
            "id": f"subj-{obj_id}-{angle.get('id') or index}",
            "label": f"{obj.get('name', 'Subject')} · {angle.get('label') or angle.get('role') or index + 1}",
            "localPath": angle.get("localPath") or "",
            "imageDataUrl": "",
            "semanticRole": "object_primary" if index == 0 else "object_variation",
            "authorityLevel": "authoritative",
            "roleConfirmed": True,
            "fidelity": 95 if index == 0 else 85,
            "fixedProduct": True,
            "purposes": [],
            "keep": [],
            "vary": [],
            "granularWeights": {"colors": 80, "lighting": 60, "composition": 70, "textures": 85},
            "userNotes": obj.get("passport", "") if index == 0 else "",
            "instructions": "",
            "inputMode": "library",
            "isAnalyzing": False,
            "analysisResult": None,
            "origin": "library",
            "kind": obj.get("kind") or "object",
            "subjectId": obj_id,
        })
    return refs


def object_remove(obj_id: str) -> bool:
    with _file_lock(objects_index()):
        items = _read_json(objects_index(), []) or []
        kept = [i for i in items if i.get("id") != obj_id]
        if len(kept) == len(items):
            return False
        removed = next((i for i in items if i.get("id") == obj_id), {})
        files = {removed.get("file", "")}
        for angle in removed.get("angles") or []:
            files.add(str(angle.get("file") or ""))
        for file_name in files:
            try:
                f = objects_dir() / file_name
                if file_name and f.exists():
                    f.unlink()
            except Exception:  # noqa: BLE001
                pass
        _write_json(objects_index(), kept)
    return True


# ---------------------------------------------------------------------------
# Feed (unified read model: history + gallery)
# ---------------------------------------------------------------------------

def feed_distinct_providers() -> List[str]:
    """Distinct provider names present in the feed (sorted, case-preserving)."""
    items = feed_list(limit=0)
    seen: Dict[str, str] = {}
    for item in items:
        raw = str(item.get("provider") or "").strip()
        if not raw:
            continue
        key = raw.lower()
        if key not in seen:
            seen[key] = raw
    return sorted(seen.values(), key=lambda s: s.lower())


def feed_list(*, source: str = "all", provider: Optional[str] = None,
              query: Optional[str] = None, limit: int = 200, sort: str = "newest") -> List[Dict[str, Any]]:
    """Unified read model: history entries (``generated``) joined with gallery
    entries that no history entry references (``saved``), newest first.

    Gallery ids referenced by any history entry appear only on the generated
    side — never duplicated. ``source`` is one of ``all``/``generated``/
    ``saved``; ``provider`` and ``query`` (matched against the prompt,
    case-insensitive) filter; ``limit`` caps the result (0 = no cap).
    """
    source = (source or "all").strip().lower()
    if source not in ("all", "generated", "saved"):
        source = "all"
    needle = (query or "").strip().lower()
    prov = (provider or "").strip().lower()

    history = _read_json(history_file(), [])
    gallery = gallery_list()
    gallery_by_id = {str(item["id"]): item for item in gallery}

    referenced: set = set()
    for entry in history:
        for gid in entry.get("gallery_ids") or []:
            if gid:
                referenced.add(str(gid))

    items: List[Dict[str, Any]] = []
    if source in ("all", "generated"):
        for entry in history:
            hid = entry.get("id")
            if not hid:
                continue
            if prov and str(entry.get("provider") or "").lower() != prov:
                continue
            prompt = str(entry.get("prompt") or "")
            if needle and needle not in prompt.lower():
                continue
            gallery_entries = list(entry.get("gallery_entries") or [])
            images = []
            for index, url in enumerate(entry.get("images") or []):
                ge = gallery_entries[index] if index < len(gallery_entries) and isinstance(gallery_entries[index], dict) else None
                ids = entry.get("gallery_ids") or []
                gallery_id = str((ge or {}).get("id") or (ids[index] if index < len(ids) else ""))
                saved = gallery_by_id.get(gallery_id)
                if saved:
                    url = saved["url"]
                    ge = saved
                images.append({
                    "url": url,
                    "galleryId": ge.get("id") if ge else None,
                    "localPath": ge.get("localPath") if ge else None,
                })
            items.append({
                "id": str(hid),
                "source": "generated",
                "ts": entry.get("ts") or 0,
                "prompt": prompt,
                "provider": entry.get("provider") or "",
                "model": entry.get("model") or "",
                "kind": entry.get("kind") or "generate",
                "images": images,
                "config": entry.get("config") or {},
                "historyId": str(hid),
                "galleryIds": [str(g) for g in (entry.get("gallery_ids") or []) if g],
            })
    if source in ("all", "saved"):
        for gallery_entry in gallery:
            gid = gallery_entry.get("id")
            if not gid or str(gid) in referenced:
                continue
            if prov and str(gallery_entry.get("provider") or "").lower() != prov:
                continue
            prompt = str(gallery_entry.get("prompt") or "")
            if needle and needle not in prompt.lower():
                continue
            file_name = str(gallery_entry.get("file") or "")
            items.append({
                "id": str(gid),
                "source": "saved",
                "ts": gallery_entry.get("ts") or 0,
                "prompt": prompt,
                "provider": gallery_entry.get("provider") or "",
                "model": gallery_entry.get("model") or "",
                "kind": gallery_entry.get("kind") or "gallery",
                "images": [{
                    "url": gallery_entry.get("url") or f"/api/plugins/imagegen/gallery/file/{file_name}",
                    "galleryId": str(gid),
                    "localPath": gallery_entry.get("localPath"),
                }],
                "config": gallery_entry.get("config") or {},
                "historyId": None,
                "galleryIds": [str(gid)],
            })
    sort = (sort or "newest").strip().lower()
    if sort == "oldest":
        items.sort(key=lambda item: item.get("ts") or 0)
    elif sort == "prompt_az":
        items.sort(key=lambda item: (str(item.get("prompt") or "").lower(), item.get("ts") or 0))
    else:
        items.sort(key=lambda item: item.get("ts") or 0, reverse=True)
    if limit and limit > 0:
        items = items[:limit]
    return items


def export_feed_zip(ids: List[str]) -> Optional[Path]:
    """Create a zip of the selected feed items' gallery images + meta sidecars."""
    safe = []
    for raw in ids or []:
        try:
            safe.append(_safe_entry_id(str(raw)))
        except ValueError:
            continue
    if not safe or len(safe) > 20:
        if not safe:
            raise ValueError("At least one id is required")
        raise ValueError("At most 20 items can be exported at once")
    export_dir().mkdir(parents=True, exist_ok=True)
    target = export_dir() / f"imagegen-bulk-{int(time.time()*1000)}-{uuid.uuid4().hex[:6]}.zip"
    added = 0
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for fid in safe:
            # Resolve history -> gallery ids, or direct gallery id
            gids: List[str] = []
            hist = _read_json(history_file(), [])
            for entry in hist:
                if str(entry.get("id")) == fid:
                    gids = [str(g) for g in (entry.get("gallery_ids") or []) if g]
                    break
            if not gids:
                try:
                    if gallery_metadata(fid) is not None:
                        gids = [fid]
                except ValueError:
                    continue
            for gid in gids:
                meta = gallery_metadata(gid)
                if not meta:
                    continue
                img = gallery_file(str(meta.get("file", "")))
                if img is None or not img.exists():
                    continue
                metadata = {k: v for k, v in meta.items() if k not in {"url", "thumb", "localPath"}}
                archive.write(img, f"{gid}/image{img.suffix}")
                archive.writestr(f"{gid}/meta.json", json.dumps(metadata, ensure_ascii=False, indent=2))
                added += 1
    if added == 0:
        try:
            target.unlink()
        except OSError:
            pass
        return None
    _prune_exports()
    return target


def feed_stats() -> Dict[str, Any]:
    """Global feed stats (unfiltered) plus the gallery byte size and distinct providers."""
    items = feed_list(limit=0)
    generated = sum(1 for item in items if item.get("source") == "generated")
    saved = len(items) - generated
    gallery = gallery_stats()
    providers = feed_distinct_providers()
    return {
        "total": len(items),
        "saved": saved,
        "generated": generated,
        "bytes": int(gallery.get("bytes") or 0),
        "providers": providers,
    }


def feed_delete(entry_id: str) -> int:
    """Cascade-delete a feed entry.

    When the id is a history id, the history entry is removed together with
    every gallery entry it owns (image files + metadata); when the id is a
    saved-only gallery id, just that gallery entry is removed. Idempotent:
    unknown ids remove nothing. Returns the number of gallery files deleted.
    """
    safe_id = _safe_entry_id(entry_id)
    gallery_ids: List[str] = []
    with _file_lock(history_file()):
        hist = _read_json(history_file(), [])
        kept = []
        for entry in hist:
            if str(entry.get("id")) == safe_id:
                gallery_ids = [str(g) for g in (entry.get("gallery_ids") or []) if g]
                continue
            kept.append(entry)
        if len(kept) != len(hist):
            _write_json(history_file(), kept)
    if not gallery_ids:
        # Saved-only entry: the id is itself a gallery id.
        try:
            if gallery_metadata(safe_id) is not None:
                gallery_ids = [safe_id]
        except ValueError:
            gallery_ids = []
    removed = 0
    for gid in gallery_ids:
        try:
            if gallery_metadata(gid) is not None:
                delete_gallery_entry(gid)
                removed += 1
        except ValueError:
            continue
    return removed
