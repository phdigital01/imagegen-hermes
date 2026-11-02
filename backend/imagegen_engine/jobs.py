"""ImageGen async job manager.

Image generations take seconds to minutes. Instead of holding the HTTP request
(and the frontend fetch), the plugin submits a job, the frontend polls
/jobs/{id}, and the result becomes ready at /jobs/{id}/result.

One daemon thread per job — no external queue, no new dependency.
A semaphore limits concurrent paid generations; cancel() is cooperative:
the engine checks the event between iterations/polls and aborts early.

Every state transition is persisted to data/jobs.json (see store.save_job_record),
so a process restart cannot lose a paid generation: queued/running records are
marked ``interrupted`` at import and re-surfaced; when they carry a ``remote``
checkpoint (the provider request_id), POST /jobs/{id}/resume re-fetches the
result and saves it to the gallery.
"""
from __future__ import annotations

import logging
import os
from copy import deepcopy
import threading
import time
import uuid
from typing import Any, Callable, Dict, Optional

from imagegen_engine import store
from imagegen_engine.events import announce
from imagegen_engine.errors import ImageGenError, JOB_INTERRUPTED
from imagegen_engine.gen_service import JobCancelledError

logger = logging.getLogger(__name__)

MAX_JOBS = 32
MAX_CONCURRENT = 3

# Limits simultaneous paid submissions (FAL/Portal). Jobs beyond that stay
# "queued" until a slot opens — the semaphore does not block the HTTP route.
_SEMAPHORE = threading.BoundedSemaphore(MAX_CONCURRENT)


