/**
 * GalleryTab — unified feed contract + accessibility tests.
 *
 * The SDK and the network layer are mocked: `@hermes/plugin-sdk` does not
 * resolve outside the desktop app and no test may touch the network. The
 * feed data is injected through the mocked `useQuery`, while `fetchFeed` is
 * a spy that records the filter params the tab sends to the backend.
 */

import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ChangeEvent, ComponentPropsWithoutRef, ReactNode } from 'react'

import type { FeedItem, FeedResponse, ImageGenConfig, FeedParams } from '../types'
import { relativeTimeActive, translate } from '../i18n'
import { fetchFeed, deleteFeedEntry } from '../api'

import { GalleryTab } from './GalleryTab'

/** Feed payload injected into the mocked SDK useQuery on every call. */
const queryState = vi.hoisted(() => ({
  data: undefined as FeedResponse | undefined,
  isLoading: false,
  isError: false
}))

vi.mock('@hermes/plugin-sdk', async () => {
  const React = await import('react')
  const { createElement, Fragment } = React

  const cn = (...args: unknown[]) => args.filter(Boolean).join(' ')

  const Codicon = ({ name, ...rest }: ComponentPropsWithoutRef<'span'> & { name?: string }) =>
    createElement('span', { ...rest, 'data-codicon': name })

  const Badge = ({ children, ...rest }: ComponentPropsWithoutRef<'span'> & { variant?: string }) =>
    createElement('span', { ...rest }, children)

  const Skeleton = ({ children, ...rest }: ComponentPropsWithoutRef<'div'>) =>
    createElement('div', { ...rest, 'data-testid': 'skeleton' }, children)

  const Button = ({ children, onClick, disabled, ...rest }: ComponentPropsWithoutRef<'button'> & { size?: string; variant?: string }) =>
    createElement('button', { type: 'button', onClick, disabled, ...rest }, children)

  const Input = (props: ComponentPropsWithoutRef<'input'>) => createElement('input', props)
  const Textarea = (props: ComponentPropsWithoutRef<'textarea'>) => createElement('textarea', props)

  const EmptyState = ({ title, description }: { title?: ReactNode; description?: ReactNode }) =>
    createElement(
      'div',
      { 'data-testid': 'empty-state' },
      createElement('div', null, title),
      description ? createElement('div', null, description) : null
    )

  const ErrorState = ({ title }: { title?: ReactNode }) =>
    createElement('div', { 'data-testid': 'error-state' }, title)

  const SegmentedControl = ({ options, value, onChange }: { options: Array<{ id: string; label: string }>; value: string; onChange?: (id: string) => void }) =>
    createElement(
      'div',
      { role: 'group' },
      options.map((option) =>
        createElement(
          'button',
          {
            key: option.id,
            type: 'button',
            'aria-pressed': value === option.id,
            onClick: () => onChange?.(option.id)
          },
          option.label
        )
      )
    )

  const SearchField = ({ value, onChange, placeholder, 'aria-label': ariaLabel, containerClassName }: { value?: string; onChange?: (value: string) => void; placeholder?: string; 'aria-label'?: string; containerClassName?: string }) =>
    createElement('input', {
      type: 'search',
      value,
      placeholder,
      'aria-label': ariaLabel,
      className: containerClassName,
      onChange: (event: ChangeEvent<HTMLInputElement>) => onChange?.(event.target.value)
    })

  const Select = ({ value, onValueChange, children }: { value?: string; onValueChange?: (value: string) => void; children?: ReactNode }) =>
    createElement(
      'select',
      { 'data-testid': 'provider-filter', value, onChange: (event: ChangeEvent<HTMLSelectElement>) => onValueChange?.(event.target.value) },
      children
    )
  const SelectTrigger = ({ children, ...rest }: ComponentPropsWithoutRef<'span'>) => createElement('span', { ...rest }, children)
  const SelectValue = () => null
  const SelectContent = ({ children }: { children?: ReactNode }) => createElement(Fragment, null, children)
  const SelectItem = ({ value, children }: { value?: string; children?: ReactNode }) => createElement('option', { value }, children)

  const ConfirmDialog = ({ open, title, description, confirmLabel, cancelLabel, onConfirm, onClose }: {
    open?: boolean
    title?: ReactNode
    description?: ReactNode
    confirmLabel?: string
    cancelLabel?: string
    onConfirm?: () => void
    onClose?: () => void
  }) => {
    if (!open) return null
    return createElement(
      'div',
      { role: 'dialog', 'aria-label': typeof title === 'string' ? title : 'confirm' },
      createElement('div', null, title),
      description ? createElement('p', null, description) : null,
      createElement('button', { type: 'button', onClick: () => void onConfirm?.() }, confirmLabel || 'Confirm'),
      createElement('button', { type: 'button', onClick: onClose }, cancelLabel || 'Cancel')
    )
  }

  const Dialog = ({ open, children }: { open?: boolean; onOpenChange?: (open: boolean) => void; children?: ReactNode }) =>
    open ? createElement('div', { role: 'dialog', 'data-testid': 'dialog' }, children) : null
  const DialogContent = ({ children }: { children?: ReactNode }) => createElement('div', null, children)
  const DialogHeader = ({ children }: { children?: ReactNode }) => createElement('div', null, children)
  const DialogTitle = ({ children }: { children?: ReactNode }) => createElement('h2', null, children)

  const DropdownMenu = ({ children }: { children?: ReactNode }) => createElement('div', { 'data-testid': 'dropdown-menu' }, children)
  const DropdownMenuTrigger = ({ children, ...rest }: ComponentPropsWithoutRef<'button'>) => createElement('button', { type: 'button', ...rest }, children)
  const DropdownMenuContent = ({ children }: { children?: ReactNode }) => createElement('div', null, children)
  const DropdownMenuItem = ({ children, onClick }: { children?: ReactNode; onClick?: () => void }) => createElement('button', { type: 'button', onClick }, children)

  const useQuery = vi.fn(({ queryFn }: { queryKey?: unknown[]; queryFn?: () => unknown; staleTime?: number }) => {
    queryFn?.()
    return { data: queryState.data, isLoading: queryState.isLoading, isError: queryState.isError }
  })


  return {
    Badge,
    Button,
    cn,
    Codicon,
    ConfirmDialog,
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    EmptyState,
    ErrorState,
    Input,
    icons: {},
    SearchField,
    SegmentedControl,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Skeleton,
    Textarea,
    useQuery
  }
})

