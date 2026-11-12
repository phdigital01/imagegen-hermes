# ImageGen Development Procedure

## Repository roles

- `<repo>` — canonical source. Edit frontend/, backend/, e2e/
  and tests/ only here.
- Installed Hermes — `$HERMES_HOME` (on Windows usually `%LOCALAPPDATA%\hermes`);
  `$HERMES_AGENT` is its `hermes-agent` checkout.
  Receives native Git installs, or explicit legacy development syncs. Never
  edit the installed plugin as the canonical source.

There is no separate test worktree: the installed Hermes checkout is both the
build target and the e2e runtime. The old dedicated worktree
was removed in 2026-08.

## Native package release (recommended)

For normal users, follow [Install in Hermes Desktop](../manual/installation.md). The
repository itself is now a native package; users install the committed
artifacts through **Settings → Plugins → Install from Git**.

Maintainers run `npm --prefix scripts ci` and `npm --prefix scripts run build` here. The package builder compiles
only ImageGen, embeds its scoped utilities and CSS, and produces
`desktop/plugin.js` plus the root native manifests. Commit those artifacts
together with source changes. No installed Hermes checkout is required.

The sections below describe the **legacy bundled development** workflow.
They are not prerequisites for native installation. Do not use that flow to
install the disk package: a bundled ImageGen shadows a disk copy with the
same ID in Hermes.

## Legacy bundled release

Run the full pipeline in one command. It syncs the frontend and e2e files,
hash-verifies the synced tree against the canonical source, runs typecheck +
build, confirms the built bundle contains the current plugin markers, then
deploys the backend with a rollback snapshot. Any failure aborts before the
backend deployment.

```bash
cd <repo>
python scripts/release_host.py
```

Use `--skip-build` to stop after sync + verify (no typecheck/build or backend deployment), and
`--skip-marker-check` to skip the bundle marker verification.

## Frontend Change

1. Edit files in `<repo>\frontend`.
2. Run the workspace check.
3. Copy the frontend to the installed Hermes checkout.
4. Start the isolated Desktop development instance.
5. Open ImageGen and do the manual smoke checks.

```bash
cd <repo>
python scripts/verify_workspace.py
python scripts/sync_frontend.py --host $HERMES_AGENT --apply
cd $HERMES_AGENT/apps/desktop
npm run typecheck
npm run build
HERMES_DESKTOP_USER_DATA_DIR='<repo>/.desktop-user-data' HERMES_DESKTOP_CDP_PORT=off npm run dev:fake-boot
```

## E2E Change

The e2e assets live in the canonical repo (`e2e/`) and are copied to the
installed checkout by the release pipeline or directly:

```bash
cd <repo>
python scripts/sync_e2e.py --host $HERMES_AGENT --apply
```

Run the automated smoke test for tab rendering. The installed checkout has the
Hermes venv, so no extra env is normally needed:

```bash
cd $HERMES_AGENT/apps/desktop
HERMES_E2E_HERMES_BIN='$HERMES_AGENT/venv/Scripts/hermes.exe' npm run test:e2e -- --grep "ImageGen"
```

Without `HERMES_E2E_HERMES_BIN` the desktop app may fall into the first-run
onboarding screen ("Set up Hermes Desktop") and the test times out, because
the Electron main process cannot resolve a backend to launch.

This smoke spec and `e2e/host-fixtures.ts` date from the bundled release. The
spec looks for a Providers tab, which is now inside the ImageGen settings, and
the fixture copy is older than the one in a current Hermes checkout. Do not
sync them into Hermes 0.23 or later; use the screen check below.

## Screen check in a sandboxed Desktop

`e2e/local-server-check.spec.ts` opens a development Hermes Desktop on a
throwaway Hermes home, installs the plugin tree of this repository there, and
walks the Local server screens against a stand-in image server: provider list,
settings link, address, connection test, model picker, one generation, the
result actions that need FAL or Magnific, one generation the server refuses,
the gallery, a reference, the four languages and the server turned off. It also
asks for one image from a chat session, through the agent's `image_generate`
tool, and opens the ImageGen card of that image in a reply. It writes one
screenshot per state and `check.log`. It never touches the real Hermes home or
the running gateway. The stand-in server is not a model: the check proves the
screens and the request, not the image.

The spec runs from the Hermes checkout, which already has Playwright and
Electron. Copy it in, run it, and remove it, so the checkout stays clean:

