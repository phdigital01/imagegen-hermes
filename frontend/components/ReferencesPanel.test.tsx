/**
 * ImageGen — ReferencesPanel component tests (vitest + testing-library).
 *
 * Contract coverage:
 * 1. A model that does not accept references (maxReferences 0 /
 *    referenceImages false) shows the unsupported state and adding is blocked.
 * 2. A model with cap N accepts up to N; the N+1 attempt is refused with a
 *    visible warning (never a silent discard — the original bug).
 * 3. The first reference is marked as the main image / edit source.
 * 4. Keyboard reorder (arrow buttons AND arrow keys) swaps the order and the
 *    first position stays the main image.
 * 5. Removing a reference removes exactly the one requested.
 * 6. Accessible names exist for reorder/remove/dropzone/list/status — the
 *    queries that lock in the a11y regression.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useState, type ButtonHTMLAttributes, type InputHTMLAttributes } from 'react'

import type { ReferenceImage } from '../types'
import { ImageGenI18nProvider } from '../i18n'
import { ReferencesPanel } from './ReferencesPanel'

const sdk = vi.hoisted(() => ({
  useQuery: vi.fn(),
  notify: vi.fn(),
  notifyError: vi.fn()
}))
const api = vi.hoisted(() => ({
  fetchPresets: vi.fn()
}))
const presets = vi.hoisted(() => ({
  persistReferenceImage: vi.fn()
}))

vi.mock('@hermes/plugin-sdk', () => ({
  cn: (...parts: unknown[]) => parts.filter(Boolean).join(' '),
  Codicon: ({ name, style }: { name?: string; style?: Record<string, unknown> }) => <span data-testid="codicon" data-name={name || ''} style={style} />,
  host: { notify: sdk.notify, notifyError: sdk.notifyError },
  Input: (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
  Button: ({ size: _size, variant: _variant, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { size?: string; variant?: string }) => (
    <button type="button" {...rest}>{children}</button>
  ),
  Skeleton: () => <span data-testid="skeleton" />,
  icons: {},
  useQuery: sdk.useQuery
}))

vi.mock('../api', () => ({
  ID: 'imagegen',
  fetchPresets: api.fetchPresets
}))

vi.mock('../presets', () => ({
  persistReferenceImage: presets.persistReferenceImage
}))

function makeRef(id: string, label: string, extra: Partial<ReferenceImage> = {}): ReferenceImage {
  return {
    id,
    label,
    semanticRole: 'object_primary',
    authorityLevel: 'authoritative',
    roleConfirmed: true,
    fidelity: 85,
    fixedProduct: false,
    purposes: [],
    keep: [],
    vary: [],
    granularWeights: { colors: 70, lighting: 70, composition: 70, textures: 70 },
    userNotes: '',
    instructions: '',
    inputMode: 'upload',
    isAnalyzing: false,
    analysisResult: null,
    origin: 'upload',
    imageDataUrl: `data:image/png;base64,${id}`,
    ...extra
  }
}

function Harness({
  initial = [],
  maxReferences = 3,
  supportsReferences = true,
  modelLabel = 'Flux'
}: {
  initial?: ReferenceImage[]
  maxReferences?: number
  supportsReferences?: boolean
  modelLabel?: string
}) {
  const [refs, setRefs] = useState<ReferenceImage[]>(initial)
  return (
    <ImageGenI18nProvider lang="en">
      <ReferencesPanel
        references={refs}
        onChange={setRefs}
        maxReferences={maxReferences}
        supportsReferences={supportsReferences}
        modelLabel={modelLabel}
      />
    </ImageGenI18nProvider>
  )
}

function pasteFiles(container: HTMLElement, files: File[]): void {
  fireEvent.paste(container.firstChild as Element, { clipboardData: { files } })
}

const imageFile = (name: string): File => new File(['x'], name, { type: 'image/png' })

beforeEach(() => {
  sdk.useQuery.mockReset()
  sdk.notify.mockReset()
  sdk.notifyError.mockReset()
  api.fetchPresets.mockReset()
  presets.persistReferenceImage.mockReset()
  sdk.useQuery.mockReturnValue({
    data: { semantic_roles: [{ value: 'object_primary', label: 'Main object' }], keep_vary: [] }
  })
  presets.persistReferenceImage.mockResolvedValue({
    imageDataUrl: 'data:image/png;base64,persisted',
    localPath: 'C:/tmp/persisted.png'
  })
})

afterEach(() => {
  cleanup()
})

describe('ReferencesPanel — capability contract', () => {
  it('shows the unsupported state and blocks adding when the model accepts no references (maxReferences 0)', () => {
    const { container } = render(
      <Harness initial={[makeRef('r1', 'Alpha')]} maxReferences={0} supportsReferences={false} modelLabel="Seedream" />
    )
    // The model-no-references state is announced politely.
    expect(screen.getByText(/Seedream does not accept reference images/)).toBeTruthy()
    const banner = screen.getByText(/does not accept reference images/).closest('[aria-live="polite"]')
    expect(banner).not.toBeNull()
    // No dropzone exists when references are unsupported.
    expect(screen.queryByRole('button', { name: /drop images here/i })).toBeNull()
    // Adding is blocked: pasting an image neither changes the list nor notifies.
    pasteFiles(container, [imageFile('x.png')])
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
    expect(sdk.notify).not.toHaveBeenCalled()
  })

  it('accepts up to N references and refuses the N+1 attempt with a visible warning', async () => {
    const { container } = render(<Harness initial={[]} maxReferences={1} />)
    const drop = screen.getByRole('button', { name: /drop images here/i })
    expect(drop.getAttribute('aria-disabled')).toBe('false')
    expect(drop.getAttribute('tabindex')).toBe('0')

    // Two files against a cap of 1: exactly one fits, the other is reported.
    pasteFiles(container, [imageFile('a.png'), imageFile('b.png')])
    await waitFor(() => expect(screen.getAllByRole('listitem')).toHaveLength(1))
    expect(sdk.notify).toHaveBeenCalledTimes(1)
    const firstCall = sdk.notify.mock.calls[0][0] as { kind?: string; title?: string; message?: string }
    expect(firstCall.kind).toBe('warning')
    expect(firstCall.title).toBe('Reference limit reached')
    expect(firstCall.message).toContain('1 file(s) skipped')

    // At the cap the dropzone reports the limit and is not tabbable.
    const capped = screen.getByRole('button', { name: 'Reference limit reached' })
    expect(capped.getAttribute('aria-disabled')).toBe('true')
    expect(capped.getAttribute('tabindex')).toBe('-1')
    expect(screen.getByRole('status').textContent).toContain('1 of 1 used')
    expect(screen.getByRole('status').textContent).toContain('Reference limit reached')

    // The N+1 attempt is refused loudly — nothing is added, the user is told.
    pasteFiles(container, [imageFile('c.png')])
    await waitFor(() => expect(sdk.notify).toHaveBeenCalledTimes(2))
    expect(screen.getAllByRole('listitem')).toHaveLength(1)
  })
})

describe('ReferencesPanel — order, main image, removal', () => {
  it('marks the first reference as the main image / edit source', () => {
    render(<Harness initial={[makeRef('r1', 'Alpha'), makeRef('r2', 'Beta')]} />)
    expect(screen.getAllByText('Main image')).toHaveLength(1)
    expect(screen.getByLabelText('References 1')).toHaveProperty('value', 'Alpha')
    expect(screen.getByLabelText('References 2')).toHaveProperty('value', 'Beta')
  })

  it('reorders with the accessible arrow buttons and keeps position 1 as main', () => {
    render(<Harness initial={[makeRef('r1', 'Alpha'), makeRef('r2', 'Beta'), makeRef('r3', 'Gamma')]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Move reference 1 down' }))
    expect(screen.getByLabelText('References 1')).toHaveProperty('value', 'Beta')
    expect(screen.getByLabelText('References 2')).toHaveProperty('value', 'Alpha')
    expect(screen.getByLabelText('References 3')).toHaveProperty('value', 'Gamma')
    // The main-image marker stays on the first position only.
    expect(screen.getAllByText('Main image')).toHaveLength(1)
    expect(screen.getAllByRole('listitem')[0].textContent).toContain('Main image')
  })

  it('reorders with arrow keys on the card and updates the accessible names', () => {
    render(<Harness initial={[makeRef('r1', 'Alpha'), makeRef('r2', 'Beta')]} />)
    const firstCard = screen.getAllByRole('listitem')[0]
    fireEvent.keyDown(firstCard, { key: 'ArrowDown' })
    expect(screen.getByLabelText('References 1')).toHaveProperty('value', 'Beta')
    expect(screen.getByLabelText('References 2')).toHaveProperty('value', 'Alpha')
    expect(screen.getAllByRole('listitem')[0].getAttribute('aria-label')).toBe('Reference 1: Beta')
    // Arrow up on the last card moves it back.
    const lastCard = screen.getAllByRole('listitem')[1]
    fireEvent.keyDown(lastCard, { key: 'ArrowUp' })
    expect(screen.getByLabelText('References 1')).toHaveProperty('value', 'Alpha')
  })

  it('removes exactly the reference whose remove button was clicked', () => {
    render(<Harness initial={[makeRef('r1', 'Alpha'), makeRef('r2', 'Beta'), makeRef('r3', 'Gamma')]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Remove reference 2: Beta' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByLabelText('References 1')).toHaveProperty('value', 'Alpha')
    expect(screen.getByLabelText('References 2')).toHaveProperty('value', 'Gamma')
    expect(screen.queryByLabelText('References 3')).toBeNull()
  })
})

describe('ReferencesPanel — accessible names', () => {
  it('names reorder buttons with the position they move', () => {
    render(<Harness initial={[makeRef('r1', 'Alpha'), makeRef('r2', 'Beta'), makeRef('r3', 'Gamma')]} />)
    expect(screen.getByRole('button', { name: 'Move reference 1 up' }).hasAttribute('disabled')).toBe(true)
    expect(screen.getByRole('button', { name: 'Move reference 1 down' }).hasAttribute('disabled')).toBe(false)
    expect(screen.getByRole('button', { name: 'Move reference 2 up' }).hasAttribute('disabled')).toBe(false)
    expect(screen.getByRole('button', { name: 'Move reference 2 down' }).hasAttribute('disabled')).toBe(false)
    expect(screen.getByRole('button', { name: 'Move reference 3 up' }).hasAttribute('disabled')).toBe(false)
    expect(screen.getByRole('button', { name: 'Move reference 3 down' }).hasAttribute('disabled')).toBe(true)
  })

  it('names remove buttons with the exact reference they delete', () => {
    render(<Harness initial={[makeRef('r1', 'Alpha'), makeRef('r2', 'Beta')]} />)
    expect(screen.getByRole('button', { name: 'Remove reference 1: Alpha' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Remove reference 2: Beta' })).toBeTruthy()
  })

  it('exposes a named dropzone, a named list of named items, and a live status', () => {
    render(<Harness initial={[makeRef('r1', 'Alpha'), makeRef('r2', 'Beta')]} maxReferences={9} />)
    const drop = screen.getByRole('button', { name: /drop images here/i })
    expect(drop.getAttribute('aria-disabled')).toBe('false')
    expect(drop.getAttribute('tabindex')).toBe('0')
    expect(screen.getByRole('list', { name: 'References' })).toBeTruthy()
    expect(screen.getAllByRole('listitem').map((item) => item.getAttribute('aria-label'))).toEqual([
      'Reference 1: Alpha',
      'Reference 2: Beta'
    ])
    // Live region announces the used count politely.
    expect(screen.getByRole('status').textContent).toContain('2 of 9 used')
  })
})