vi.mock('../api', async (original) => ({
  ...(await original<typeof import('../api')>()),
  ID: 'imagegen',
  fetchFeed: vi.fn(),
  fetchFeedStats: vi.fn(() => Promise.resolve({ stats: { total: 0, saved: 0, generated: 0 } })),
  deleteFeedEntry: vi.fn(),
  exportFeedZip: vi.fn(),
  exportGalleryPack: vi.fn(),
  getStored: vi.fn((_key: string, fallback: unknown) => fallback),
  setStored: vi.fn(),
  invalidateFeed: vi.fn(),
  queryClient: { invalidateQueries: vi.fn() },
  rest: vi.fn(),
  fetchJob: vi.fn(),
  cancelJob: vi.fn(),
  retryJob: vi.fn()
}))

/** Test seam: translate into the plugin's default language (en). */
const T = (key: string, args?: Record<string, string>) => translate('en', key, args)

function makeItem(overrides: Partial<FeedItem> = {}): FeedItem {
  return {
    id: 'item-1',
    source: 'generated',
    ts: 1700000000000,
    prompt: 'A red apple on a table',
    provider: 'fal',
    model: 'fal-1',
    kind: 'generate',
    images: [{ url: 'http://img.local/1.png', galleryId: 'g1', localPath: 'C:/pics/1.png' }],
    config: {},
    galleryIds: ['g1'],
    ...overrides
  }
}

function makeFeed(items: FeedItem[]): FeedResponse {
  return {
    items,
    stats: {
      total: items.length,
      saved: items.filter((item) => item.source === 'saved').length,
      generated: items.filter((item) => item.source === 'generated').length,
      bytes: 1024
    }
  }
}

