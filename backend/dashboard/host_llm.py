"""The host-owned LLM facade (``ctx.llm``) handed to ``register(ctx)``.

Hermes gives each plugin a ``PluginLlm`` bound to its identity and trust policy.
``register`` stores the context here and the REST routes read ``ctx.llm`` on
first use (the host builds it lazily); the plugin never builds its own client
or reads provider credentials.
"""
from __future__ import annotations

import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_ctx: Optional[Any] = None
_tasks: set[str] = set()

# Own auxiliary slots, listed in Settings > Models > Auxiliary so the user can
# pick a model per job. Prompt writing uses the main model until pinned; image
# reading follows the user's vision slot.
TASKS = {
    "imagegen_prompt": dict(display_name="ImageGen prompts",
                            description="Writes, refines and translates ImageGen image prompts."),
    "imagegen_vision": dict(display_name="ImageGen image reading", inherit_from="vision",
                            description="Reads ImageGen reference images to plan compositions."),
}


def bind(ctx: Any) -> None:
    global _ctx
    registered = set()
    register_task = getattr(ctx, "register_auxiliary_task", None)
    for key, spec in TASKS.items():
        try:
            if register_task is not None:
                register_task(key, **spec)
                registered.add(key)
        except Exception as exc:  # noqa: BLE001 — older host or a stub context
            logger.warning("auxiliary task %s not registered: %s", key, exc)
    with _lock:
        _ctx = ctx
        _tasks.clear()
        _tasks.update(registered)


def task(key: str) -> Optional[str]:
    """``key`` when this plugin registered it; otherwise None (main model)."""
    return key if key in _tasks else None


def get() -> Optional[Any]:
    """The bound facade; loads plugins once when this process has not yet."""
    if _ctx is None:
        try:
            # Idempotent public loader: it calls register(ctx) for enabled plugins,
            # which binds the facade in a process that serves routes before loading.
            from hermes_cli.plugins import discover_plugins

            discover_plugins()
        except Exception:  # noqa: BLE001 — outside Hermes there is no host LLM
            return None
    return getattr(_ctx, "llm", None)
