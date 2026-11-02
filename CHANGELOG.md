# Changelog

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