```bash
cp <repo>/e2e/local-server-check.spec.ts $HERMES_AGENT/apps/desktop/e2e/imagegen-local-server-check.spec.ts
cd $HERMES_AGENT/apps/desktop
HERMES_E2E_IMAGEGEN_OUT=<absolute scratch folder> HERMES_E2E_IMAGEGEN_REPO=<repo> \
  npx playwright test e2e/imagegen-local-server-check.spec.ts --reporter=list --trace off \
  --output <absolute scratch folder>/pw-output
rm $HERMES_AGENT/apps/desktop/e2e/imagegen-local-server-check.spec.ts
```

It takes about four minutes. Notes:

- With `HERMES_E2E_IMAGEGEN_SERVER=http://127.0.0.1:1234` the same walk passes
  through a real image server at that address, so the two images are the
  model's. Start the server first and ask it for one image, because the first
  one after a start can take minutes. The waits grow to fit a slow model.
- The chat steps use the mock model of the Hermes suite: a message
  `E2E_CALL(tool)[arguments]` makes it call that tool. A session that defers
  its tools has no `image_generate` of its own, so the spec then calls it
  through the `tool_call` bridge, as a model does.
- When a state fails, the sandbox logs are copied to `sandbox-logs` in the
  scratch folder.
- It installs `HEAD`. For work that is not committed yet, build first and pass
  `HERMES_E2E_IMAGEGEN_REF=$(git -C <repo> stash create)`.
- Paths must be absolute, and `--output` must point outside the checkout: the
  suite moves the temporary folder for each run, and the default output folders
  are not ignored by the checkout's Git.
- The spec starts the sandbox gateway itself. From a tool shell on Windows the
  Desktop cannot start it (`windows_breakaway_unavailable`).
- The Desktop half of a plugin under `<home>/plugins` stays off until the
  person turns it on in Capabilities → Plugins. The spec stores that choice in
  `localStorage` (`hermes.desktop.pluginDecisions.v2`).
- A new screen state gets a `step` in the spec with its own screenshot.

## Backend Change

1. Edit files in `<repo>\backend`.
2. Run the backend tests (dedicated uv venv — the Hermes venv is stripped and
   has no pip/pytest; use the one-time setup below).
3. Run the backend sync in dry-run mode.
4. Read the target path.
5. Use `--apply` only when you want to test the installed backend.
6. Restart the Desktop application after you apply the backend.

`sync_backend.py --apply` now also:
- creates the installed plugin directory when it is missing (first install),
- adds `imagegen` to `plugins.enabled` in `config.yaml` (via `hermes plugins
  enable` or a minimal YAML edit fallback) — the backend only mounts when the
  plugin is on that allow-list. Disable with `--no-enable`.

One-time test venv setup. `pyyaml` lets the capability tests import the host's
`tools.image_generation_tool` and assert against the real FAL catalog instead
of skipping:

```bash
cd <repo>
uv venv ".venv-test" --python 3.11
uv pip install --python ".venv-test/Scripts/python.exe" pytest pyyaml fastapi httpx pillow
```

Run tests. Put the installed Hermes checkout on `PYTHONPATH` (`;`-separated on
Windows) so the tests that resolve capabilities against the real provider
catalog run instead of skipping:

```bash
cd <repo>
PYTHONPATH="backend;$HERMES_AGENT" \
  HERMES_HOME="$HERMES_HOME" \
  ".venv-test/Scripts/python.exe" \
  -m pytest -q tests backend/tests --basetemp .pytest-basetemp
```

The backend sync creates a rollback snapshot in `.snapshots/`. It does not copy `data/` or `.env` files.

## MCP integration

The plugin exposes its engine to the Hermes agent as MCP tools over stdio, so
the agent can generate with the plugin's provider catalog (capabilities
resolved by `imagegen_engine.capabilities.resolve_capabilities`), its subject
library and its reference pipeline instead of the host's generic image tool.

- Source of truth: `backend/mcp_server.py` (canonical). `sync_backend.py`
  copies it to the installed plugin (`$HERMES_HOME/plugins/imagegen/`), which
  is the file the host actually spawns in a legacy sync. A native Git install
  keeps the entry at `$HERMES_HOME/plugins/imagegen/backend/mcp_server.py`;
  use that path in the example below when configuring a native package.
