# Providers, jobs and accounting

## Magnific API

Magnific (formerly Freepik) is a multi-model provider. Add its API key in
**Settings → Plugins → ImageGen**. The integration uses the direct API.

The generation catalog includes Mystic, Magnific One, GPT Image 2/2.5, FLUX.2
Pro/Flex/Turbo/Klein, FLUX Kontext Pro/Max, FLUX 1.1 Pro, FLUX Dev, Hyperflux,
Seedream 4/4.5/5 Lite/5 Pro, Nano Banana Pro/Pro Flash/2.1, Ideogram 4/4.5,
Recraft V4/V4.1/V4 Pro, Runway, and Z-Image Turbo.
Reference support, aspect ratios, seeds, and resolution controls follow each
model's contract. Local references use original bytes or Magnific's own upload
service, depending on the endpoint. No FAL key is needed for Magnific uploads.

Models such as GPT Image redraw the whole picture on every edit, which softens
it over repeated edits. So an instruction or masked edit sends the source without
loss, compares the answer with it and returns only the changed area over the
source. A change to the whole picture (a new style, warmer light) keeps the whole
answer and says so; choosing **Whole image** instead of **Keep what did not change** turns the comparison off.
Providers that take references, such as GPT Image on a subscription, do the
instruction and masked edits, expansion, relighting, style transfer, camera
changes and skin retouch, without the fine controls of Magnific. The source is mirrored outward to the shape the
provider delivers and cropped back, and a masked edit sends only the area around
the mask, so the model draws it at its full size. Inside the changed area the
detail is the model's: upscale the approved final, not every step.

The Edit screen offers Magnific instruction editing, masked editing with
Ideogram, relighting, style transfer, expansion (Flux Pro, Ideogram or Seedream
4.5), camera angle changes, skin retouching, background removal, and
Precision, Precision v2 (up to 16×) and Creative upscaling. The Generate tab
adds two prompt helpers: a prompt written from an image, and an improved
version of the current prompt.

Asynchronous requests save the actual model endpoint and task ID for recovery.
Background removal returns synchronously and is saved by the local job.
Cancellation stops local polling; the remote operation may still complete.
Magnific USD prices remain unknown in the local ledger, so an active local
budget blocks paid Magnific operations. Video, audio, and stock search are
outside this image-focused integration.

See [coverage, contracts, and limitations](../references/magnific.md).

## What each access does

Measured with one real call per function, except FAL, whose functions follow
their documented contracts. Vertex was not measured for expansion, skin or
background.

| Function | GPT subscription | Grok | Vertex | Meta | FAL | Magnific |
|---|---|---|---|---|---|---|
| Generate from text | yes | yes | yes | yes | yes | yes |
| Generate with references | yes | yes | yes | no | yes | by model |
| Instruction and region edit | yes | yes | yes | no | yes | yes |
| Expand | yes | yes | yes | no | yes | yes |
| Light, style, camera, skin | yes | weaker | yes | no | no | yes, fine controls |
| Remove background | no | no | no | no | yes | yes |
| Upscale | no | no | no | no | yes | yes |

A local server generates from text only. Prompt helpers use the main Hermes model, so they need no image provider.
On Grok, the light request also recolored objects and the camera request bent
straight lines. Vertex limits requests per minute: several at once may answer 429.

On Magnific, the skin retouch also enlarges the image: a 1024 pixel portrait came
back at 4800 pixels and 33 MB. Style transfer answered at 880 pixels for a 1024
pixel source. Images over 10 MB stay in the gallery but cannot be sent again as a
source, so upscale only the approved final.

## Vertex AI

Vertex AI runs Google's Gemini image models on your Google Cloud project: Nano
Banana 2.1, Nano Banana 2, Nano Banana Pro and Nano Banana 2 Lite. Add a Vertex AI API key in **Settings → Plugins →
ImageGen**. A key bound to a service account also needs the project ID; an
express-mode key does not. Each model keeps its own limits: up to 14 references,
14 aspect ratios, and 1K, 2K or 4K output where the model offers it (Lite makes
1K only). Seeds and negative prompts are not supported. The local budget
counts an estimate per image from Google's published prices; the Google Cloud
bill is the real cost.

## Local server

ImageGen can generate on an image server that runs on your own computer or
network, with no API key and no cost. The server must answer the OpenAI images
API (`GET /v1/models` and `POST /v1/images/generations`): stable-diffusion.cpp
`sd-server`, LocalAI and Ollama 0.14 or later do. It was measured with
stable-diffusion.cpp.

1. Start the server and note its address, for example `http://127.0.0.1:1234`.
2. Fill **Local server address** in **Settings → Plugins → ImageGen**. Fill
   **Local server token** only when the server asks for a bearer token.
3. In ImageGen's settings, press **Test connection** on **Local server**. It
   says how many models the server reported.

The model list is what the server reports, read again about once a minute.
ImageGen shows every id in it, so a server that also runs text models lists them
too: pick an image model. While the server does not answer, the provider shows
**Server not answering** and its models leave the picker.

- Text to image only. A local model takes no references, edits, negative prompt
  or seed from ImageGen. A reference is refused with a message, never dropped.
- Sizes are 512px, 768px, 1K and 2K on the longest side, with both sides in
  multiples of 64. Pick the size the model was trained for: 512px for Stable
  Diffusion 1.5, 1K for SDXL and FLUX.
- The first image after the server starts can take minutes while the model
  loads. ImageGen waits up to 30 minutes for one image and never sends the
  request a second time.
- stable-diffusion.cpp repeats the same image for the same prompt unless it
  starts with a random seed:

  ```text
  sd-server -m <model file> --listen-port 1234 --seed -1
  ```

- Prompts go only to the address you set. ImageGen uses no proxy for it,
  follows no redirect, and reads an image link only from that same address.
- A local image costs nothing in the local budget, so an active monthly limit
  never blocks it.
- The agent can use it too: pick ImageGen under **Tools → Image Generation**.
  When the local server is the only provider connected, its first model is used.

## Jobs, editing, and local accounting

Generation, editing, masked filling, expansion, background removal, and
upscaling run as jobs. Editing routes return a job ID; read
`GET /jobs/{id}/result` for the `{result: {...}}` envelope. Available partial
results remain readable after failure or cancellation. Recovery retrieves
existing FAL (with a `FAL_KEY`) or Magnific requests; it does not generate missing
images. An explicit paid retry is a separate action. Campaign retries must
be started from the campaign screen.

The monthly limit uses estimated image costs, including reservations made
before submission. It is not a provider invoice or an account-wide spending
cap. Unknown prices are recorded and blocked while a local limit is active.
The Dashboard and ImageGen MCP process coordinate JSON updates through OS
file locks. Keep their shared data directory on the same local machine.
