import { expect, test } from './test'
import { type MockBackendFixture, setupMockBackend, waitForAppReady } from './fixtures'

let fixture: MockBackendFixture | null = null

test.afterAll(async () => {
  await fixture?.cleanup()
  fixture = null
})

test('ImageGen opens and renders the current feature tabs', async () => {
  fixture = await setupMockBackend({
    desktopEnv: process.env.HERMES_E2E_HERMES_BIN
      ? {
          HERMES_DESKTOP_HERMES: process.env.HERMES_E2E_HERMES_BIN,
          HERMES_DESKTOP_HERMES_ROOT: '',
          HERMES_DESKTOP_IGNORE_EXISTING: '0'
        }
      : {}
  })
  await waitForAppReady(fixture, 90_000)

  await fixture.page.getByRole('button', { name: 'ImageGen', exact: true }).click()

  await expect(fixture.page.locator('div.text-sm.font-semibold', { hasText: 'ImageGen' })).toBeVisible()

  for (const tab of ['Gerar', 'Editar', 'Campanha', 'Galeria', 'Provedores']) {
    await expect(fixture.page.getByRole('button', { name: tab, exact: true })).toBeVisible()
  }

  // History folded into Gallery and Inpainting folded into Edit. Both tabs must
  // stay gone, otherwise the consolidation regressed.
  for (const retired of ['Histórico', 'Inpainting']) {
    await expect(fixture.page.getByRole('button', { name: retired, exact: true })).toHaveCount(0)
  }

  // The reference panel is the surface that was broken; it must render on Generate.
  await expect(fixture.page.getByText('Referências', { exact: false }).first()).toBeVisible()
})