class Job:
    __slots__ = (
        "id", "kind", "status", "created", "started", "finished",
        "progress", "message", "result", "error", "error_code", "error_params",
        "payload", "remote", "_cancel", "thread",
        "remotes", "owner_pid", "client_request_id",
    )

    def __init__(self, kind: str) -> None:
        self.id = uuid.uuid4().hex[:10]
        self.kind = kind
        self.status = "queued"  # queued | running | completed | failed | cancelled | interrupted
        self.created = time.time()
        self.started: Optional[float] = None
        self.finished: Optional[float] = None
        self.progress: Optional[float] = None  # 0..1 (when known)
        self.message: str = ""
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.error_code: Optional[str] = None
        self.error_params: Dict[str, Any] = {}
        self.payload: Optional[Dict[str, Any]] = None
        self.remote: Optional[Dict[str, Any]] = None
        self.remotes: list[Dict[str, Any]] = []
        self.owner_pid = os.getpid()
        self.client_request_id = ""
        self._cancel = threading.Event()
        self.thread: Optional[threading.Thread] = None

    @classmethod
    def from_record(cls, record: Dict[str, Any]) -> "Job":
        """Rebuild a Job from a persisted record (no thread, no cancel event).

        Used to hydrate records left by a previous process. ``interrupted``
        records get the JOB_INTERRUPTED error code so the frontend can map the
        state to a localized message.
        """
        job = cls.__new__(cls)
        job.id = str(record.get("id") or "")
        job.kind = str(record.get("kind") or "generate")
        job.status = str(record.get("status") or "interrupted")
        job.created = float(record.get("created") or time.time())
        started = record.get("started")
        job.started = float(started) if isinstance(started, (int, float)) else None
        finished = record.get("finished")
        job.finished = float(finished) if isinstance(finished, (int, float)) else None
        job.progress = record.get("progress")
        job.message = str(record.get("message") or "")
        result = record.get("result")
        job.result = deepcopy(result) if isinstance(result, dict) else None
        job.error = record.get("error")
        job.error_code = record.get("errorCode")
        job.error_params = dict(record.get("errorParams") or {})
        payload = record.get("payload")
        job.payload = dict(payload) if isinstance(payload, dict) else None
        remote = record.get("remote")
        job.remote = dict(remote) if isinstance(remote, dict) and remote.get("requestId") else None
        job.remotes = [dict(item) for item in (record.get("remotes") or []) if isinstance(item, dict) and item.get("requestId")]
        if not job.remotes and job.remote:
            job.remotes = [job.remote]
        job.owner_pid = int(record.get("ownerPid") or 0)
        job.client_request_id = str(record.get("clientRequestId") or "")
        job._cancel = threading.Event()
        job.thread = None
        if job.status == "interrupted":
            job.error_code = job.error_code or JOB_INTERRUPTED
            job.error = job.error or "Interrupted by process restart"
        return job

    def cancel(self) -> None:
        self._cancel.set()
        self.message = "Cancelling…"

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check_cancelled(self) -> bool:
        """Cooperative poll for the engine (bound method, re-evaluated on each
        iteration/poll — the ``cancelled`` property is a bool and does not work)."""
        if not self._cancel.is_set():
            record = store.get_job_record(self.id)
            if record and record.get("cancelRequested"):
                self._cancel.set()
        return self._cancel.is_set()

    def elapsed(self) -> float:
        base = self.started or self.created
        end = self.finished or time.time()
        return max(0.0, end - base)

    def to_dict(self, include_result: bool = False) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created": self.created,
            "elapsed": round(self.elapsed(), 1),
            "message": self.message,
        }
        if self.progress is not None:
            d["progress"] = round(self.progress, 3)
        if self.error:
            d["error"] = self.error
        if self.error_code:
            d["errorCode"] = self.error_code
            d["errorParams"] = dict(self.error_params)
        if self.remote:
            d["remote"] = dict(self.remote)
        d["recoverable"] = any(not item.get("saved") for item in self.remotes)
        from imagegen_engine.operations import RETRY_KINDS
        d["retryable"] = self.status == "failed" and self.kind in RETRY_KINDS and self.payload is not None and not d["recoverable"]
        d["hasPartialResult"] = self.result is not None
        if include_result and self.result is not None:
            d["result"] = self.result
        return d

    def to_record(self) -> Dict[str, Any]:
        """Full persisted shape (contract for data/jobs.json)."""
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "created": self.created,
            "started": self.started,
            "finished": self.finished,
            "message": self.message,
            "error": self.error,
            "errorCode": self.error_code,
            "errorParams": dict(self.error_params),
            "payload": dict(self.payload) if self.payload else None,
            "remote": dict(self.remote) if self.remote else None,
            "remotes": deepcopy(self.remotes),
            "result": deepcopy(self.result),
            "progress": self.progress,
            "ownerPid": self.owner_pid,
            "clientRequestId": self.client_request_id,
            "cancelRequested": self._cancel.is_set(),
        }

    def set_remote(self, provider: str, model: str, request_id: str, endpoint: str) -> None:
        """Record the provider checkpoint and persist it immediately.

        Called the moment the provider accepts the paid request — from here on
        the money has been spent, and the request_id is the only way to recover
        the result after a restart (see POST /jobs/{id}/resume).
        """
        checkpoint = request_id if isinstance(request_id, dict) else {}
        self.remote = {
            "provider": str(provider),
            "model": str(model),
            "requestId": str(request_id),
            "endpoint": str(endpoint),
            **checkpoint,
        }
        if not any(item.get("requestId") == self.remote["requestId"] for item in self.remotes):
            self.remotes.append(dict(self.remote))
        store.save_job_record(self.to_record())

    def checkpoint(self, remote: Dict[str, Any]) -> None:
        self.set_remote(remote.get("provider", "fal"), remote.get("model", ""), remote, remote.get("endpoint", ""))

    def save_partial(self, result: Dict[str, Any], *, completed_request: bool = False) -> None:
        previous_result = self.result
        previous_remotes = deepcopy(self.remotes)
        previous_remote = deepcopy(self.remote)
        self.result = deepcopy(result)
        if completed_request:
            self.mark_remote_saved()
        try:
            store.save_job_record(self.to_record())
        except Exception:
            self.result = previous_result
            self.remotes = previous_remotes
            self.remote = previous_remote
            raise

    def mark_remote_saved(self) -> None:
        if self.remotes:
            self.remotes[-1]["saved"] = True
            if self.remote:
                self.remote["saved"] = True


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()

    def _persist(self, job: Job) -> None:
        """Best-effort write of a job record — never breaks the job thread."""
        try:
            store.save_job_record(job.to_record())
        except Exception:  # noqa: BLE001
            logger.exception("failed to persist job %s", job.id)
        _announce(job)

    def submit(self, kind: str, fn: Callable[[Job], Dict[str, Any]], payload: Optional[Dict[str, Any]] = None) -> Job:
        job = Job(kind)
        job.payload = deepcopy(payload)
        job.client_request_id = str((payload or {}).get("clientRequestId") or "")
        with self._lock, store._file_lock(store.jobs_file()):
            if job.client_request_id:
                for record in store.load_job_records():
                    if record.get("clientRequestId") == job.client_request_id:
                        if record.get("payload") != job.payload or record.get("kind") != kind:
                            raise ImageGenError("job.conflict", "Request ID already belongs to another operation")
                        return self._jobs.get(record["id"]) or Job.from_record(record)
            if sum(item.status in ("queued", "running", "recovering") for item in self._jobs.values()) >= MAX_JOBS:
                raise ImageGenError("job.queue_full", "The job queue is full; wait for a task to finish")
            # Prune old jobs (keep the 32 most recent)
            if len(self._jobs) >= MAX_JOBS:
                for old in sorted(
                    [j for j in self._jobs.values() if j.status in ("completed", "failed", "cancelled")],
                    key=lambda j: j.finished or 0,
                )[:8]:
                    self._jobs.pop(old.id, None)
            # Durability is required before starting a potentially paid worker.
            store.save_job_record(job.to_record())
            self._jobs[job.id] = job

        def _run() -> None:
            if job.check_cancelled():
                job.status = "cancelled"
                job.message = "Cancelled"
                job.finished = time.time()
                self._persist(job)
                return
            _SEMAPHORE.acquire()
            try:
                if job.check_cancelled():
                    job.status = "cancelled"
                    job.message = "Cancelled"
                    job.finished = time.time()
                    self._persist(job)
                    return
                job.status = "running"
                job.started = time.time()
                job.message = "Starting…"
                self._persist(job)
                try:
                    result = fn(job)
                    job.result = result
                    if job.cancelled:
                        job.status = "cancelled"
                        job.message = "Cancelled"
                    else:
                        job.status = "completed"
                        job.result = result
                        job.message = "Completed"
                except JobCancelledError:
                    job.status = "cancelled"
                    job.message = "Cancelled"
                except Exception as exc:  # noqa: BLE001
                    logger.exception("job %s failed", job.id)
                    pending = any(not item.get("saved") for item in job.remotes)
                    job.status = "cancelled" if job.cancelled else "interrupted" if pending else "failed"
                    job.error = str(exc)
                    if isinstance(exc, ImageGenError):
                        job.error_code = exc.code
                        job.error_params = dict(exc.params)
                    job.message = "Failed"
                finally:
                    job.finished = time.time()
            finally:
                _SEMAPHORE.release()
            self._persist(job)

        job.thread = threading.Thread(target=_run, name=f"imagegen-{job.kind}", daemon=True)
        job.thread.start()
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None and job.owner_pid == os.getpid():
                return job
            record = store.get_job_record(job_id)
            if record is not None:
                job = Job.from_record(record)
                self._jobs[job_id] = job
            return job

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if job is None or job.status not in ("queued", "running"):
            return False
        job.cancel()
        with store._file_lock(store.jobs_file()):
            record = store.get_job_record(job_id)
            if record:
                record["cancelRequested"] = True
                store.save_job_record(record)
        if job.status == "queued" and job.owner_pid == os.getpid() and job.thread is not None:
            job.status = "cancelled"
            job.finished = time.time()
            self._persist(job)
        return True

    def resume(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return the persisted record of an interrupted job with a checkpoint.

        ``None`` when the job does not exist, is not interrupted, or carries no
        ``remote`` request id (nothing to re-fetch). The route uses the record's
        ``remote`` to re-poll the provider and its ``payload`` to re-run the
        gallery save.
        """
        job = self.get(job_id)
        if job is None or job.status not in ("interrupted", "failed", "cancelled") or not any(not item.get("saved") for item in job.remotes):
            return None
        with store._file_lock(store.jobs_file()):
            current = store.get_job_record(job_id)
            if not current or current.get("status") not in ("interrupted", "failed", "cancelled"):
                return None
            job.status = "recovering"
            job.owner_pid = os.getpid()
            store.save_job_record(job.to_record())
        return job.to_record()

    def recovery_failed(self, job_id: str) -> None:
        job = self.get(job_id)
        if job is not None and job.status == "recovering":
            job.status = "interrupted"
            self._persist(job)

    def mark_completed(self, job_id: str, result: Dict[str, Any]) -> bool:
        """Transition an interrupted job to completed after a successful resume."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status not in ("interrupted", "recovering"):
                return False
            job.status = "completed"
            job.result = result
            job.error = None
            job.error_code = None
            job.error_params = {}
            job.message = "Completed"
            job.finished = time.time()
        self._persist(job)
        return True

    def list(self) -> list:
        with self._lock:
            for record in store.load_job_records():
                if record["id"] not in self._jobs or self._jobs[record["id"]].owner_pid != os.getpid():
                    try:
                        self._jobs[record["id"]] = Job.from_record(record)
                    except Exception:  # noqa: BLE001 — a hand-edited record must not break GET /jobs
                        logger.warning("skipping malformed job record %s", record.get("id"))
            jobs = sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)
            return [j.to_dict() for j in jobs[:10]]


def _announce(job: Job) -> None:
    announce("job.changed", {"id": job.id, "kind": job.kind, "status": job.status})


def _hydrate_persisted_jobs() -> None:
    """Re-surface jobs left by a previous process (called once at import).

    Records that were queued/running become ``interrupted`` in the store and
    are hydrated into the manager so they appear in GET /jobs and can be
    resumed when they carry a ``remote`` checkpoint. A missing or corrupt
    jobs.json is handled inside the store and never breaks the import.
    """
    try:
        orphans = store.mark_orphan_jobs_interrupted()
    except Exception:  # noqa: BLE001
        logger.exception("job store unavailable; persisted jobs not hydrated")
        return
    for record in orphans:
        try:
            job = Job.from_record(record)
        except Exception:  # noqa: BLE001
            logger.exception("could not hydrate job record %s", record.get("id"))
            continue
        if job.id:
            manager._jobs[job.id] = job


manager = JobManager()
_hydrate_persisted_jobs()
