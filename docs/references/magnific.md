# Magnific image integration

Magnific is the former Freepik platform, with generation, editing, video,
audio, and stock APIs. This plugin currently integrates image generation and
editing. The catalog is explicit and reviewed against endpoint contracts;
it does not claim to expose every Magnific product or advanced parameter.

## Generation coverage

Select **Magnific API** in the model catalog. Configure the key in the
Providers panel, or set `MAGNIFIC_API_KEY` in the active Hermes environment.
The key stays in the backend and is sent as `x-magnific-api-key` only to the
Magnific API. Model availability also depends on the user's API entitlement.

| Model ID | References | Size controls | Seed |
| --- | --- | --- | --- |
| `mystic` | None | Aspect ratio; 1K, 2K, 4K | No |
| `magnific-one` | Up to 10 public URLs | Aspect ratio; 1K, 2K, 4K | No |
| `gpt-image-2`, `gpt-image-2-5` | Up to 16, through their edit endpoints | Named aspect ratios; 1K, 2K, 4K | No |
| `flux-2-pro` | Up to 4 | Aspect ratio; 1K long side (max 1440 px) | Yes |
| `flux-2-flex` | Up to 4 | Aspect ratio; 1K long side (max 1920 px) | Yes |
| `flux-2-turbo` | None | Aspect ratio; 1K, 2K long side | Yes |
| `flux-2-klein` | Up to 4 | Aspect ratio; 1K, 2K presets | Yes |
| `flux-kontext-pro` | 1 | Aspect ratio; provider output size | Yes |
| `flux-kontext-max` | 1–4 (required) | Aspect ratio; provider output size | Yes |
| `flux-pro-v1-1`, `flux-dev`, `hyperflux` | None | Aspect ratio; provider output size | Yes (Dev and Hyperflux from 1) |
| `seedream-v4`, `seedream-v4-5`, `seedream-v5-lite` | Up to 5, through their edit endpoints | Aspect ratio; provider output size | Yes |
| `seedream-v5-pro` | Up to 10, through its edit endpoint | Aspect ratio; 1.5K, 2K | Yes |
| `nano-banana-pro`, `nano-banana-pro-flash` | Up to 3 | Aspect ratio; 1K, 2K, 4K | No |
| `nano-banana-2-1` | Up to 14 | Aspect ratio including 1:8 to 8:1; 1K, 2K, 4K | No |
| `ideogram-4` | None | Aspect ratio including 16:10 | 0–2,147,483,647 |
| `ideogram-4-5` | Up to 5; the first is the image to edit | Aspect ratio | 0–2,147,483,647 |
| `recraft-v4`, `recraft-v4-1`, `recraft-v4-pro` | None | Named aspect ratios | No |
| `runway` | None in this adapter | Documented output dimensions | Yes |
| `z-image` | None | Documented 1K aspect presets | Yes |

Except where specified, exposed seeds range from 0 to 4,294,967,295. Negative
prompts are not exposed for these contracts. Resolution controls are hidden
when the endpoint chooses output size. Supported aspect ratios vary by model;
the UI filters choices and adjusts incompatible settings on model change.
FLUX.2 dimensions preserve the selected ratio; the shorter side is increased
when needed to meet the endpoint's minimum dimension.

Excluded on purpose: Imagen 4 (deprecated and absent from the OpenAPI
document), classic Seedream and Gemini 2.5 Flash preview (superseded; no ratio
field), the legacy synchronous `text-to-image` route, and beta Reimagine FLUX.

Source contracts (the 2026-10-27 additions were read from the official API
reference at docs.magnific.com and its OpenAPI document):