- Registration: the host launches MCP servers listed under `mcp_servers` in
  `<HERMES_HOME>/config.yaml`. The `imagegen` entry follows the same shape as
  `codegraph` (back up `config.yaml` before editing, and edit the block
  surgically — never reserialize the file):

  ```yaml
  mcp_servers:
    codegraph:
      command: codegraph
      args:
        - serve
        - --mcp
      timeout: 120
      connect_timeout: 60
      enabled: true
    imagegen:
      command: $HERMES_AGENT/venv/Scripts/python.exe
      args:
        - $HERMES_HOME/plugins/imagegen/mcp_server.py
      timeout: 120
      connect_timeout: 60
      enabled: true
  ```

  `command` must be the hermes-agent venv python — the `mcp` SDK and the host
  packages (`tools.*`, `agent.*`) only resolve in that venv.

- Validate: run the installed server and perform a minimal stdio handshake
  (initialize + tools/list + one read-only tool call) with the hermes venv
  python:

  ```bash
  cd $HERMES_AGENT/venv
  ./Scripts/python.exe - <<'PY'
  import asyncio, os
  from mcp import ClientSession, StdioServerParameters
  from mcp.client.stdio import stdio_client

  async def main():
      params = StdioServerParameters(
          command="$HERMES_AGENT/venv/Scripts/python.exe",
          args=["$HERMES_HOME/plugins/imagegen/mcp_server.py"],
          env={**os.environ, "HERMES_HOME": "$HERMES_HOME"},
      )
      async with stdio_client(params) as (read, write):
          async with ClientSession(read, write) as session:
              await session.initialize()
              tools = await session.list_tools()
              print([t.name for t in tools.tools])
              res = await session.call_tool("imagegen_providers", {})
              print(res.content[0].text)

  asyncio.run(main())
  PY
  ```

  The handshake succeeds when it prints the tool names and the providers
  catalog (models with `refs=N`/`edit`/`upscale` flags).

- Tools (docstrings are what the agent reads to decide — keep them precise):
  - `imagegen_providers` — full provider/model catalog with capabilities.
  - `imagegen_subjects_list` — search the subject library.
  - `imagegen_subject_refs` — resolve a subject into reference image paths.
  - `imagegen_analyze` — vision analysis of refs + request → brief + prompt.
  - `imagegen_passport` — technical product passport from images.
  - `imagegen_optimize` — production-grade prompt rewrite.
  - `imagegen_generate` — catalog-aware generation with references; saves to
    the plugin gallery when `save_to_gallery` is true.
  - `imagegen_upscale` — FAL Clarity upscale. The desktop editing flow also
    exposes direct Magnific Precision and Creative; see [coverage](../references/magnific.md).
  - `imagegen_bg_remove` — background removal to transparent PNG.
- Every tool is guarded: `ImageGenError` failures return the stable code and
  message (e.g. `ERROR [refs.too_many]: ...`), never a traceback.

## Manual Smoke Check

1. Open ImageGen.
2. Open Generate, Edit, Campaign, and Gallery.
3. Change the ImageGen language.
4. Confirm that the thumbnail images render.
5. Generate a low-cost test image only when a configured provider is available.
6. Read the Desktop log for ImageGen errors.

## Release Build

Use a package build only after the isolated smoke check passes. The desktop
app executes from `release/win-unpacked`, so the app MUST be closed first
(otherwise the builder fails with EBUSY on locked files) and the packaging
must run from a plain terminal outside Hermes.

```bash
cd <repo>
python scripts/package_win_unpacked.py
```

The script rebuilds `dist/`, packages `win-unpacked`, and restores the exact
previous bytes of `apps/desktop/electron/main.cjs` in a `finally` block. The
builder can overwrite this source file with bundled output; keeping that
output in the checkout triggers the Hermes updater update-loop.

After packaging: start Hermes Desktop again.

Do not use the installed Hermes checkout as the editable source directory.

## Host maintenance

The installed Hermes checkout is updated by the Hermes updater. QA patches
that upstream may remove (Windows `electron.exe` resolution, `desktopEnv`
passthrough in `apps/desktop/e2e/fixtures.ts`, and the ImageGen smoke spec
under `apps/desktop/e2e/`) live canonically in `e2e/` here and are re-applied
by `sync_e2e.py` after any host update:

```bash
cd <repo>
python scripts/sync_e2e.py --host $HERMES_AGENT --apply
```

## Repository hygiene

