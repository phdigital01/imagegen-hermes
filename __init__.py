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
in its gallery and budget (``imagegen_engine/chat_provider.py``).

It also registers ``hermes imagegen``, the command line for scripts and coding
agents (``imagegen_cli.py``). Hermes loads the profile picked with ``-p`` and
its secrets before the command runs.
"""


def register(ctx) -> None:  # noqa: ANN001 - ctx is the host PluginContext
    """Plugin entry point.

    Hands the host-owned LLM facade (``ctx.llm``) to the REST routes, which use
    it to write prompts and read reference images, and registers the opt-in
    ``imagegen`` image provider.
    """
    import sys
    from pathlib import Path

    # Same resolution as dashboard/plugin_api.py: the engine sits beside this
    # file (development sync) or under backend/ (package install).
    backend = Path(__file__).resolve().parent
    backend = backend if (backend / "imagegen_engine" / "host_llm.py").is_file() else backend / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from imagegen_engine import host_llm

    host_llm.bind(ctx)

    if hasattr(ctx, "register_image_gen_provider"):
        from imagegen_engine.chat_provider import ImageGenChatProvider

        ctx.register_image_gen_provider(ImageGenChatProvider())

    if hasattr(ctx, "register_cli_command"):
        import importlib.util

        # One gateway process hosts several profiles. A plain `import imagegen_cli` can return the module
        # that another profile, or the version replaced by an update, already left in sys.modules.
        source = backend / "imagegen_cli.py"
        spec = importlib.util.spec_from_file_location(f"imagegen_cli_{abs(hash(str(source)))}", source)
        imagegen_cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(imagegen_cli)

        ctx.register_cli_command(
            name="imagegen", help="Generate and edit images with ImageGen",
            setup_fn=imagegen_cli.setup_hermes_command, handler_fn=imagegen_cli.run_hermes_command,
            description="Generate or edit images with the profile's ImageGen providers, gallery and budget. "
                        "Run `hermes -p <profile> imagegen --list` to see the providers.")