/** Point the mocked useQuery at a feed payload (and record fetchFeed calls). */
function stubFeed(feed: FeedResponse, opts: { isLoading?: boolean; isError?: boolean } = {}) {
  queryState.data = feed
  queryState.isLoading = opts.isLoading ?? false
  queryState.isError = opts.isError ?? false
}

function renderTab(feed: FeedResponse) {
  stubFeed(feed)
  return render(
    <GalleryTab
      config={{} as ImageGenConfig}
      updateConfig={vi.fn()}
      onGoToTab={vi.fn()}
      onUseConfig={vi.fn()}
      library={[]}
      prompt=""
    />
  )
}

const lastFeedParams = (): FeedParams | undefined =>
  vi.mocked(fetchFeed).mock.calls.map((call) => call[0] as FeedParams).at(-1)

/** Wait out the 250ms search debounce with real timers. */
async function flushDebounce() {
  let resolve!: () => void
  const promise = new Promise<void>((r) => {
    resolve = r
  })
  setTimeout(resolve, 300)
  await act(async () => {
    await promise
  })
}

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  cleanup()
})

describe('GalleryTab — unified feed', () => {
  it('renders generated and saved items in a single grid', () => {
    const feed = makeFeed([
      makeItem({ id: 'gen-1', source: 'generated', prompt: 'Sunset over the ocean' }),
      makeItem({ id: 'sav-1', source: 'saved', prompt: 'Product shot of a watch' })
    ])
    renderTab(feed)

    const grid = screen.getByRole('list', { name: T('feedGridLabel') })
    expect(within(grid).getAllByRole('listitem')).toHaveLength(2)

    // Both source badges render inside the one grid.
    expect(within(grid).getByText(T('feedGenerated'))).toBeTruthy()
    expect(within(grid).getByText(T('feedSaved'))).toBeTruthy()

    // Every card has an accessible name identifying the image (prompt + meta).
    expect(
      screen.getByRole('button', {
        name: T('feedItemName', { prompt: 'Sunset over the ocean', meta: `fal · fal-1 · ${relativeTimeActive(1700000000000)}` })
      })
    ).toBeTruthy()
    expect(
      screen.getByRole('button', {
        name: T('feedItemName', { prompt: 'Product shot of a watch', meta: `fal · fal-1 · ${relativeTimeActive(1700000000000)}` })
      })
    ).toBeTruthy()
  })

  it('loads the feed with the default filters', () => {
    renderTab(makeFeed([makeItem()]))
    expect(lastFeedParams()).toEqual(expect.objectContaining({ source: 'all', limit: 200 }))
  })
})

describe('GalleryTab — filters', () => {
  it('restricts the feed by source', () => {
    renderTab(makeFeed([makeItem()]))
    fireEvent.click(screen.getByRole('button', { name: T('feedSaved') }))
    expect(lastFeedParams()).toEqual(expect.objectContaining({ source: 'saved' }))
  })

  it('filters by provider', () => {
    renderTab(makeFeed([makeItem({ provider: 'fal', model: 'fal-1' })]))
    fireEvent.change(screen.getAllByTestId('provider-filter')[0], { target: { value: 'fal' } })
    expect(lastFeedParams()).toEqual(expect.objectContaining({ provider: 'fal' }))
  })

  it('filters by search prompt (debounced)', async () => {
    renderTab(makeFeed([makeItem()]))
    fireEvent.change(screen.getByRole('searchbox', { name: T('feedSearchLabel') }), { target: { value: 'watch' } })
    await flushDebounce()
    expect(lastFeedParams()).toEqual(expect.objectContaining({ q: 'watch' }))
  })
})