- Do not commit `data/`, `.env`, caches, build output, or generated images.
- Exception: `desktop/plugin.js` and `desktop/build.json` are the committed
  native distribution artifacts. Rebuild them after frontend changes.
- `scripts/verify_workspace.py` fails on generated or secret files; run it
  before a release.
- Backend sync rollback snapshots live in `.snapshots/` and are safe to
  delete once a release is verified.

## ImageGen active-plan contracts

The ImageGen plugin keeps product data in
`$HERMES_HOME/plugin-data/imagegen/`, outside its installation directory.
The `data/` paths below are shorthand for that persistent root. No legacy
test-data migration is performed by native installation.
The active canvas flow uses these contracts:

- `data/handoffs/last.json` points to the latest successful generation handoff.
- `data/handoffs/{id}.json` stores the generation brief, prompt, references,
  model, provider, and feedback history.
- `GET /handoff/last`, `GET /handoff/{id}`, and `POST /handoff/feedback` are
  the agent bridge. The first agent action copies a short brief to the
  clipboard; it does not require MCP or a chat deep-link.
- Feedback refinement returns a diagnosis and a proposed prompt. It must not
  start a generation job until the user confirms the prompt.
- Edit is the single image-editing surface. Its modes are Global, Region,
  Expand, and Background. Stored `inpaint` tabs must migrate to `edit`.
- Subject Library records use an open `kind` string. Presets are shortcuts,
  not a closed enum; custom slugs such as `packaging_box` are valid.
- Subjects extend the objects index: multi-angle `angles[]`, content-hash
  dedupe on import, `GET /subjects`, `GET /subjects/kinds`,
  `POST /subjects/{id}/as-refs`, `POST /subjects/{id}/angles`,
  `PATCH /subjects/{id}`. Legacy `/objects*` routes remain aliases.
- Export pack: `GET /gallery/{id}/export-pack` returns JSON
  `{ path, url, filename }`; zip is at `GET /exports/{filename}`.
- Clear scoped data: `POST /settings/clear-data` with `confirm: "CLEAR"`.
- Model capabilities have ONE resolver: `dashboard/capabilities.py`
  `resolve_capabilities(provider, model, provider_obj=, model_meta=)`. FAL and
  Nous Portal catalog ids resolve through the host's `FAL_MODELS`
  (`edit_endpoint`, `max_reference_images`); registered Hermes providers
  resolve through `provider_obj.capabilities()`. `referenceImages` is always
  derived as `maxReferences > 0` — never trusted from input.
- References are prepared per provider by
  `gen_service.prepare_reference_sources(provider, model, refs, max_refs=)`.
  `reference_mode_for(provider)` returns `url` for backends that fetch the
  image (fal, krea — local paths are published through the FAL / nous-upload
  gateway) and `local` for SDKs that read the bytes themselves (openai,
  openai-codex, xai, openrouter, nous).
- A reference is never dropped in silence. Over the model's cap, unresolvable,
  or unsupported by the backend all raise with an actionable message.
- `GET /feed` is the single read model over the two stores: history entries
  (`source: "generated"`) joined with gallery entries that no history entry
  owns (`source: "saved"`), deduped by `gallery_ids` and sorted by `ts`.
  `DELETE /feed/{id}` cascades to the gallery files and metas.
- The UI has four tabs: Generate, Edit, Campaign, Gallery. Gallery is the only
  library surface — the former History tab is a `source` filter on the feed.
  Stored `history` tabs migrate to `gallery`, stored `inpaint` tabs to `edit`.
- Campaign is the only matrix surface. `ZONE_PRESETS`, `MatrixScene`, and
  `MatrixCell` must exist only in `CampaignMatrixTab.tsx`.
- The active generation job ID lives in `plugin.tsx`. Edit and Campaign
  persist their own job IDs in namespaced storage, so switching tabs does
  not discard their tracking IDs.
- The REST surface is split by domain. `dashboard/plugin_api.py` is a thin
  aggregator exporting `router`; the handlers live in `dashboard/routes/*`
  (system, llm, jobs, generation, library, media), each built with
  `api_core.make_router()` so the structured error envelope applies to every
  route. Shared pieces: `api_core` (envelope, URL helpers, `_to_thread`),
  `providers_catalog` (provider listing), `generation_artifacts`
  (gallery/history persistence, generation job builder) and `operations`
  (validated operation factories shared with explicit retries).