- [Mystic](https://docs.magnific.com/api-reference/mystic/post-mystic)
- [FLUX.2 Pro](https://docs.magnific.com/api-reference/text-to-image/post-flux-2-pro), [Turbo](https://docs.magnific.com/api-reference/text-to-image/post-flux-2-turbo), [Klein](https://docs.magnific.com/api-reference/text-to-image/flux-2-klein/generate), [Kontext Pro](https://docs.magnific.com/api-reference/text-to-image/flux-kontext-pro/post-flux-kontext-pro)
- [Seedream 4](https://docs.magnific.com/api-reference/text-to-image/seedream-4/overview), [4 Edit](https://docs.magnific.com/api-reference/text-to-image/seedream-4-edit/post-seedream-v4-edit), [4.5](https://docs.magnific.com/api-reference/text-to-image/post-seedream-v4-5), [4.5 Edit](https://docs.magnific.com/api-reference/text-to-image/post-seedream-v4-5-edit), [5 Lite](https://docs.magnific.com/api-reference/text-to-image/post-seedream-v5-lite), [5 Lite Edit](https://docs.magnific.com/api-reference/text-to-image/post-seedream-v5-lite-edit)
- [Nano Banana Pro](https://docs.magnific.com/api-reference/text-to-image/post-nano-banana-pro), [Pro Flash](https://docs.magnific.com/api-reference/text-to-image/nano-banana-pro-flash/generate)
- [Runway](https://docs.magnific.com/api-reference/text-to-image/post-runway), [Z-Image](https://docs.magnific.com/api-reference/text-to-image/post-z-image)

## Editing coverage

The Edit screen has an independent provider/model selector. A generation model
selection does not silently redirect a masked edit or another image operation.
The variation menu displays its engine: Magnific uses the selected model when
it accepts references, or FLUX.2 Pro otherwise. Other providers retain the
existing FAL FLUX.2 Pro variation workflow.

| UI action | Local route | Magnific endpoint under `/v1/ai/` |
| --- | --- | --- |
| Global edit | `POST /edit` | Selected reference-capable generation/edit model |
| Relight | `POST /relight` | `image-relight` |
| Style transfer | `POST /style-transfer` | `image-style-transfer` |
| Expand | `POST /outpaint` | `image-expand/flux-pro` |
| Remove background | `POST /bg-remove` | `beta/remove-background` |
| Region (mask) | `POST /inpaint` | `ideogram-image-edit` |
| Expand | `POST /outpaint` | `image-expand/ideogram`, `image-expand/seedream-v4-5` |
| Change camera | `POST /camera` | `image-change-camera` |
| Skin | `POST /skin` | `skin-enhancer/creative`, `/faithful`, `/flexible` |
| Upscale Precision | `POST /upscale` | `image-upscaler-precision` |
| Upscale Precision v2 | `POST /upscale` | `image-upscaler-precision-v2` |
| Upscale Creative | `POST /upscale` | `image-upscaler` |
| Prompt from image | `POST /prompt-helper` | `image-to-prompt` |
| Improve prompt | `POST /prompt-helper` | `improve-prompt` |

Pass `provider: "magnific"` on operation routes. These local routes return a
job ID; use `GET /jobs/{id}/result` to retrieve its result envelope.

Relighting accepts a prompt and/or a second lighting reference, a 0–100
`strength`, and `changeBackground` (default false). Style transfer requires
`referenceImage`, with 0–100 `strength` and `structureStrength`. In the UI,
the first image is the source and the second is the reference. Expansion uses
`direction` and `expandPx` (1–2048 per selected side). Upscaling uses `mode:
"classic"` for Precision or `"creative"` with `scale: 2|4` and `creativity:
0..1`. Precision does not accept an explicit scale; `mode: "precision-v2"`
takes `scale: 2|4|8|16` and an optional `flavor` (`sublime`, `photo`,
`photo_denoiser`). Expansion takes `expandModel`: `flux-pro` (default),
`ideogram` or `seedream-v4-5`; the last two write their own prompt when it is
empty.

Region editing with Magnific sends the image, the prompt and the mask to
Ideogram. The ImageGen brush paints the area white; Ideogram edits the black
part, so the adapter inverts the mask and rejects a mask whose size differs
from the image. With FAL, region editing still uses Flux Fill.

Change camera takes `horizontalAngle` (0–360), `verticalAngle` (-30–90) and
`zoom` (0–10); the image is staged as a public URL. Skin takes `skinMode`
(`creative`, `faithful`, `flexible`), `sharpen` and `smartGrain` (0–100),
`skinDetail` for faithful and `optimizedFor` for flexible. Skin tasks submit
to their mode path and poll `skin-enhancer/{task-id}`.

`POST /prompt-helper` answers directly with `{ "text" }`: `action: "describe"`
with an `image`, or `action: "improve"` with a `prompt` of up to 2,500
characters. The Generate tab shows both buttons when Magnific is configured.

LoRA training, lightmaps,
Google Search grounding, advanced style engines, and other specialized
parameters are not exposed. Imagen 4 Fast/Ultra were excluded because their
[task documentation marks them deprecated](https://docs.magnific.com/api-reference/text-to-image/imagen4-fast/task-by-id).

Source contracts: [Relight](https://docs.magnific.com/api-reference/image-relight/post-image-relight),
[Style Transfer](https://docs.magnific.com/api-reference/image-style-transfer/post-image-style-transfer),
[Expand](https://docs.magnific.com/api-reference/image-expand/post-flux-pro),
[Remove Background](https://docs.magnific.com/api-reference/remove-background/post-beta-remove-background),
[Creative Upscaler](https://docs.magnific.com/api-reference/image-upscaler-creative/image-upscaler),
[Precision Upscaler](https://docs.magnific.com/api-reference/image-upscaler-precision/image-upscaler).

## References and persistence

Base64-capable endpoints receive original image bytes. URL-based endpoints
use Magnific's [Upload Files API](https://docs.magnific.com/upload-files) for
local files: request a signed upload URL, PUT bytes with the supplied storage
headers, and use the returned asset URL. The API key is never sent to storage.
Temporary signed URLs are not written into the job payload or recipe; those
retain the original local source. A later submission uploads again as needed.
Uploads are provider staging storage, not a durable output archive.

Seedream references are checked for PNG/JPEG, a 10 MB limit, and minimum
256×256 dimensions. Background removal accepts PNG/JPEG up to 20 MB; its
temporary result is saved promptly by the local job.

Generation and asynchronous edits submit once, save the actual task endpoint,
and poll that task. Recovery performs GET requests only. Seedream history
records the actual edit endpoint, while its reusable config selects the
corresponding generation model. Background removal is synchronous upstream
and has no provider task ID to recover. Local cancellation cannot guarantee
that the provider stops processing or charging.

## Accounting and validation

The adapter does not fabricate USD prices from provider credits or EUR rates.
An active local USD budget blocks unknown-price Magnific image operations;
without that limit, they are recorded as unknown cost. Provider billing is
authoritative. Upload requests are staging operations and do not reserve an
image-generation estimate.

Reviewed by source inspection against official documentation on 2026-09-05;
the 2026-10-27 additions were read from the official API reference and
OpenAPI document. Request payloads are covered by mocked contract tests
(`backend/tests/test_catalog_contracts.py`). No live generation or paid
operation was run.
