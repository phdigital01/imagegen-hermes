/**
 * Screen check of the Local server provider in a sandboxed Hermes Desktop.
 *
 * It installs the plugin tree of this repository into a throwaway Hermes home, starts a stand-in
 * image server that speaks the OpenAI images API, and walks the screens a person uses: the
 * provider list without an address, the settings link, the address, the connection test, the
 * model picker, one generation, the gallery, a reference with a local model, one image asked
 * from a chat session through the agent's `image_generate` tool, the four languages and the
 * server turned off. It writes one screenshot per state. The stand-in server is not a model: it
 * proves the screens and the request, not the image. With HERMES_E2E_IMAGEGEN_SERVER set to the
 * address of a real server, the same walk passes through it and the images are the model's.
 *
 * How to run it is in docs/runbooks/development.md, "Screen check in a sandboxed Desktop".
 * The file runs from `apps/desktop/e2e/` of a Hermes checkout, so its imports resolve there.
 */
import { execFileSync, spawn } from 'node:child_process'
import * as fs from 'node:fs'
import * as http from 'node:http'
import * as path from 'node:path'
import * as zlib from 'node:zlib'

import type { Page } from '@playwright/test'

import { composerText, waitForChatReady } from '../../../tests-js/scripts/desktop-chat-smoke'
import { writeEnvFile, writeMockProviderConfig } from '../../../tests-js/scripts/mock-provider-config'
import { MOCK_REPLY, startMockServer } from '../../../tests-js/scripts/mock-server'

import { buildAppEnv, createSandbox, launchDesktop, waitForAppReady } from './fixtures'
import { expect, test } from './test'

// Absolute paths: the suite moves TEMP and the working directory for each run.
const OUT = process.env.HERMES_E2E_IMAGEGEN_OUT ?? ''
const REPO = process.env.HERMES_E2E_IMAGEGEN_REPO ?? ''
// A commit or tree of REPO; `git stash create` gives one for uncommitted work.
const REF = process.env.HERMES_E2E_IMAGEGEN_REF || 'HEAD'
// The address of a real image server, such as http://127.0.0.1:1234. Empty: the stand-in answers.
const REAL = (process.env.HERMES_E2E_IMAGEGEN_SERVER ?? '').replace(/\/+$/, '')
const WINDOWS = process.platform === 'win32'
const PROMPT = 'A lighthouse on a cliff at sunset, soft light'
const CHAT_PROMPT = 'A paper boat on a calm lake, morning light'
const CARD_REPLY = 'Here is the image.'
// A real model can take minutes for an image.
const IMAGE_WAIT = REAL ? 900_000 : 60_000

const log: string[] = []
const failures: string[] = []

function note(line: string): void {
  log.push(line)
  console.log(`[check] ${line}`)
}

/** One state of the walk. A failure is recorded and the walk goes on, so one run shows every state. */
async function step(name: string, run: () => Promise<void>): Promise<void> {
  try {
    await run()
    note(`ok   ${name}`)
  } catch (error) {
    failures.push(name)
    note(`FAIL ${name}: ${String(error).split('\n')[0]}`)
  }
}

async function shot(page: Page, name: string): Promise<void> {
  await page.waitForTimeout(600)
  await page.screenshot({ path: path.join(OUT, 'shots', `${name}.png`) })
}

/** A gradient PNG, so the result and the gallery show something that is clearly not a model's image. */
function standInPng(size = 512): Buffer {
  const raw = Buffer.alloc((size * 3 + 1) * size)

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const at = y * (size * 3 + 1) + 1 + x * 3
      raw[at] = 40 + Math.round((x / size) * 180)
      raw[at + 1] = 70 + Math.round((y / size) * 120)
      raw[at + 2] = 170
    }
  }

  const crc = (data: Buffer): number => {
    let value = 0xffffffff

    for (const byte of data) {
      value ^= byte

      for (let bit = 0; bit < 8; bit++) {
        value = (value >>> 1) ^ (value & 1 ? 0xedb88320 : 0)
      }
    }

    return (value ^ 0xffffffff) >>> 0
  }

  const chunk = (type: string, data: Buffer): Buffer => {
    const body = Buffer.concat([Buffer.from(type, 'latin1'), data])
    const out = Buffer.alloc(body.length + 8)
    out.writeUInt32BE(data.length, 0)
    body.copy(out, 4)
    out.writeUInt32BE(crc(body), body.length + 4)

    return out
  }

  const header = Buffer.alloc(13)
  header.writeUInt32BE(size, 0)
  header.writeUInt32BE(size, 4)
  header.set([8, 2, 0, 0, 0], 8)

  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk('IHDR', header),
    chunk('IDAT', zlib.deflateSync(raw)),
    chunk('IEND', Buffer.alloc(0))
  ])
}

