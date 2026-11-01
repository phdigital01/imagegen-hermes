"""Structured error contract between the backend and the plugin UI.

Generation and reference failures raise :class:`ImageGenError` with a stable
dotted ``code`` and interpolation ``params``. The frontend maps the code to a
localized message (see ``frontend/i18n.ts``) and interpolates the params, so a
user in any supported language sees an actionable message in their language.

``str(exc)`` returns the English fallback message, so existing ``str(exc)``
call sites (job error strings, logs) keep working unchanged. The class
subclasses ``RuntimeError``, so existing ``except RuntimeError`` handlers
still catch every generation failure.
"""
from __future__ import annotations

from typing import Any, Dict


class ImageGenError(RuntimeError):
    """A failure the user can act on, carrying a stable code for localization."""

    def __init__(self, code: str, message: str, **params: object) -> None:
        super().__init__(message)
        self.code: str = code
        self.message: str = message
        self.params: Dict[str, Any] = dict(params)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to the wire shape ``{"code", "message", "params"}``."""
        return {"code": self.code, "message": self.message, "params": dict(self.params)}


# ---------------------------------------------------------------------------
# Stable error codes. The frontend i18n bundles carry one localized message
# per code (same placeholders). Add a code here only when a new domain needs
# one; keep the set small and named by domain.
# ---------------------------------------------------------------------------

# Reference-image pipeline.
REFS_MODEL_UNSUPPORTED = "refs.model_unsupported"      # params: model, provider
REFS_TOO_MANY = "refs.too_many"                        # params: model, max, provided
REFS_UNRESOLVED = "refs.unresolved"                    # params: ref
REFS_UPLOAD_FAILED = "refs.upload_failed"              # params: ref, detail
REFS_PROVIDER_UNSUPPORTED = "refs.provider_unsupported"  # params: provider

# Provider pipeline.
PROVIDER_UNAVAILABLE = "provider.unavailable"          # params: provider
PROVIDER_NOT_REGISTERED = "provider.not_registered"    # params: provider
PROVIDER_FAILED = "provider.failed"                    # params: provider, detail

# Model pipeline.
MODEL_NO_IMAGE = "model.no_image"                      # params: model, provider
MODEL_INVALID = "model.invalid"                        # params: model

# Jobs / auxiliary services.
JOB_CANCELLED = "job.cancelled"                        # params: {}
JOB_INTERRUPTED = "job.interrupted"                    # params: {}
LLM_UNAVAILABLE = "llm.unavailable"                    # params: detail (optional)
LLM_NO_VISION = "llm.no_vision_provider"               # params: detail
LLM_EMPTY_RESPONSE = "llm.empty_response"              # params: detail
LLM_TIMEOUT = "llm.timeout"                            # params: detail
VISION_UNAVAILABLE = LLM_NO_VISION                     # alias — same code, semantic name
VISION_EMPTY = LLM_EMPTY_RESPONSE                      # alias

# Spend control.
BUDGET_EXCEEDED = "budget.exceeded"                    # params: spent, limit, estimate
