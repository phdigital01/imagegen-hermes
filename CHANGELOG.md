# Changelog

## 1.7.0

- Providers: **Local server**. Set the address of an image server on your own machine in
  **Settings → Plugins → ImageGen** and its models appear in the picker, with no API key and no
  cost. It works with servers that answer the OpenAI images API (stable-diffusion.cpp `sd-server`,
  LocalAI, Ollama) and generates from text only: references and edits are refused with a message.
  Sizes are 512px, 768px, 1K and 2K in multiples of 64. The provider list never waits on that
  server, and a server that stops answering leaves the picker until it answers again.
- Budget: an operation that costs nothing is no longer blocked by a monthly limit that was already
  reached.
- Settings: **Set key in Settings** now opens the ImageGen settings page. Before, it stopped at the
  plugin list with "That plugin has no settings page". The result of **Test connection** shows in
  the row of the provider you tested instead of at the end of the list.
- Generate: **Variations** on an image made by a provider other than FAL or Magnific now runs on
  FAL's FLUX.2 Pro Edit, the model its menu names. Before, it sent that provider's model to FAL,
  which refused it.
- Generate: on a result, **Edit**, **Variations**, **Upscale** and **Remove background** show a
  lock and name the provider they need when it is not connected. **Variations** then answers with
  the access notice and its link to Settings, instead of starting a job that fails.
- Jobs: after a generation fails, the Generate button is ready again while the failure stays on
  screen. Before, it read "Generating…" until you closed the failure. The retry button says
  **Try again (paid)** when no image was delivered, and **Retry** when the local server failed,
  which costs nothing; "Generate remaining images" appears only when some images arrived. The job
  in the failure panel is no longer listed a second time in the job queue above it.
- Chat: the ImageGen card under an image no longer has empty space above and below its content.

## 1.6.0

- Command line: `hermes -p <profile> imagegen ...` is now a Hermes subcommand, registered with
  `ctx.register_cli_command`, so Hermes loads the profile and its secrets. `python imagegen_cli.py`
  still works with the current process's environment only. The `--profile` option is removed and
  points to the new command. The plugin loads the command from its own files, so a gateway that
  hosts several profiles, or still holds the version an update replaced, no longer fails to load it.
- Settings: the gallery and history limits are the **Gallery limit** and **History limit** plugin
  settings. `IMAGEGEN_GALLERY_CAP` and `IMAGEGEN_HISTORY_CAP` are no longer read.
- Generate: one request at a time. **New request** clears the open text, references, product and
  direction and keeps the model and preferences; a recipe or a gallery entry replaces the open
  request instead of merging into it. **One image | Several ideas** puts the batch inside the composer.
- Generate: **Optimize with AI** and **Translate to English** are toggles in the brief. Translate
  appears only when the brief is not in English and always targets English; quoted text stays as
  written; a failed translation sends the text as written and says so.
- Generate: a **Product** strip picks a saved library product. **Direction** is a row of chips that
  marks your choices and the AI's suggestions. **Advanced** is collapsed and names what is on. The
  footer shows the image count, format and cost (or "included in your subscription") and one
  **Generate with {model}** button. The empty stage lists the ready providers and three examples;
  results carry named Edit, Variations and Download actions with the rest in a menu.
- Generate: a saved palette counts only when it was turned on, so an old draft no longer adds colors
  by itself. The variation count is kept with the request.
- Campaign: starts with one scene and no text space (it used to start at 6 images) and shows the
  image count before generating. A campaign image opens in Generate as a reference.
- Edit: numbered steps, a clear choice between keeping what did not change, the whole image or one
  painted area, and a before/after slider with the share of the image that stayed identical.
- Gallery: cards show the prompt and the model's name; a Select mode for compare and export; the
  detail has Edit, Download, **Use again** (as a reference, repeat these settings, save recipe) and
  a menu for the rest.
- Previews: results and gallery images show in a secondary profile, which Hermes serves from
  `http://plugin-host`; they used to render broken there. Gallery cards load the local file first,
  so a large gallery fills at once, and a lazy image is read only when it nears the screen.
- Jobs: a job the open profile cannot read says so, with one Close and no Cancel, instead of a
  spinner that never ends. A status read that fails is tried again a few times without sending the
  request again. A blocked image names the provider's content policy and offers no retry; a
  temporary provider error says a retry may be billed.
- Gallery: ages such as "20 min. ago" follow the plugin's language.
- Campaign: the button says "Generate 1 image" for a single image.

## 1.5.0

- Optionally optimize a brief with the Hermes text model. Preview and edit its prompt, keep manual art direction, and use its supported format when generating. Batch lines use their supplied prompts.

- Generate up to 32 independent prompts in the Desktop composer. Review the count and available cost estimate, track each image and retry an individual failed job.