test('ImageGen local server on the Desktop', async () => {
  test.setTimeout(REAL ? 2_700_000 : 900_000)
  expect(OUT && REPO, 'set HERMES_E2E_IMAGEGEN_OUT and HERMES_E2E_IMAGEGEN_REPO').toBeTruthy()
  fs.mkdirSync(path.join(OUT, 'shots'), { recursive: true })

  const model = REAL
    ? String(((await (await fetch(`${REAL}/v1/models`)).json()) as { data: Array<{ id: string }> }).data[0].id)
    : 'sd-standin'

  // The image server the plugin talks to: the stand-in, or a pass-through to the real one. Every
  // request is logged, so the log proves what the plugin sent.
  const posts: Array<Record<string, unknown>> = []
  // Set before a generation that must fail: the server refuses that one request, in either mode.
  let refuseNext = false
  const png = standInPng().toString('base64')
  const server = http.createServer((req, res) => {
    const chunks: Buffer[] = []
    req.on('data', (chunk) => chunks.push(chunk))
    req.on('end', () => {
      const body = Buffer.concat(chunks).toString('utf8')
      note(`server ${req.method} ${req.url} ${body.slice(0, 400)}`)
      const send = (status: number, payload: unknown) => {
        res.writeHead(status, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify(payload))
      }

      const generation = req.method === 'POST' && req.url === '/v1/images/generations'

      if (generation && refuseNext) {
        refuseNext = false
        send(500, { error: 'refused for the check' })

        return
      }

      if (generation) {
        posts.push(JSON.parse(body))
      }

      if (REAL) {
        // node:http and not fetch, which gives up on an answer that takes more than five minutes.
        const upstream = http.request(
          `${REAL}${req.url}`,
          { method: req.method, headers: { 'Content-Type': 'application/json' } },
          (answer) => {
            res.writeHead(answer.statusCode ?? 502, { 'Content-Type': answer.headers['content-type'] ?? 'application/json' })
            answer.pipe(res)
          }
        )
        upstream.on('error', () => send(502, {}))
        upstream.end(body)
      } else if (req.method === 'GET' && req.url === '/v1/models') {
        send(200, { object: 'list', data: [{ id: model }] })
      } else if (generation) {
        setTimeout(() => send(200, { data: [{ b64_json: png }] }), 1500)
      } else {
        send(404, {})
      }
    })
  })
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
  const address = `http://127.0.0.1:${(server.address() as { port: number }).port}`

  // The mock model also plays the reply a model gives after an image: its text and ImageGen's card.
  const mock = await startMockServer({
    replyForPrompt: (prompt) => {
      const id = /E2E_IMAGEGEN_CARD ([\w-]+)/.exec(prompt)?.[1]

      return id ? `${CARD_REPLY}\n\n::imagegen-image{id="${id}"}` : MOCK_REPLY
    }
  })
  const sandbox = createSandbox('imagegen-local')
  // `image_gen.provider` is the choice a person makes under Tools > Image Generation.
  writeMockProviderConfig(
    sandbox.hermesHome,
    mock.url,
    undefined,
    'plugins:\n  enabled:\n    - imagegen\nimage_gen:\n  provider: imagegen\n'
  )
  writeEnvFile(sandbox.hermesHome)

  const pluginDir = path.join(sandbox.hermesHome, 'plugins', 'imagegen')
  fs.mkdirSync(pluginDir, { recursive: true })
  const tarball = path.join(sandbox.root, 'imagegen.tar')
  execFileSync('git', ['-C', REPO, 'archive', '--format=tar', '-o', tarball, REF])
  // Windows' own tar: the one in Git Bash reads `C:` as a remote host.
  execFileSync(WINDOWS ? 'C:\\Windows\\System32\\tar.exe' : 'tar', ['-xf', tarball, '-C', pluginDir])
  fs.rmSync(tarball)

  // The Desktop starts its gateway detached from the caller's job object, which a tool shell on
  // Windows does not allow. Start the sandbox gateway here as a plain child; the Desktop attaches.
  const hermesRoot = path.resolve(import.meta.dirname, '..', '..', '..')
  const gatewayLog = fs.openSync(path.join(OUT, 'sandbox-gateway.log'), 'w')
  const gateway = spawn(
    path.join(hermesRoot, 'venv', WINDOWS ? 'Scripts' : 'bin', WINDOWS ? 'python.exe' : 'python'),
    ['-m', 'hermes_cli.main', '--profile', 'default', 'gateway', 'run', '--quiet'],
    {
      cwd: hermesRoot,
      env: { ...buildAppEnv(sandbox), HERMES_GATEWAY_DETACHED: '1', PYTHONIOENCODING: 'utf-8' },
      stdio: ['ignore', gatewayLog, gatewayLog],
      windowsHide: true
    }
  )
  const gatewayDeadline = Date.now() + 90_000

  while (!fs.existsSync(path.join(sandbox.hermesHome, 'gateway.pid')) && Date.now() < gatewayDeadline && gateway.exitCode === null) {
    await new Promise((resolve) => setTimeout(resolve, 1000))
  }

  await new Promise((resolve) => setTimeout(resolve, 5000))

  const { app, page } = await launchDesktop(buildAppEnv(sandbox))
  const dismiss = (name: string) => page.getByRole('button', { name }).click({ timeout: 4000 }).catch(() => undefined)
  const openImageGen = async () => {
    await page.getByRole('button', { name: 'ImageGen', exact: true }).click({ timeout: 30_000 })
    await page.waitForTimeout(2500)
  }
  const openSettings = async (settingsName: string, localName: string) => {
    await page.getByRole('button', { name: settingsName, exact: true }).click({ timeout: 10_000 })
    await page.waitForTimeout(1500)
    await page.getByText(localName, { exact: true }).first().scrollIntoViewIfNeeded({ timeout: 10_000 })
  }
  const localRow = (localName: string) =>
    page.locator('.if-settings div.rounded-lg').filter({ has: page.getByText(localName, { exact: true }) }).first()
  const closeDialog = async () => {
    await page.keyboard.press('Escape')
    await page.waitForTimeout(800)
  }

  try {
    await waitForAppReady({ app, page } as never, 120_000)
    await dismiss('Dismiss notification')
    await dismiss('No thanks')
    // The Desktop half of a package in <home>/plugins stays off until the person turns it on in
    // Capabilities > Plugins; this stores the same choice that switch stores.
    await page.evaluate(() => window.localStorage.setItem('hermes.desktop.pluginDecisions.v2', JSON.stringify({ imagegen: true })))
    await page.reload()
    await waitForAppReady({ app, page } as never, 120_000)
    await dismiss('Dismiss notification')

    await step('open ImageGen', openImageGen)
    await shot(page, '01-imagegen')

    await step('provider list without an address', async () => {
      await openSettings('Settings', 'Local server')
      await expect(localRow('Local server').getByText('Not configured')).toBeVisible()
      await expect(localRow('Local server').getByRole('button', { name: 'Test connection' })).toHaveCount(0)
    })
    await shot(page, '02-providers-no-address')

    const addressField = page.locator('xpath=//*[normalize-space(text())="Local server address"]/following::input[1]')
    await step('the settings link opens the ImageGen settings page', async () => {
      await page.getByRole('button', { name: 'Set address in Settings' }).click({ timeout: 10_000 })
      await addressField.waitFor({ state: 'visible', timeout: 30_000 })
      await addressField.scrollIntoViewIfNeeded()
    })
    await shot(page, '03-hermes-plugin-settings')

    await step('save the address', async () => {
      await addressField.fill(address)
      await page.getByRole('button', { name: /^Save/ }).first().click({ timeout: 5000 })
      await page.waitForTimeout(2500)
      expect(fs.readFileSync(path.join(sandbox.hermesHome, 'config.yaml'), 'utf8')).toContain(address)
    })
    await shot(page, '04-address-saved')

    // Leave the settings route before reloading: the app counts as ready only on a chat route.
    await page.getByRole('button', { name: 'Close settings' }).click({ timeout: 10_000 }).catch(() => undefined)
    await page.reload()
    await page.getByRole('button', { name: 'ImageGen', exact: true }).waitFor({ state: 'visible', timeout: 120_000 })
    await page.waitForTimeout(3000)
    await dismiss('Dismiss notification')
    await step('open ImageGen again', openImageGen)

    await step('connection test with the server on', async () => {
      await openSettings('Settings', 'Local server')
      await localRow('Local server').getByRole('button', { name: 'Test connection' }).click({ timeout: 15_000 })
      await expect(localRow('Local server').getByText('Models found: 1')).toBeVisible({ timeout: 15_000 })
      await expect(localRow('Local server').getByText('Configured', { exact: true })).toBeVisible()
    })
    await shot(page, '05-test-connection-ok')
    await closeDialog()

    await step('model picker lists the local model', async () => {
      await page.getByRole('button', { name: 'Change model', exact: true }).click({ timeout: 10_000 })
      await page.locator('[role="dialog"] select').first().selectOption('local')
      await page.waitForTimeout(1200)
      await shot(page, '06-model-picker-local')
      await page.locator('[role="dialog"] button', { hasText: model }).first().click({ timeout: 10_000 })
      await page.waitForTimeout(800)
    })

    await step('generate', async () => {
      await page.getByPlaceholder('Describe the subject, the scene, and the style.').fill(PROMPT)
      await page.waitForTimeout(800)
      await shot(page, '07-create-ready')
      await page.getByRole('button', { name: /^Generate with/ }).click({ timeout: 10_000 })
      await page.locator('.if-pop').getByText('Confirm generation').waitFor({ timeout: 10_000 })
      await shot(page, '08-confirm-generation')
      await page.locator('.if-pop').getByRole('button', { name: /^Generate/ }).click({ timeout: 10_000 })
      await expect(page.getByText('saved to gallery')).toBeVisible({ timeout: IMAGE_WAIT })
      expect(posts).toHaveLength(1)
      expect(posts[0]).toMatchObject({ model, n: 1, size: '1024x1024', response_format: 'b64_json' })
      expect(String(posts[0].prompt)).toContain(PROMPT)
    })
    await shot(page, '09-create-result')

    // This home has only the local server. The result actions that run on FAL or Magnific say so
    // before the click, and a click answers with the notice instead of a job that fails.
    const variations = page.getByRole('button', { name: /^Variations/ }).first()
    await step('result actions that need another provider show a lock', async () => {
      await variations.scrollIntoViewIfNeeded({ timeout: 10_000 })
      await expect(variations).toHaveAttribute('title', 'This function needs FAL.')
      await expect(variations.locator('.codicon-lock')).toBeVisible()
      await expect(page.getByRole('button', { name: /^Edit, Result image 1/ })).toHaveAttribute('title', 'This function needs FAL / Magnific.')
      await page.getByRole('button', { name: /^More actions/ }).first().click({ timeout: 5000 })
      await expect(page.getByRole('menuitem', { name: 'Upscale · needs FAL / Magnific' })).toBeVisible({ timeout: 5000 })
      await expect(page.getByRole('menuitem', { name: 'Remove background · needs FAL' })).toBeVisible()
    })
    await shot(page, '09b-result-actions-locked')
    await closeDialog()
    await step('a variation without FAL says what it needs and starts no job', async () => {
      await variations.click({ timeout: 10_000 })
      await expect(page.locator('.if-access-notice').getByText('This function needs FAL.')).toBeInViewport({ timeout: 5000 })
      await expect(page.getByText('FAL · FLUX.2 Pro Edit')).toHaveCount(0)
      await expect(page.getByText('Generation failed')).toHaveCount(0)
      expect(posts).toHaveLength(1)
    })
    await shot(page, '09c-variation-needs-fal')
    await page.locator('.if-access-notice').getByRole('button', { name: 'Close' }).click({ timeout: 5000 }).catch(() => undefined)

    // A generation the server refuses: the failure stays on screen and the screen stays usable.
    const failure = page.locator('[role="status"]').filter({ hasText: 'Generation failed' })
    await step('a failed generation leaves the Generate button ready', async () => {
      refuseNext = true
      await page.getByRole('button', { name: /^Generate with/ }).click({ timeout: 10_000 })
      await page.locator('.if-pop').getByText('Confirm generation').waitFor({ timeout: 10_000 })
      await page.locator('.if-pop').getByRole('button', { name: /^Generate/ }).click({ timeout: 10_000 })
      await expect(failure).toBeVisible({ timeout: 30_000 })
      await expect(page.getByRole('button', { name: /^Generate with/ })).toBeEnabled({ timeout: 5000 })
      await expect(page.getByRole('button', { name: /^Generating/ })).toHaveCount(0)
      // Nothing was delivered and the local server charges nothing: the retry says only that.
      await expect(failure.getByRole('button', { name: 'Retry', exact: true })).toBeVisible()
      await expect(page.getByRole('button', { name: /remaining images|paid/ })).toHaveCount(0)
      // The panel is the only place that shows this job while it is open.
      await expect(page.getByText('Job queue')).toHaveCount(0, { timeout: 15_000 })
      expect(posts).toHaveLength(1)
    })
    await shot(page, '09d-generation-failed')
    await step('closing the failure removes its panel', async () => {
      await failure.getByRole('button', { name: 'Close', exact: true }).click({ timeout: 5000 })
      await expect(page.getByText('Generation failed')).toHaveCount(0, { timeout: 10_000 })
      await expect(page.getByRole('button', { name: /^Generate with/ })).toBeEnabled()
    })

    await step('the image is in the gallery', async () => {
      await page.getByRole('button', { name: 'Gallery', exact: true }).click({ timeout: 10_000 })
      await expect(page.getByText(/1 items/)).toBeVisible({ timeout: 15_000 })
    })
    await shot(page, '10-gallery')

    await step('a reference with a local model is refused in words', async () => {
      await page.getByRole('button', { name: 'Generate', exact: true }).click({ timeout: 10_000 })
      await page.getByRole('button', { name: 'Add references' }).click({ timeout: 10_000 })
      await expect(page.getByText(`${model} does not accept reference images`, { exact: false })).toBeVisible({ timeout: 5000 })
      await expect(page.locator('input[type="file"]')).toHaveCount(0)
    })
    await shot(page, '11-reference-with-local')
    await closeDialog()

    await step('the Edit tab does not offer the local server', async () => {
      await page.getByRole('button', { name: 'Edit', exact: true }).click({ timeout: 10_000 })
      await page.waitForTimeout(2000)
      await expect(page.locator('select option', { hasText: 'Local server' })).toHaveCount(0)
    })
    await shot(page, '12-edit-tab')

    // The mock model answers `E2E_CALL(tool)[arguments]` with that tool call and then with the
    // tool's result, so the image comes from the agent's own `image_generate` in a real session.
    const assistant = page.locator('[data-slot="aui_assistant-message-content"]')
    // A new session each time: the mock answers from the first tool result it finds in the history.
    const say = async (text: string, answer: string, wait: number): Promise<string> => {
      const reply = assistant.filter({ hasText: answer })
      await page.getByRole('button', { name: /^New session/ }).first().click({ timeout: 10_000 })
      const composer = await waitForChatReady(page, 60_000)
      await expect(reply).toHaveCount(0, { timeout: 15_000 })
      await composer.evaluate((node) => (node as HTMLElement).focus({ preventScroll: true }))
      await page.keyboard.type(text)
      await expect.poll(() => composerText(composer), { timeout: 15_000 }).toContain(text.slice(-20))
      await page.keyboard.press('Enter')
      await expect(reply).toHaveCount(1, { timeout: wait })
      await expect(
        page.locator(
          '[data-slot="composer-root"] button[aria-label="Start voice conversation"]:visible, ' +
            '[data-slot="composer-root"] button[type="submit"][aria-label="Send"]:visible'
        )
      ).toBeVisible({ timeout: 90_000 })

      return (await reply.textContent()) ?? ''
    }
    let galleryId = ''

    await step('a chat session generates through the local server', async () => {
      const ask = (tool: string, args: unknown) => say(`E2E_CALL(${tool})[${JSON.stringify(args)}]`, 'E2E_CALL_RESULT', IMAGE_WAIT)
      const args = { prompt: CHAT_PROMPT, aspect_ratio: 'square' }
      let reply = await ask('image_generate', args)

      // A session that defers its tools reaches them through the `tool_call` bridge, as a model does.
      if (reply.includes('does not exist')) {
        reply = await ask('tool_call', { calls: [{ name: 'image_generate', arguments: args }] })
      }

      note(`chat reply ${reply.slice(0, 600)}`)
      galleryId = /"gallery_id\\?":\s*\\?"([\w-]+)/.exec(reply)?.[1] ?? ''
      // The result can arrive as JSON inside JSON, with its quotes escaped.
      expect(reply).toMatch(/"success\\?":\s*true/)
      expect(reply).toMatch(/"via\\?":\s*\\?"local/)
      expect(posts).toHaveLength(2)
      expect(posts[1]).toMatchObject({ model, n: 1, size: '1024x1024', response_format: 'b64_json' })
      expect(String(posts[1].prompt)).toContain(CHAT_PROMPT)
    })
    await shot(page, '13-chat-image')

    await step('the reply shows the ImageGen card of that image', async () => {
      expect(galleryId, 'the gallery id in the tool result').not.toBe('')
      await say(`E2E_IMAGEGEN_CARD ${galleryId}`, CARD_REPLY, 60_000)
      const card = page.locator('.imagegen-ui').filter({ hasText: 'Saved in the ImageGen gallery' })
      await expect(card.getByText(model)).toBeVisible({ timeout: 15_000 })
      await expect(card.getByRole('button', { name: 'Edit in ImageGen' })).toBeVisible()
      await expect.poll(() => card.locator('img').evaluate((img: HTMLImageElement) => img.naturalWidth), { timeout: 15_000 }).toBeGreaterThan(0)
      // The chat's typography adds a margin to every image; the card must stay as tall as its three lines.
      expect((await card.boundingBox())?.height ?? 0).toBeLessThan(84)
    })
    await shot(page, '14-chat-card')

    await step('the chat image is in the gallery', async () => {
      await openImageGen()
      await page.getByRole('button', { name: 'Gallery', exact: true }).click({ timeout: 10_000 })
      await expect(page.getByText(/2 items/)).toBeVisible({ timeout: 15_000 })
    })
    await shot(page, '15-gallery-after-chat')

    // [language, name of the settings button before the change, provider name after it]
    const languages: Array<[string, string, string]> = [
      ['pt', 'Settings', 'Servidor local'],
      ['es', 'Configurações', 'Servidor local'],
      ['zh', 'Ajustes', '本地服务器']
    ]

    for (const [lang, settingsName, localName] of languages) {
      await step(`provider list in ${lang}`, async () => {
        await page.getByRole('button', { name: settingsName, exact: true }).click({ timeout: 10_000 })
        await page.waitForTimeout(1200)
        await page.locator('.if-settings select').first().selectOption(lang)
        await page.waitForTimeout(1200)
        await page.getByText(localName, { exact: true }).first().scrollIntoViewIfNeeded({ timeout: 10_000 })
      })
      await shot(page, `16-providers-${lang}`)
      await closeDialog()
    }

    await step('connection test with the server off', async () => {
      server.closeAllConnections()
      await new Promise<void>((resolve) => server.close(() => resolve()))
      await page.getByRole('button', { name: '设置', exact: true }).click({ timeout: 10_000 })
      await page.waitForTimeout(1200)
      await page.locator('.if-settings select').first().selectOption('pt')
      await page.waitForTimeout(1200)
      await localRow('Servidor local').getByRole('button', { name: 'Testar conexão' }).click({ timeout: 15_000 })
      await expect(localRow('Servidor local').getByText(`${address} did not answer`, { exact: false })).toBeVisible({ timeout: 15_000 })
      await expect(localRow('Servidor local').getByText('Servidor não responde')).toBeVisible({ timeout: 15_000 })
    })
    await shot(page, '17-server-off-pt')
  } finally {
    fs.writeFileSync(path.join(OUT, 'check.log'), log.join('\n') + '\n')
    await app.close().catch(() => undefined)
    gateway.kill()
    fs.closeSync(gatewayLog)

    // The sandbox goes away below; its logs explain a state that failed.
    if (failures.length && fs.existsSync(path.join(sandbox.hermesHome, 'logs'))) {
      fs.cpSync(path.join(sandbox.hermesHome, 'logs'), path.join(OUT, 'sandbox-logs'), { recursive: true })
    }

    await mock.close()
    server.close()
    sandbox.cleanup()
  }

  expect(failures, 'states that failed; see check.log and the screenshots').toEqual([])
})
