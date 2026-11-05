/**
 * ResultGrid — per-image accessible names + job lifecycle contract tests.
 *
 * The SDK and the network layer are mocked. `fetchJob` drives JobProgress
 * through its states; ResultGrid itself is pure render + callbacks.
 */

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ComponentPropsWithoutRef, ReactNode } from 'react'

import type { JobStatus } from '../types'
import { translate } from '../i18n'
import { fetchJob } from '../api'

import { ResultGrid, JobProgress } from './ResultGrid'

vi.mock('@hermes/plugin-sdk', async () => {
  const React = await import('react')
  const { createElement } = React

  const cn = (...args: unknown[]) => args.filter(Boolean).join(' ')

  const Codicon = ({ name, ...rest }: ComponentPropsWithoutRef<'span'> & { name?: string }) =>
    createElement('span', { ...rest, 'data-codicon': name })

  const Skeleton = ({ children, ...rest }: ComponentPropsWithoutRef<'div'>) =>
    createElement('div', { ...rest, 'data-testid': 'skeleton' }, children)

  const Button = ({ children, onClick, disabled, ...rest }: ComponentPropsWithoutRef<'button'> & { size?: string; variant?: string }) =>
    createElement('button', { type: 'button', onClick, disabled, ...rest }, children)

  const DropdownMenu = ({ children }: { children?: ReactNode }) => createElement('div', { 'data-testid': 'dropdown-menu' }, children)
  const DropdownMenuTrigger = ({ children, ...rest }: ComponentPropsWithoutRef<'button'>) => createElement('button', { type: 'button', ...rest }, children)
  const DropdownMenuContent = ({ children }: { children?: ReactNode }) => createElement('div', null, children)
  const DropdownMenuItem = ({ children, onClick }: { children?: ReactNode; onClick?: () => void }) => createElement('button', { type: 'button', onClick }, children)

  return {
    cn,
    Codicon,
    Button,
    Skeleton,
    icons: {},
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger
  }
})

vi.mock('../api', async (original) => ({
  ...(await original<typeof import('../api')>()),
  ID: 'imagegen',
  fetchFeed: vi.fn(),
  fetchJob: vi.fn(),
  cancelJob: vi.fn(),
  retryJob: vi.fn(),
  resumeJob: vi.fn(),
  invalidateFeed: vi.fn(),
  getStored: vi.fn((_key: string, fallback: unknown) => fallback),
  setStored: vi.fn(),
  queryClient: { invalidateQueries: vi.fn() },
  rest: vi.fn()
}))

/** Test seam: translate into the plugin's default language (en). */
const T = (key: string, args?: Record<string, string>) => translate('en', key, args)

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  cleanup()
})

describe('ResultGrid — per-image accessibility', () => {
  it('gives every result a meaningful alt text and actions that name their image', () => {
    render(
      <ResultGrid
        images={['http://img.local/a.png', 'http://img.local/b.png']}
        onDownload={vi.fn()}
        onEdit={vi.fn()}
        onVary={vi.fn()}
        onUseAsRef={vi.fn()}
        onUpscale={vi.fn()}
        onBgRemove={vi.fn()}
        onAnimate={vi.fn()}
      />
    )

    const alts = screen.getAllByRole('img').map((img) => img.getAttribute('alt'))
    expect(alts).toEqual([T('resultImageName', { n: '1' }), T('resultImageName', { n: '2' })])

    // Each action says which image it acts on — and the names are distinct.
    expect(screen.getByRole('button', { name: `${T('download')}, ${T('resultImageName', { n: '1' })}` })).toBeTruthy()
    expect(screen.getByRole('button', { name: `${T('download')}, ${T('resultImageName', { n: '2' })}` })).toBeTruthy()
    expect(screen.getByRole('button', { name: `${T('editImage')}, ${T('resultImageName', { n: '1' })}` })).toBeTruthy()
    expect(screen.getByRole('button', { name: `${T('moreActions')}, ${T('resultImageName', { n: '2' })}` })).toBeTruthy()

    // The named controls (image openers + per-image actions) are all distinct.
    const named = screen.getAllByRole('button').filter((button) => button.getAttribute('aria-label'))
    expect(named.length).toBeGreaterThan(0)
    expect(new Set(named.map((button) => button.getAttribute('aria-label'))).size).toBe(named.length)
  })

  it('opens the lightbox with the same accessible name when an image is clicked', () => {
    render(<ResultGrid images={['http://img.local/a.png']} onDownload={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: T('resultImageName', { n: '1' }) }))

    const dialog = screen.getByRole('dialog', { name: T('resultImageName', { n: '1' }) })
    expect(dialog.querySelector('img')?.getAttribute('alt')).toBe(T('resultImageName', { n: '1' }))
    expect(screen.getByRole('button', { name: T('close') })).toBeTruthy()
  })
})

