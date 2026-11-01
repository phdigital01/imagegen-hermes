# Native Hermes Desktop installation

## From Git

In **Capabilities → Plugins → Install from Git**, enter:

```text
https://github.com/phdigital01/imagegen-hermes
```

For a local checkout, use its `file://` URL instead (for example
`file:///C:/src/imagegen-hermes`).

Select both **Agent plugin** (the Python API) and **Desktop UI**, enable the
agent plugin, and confirm. Hermes installs the Desktop UI turned off: turn on
ImageGen in **Capabilities → Plugins**. Restart Hermes once so its gateway
imports the new REST routes.

The installer uses `git clone`, including for local URLs: only committed
files are installed. It may show `imagegen-hermes` as the Desktop package
folder; the actual plugin ID and backend namespace remain `imagegen`.

If an older test installation already owns either target folder, the
installer offers **Force reinstall**. This replaces the installed package.
The new package keeps runtime data in the profile's `plugin-data/imagegen/`.
It does not import data from the old bundled test version.

An existing custom app with a **bundled** ImageGen skips disk copies with the
same ID. Disabling that bundled plugin does not remove this precedence rule.
Install into a regular Hermes Desktop build without the bundled test copy.
The package does not modify or rebuild the user's application.

## Remote repository and install button

A fork can be hosted in any public or private Git repository. Paste its
HTTPS/SSH URL into the same installer. For private repositories, Git must
already authenticate noninteractively in the Desktop environment.

A web page can link straight to the Desktop installer:

```html
<a href="hermes://plugin/install?repo=phdigital01/imagegen-hermes&enable=1">Install in Hermes</a>
```

The link opens the Desktop confirmation dialog; it does not install silently.

## Package contract

- Root `plugin.yaml` and `__init__.py` identify the native backend package.
- `dashboard/manifest.json` points to a small entry bridge; all API source
  remains under `backend/dashboard/`.
- `desktop/plugin.js` is a single ESM bundle. It contains the compiled UI,
  translations, Tailwind utilities, and custom styles. It imports only the
  host's `@hermes/plugin-sdk`, `react`, and `react/jsx-runtime` singletons.
- Styles attach when enabled and are removed on disposal. Utility styles are
  scoped to ImageGen roots and its portalled dialogs/menus. No document-wide
  Tailwind reset is included.
- `desktop/build.json` records bundle size, SHA-256, version, and normalized
  source hashes. Build inputs and dependency versions are in this repository.
- Credentials remain in the Hermes profile (plugin secrets in Settings → Plugins → ImageGen). Images, jobs, recipes, gallery,
  and accounting records use `plugin-data/imagegen/` outside the Git tree.

Hermes supplies the Python runtime, backend dependencies, and provider
registry. The optional MCP entry remains `backend/mcp_server.py` in a native
Git installation; configuring that separate MCP process is not required for
the Desktop UI and is not performed by this installer.

## Preparing updates

Maintainers run `npm --prefix scripts ci` and `npm --prefix scripts run build`,
then commit source and generated package files together. Do not edit generated
root manifests or the bundle by hand. Update versions in `scripts/package.json`,
`backend/plugin.yaml`, and `backend/dashboard/manifest.json` together. The
build tooling lives in `scripts/` so the plugin root has no `package.json`:
Hermes would otherwise offer to install build-only Node packages at install
time. Installation has no npm/Python build step and does not use the legacy
`release_host.py` pipeline.

Use the native installer to reinstall both components for a Desktop update.
Updating only the agent package can leave the separately installed Desktop
copy on its previous version. Keep both components on the same revision.

Sources: [Desktop SDK](https://hermes-agent.nousresearch.com/docs/developer-guide/desktop-plugin-sdk),
[Desktop installation](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins#one-click-install-links-desktop),
[persistent plugin data](https://hermes-agent.nousresearch.com/docs/developer-guide/plugins#ship-data-files).
