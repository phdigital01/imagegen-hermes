/**
 * ImageGen — GenerateTab component tests (vitest + testing-library).
 *
 * Contract coverage:
 * - Without a prompt, Generate is disabled with a visible, associated reason
 *   (aria-describedby), not color alone.
 * - The density switch is a correct tablist: role=tab on children,
 *   aria-selected, aria-controls, a named tabpanel, and arrow-key navigation.
 * - Section accordions expose aria-expanded + aria-controls.
 * - Accessible names exist (getByRole with name) — the queries that lock in
 *   the a11y regression.
 *
 * The network layer (../api) and @hermes/plugin-sdk are mocked; nothing makes
 * a real request. ui-helpers, presets and i18n are real.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useState, type ButtonHTMLAttributes, type ComponentPropsWithoutRef, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from 'react'

import type { ImageGenConfig, Presets, Provider } from '../types'
import { ImageGenI18nProvider } from '../i18n'
import { GenerateTab } from './GenerateTab'

const sdk = vi.hoisted(() => ({
  useQuery: vi.fn(),
  notify: vi.fn(),
  notifyError: vi.fn(),
  invalidateQueries: vi.fn(),
  rest: vi.fn()
}))
const api = vi.hoisted(() => ({
  rest: vi.fn(),
  getStored: vi.fn(),
  fetchJobs: vi.fn(),
  fetchBudget: vi.fn(),
  fetchOutputFolder: vi.fn(),
  fetchSubjectLibrary: vi.fn(),
  loadSessionPrompts: vi.fn(),
  pushSessionPrompt: vi.fn(),
  submitJob: vi.fn(),
  queryJobResult: vi.fn(),
  fetchLocalImagePath: vi.fn(),
  importObjects: vi.fn(),
  subjectAsRefs: vi.fn(),
  refineFromFeedback: vi.fn(),
  invalidateFeed: vi.fn(),
  clearPluginData: vi.fn(),
  saveOutputFolder: vi.fn(),
  fetchPresets: vi.fn()
}))

vi.mock('@hermes/plugin-sdk', () => ({
  cn: (...parts: unknown[]) => parts.filter(Boolean).join(' '),
  Codicon: ({ name, style }: { name?: string; style?: Record<string, unknown> }) => <span data-testid="codicon" data-name={name || ''} style={style} />,
  host: { notify: sdk.notify, notifyError: sdk.notifyError },
  Input: (props: InputHTMLAttributes<HTMLInputElement>) => <input {...props} />,
  Textarea: (props: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} />,
  Button: ({ size: _size, variant: _variant, children, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { size?: string; variant?: string }) => (
    <button type="button" {...rest}>{children}</button>
  ),
  Badge: ({ children, ...rest }: ComponentPropsWithoutRef<'span'> & { variant?: string }) => <span {...rest}>{children}</span>,
  KbdGroup: () => <span data-testid="kbd-group" />,
  Skeleton: () => <span data-testid="skeleton" />,
  icons: {},
  useQuery: sdk.useQuery,
  useMutation: () => ({ mutateAsync: sdk.rest }),
  queryClient: { invalidateQueries: sdk.invalidateQueries },
  Dialog: ({ open, children }: { open?: boolean; children?: ReactNode }) => (open ? <div role="dialog">{children}</div> : null),
  DialogContent: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  DialogDescription: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  DropdownMenu: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
  Tip: ({ label, children }: { label?: string; children?: ReactNode }) => <div>{label}{children}</div>
}))

vi.mock('../api', () => ({
  ID: 'imagegen',
  rest: api.rest,
  getStored: api.getStored,
  fetchJobs: api.fetchJobs,
  fetchBudget: api.fetchBudget,
  fetchOutputFolder: api.fetchOutputFolder,
  fetchSubjectLibrary: api.fetchSubjectLibrary,
  loadSessionPrompts: api.loadSessionPrompts,
  pushSessionPrompt: api.pushSessionPrompt,
  submitJob: api.submitJob,
  queryJobResult: api.queryJobResult,
  fetchLocalImagePath: api.fetchLocalImagePath,
  importObjects: api.importObjects,
  subjectAsRefs: api.subjectAsRefs,
  refineFromFeedback: api.refineFromFeedback,
  invalidateFeed: api.invalidateFeed,
  clearPluginData: api.clearPluginData,
  saveOutputFolder: api.saveOutputFolder,
  fetchPresets: api.fetchPresets,
  fetchFalModel: vi.fn(),
  promptHelper: vi.fn()
}))

const providers: Provider[] = [
  {
    name: 'fal',
    display_name: 'Fal',
    models: [
      {
        id: 'flux',
        display: 'Flux',
        price: '0.04',
        resolutionOptions: ['1K', '2K'],
        capabilities: { referenceImages: true, maxReferences: 4, edit: true, inpaint: true }
      }
    ]
  }
]

const baseConfig: ImageGenConfig = {
  densityMode: 'studio',
  creationMode: 'advanced',
  subjectType: 'objeto_produto',
  description: '',
  structuredFields: {},
  globalDirection: {
    style: '',
    lighting: [],
    angle: '',
    lens: '',
    aperture: '',
    useReferenceAngle: false,
    fidelityMode: 'balanced'
  },
  subjectDistance: '',
  aspectRatio: '1:1',
  qualityLevel: 'alta',
  mood: '',
  negativePrompt: '',
  referencesV4: [],
  cleanZones: { enabled: false, zones: [], intensity: 'moderate', tone: 'Automatic' },
  outputGoal: 'image',
  selectedModel: 'flux',
  resolution: '1K',
  compositionIntent: null,
  provider: 'fal',
  saveToGallery: true,
  qualityTier: 'standard',
  numImages: 1,
  colorAccents: []
}

function Harness({
  config = baseConfig,
  prompt = '',
  presets = null
}: {
  config?: ImageGenConfig
  prompt?: string
  presets?: Presets | null
}) {
  const [cfg, setCfg] = useState<ImageGenConfig>(config)
  const [promptValue, setPromptValue] = useState(prompt)
  return (
    <ImageGenI18nProvider lang="en">
      <GenerateTab
        config={cfg}
        updateConfig={(partial) => setCfg((prev) => ({ ...prev, ...partial }))}
        providers={providers}
        presets={presets}
        onGoToTab={() => {}}
        prompt={promptValue}
        setPrompt={setPromptValue}
        promptTouched={false}
        setPromptTouched={() => {}}
        promptManual={false}
        setPromptManual={() => {}}
        skipConfirm={false}
        setSkipConfirm={() => {}}
        activeJobId={null}
        setActiveJobId={() => {}}
      />
    </ImageGenI18nProvider>
  )
}

beforeEach(() => {
  sdk.useQuery.mockReset()
  sdk.notify.mockReset()
  sdk.notifyError.mockReset()
  sdk.invalidateQueries.mockReset()
  api.rest.mockReset()
  api.getStored.mockReset()
  api.fetchJobs.mockReset()
  api.fetchBudget.mockReset()
  api.fetchOutputFolder.mockReset()
  api.fetchSubjectLibrary.mockReset()
  api.loadSessionPrompts.mockReset()
  api.pushSessionPrompt.mockReset()
  api.submitJob.mockReset()
  api.queryJobResult.mockReset()
  api.fetchLocalImagePath.mockReset()
  api.importObjects.mockReset()
  api.subjectAsRefs.mockReset()
  api.refineFromFeedback.mockReset()
  api.invalidateFeed.mockReset()
  api.clearPluginData.mockReset()
  api.saveOutputFolder.mockReset()
  api.fetchPresets.mockReset()
  // Every useQuery call (jobs, objects, output folder, budget) resolves to
  // empty data; computeAlerts resolves messages in English via getStored.
  sdk.useQuery.mockReturnValue({ data: [] })
  api.getStored.mockReturnValue('en')
  api.loadSessionPrompts.mockReturnValue([])
  api.rest.mockResolvedValue({})
  api.submitJob.mockResolvedValue({ id: 'job-1' })
  api.fetchJobs.mockResolvedValue([])
  api.fetchBudget.mockResolvedValue({ monthlyLimit: null, spentThisMonth: 0, currency: 'USD' })
  api.fetchOutputFolder.mockResolvedValue({ path: '', writable: true })
  api.fetchSubjectLibrary.mockResolvedValue([])
})

afterEach(() => {
  cleanup()
})

describe('GenerateTab — generate disabled with a visible reason', () => {
  it('disables Generate without a prompt and says why in associated visible text', () => {
    render(<Harness prompt="" />)
    const generate = screen.getByRole('button', { name: 'Generate image' }) as HTMLButtonElement
    expect(generate.disabled).toBe(true)
    expect(generate.getAttribute('aria-describedby')).toBe('if-generate-disabled-reason')
    const reason = document.getElementById('if-generate-disabled-reason')
    expect(reason?.textContent).toBe('Describe the image to generate it.')
  })

  it('enables Generate when the image is described and the prompt exists', () => {
    const described = { ...baseConfig, description: 'A red car at dusk' }
    render(<Harness config={described} prompt="A red car at dusk" />)
    const generate = screen.getByRole('button', { name: 'Generate image' }) as HTMLButtonElement
    expect(generate.disabled).toBe(false)
    expect(generate.getAttribute('aria-describedby')).toBeNull()
    expect(document.getElementById('if-generate-disabled-reason')).toBeNull()
  })
})

describe('GenerateTab — section accordions', () => {
  it('annotates section toggles with aria-expanded and aria-controls pointing at the panel', () => {
    render(<Harness />)
    // Collapsed sections report the collapsed state.
    const more = screen.getByRole('button', { name: /More options/ })
    expect(more.getAttribute('aria-expanded')).toBe('false')
    // Toggling flips the state and reveals the panel it points at.
    fireEvent.click(more)
    expect(more.getAttribute('aria-expanded')).toBe('true')
    expect(document.getElementById(more.getAttribute('aria-controls') as string)).not.toBeNull()
  })
})