describe('JobProgress — job lifecycle', () => {
  it('shows a localized error for a failed job, never the raw backend string', async () => {
    vi.mocked(fetchJob).mockResolvedValue({
      id: 'j1',
      kind: 'generate',
      status: 'failed',
      errorCode: 'model.no_image',
      errorParams: { model: 'fal-1' },
      error: 'RAW_BACKEND_DETAILS'
    } satisfies JobStatus)
    render(<JobProgress jobId="j1" failedLabel={T('jobFailed')} />)

    expect(await screen.findByText(T('model.no_image', { model: 'fal-1' }))).toBeTruthy()
    expect(screen.getByText(T('jobFailed'))).toBeTruthy()
    expect(screen.queryByText('RAW_BACKEND_DETAILS')).toBeNull()

    // The failure is announced through a polite live region.
    const status = screen.getByRole('status')
    expect(status.getAttribute('aria-live')).toBe('polite')
  })

  it('keeps the error panel mounted and defers onDone until the user dismisses a failed job', async () => {
    const onDone = vi.fn()
    const job: JobStatus = { id: 'j1', kind: 'generate', status: 'failed', errorCode: 'model.no_image', errorParams: { model: 'fal-1' } }
    vi.mocked(fetchJob).mockResolvedValue(job)
    render(<JobProgress jobId="j1" onDone={onDone} failedLabel={T('jobFailed')} />)

    // The failure panel paints and stays mounted. Auto-firing onDone here
    // would unmount JobProgress in the same batch, making failures silent.
    expect(await screen.findByText(T('model.no_image', { model: 'fal-1' }))).toBeTruthy()
    expect(screen.getByRole('status')).toBeTruthy()
    expect(onDone).not.toHaveBeenCalled()

    // The dismiss button hands the terminal job to the consumer.
    fireEvent.click(screen.getByRole('button', { name: T('close') }))
    expect(onDone).toHaveBeenCalledWith(job)
  })

  it('shows progress and a live region while the job is running', async () => {
    vi.useFakeTimers()
    try {
      vi.mocked(fetchJob).mockResolvedValue({
        id: 'j1',
        kind: 'generate',
        status: 'running',
        progress: 0.5,
        message: 'Working hard'
      } satisfies JobStatus)
      render(<JobProgress jobId="j1" generatingLabel={T('jobRunning')} cancel={T('cancel')} />)

      await act(async () => {})

      expect(screen.getByText(T('jobRunning'))).toBeTruthy()
      expect(screen.getByText('Working hard')).toBeTruthy()
      expect(screen.getByRole('button', { name: T('cancel') })).toBeTruthy()
      const status = screen.getByRole('status')
      expect(status.getAttribute('aria-live')).toBe('polite')
    } finally {
      vi.useRealTimers()
    }
  })

  it('announces completion and hands the job to onDone', async () => {
    const onDone = vi.fn()
    const job: JobStatus = { id: 'j1', kind: 'generate', status: 'completed', result: { images: ['http://img.local/a.png'] } }
    vi.mocked(fetchJob).mockResolvedValue(job)
    render(<JobProgress jobId="j1" onDone={onDone} />)

    expect(await screen.findByText(T('jobCompleted'))).toBeTruthy()
    expect(screen.getByRole('status').getAttribute('aria-live')).toBe('polite')
    expect(onDone).toHaveBeenCalledWith(job)
  })
})
