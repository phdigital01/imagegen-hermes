# Generated from backend/__init__.py by npm run build.
"""ImageGen plugin package.

ImageGen is a *dashboard/desktop* plugin: its surface is the FastAPI router in
``dashboard/plugin_api.py``, discovered through ``dashboard/manifest.json`` and
mounted at ``/api/plugins/imagegen/*``. The desktop UI reaches it via
``ctx.rest``.

It adds no agent tool: the host's ``image_generate`` tool stays the only one,
so the model never sees two competing tools for one job. Instead ImageGen
registers an ``image_gen`` provider. When the user picks it under Tools ->
Image Generation, the agent's images go through ImageGen's providers and land
in its gallery and budget (``dashboard/chat_provider.py``).
"""


def register(ctx) -> None:  # noqa: ANN001 - ctx is the host PluginContext
    """Plugin entry point.

    Hands the host-owned LLM facade (``ctx.llm``) to the REST routes, which use
    it to write prompts and read reference images, and registers the opt-in
    ``imagegen`` image provider.
    """
    import sys
    from pathlib import Path

    # Same resolution as dashboard/plugin_api.py: dashboard.* is backend/dashboard.
    backend = Path(__file__).resolve().parent
    backend = backend if (backend / "dashboard" / "host_llm.py").is_file() else backend / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from dashboard import host_llm

    host_llm.bind(ctx)

    if hasattr(ctx, "register_image_gen_provider"):
        from dashboard.chat_provider import ImageGenChatProvider

        ctx.register_image_gen_provider(ImageGenChatProvider())
