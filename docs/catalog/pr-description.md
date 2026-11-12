# plugin-catalog: bump imagegen to 1.7.0

Draft body for the catalog update PR against `NousResearch/hermes-agent`. ImageGen was added in
NousResearch/hermes-agent#147403. Fill in the new SHA and the check results on the day it is opened.

---

`sha` `f00dbf8` → `<new sha>`, `version` `1.6.0` → `1.7.0`, and `image:` and `screenshots:` follow
the pin. The description names the new provider and its disclosure. Submitted by the plugin's owner.

## New in 1.7.0

- **Local server provider.** With an address set in Settings → Plugins → ImageGen, the models of
  an image server on the user's own machine or network appear in the picker, with no API key and
  no cost. It speaks the OpenAI images API (`GET /v1/models`, `POST /v1/images/generations`), so
  it works with stable-diffusion.cpp `sd-server`, LocalAI and Ollama. Text to image only:
  references and edits are refused with a message. It answers public issue
  phdigital01/imagegen-hermes#1.
- **Budget.** An operation that costs nothing is no longer blocked by a monthly limit that was
  already reached.
- **Fixes.** "Set key in Settings" opens the ImageGen settings page. Variations on an image from a
  provider other than FAL or Magnific run on the model the menu names. After a failed generation
  the Generate button is ready again, and the retry button says whether a retry is paid. Result
  actions that need a provider the profile lacks show a lock before the click. The chat card no
  longer has empty space.

The full list is in `CHANGELOG.md` at the pin.

## Disclosure change

- **Network.** One new destination, and only when the user sets it: the local server address.
  Prompts for its models go straight to that address, with no proxy. ImageGen asks it for its
  model list at most once a minute, and the provider list never waits on it. Nothing is sent
  there while the address is empty, which is the default.
- **Settings.** Two new `config_schema` entries: `local_server_url` (`str`, read with
  `ctx.get_config`) and `local_server_key` (`secret`, env `IMAGEGEN_LOCAL_SERVER_KEY`, read with
  `agent.secret_scope.get_secret`), the second only for a server that asks for a bearer token.
- **Cost.** Local generations are recorded at zero cost.

The catalog description and the README at the pin say the same (rule 13).

## What did not change

- Declared capabilities: no tools, hooks or middleware. One `image_gen` provider, one transcript
  directive, one on-demand pane and the `hermes imagegen` subcommand, as in 1.6.0.
- Python dependencies: none added. The local provider uses the standard library.
- Private host imports (rule 9 warning): the same modules as 1.6.0, none added.
- `requires_hermes` stays `">=0.22.5"`.

## Verified

- `scripts/validate_plugin_catalog.py plugin-catalog/imagegen.yaml`: <result>.
- `hermes plugins validate` on the plugin tree at the pin: <result>.
- Installed from this public repository at the pin into a throwaway `HERMES_HOME`: <result>.
- Local server: <what ran against a real server and against the stand-in>.
- Backend and frontend suites on Windows 11: <counts>.
- The banner and screenshot URLs at the new pin return 200.