describe('GalleryTab — empty states', () => {
  it('shows the generic empty state when the gallery is empty', () => {
    renderTab(makeFeed([]))
    expect(screen.getByText(T('emptyGallery'))).toBeTruthy()
    expect(screen.getByText(T('galleryHint'))).toBeTruthy()
  })

  it('shows the search-specific empty state once the debounce lands', async () => {
    renderTab(makeFeed([]))
    fireEvent.change(screen.getByRole('searchbox', { name: T('feedSearchLabel') }), { target: { value: 'zzz' } })
    await flushDebounce()
    expect(screen.getByText(T('noResult'))).toBeTruthy()
    expect(screen.getByText(T('feedEmptySearchHint'))).toBeTruthy()
    expect(screen.queryByText(T('emptyGallery'))).toBeNull()
  })

  it('shows the saved-only empty state when the source filter is saved', () => {
    renderTab(makeFeed([]))
    fireEvent.click(screen.getByRole('button', { name: T('feedSaved') }))
    expect(screen.getByText(T('feedEmptySavedTitle'))).toBeTruthy()
    expect(screen.getByText(T('feedEmptySavedHint'))).toBeTruthy()
  })
})

describe('GalleryTab — delete confirmation', () => {
  it('asks for confirmation and announces that history + files are removed', async () => {
    vi.mocked(deleteFeedEntry).mockResolvedValue({ ok: true })
    renderTab(makeFeed([makeItem({ prompt: 'Old draft' })]))

    const cardName = T('feedItemName', { prompt: 'Old draft', meta: `fal · fal-1 · ${relativeTimeActive(1700000000000)}` })
    fireEvent.click(screen.getByRole('button', { name: cardName }))
    fireEvent.click(screen.getByRole('button', { name: T('delete') }))

    const dialog = screen.getByRole('dialog')
    const description = T('confirmDeleteFeedName', { name: 'Old draft' })
    expect(within(dialog).getByText(description)).toBeTruthy()
    // The confirmation names what is deleted: the history entry and the files.
    expect(description).toMatch(/history/)
    expect(description).toMatch(/files/)

    fireEvent.click(within(dialog).getByRole('button', { name: T('delete') }))
    await act(async () => {})
    expect(deleteFeedEntry).toHaveBeenCalledWith('item-1')
  })
})

describe('GalleryTab — detail panel', () => {
  it('exposes distinct accessible actions and focuses the panel on open', () => {
    renderTab(makeFeed([makeItem()]))

    const card = screen.getByRole('button', { name: T('feedItemName', { prompt: 'A red apple on a table', meta: `fal · fal-1 · ${relativeTimeActive(1700000000000)}` }) })
    fireEvent.click(card)

    const panel = screen.getByRole('region', { name: T('generationDetails') })
    expect(document.activeElement).toBe(panel)

    const names = within(panel)
      .getAllByRole('button')
      .map((button) => button.getAttribute('aria-label') || button.textContent?.trim() || '')
    // The mocked menus render inline: Edit, Download, the two menu triggers and every item.
    expect(new Set(names).size).toBe(names.length)
    expect(names).toEqual(
      expect.arrayContaining([
        T('download'),
        T('sendToEdit'),
        T('useAgain'),
        T('useAgainAsRef'),
        T('moreActions'),
        T('useInGenerator'),
        T('copyPrompt'),
        T('saveRecipe'),
        T('exportPack'),
        T('viewInFolder'),
        T('delete'),
        T('close')
      ])
    )
  })

  it('returns focus to the card when the panel closes', () => {
    renderTab(makeFeed([makeItem()]))

    const card = screen.getByRole('button', { name: T('feedItemName', { prompt: 'A red apple on a table', meta: `fal · fal-1 · ${relativeTimeActive(1700000000000)}` }) })
    // A real click focuses the card before selectItem captures it.
    card.focus()
    fireEvent.click(card)
    expect(document.activeElement).toBe(screen.getByRole('region', { name: T('generationDetails') }))

    fireEvent.click(screen.getByRole('button', { name: T('close') }))
    expect(document.activeElement).toBe(card)
    expect(screen.queryByRole('region', { name: T('generationDetails') })).toBeNull()
  })
})

describe('GalleryTab — filter accessibility', () => {
  it('associates labels with the source, search, and provider filters', () => {
    const { container } = renderTab(makeFeed([makeItem()]))

    expect(screen.getByRole('group', { name: T('filterBySource') })).toBeTruthy()
    expect(screen.getByRole('searchbox', { name: T('feedSearchLabel') })).toBeTruthy()
    expect(container.querySelector(`[aria-label="${T('filterByProvider')}"]`)).not.toBeNull()
  })
})