- The service layer has two halves that never import each other:
  `gen_service` produces pixels and spends money (providers, references, cost,
  `billing.run`); `llm_service` writes text and reads images (`_llm_call`,
  `_vision_call`, optimize/refine/translate/composition/passport). Routes may
  depend on both. `test_imagegen_contracts.py` pins the direction — a single
  import across it merges them back into one module with two filenames.
- Provider dispatch is a registry: `gen_service._PROVIDER_BACKENDS` maps a
  provider to a backend with one shared keyword-only signature. Anything not
  in the registry falls through to the registered-provider / FAL path. Every
  backend returns `{images, provider, model, modality, references_used,
  cost_estimate}`.
- Jobs survive a restart. `data/jobs.json` holds one record per job; the FAL
  `request_id` is checkpointed via `Job.set_remote(...)` the moment the queue
  accepts, because that is when the money is spent. On import, `jobs.py`
  turns orphaned `queued`/`running` records into `interrupted` and hydrates
  them, so `GET /jobs` still lists them and `POST /jobs/{id}/resume` can
  re-fetch the paid result into the gallery.
- Spend is estimated. `billing.run` reserves image cost in `data/spend.json`
  before submission under an OS file lock shared by Dashboard and MCP.
  `store.budget_status()` includes estimated, unknown-price, and pending
  counts. Ambiguous submissions remain counted; known rejections release
  their reservation. Unknown prices are blocked under a configured limit.
  This does not measure provider invoices or prompt/vision LLM usage.
- Backend errors are localized at one place. Routes fail with
  `{ok:false,error:{code,message,params}}`; `api.rest` parses that envelope and
  throws `ImageGenApiError` whose message is already translated via
  `translateActive`. Never surface a raw backend string to the user — every
  `host.notifyError(error, …)` call site depends on this.
- The MCP server (`backend/mcp_server.py`) is the agent's door into the same
  engine. It is registered under `mcp_servers.imagegen` in the host
  `config.yaml`; see the MCP integration section.

Keep these regression checks when changing the plugin:

1. Clone REST request bodies before reading or modifying them.
2. Serve WebP with `image/webp`, including on Windows.
3. Key thumbnails by option value, not by display label.
4. Return absolute image URLs when the renderer is loaded from `file://`.
5. Do not auto-generate from a Not-good submission.
6. Subject `imageDataUrl` must never hold a filesystem path.
7. User-supplied image references only resolve inside `data/` or the Hermes
   image cache (magic-bytes + size validated); downloads are https-only with
   no redirects and no private-IP targets.
8. Cap `numImages` at `MAX_GENERATIONS` (8) before any paid submit.
9. Entry ids (`generationId`, gallery/handoff ids) are sanitized before use
   as filenames — no path traversal.
10. Long-running engine calls must not run inline on the gateway event loop
    (use `_to_thread` in routes; jobs already run in threads).
11. Every model in `GET /providers` carries capabilities from
    `resolve_capabilities`, including registered providers — `list_models()`
    does not report capabilities, `provider.capabilities()` does.
12. `POST /upload` writes the format `detect_mime` reports, and
    `GET /refs/{filename}` serves the matching media type.
13. `configForHistory` keeps `referencesV4` metadata (never `imageDataUrl`) so
    reusing a stored generation restores its references.
14. `frontend/i18n.ts`: every key declared in `Messages` exists in all four
    languages, no duplicates, and every `t('key')` call site resolves.
15. The `(method, path)` set mounted on `plugin_api.router` is pinned by
    `backend/tests/test_route_registry.py`. A route lost in a refactor fails
    there; static paths must stay ahead of the parametric ones that would
    shadow them.
16. `JobProgress` never auto-fires `onDone` for a terminal FAILURE. Consumers
    clear the job id inside `onDone`, which unmounts the panel in the same
    React batch — auto-firing makes the failure invisible. Only `completed`
    fires automatically; failed/cancelled/interrupted wait for the user.
17. A paid submission is checkpointed before it can be lost: FAL's
    `request_id` reaches `data/jobs.json` as soon as the queue accepts.
18. Money is never rendered with a flat `toFixed(2)` — per-image prices are
    sub-cent, so use `ui-helpers.formatUsd`.
19. No user-facing Portuguese in backend code. Route `detail=`, raised
    messages, and stored display defaults are English; the frontend localizes
    by error code or `t('key')`. Known exception: the preset catalog in
    `presets.py` (subject types, genres, structures) is still PT-only content.
