# Contributing

Bug reports and pull requests are welcome. Open an issue first for a large change or a new provider.
Never paste a key, a private image or a local path in an issue.

## Repository layout

```text
plugin.yaml  Native installer manifest (generated from backend/)
__init__.py  Native Python entry (generated from backend/)
dashboard/   Native REST manifest and entry bridge
desktop/     Committed ESM bundle and build metadata
frontend/    TypeScript and CSS source
backend/     Canonical Python implementation and metadata
tests/       Backend tests
scripts/     Package build and legacy development sync tools
docs/        Manual, runbooks, references and the catalog entry
```

The optional legacy bundled development flow copies `frontend/` to:

`apps/desktop/src/plugins/imagegen/`

Normal installation clones this whole repository into:

`$HERMES_HOME/plugins/imagegen/`

Runtime data lives in `$HERMES_HOME/plugin-data/imagegen/`, outside the install
tree. Native reinstalls and updates do not replace that data directory.

## Local workflow

Read [docs/runbooks/development.md](docs/runbooks/development.md) before you change source files.

To prepare a distributable update (maintainers only):

```bash
npm --prefix scripts ci
npm --prefix scripts run build
```

Commit source changes together with `desktop/`, `plugin.yaml`, `__init__.py`,
and `dashboard/manifest.json`. The installer clones Git and never builds files.
The build tooling stays in `scripts/` on purpose: a `package.json` at the root
would make Hermes offer to install build-only Node packages.

Run the repository check:

```bash
python scripts/verify_workspace.py
```

Run backend tests:

```bash
cd backend
python -m pytest -q tests ../tests  # needs pytest, pyyaml, fastapi, httpx, pillow
```

Use `npm run dev:fake-boot` with isolated `HERMES_HOME` and user-data directories for a frontend smoke check.

Versions move together in `scripts/package.json`, `backend/plugin.yaml` and
`backend/dashboard/manifest.json`. Record each release in `CHANGELOG.md`.

New provider or model: [docs/runbooks/adding-models.md](docs/runbooks/adding-models.md).

## Rules

- Keep the user's intent and the reference image as separate inputs. Never drop a reference in silence.
- Base strings are in English and translated to pt, es and zh.
- Provider keys are `config_schema` secrets read with `get_secret`. LLM calls go through `ctx.llm`.

## Safety

- Do not edit ImageGen source in the installed Hermes checkout.
- Do not commit runtime data, `.env` files, caches, host build output, or generated images. The documented `desktop/` bundle is a required distribution artifact.
- `sync_backend.py` runs in dry-run mode by default.
- The backend sync creates a rollback snapshot before it changes installed files.
