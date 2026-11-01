"""Reserve estimated spend across processes before any billable submission."""
from __future__ import annotations

import logging
from typing import Callable, Optional, TypeVar

from dashboard import store
from dashboard.errors import ImageGenError, MODEL_INVALID, PROVIDER_UNAVAILABLE

T = TypeVar("T")
logger = logging.getLogger(__name__)


def run(provider: str, model: str, estimate: Optional[float], operation: Callable[[], T], *, count: int = 1) -> T:
    reservation = store.reserve_spend(provider, model, estimate, count)
    try:
        result = operation()
    except BaseException as exc:
        rejected = isinstance(exc, ImageGenError) and exc.code in (MODEL_INVALID, PROVIDER_UNAVAILABLE)
        cause = exc
        while cause is not None:
            status = getattr(cause, "status_code", None) or getattr(cause, "code", None)
            if status in (400, 401, 403, 404, 422):
                rejected = True
            cause = cause.__cause__
        try:
            store.settle_spend(reservation, "rejected" if rejected else "uncertain")
        except Exception:
            logger.exception("Could not settle spend reservation %s", reservation)
        raise
    # A provider may report a failure in its answer; the attempt may still have been billed.
    failed = isinstance(result, dict) and result.get("success") is False
    # The reservation already counts toward the limit if this final write fails.
    try:
        store.settle_spend(reservation, "uncertain" if failed else "submitted")
    except Exception:
        logger.exception("Could not settle spend reservation %s", reservation)
    return result
