# ImageGen for Hermes Desktop

![ImageGen](docs/catalog/banner.png)

One studio for all your image models, inside Hermes Desktop. Generate, edit, relight,
restyle, cut out and run campaigns from one place, and keep every result in one gallery.
Use the ChatGPT subscription you already pay for, or any API key your Hermes profile has.

- **All your models in one form.** GPT Image on your subscription, FAL, Nous Portal,
  Magnific, Vertex AI and the Hermes image providers. The form applies each model's real
  limits, and Settings says what each provider can do.
- **Direct with pictures, not jargon.** Style, light, angle, framing and camera are
  a board of images. Each option shows the same scene with that one change.
- **Edit without losing quality.** Models redraw the whole picture on every edit,
  so an image gets softer each round. ImageGen puts back only the area that changed.
  The rest stays identical, pixel for pixel, after any number of edits. When you
  change the whole picture, it keeps the model's answer and tells you.
- **Campaigns and a gallery.** One product across several scenes in one batch. Every
  result keeps its prompt, model and settings, ready to reuse.
- **Works from any coding agent.** Claude Code, Codex or anything with a terminal can
  [generate a hundred images in one command](#use-it-from-coding-agents), and they land
  in the same gallery as yours.

![Two edits in a row: only the changed area returns over the source](docs/catalog/edit-demo.gif)

## What it does

- **Generate** with FAL, Nous Portal, Magnific, Vertex AI and the Hermes image providers
  (OpenAI, Grok, Krea, DeepInfra, OpenRouter) from one form, with each model's
  real limits applied (references, sizes, seeds). FAL's whole public catalog
  is listed and kept up to date, so new FAL models appear without an update.
- **Compose** from reference images: the active Hermes model reads them and
  plans the shot before you pay for a generation.
- **Edit**: instruction edits with any FAL edit model or with GPT Image on your
  subscription, masked fill, relight, style transfer, expand, camera angle, skin
  retouch, background removal and upscaling. An edit returns only the area that
  changed, so five edits in a row leave the rest of the image pixel for pixel as
  it was. Every step stays as a version you can go back to.
  A subscription does all of this except background removal and upscaling.
- **Campaign**: one product across several scenes in one batch.
- **Gallery and recipes**: every result keeps its prompt, model and settings.
- **Local budget**: a monthly limit that reserves the estimated cost before a
  paid request is sent.
- **Works with the chat**: pick ImageGen under **Tools → Image Generation** and
  the agent's images use your ImageGen provider, land in the gallery and count
  toward the budget, with an Edit button under each one. **Ask the agent**
  puts an image and its prompt in the chat input, and a small pane beside the
  chat shows the job in progress and your latest images.

ImageGen starts on the provider your account already has: a linked ChatGPT
subscription or Nous Portal first, then your API keys.

The interface follows the Hermes app language (English, Portuguese, Spanish
or Chinese) and can be pinned to one of them.

## Install

1. In Hermes Desktop, open **Capabilities → Plugins → Install from Git**.
2. Paste `https://github.com/phdigital01/imagegen-hermes`.
3. Select **Agent plugin** and **Desktop UI**, keep **Enable agent plugin after
   install** on, and confirm.
4. Hermes installs the Desktop UI turned off. Turn on **ImageGen** in
   **Capabilities → Plugins**.
5. Restart Hermes once so the backend routes load, then open **ImageGen** in
   the sidebar.

From a terminal: `hermes plugins install phdigital01/imagegen-hermes --enable`,
then turn on the Desktop UI as in step 4. Requires Hermes 0.22.5 or newer.

## Screenshots

| Generate | Gallery |
|---|---|
| ![Generate](docs/catalog/screenshots/generate.png) | ![Gallery](docs/catalog/screenshots/gallery.png) |
| **Edit** | **Campaign** |
| ![Edit](docs/catalog/screenshots/edit.png) | ![Campaign](docs/catalog/screenshots/campaign.png) |

The sample images were generated with GPT Image through ImageGen.

## Use it from coding agents

ImageGen also works without opening the screen. Claude Code, Codex or any other agent that can run
a terminal command can call its command line. It uses the keys, the gallery and the budget of a
Hermes profile, so images made by an agent appear in the same gallery as yours.

```text
python $HERMES_HOME/plugins/imagegen/backend/imagegen_cli.py --profile <name> \
    --prompt-file prompt.txt --ref photo.jpg --aspect 4:5 --out ./images --name hero
```

Use the Python of the Hermes install. The result prints as JSON, and `--batch` runs many images
at once. Each image is billed by its provider. Details are in
[What this plugin does on your machine](#what-this-plugin-does-on-your-machine).

## Providers and keys

ImageGen reuses what your Hermes profile already has. A Nous Portal
subscription and the Hermes image providers need no extra setup. These keys are
optional and live in **Settings → Plugins → ImageGen**:

| Setting | Variable | Enables |
|---|---|---|
| FAL API key | `FAL_KEY` | FAL models without a Nous Portal subscription |
| Magnific API key | `MAGNIFIC_API_KEY` | Magnific generation, upscale, relight and background removal |
| Vertex AI API key | `VERTEX_API_KEY` | Gemini image generation on Google Cloud Vertex AI |
| Vertex AI project ID | `VERTEX_PROJECT` | The project for a key bound to a service account |

The plugin reads them through the Hermes secret store and never opens or writes
`.env` files itself. The only exception is the command line below: `--profile`
asks Hermes's own loader to load that profile's keys, as Hermes does at start.

Prompt writing and image reading use your active Hermes model through the
plugin LLM API. They appear as two auxiliary slots, **ImageGen prompts** and
**ImageGen image reading**, in **Settings → Models → Auxiliary**. Image reading
follows your vision model until you pin another one.

## What this plugin does on your machine

Read this before you install.

- **Paid requests.** Each generation, edit or upscale is billed by the
  provider that runs it: FAL, Magnific, the Nous Portal, Vertex AI, or the Hermes image
  provider you pick. On the ImageGen screen every paid action starts from a
  button you click. The agent spends only if you choose ImageGen under
  **Tools → Image Generation** (then each `image_generate` call goes through
  ImageGen) or register the optional MCP server below. The local monthly budget uses ImageGen's own
  estimates. It is not a provider invoice. Unknown prices are blocked while a
  limit is set.
- **Network calls.** Prompts and reference images go to the provider you pick:
  `queue.fal.run` and `fal.run` (FAL, including reference uploads),
  `api.magnific.com` (Magnific), `aiplatform.googleapis.com` (Vertex AI), the Nous Portal tool gateway, or the endpoint
  of the Hermes image provider. A linked ChatGPT subscription is reached only
  through that Hermes provider, so ImageGen never sees its sign-in token. Prompt
  writing and image reading go to your
  active Hermes model. Once a day ImageGen also reads FAL's public model list
  from `api.fal.ai` (no prompts or images are sent).
- **Local data.** Images, gallery, history, recipes, jobs and the spending
  ledger are stored in `$HERMES_HOME/plugin-data/imagegen/`. You can also set
  an export folder. Clearing data in the plugin asks for confirmation.
- **Agent integration.** The plugin registers no tools, hooks or commands. It
  registers one image provider, **ImageGen**, which stays unused until you pick
  it under **Tools → Image Generation**. Its results tell the model it may add
  an `::imagegen-image{id="…"}` line, which Desktop shows as ImageGen's Edit
  and gallery buttons.
- **Host integration.** To list and call the Hermes image providers, the Nous
  Portal gateway and the FAL catalog, ImageGen imports a few Hermes modules
  that are not yet public plugin APIs. A Hermes update can change them and
  break those providers until ImageGen is updated.
- **Optional MCP server.** `backend/mcp_server.py` exposes generation to the
  agent over stdio. It runs only if you add it to `mcp_servers` in your Hermes
  `config.yaml` yourself; it then spends money like the screen does.
- **Command line.** `backend/imagegen_cli.py` runs one generation from a
  terminal or a coding agent, with the Hermes venv Python. Each run is billed
  like a click on **Generate**, and `--retries` attempts may each be billed.

  ```text
  python $HERMES_HOME/plugins/imagegen/backend/imagegen_cli.py --profile <name> \
      --prompt-file prompt.txt --ref photo.jpg --aspect 4:5 --out ./images --name hero
  ```

  `--profile` uses that profile's keys and gallery. Without `--provider` and
  `--model` it uses ImageGen's own choice; `--list`
  prints the providers it can use now and `--list <provider>` their models. References
  may come from any folder: they are copied into the plugin's reference store
  first. Each image lands in the gallery and is copied to `--out` without
  overwriting an earlier file. The result prints as JSON.

  `--batch jobs.jsonl --workers 8` runs many generations at once in one process. Each line is
  `{"prompt": "...", "name": "...", "refs": ["photo.jpg"], "aspect": "1:1", "out": "folder"}`; only
  `prompt` and `name` are required. A job whose file already exists is skipped, so repeating the
  command only does what is missing. Every job is billed like one run. Providers limit parallel
  use, and a ChatGPT subscription has its own usage window and terms: start with a small batch
  and raise `--workers` only if the provider accepts it.

  `--edit photo.png --prompt "..."` edits an image and keeps every pixel the model did not change.
  `--mask area.png` (white on the area) fixes the area, and `--whole` takes the model's whole answer.
  A batch line takes `"edit"` and `"mask"`.

  Options for large runs:

  - `--label <client>`, or `"label"` in a batch line, records who the spend is for.
    `--spend` prints this month's images, cost and failed attempts by label. A failed attempt
    keeps its cost because the provider may have billed it.
  - `--replace` overwrites the file of the same name. With `--batch` it generates existing files again.
  - `--retries` waits longer at each attempt, and longer still on a rate limit (HTTP 429).
  - References longer than 2048 pixels are reduced before sending, which shortens the upload.
    `--ref-max-side 0` sends them as they are.
  - The gallery and the history keep 200 items. `IMAGEGEN_GALLERY_CAP` and `IMAGEGEN_HISTORY_CAP`
    in the profile's `.env` change this. The oldest gallery files are deleted past the limit, so
    a large batch without a higher limit pushes out earlier images. Files in `--out` are never removed.

More about each provider, jobs and accounting: [docs/manual/providers.md](docs/manual/providers.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) and [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