## 1.4.1

- Editing the main description releases a restored manual prompt and blocks submission until the new prompt is ready.
- Result, gallery, reference and editing views load plugin media through the active profile's authenticated bridge.
- The latest result stays visible when returning from another tab.
- Text-safe controls wrap to the panel width. Accent colors can be disabled while keeping the palette for later.

## 1.4.0

Changes asked in the Hermes plugin catalog review.

- Providers: the plugin no longer loads or registers Hermes's image providers itself. It runs
  Hermes's plugin discovery once and only reads `agent.image_gen_registry`.
- Nous subscription: FAL without a key now runs through Hermes's own `fal` provider, with the model
  set in Hermes. The plugin no longer builds the managed gateway client. Queue resume and reference
  uploads on FAL need a `FAL_KEY` and say so when it is missing. The pinned Portal catalog is gone.
- Desktop: "Show in folder" uses the SDK's `ctx.os.revealPath`. The output folder is a typed field;
  the folder picker button is gone.
- Package: the backend engine is now `imagegen_engine`, so it cannot clash with another plugin's
  `dashboard` package. `dashboard/plugin_api.py` stays as the Hermes entry.
- Storage: the data folder and the Hermes home are resolved on each call, so a profile switch takes
  effect without a restart.

## 1.3.0

- Access: a linked subscription or a Hermes provider with a key now counts as connected. Before,
  only FAL, Magnific, Vertex and Nous did, so the others showed "not connected" and Edit stayed locked.
- Command line: `--batch` runs many generations at once in one process, with `--workers` to set how
  many. Jobs whose file already exists are skipped, and a failed job does not stop the others.
- Reference store: files removed by another process no longer fail a running generation.
- Gallery: images saved in the same millisecond now keep their order.
- Command line: `--label` and `--spend` separate spend by client or project, `--replace` overwrites
  a file of the same name, and `--retries` waits longer at each attempt, more on a rate limit.
- Command line: references longer than 2048 pixels are reduced before sending (`--ref-max-side`),
  keeping orientation and transparency.
- Accounting: an attempt whose provider answers with a failure is no longer counted as delivered.
- `IMAGEGEN_GALLERY_CAP` and `IMAGEGEN_HISTORY_CAP` change the limit of 200 items.
- New interface: a top bar with the four screens, the model and the settings; Generate keeps the
  choices on the left, the image on the right and the Generate button always visible.
- Direction board: subject, style, light, angle, framing, camera, mood and format are eight pictures
  on one screen. Each opens a window where every option shows the same scene with that change.
- All picker images are new, and option names and explanations follow the app language.
- References sit in the description box: add, paste or drop images there. Each reference shows its
  settings only when you ask to adjust it.
- Access: a function that needs another provider shows a lock, says what it needs and links to
  Settings. Settings says which providers use a subscription or an API key and what each one unlocks.
- Choosing a subject suggests a direction and a format without replacing what you already chose.
- Fixed: an image pasted in the description had a role no option matched.
- Fixed: the Photorealistic style showed a blank picture, and a single result sat inside a square
  with empty bands. It now keeps its own shape.
- Edits keep the image: only the area the model changed returns over the source, so pixels outside
  it stay identical across repeated edits. A change to the whole picture keeps the whole answer and
  says so, and **Keep what did not change intact** turns this off.
- GPT Image and other providers that take references now do instruction and region edits, expansion,
  relighting, style transfer, camera changes and skin retouch on the Edit screen, so a subscription
  only needs an API key to remove backgrounds and upscale. Expansion keeps the source pixels intact.
- Fixed: generated images came up broken in Generate, Edit and Campaign, and their download failed,
  because the Desktop refuses plain plugin addresses. They now load through the plugin's API.
- FAL: a refused upload now says the provider's reason, such as an exhausted balance.
- Magnific: background removal, skin retouch, Precision upscale and Precision v2 were paid for and then
  lost. Their files were refused for being generic binary, for being over 10 MB, or for arriving a moment
  after the task finished. All of them now reach the gallery, up to 128 MB.
- Magnific: expansion keeps the source pixels, and a failed task says the provider's reason.
- Light and style start at strength 60, and style at structure 80: at 100 and 50 the style replaced the scene.
- Edit screen: every step is a version, the next edit starts from the latest one, and any earlier
  one, including the original, can be reopened. A warning appears after three whole redraws.
- Command line: `--edit`, `--mask` and `--whole`, and `"edit"` and `"mask"` in batch lines.

## 1.2.0

- The default model follows the account you have linked.
- ImageGen can serve the agent's image generation under **Tools → Image Generation**.
- Chat integration: an image card with an Edit button and a pane beside the chat.
- Live job events.

Earlier versions were not released publicly.
