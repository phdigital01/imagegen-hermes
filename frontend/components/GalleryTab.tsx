/**
 * ImageGen — unified gallery tab.
 * Single library surface over the backend feed: generated (history) and saved
 * (gallery) entries share one grid, one detail panel, and one action set.
 * Bulk: checkbox per card, selected count badge, Compare (2-4) side-by-side
 * modal + Export zip, provider filter via GET /feed/stats distinct, sort.
 */

import {
  Badge,
  Button,
  cn,
  Codicon,
  ConfirmDialog,
  Dialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DialogContent,
  DialogHeader,
  DialogTitle,
  EmptyState,
  ErrorState,
  Input,
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
} from '@hermes/plugin-sdk'
import { useEffect, useMemo, useRef, useState, type ChangeEvent } from 'react'

import type { FeedItem, FeedParams, FeedSource, FeedSort, ImageGenConfig, LibraryEntry, Provider } from '../types'
import { ID, deleteFeedEntry, exportFeedZip, exportGalleryPack, fetchFeed, fetchFeedStats, getStored, invalidateFeed, queryClient, rest, setStored } from '../api'
import { relativeTimeActive, useImageGenT } from '../i18n'
import { GRID, ImagePreview, Thumb, copyText, displayUrl, downloadFromUrl, revealInFolder } from './ui-helpers'
import { refsToMeta } from '../presets'

type FeedSourceFilter = 'all' | FeedSource

/** Persisted filter keys — filters survive tab switches and reloads. */
const FEED_SOURCE_KEY = 'feed.source'
const FEED_QUERY_KEY = 'feed.q'
const FEED_PROVIDER_KEY = 'feed.provider'
const FEED_SORT_KEY = 'feed.sort'
/** Radix Select rejects an empty string value, so "no filter" needs a token. */
const ALL_PROVIDERS = '__all__'

export function GalleryTab({
  config,
  onGoToTab,
  onUseConfig,
  library,
  prompt,
  providers: providerList = []
}: {
  config: ImageGenConfig
  updateConfig: (partial: Partial<ImageGenConfig>) => void
  onGoToTab: (tab: string, options?: { image?: string }) => void
  onUseConfig: (config: Partial<ImageGenConfig>, prompt?: string) => void
  library: LibraryEntry[]
  prompt: string
  /** Used only to show a model's friendly name on the cards. */
  providers?: Provider[]
}) {
  const t = useImageGenT()
  const [source, setSource] = useState<FeedSourceFilter>(() => getStored<FeedSourceFilter>(FEED_SOURCE_KEY, 'all'))
  const [q, setQ] = useState<string>(() => getStored<string>(FEED_QUERY_KEY, ''))
  const [qInput, setQInput] = useState<string>(() => getStored<string>(FEED_QUERY_KEY, ''))
  const [provider, setProvider] = useState<string>(() => getStored<string>(FEED_PROVIDER_KEY, ''))
  const [sort, setSort] = useState<FeedSort>(() => getStored<FeedSort>(FEED_SORT_KEY, 'newest'))

  const [selected, setSelected] = useState<FeedItem | null>(null)
  const [activeIndex, setActiveIndex] = useState(0)

  // Bulk selection: checkbox per card + selected count badge + actions bar
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [selecting, setSelecting] = useState(false)
  const [compareOpen, setCompareOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState('')

  // Detail-panel focus management: focus moves into the panel when it opens
  // and returns to the card that opened it when it closes.
  const panelRef = useRef<HTMLDivElement | null>(null)
  const lastFocusedRef = useRef<HTMLElement | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<FeedItem | null>(null)
  const [clearOpen, setClearOpen] = useState(false)
  const [folderError, setFolderError] = useState('')
  const [copied, setCopied] = useState(false)

  // Recipe (prompt library) dialog state.
  const [libraryOpen, setLibraryOpen] = useState(false)
  const [libName, setLibName] = useState('')
  const [libPrompt, setLibPrompt] = useState('')
  const [libEditId, setLibEditId] = useState<string | null>(null)
  const [librarySaving, setLibrarySaving] = useState(false)
  const [libraryError, setLibraryError] = useState('')
  const [librarySaved, setLibrarySaved] = useState(false)

  useEffect(() => { setStored(FEED_SOURCE_KEY, source) }, [source])
  useEffect(() => { setStored(FEED_QUERY_KEY, q) }, [q])
  useEffect(() => { setStored(FEED_PROVIDER_KEY, provider) }, [provider])
  useEffect(() => { setStored(FEED_SORT_KEY, sort) }, [sort])

  // Debounce the search field (~250ms) before it hits the feed query.
  useEffect(() => {
    const timer = setTimeout(() => setQ(qInput.trim()), 250)
    return () => clearTimeout(timer)
  }, [qInput])

  const filters = useMemo<FeedParams>(() => ({
    source,
    provider: provider || undefined,
    q: q || undefined,
    limit: 200,
    sort
  }), [source, provider, q, sort])

  const feedQuery = useQuery({
    queryKey: [ID, 'feed', filters],
    queryFn: () => fetchFeed(filters),
    staleTime: 30_000
  })

  const statsQuery = useQuery({
    queryKey: [ID, 'feed', 'stats'],
    queryFn: () => fetchFeedStats(),
    staleTime: 60_000
  })

  const items = feedQuery.data?.items || []
  const stats = feedQuery.data?.stats
  const isLoading = feedQuery.isLoading
  const isError = feedQuery.isError

  // Provider options via GET /feed/stats distinct, fallback to derived from items
  const providers = useMemo(() => {
    const fromStats = statsQuery.data?.providers || statsQuery.data?.stats?.providers || []
    if (fromStats.length > 0) return [...fromStats].sort((a, b) => a.localeCompare(b))
    const seen = new Set<string>()
    items.forEach((item) => { if (item.provider) seen.add(item.provider) })
    return [...seen].sort((a, b) => a.localeCompare(b))
  }, [items, statsQuery.data])

  // Client-side sort as safety when backend sort is not yet deployed; also
  // covers the case where the user toggles sort without a refetch.
  const sortedItems = useMemo(() => {
    const copy = [...items]
    if (sort === 'oldest') copy.sort((a, b) => (a.ts || 0) - (b.ts || 0))
    else if (sort === 'prompt_az') copy.sort((a, b) => (a.prompt || '').localeCompare(b.prompt || '') || (a.ts || 0) - (b.ts || 0))
    else copy.sort((a, b) => (b.ts || 0) - (a.ts || 0))
    return copy
  }, [items, sort])

  const activeImage = selected ? (selected.images[activeIndex] ?? selected.images[0]) : undefined

  // Keep selectedIds consistent when items change (e.g. after delete)
  useEffect(() => {
    if (selectedIds.size === 0) return
    const ids = new Set(sortedItems.map((it) => it.id))
    let changed = false
    for (const sid of [...selectedIds]) if (!ids.has(sid)) { selectedIds.delete(sid); changed = true }
    if (changed) setSelectedIds(new Set(selectedIds))
  }, [sortedItems]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleSelected = (id: string, checked?: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      const willAdd = checked !== undefined ? checked : !next.has(id)
      if (willAdd) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const selectedItems = useMemo(() => sortedItems.filter((it) => selectedIds.has(it.id)), [sortedItems, selectedIds])
  const canCompare = selectedIds.size >= 2 && selectedIds.size <= 4
  const modelName = (item: FeedItem) => providerList.find((entry) => entry.name === item.provider)?.models.find((entry) => entry.id === item.model)?.display || item.model || item.provider || ''
  const selectedCount = selectedIds.size

  const doExportZip = async () => {
    if (selectedIds.size === 0) return
    setExporting(true)
    setExportError('')
    try {
      const payload = await exportFeedZip([...selectedIds])
      if (payload.url) window.open(payload.url, '_blank')
      else if (payload.path) window.open(payload.path, '_blank')
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e))
    } finally {
      setExporting(false)
    }
  }

  const selectItem = (item: FeedItem) => {
    lastFocusedRef.current = document.activeElement as HTMLElement | null
    setSelected(item)
    setActiveIndex(0)
    setFolderError('')
    setCopied(false)
  }

  const closeDetail = () => {
    setSelected(null)
    setActiveIndex(0)
    const node = lastFocusedRef.current
    lastFocusedRef.current = null
    if (node && node.isConnected) node.focus()
  }

  // Move focus into the detail panel the moment it opens.
  useEffect(() => {
    if (selected) panelRef.current?.focus()
  }, [selected])

  const del = async (item: FeedItem) => {
    try {
      await deleteFeedEntry(item.id)
      invalidateFeed()
      setSelectedIds((prev) => { const n = new Set(prev); n.delete(item.id); return n })
      if (selected?.id === item.id) {
        setSelected(null)
        setActiveIndex(0)
      }
    } finally {
      setDeleteTarget(null)
    }
  }

  const clearGallery = async () => {
    try {
      await rest('/gallery', 'DELETE')
      setSelected(null)
      setSelectedIds(new Set())
      invalidateFeed()
    } finally {
      setClearOpen(false)
    }
  }

  const formatBytes = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
  }

  const galleryIdFor = (item: FeedItem): string => {
    const image = item.images[activeIndex] ?? item.images[0]
    return image?.galleryId || item.galleryIds?.[0] || ''
  }

  const revealSelected = async () => {
    setFolderError('')
    if (!activeImage?.localPath || await revealInFolder(activeImage.localPath)) return
    setFolderError(t('viewInFolderFailed'))
  }

  const copyPrompt = async () => {
    if (!selected?.prompt) return
    await copyText(selected.prompt)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const exportPack = async (item: FeedItem) => {
    const gid = galleryIdFor(item)
    if (!gid) return
    const payload = await exportGalleryPack(gid)
    if (payload.url) window.open(payload.url, '_blank')
  }

  const saveLibrary = async () => {
    if (!libName.trim()) {
      setLibraryError(t('recipeNameRequired'))
      return
    }
    if (!libPrompt.trim()) {
      setLibraryError(t('recipePromptRequired'))
      return
    }
    setLibrarySaving(true)
    setLibraryError('')
    setLibrarySaved(false)
    const original = libEditId ? library.find((item) => item.id === libEditId) : undefined
    const cfg = (original?.config || selected?.config || config) as ImageGenConfig
    const refs = refsToMeta(cfg.referencesV4 || [])
    const cleanCfg = { ...cfg, referencesV4: refs }
    try {
      await rest('/library', 'POST', {
        id: libEditId || undefined,
        name: libName.trim(),
        prompt: libPrompt.trim(),
        config: cleanCfg,
        refs,
        genre: cfg.genre || '',
        negativePrompt: cfg.negativePrompt || ''
      })
      setLibrarySaved(true)
      queryClient.invalidateQueries({ queryKey: [ID, 'library'] })
    } catch (error) {
      setLibraryError(error instanceof Error ? error.message : t('recipeSaveFailed'))
    } finally {
      setLibrarySaving(false)
    }
  }

  const resetLibraryDialog = () => {
    setLibraryOpen(false)
    setLibName('')
    setLibPrompt('')
    setLibEditId(null)
    setLibraryError('')
    setLibrarySaved(false)
  }

  const openNewRecipe = (initialPrompt = prompt) => {
    setLibEditId(null)
    setLibName('')
    setLibPrompt(initialPrompt || config.description || '')
    setLibraryError('')
    setLibrarySaved(false)
    setLibraryOpen(true)
  }

  const editLibrary = (entry: LibraryEntry) => {
    setLibEditId(entry.id)
    setLibName(entry.name)
    setLibPrompt(entry.prompt || '')
    setLibraryOpen(true)
  }

  const applyLibrary = (entry: LibraryEntry) => {
    const cfg = (entry.config && Object.keys(entry.config).length > 3 ? entry.config : config) as ImageGenConfig
    const merged = { ...config, ...cfg, selectedModel: cfg.selectedModel || config.selectedModel }
    onUseConfig(merged as Partial<ImageGenConfig>, entry.prompt)
  }

  const handleSearchChange = (value: string | ChangeEvent<HTMLInputElement>) => {
    setQInput(typeof value === 'string' ? value : value.target.value)
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label={t('filterBySource')}>
          <SegmentedControl
            value={source}
            onChange={(id) => setSource(id)}
            options={[
              { id: 'all' as const, label: t('all') },
              { id: 'generated' as const, label: t('feedGenerated') },
              { id: 'saved' as const, label: t('feedSaved') }
            ]}
          />
        </div>
        <SearchField
          value={qInput}
          onChange={handleSearchChange}
          placeholder={t('feedSearchPlaceholder')}
          aria-label={t('feedSearchLabel')}
          containerClassName="w-56"
        />
        <Select value={provider || ALL_PROVIDERS} onValueChange={(value) => setProvider(value === ALL_PROVIDERS ? '' : value)}>
          <SelectTrigger aria-label={t('filterByProvider')} className="h-8 w-44 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_PROVIDERS}>{t('allProviders')}</SelectItem>
            {providers.map((name) => (
              <SelectItem key={name} value={name}>{name}</SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={sort} onValueChange={(v) => setSort(v as FeedSort)}>
          <SelectTrigger aria-label={t('sortBy')} className="h-8 w-36 text-xs">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="newest">{t('newest')}</SelectItem>
            <SelectItem value="oldest">{t('oldest')}</SelectItem>
            <SelectItem value="prompt_az">{t('promptAZ')}</SelectItem>
          </SelectContent>
        </Select>
        <div className="ml-auto flex items-center gap-2">
          <Button size="sm" variant={selecting ? 'default' : 'outline'} className="h-8 gap-1 text-xs" aria-pressed={selecting} onClick={() => { if (selecting) setSelectedIds(new Set()); setSelecting(!selecting) }}>
            <Codicon name="checklist" style={{ fontSize: 13 }} />
            {selecting ? t('selectDone') : t('selectMode')}
          </Button>
          {selectedCount > 0 && (
            <Badge variant="outline" className="text-[10px]" aria-label={t('selectedCount', { count: String(selectedCount) })}>
              {t('selectedCount', { count: String(selectedCount) })}
            </Badge>
          )}
          <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" onClick={() => openNewRecipe()}>
            <Codicon name="book" style={{ fontSize: 13 }} />
            {t('saveRecipe')}
            {library?.length > 0 && (
              <Badge variant="muted" className="text-[9px]">
                {library.length}
              </Badge>
            )}
          </Button>
        </div>
      </div>

      {/* Bulk actions bar */}
      {selectedCount > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) px-3 py-2" role="toolbar" aria-label={t('bulkActions')}>
          <span className="text-xs font-medium">{t('selectedCount', { count: String(selectedCount) })}</span>
          <div className="ml-auto flex items-center gap-2">
            <Button
              size="sm"
              variant="outline"
              className="h-7 text-xs"
              disabled={!canCompare}
              title={canCompare ? t('compareHint') : t('compareNeeds')}
              onClick={() => setCompareOpen(true)}
            >
              <Codicon name="compare-changes" style={{ fontSize: 12 }} />
              {t('compare')} {selectedCount >= 2 ? `(${selectedCount})` : ''}
            </Button>
            <Button size="sm" className="h-7 gap-1 text-xs" disabled={exporting} onClick={() => void doExportZip()}>
              <Codicon name="archive" style={{ fontSize: 12 }} />
              {exporting ? t('exporting') : t('exportZip')}
            </Button>
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setSelectedIds(new Set())}>
              {t('clear')}
            </Button>
          </div>
        </div>
      )}
      {exportError && <div className="rounded-md border border-(--ui-error)/30 bg-(--ui-error)/10 px-2.5 py-2 text-[11px] text-(--ui-error)">{exportError}</div>}
      {!canCompare && selectedCount > 0 && selectedCount !== 1 && (
        <div className="text-[11px] text-(--ui-text-tertiary)">{t('compareNeeds')}</div>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-(--ui-stroke-secondary) px-3 py-2 text-[10px] text-(--ui-text-tertiary)">
        <span>
          {stats
            ? t('feedSummary', {
                total: String(stats.total),
                saved: String(stats.saved),
                generated: String(stats.generated),
                bytes: formatBytes(stats.bytes)
              })
            : `${t('storage')}…`}
        </span>
        <Button size="sm" variant="ghost" className="h-6 px-2 text-[10px] text-(--ui-error)" disabled={!stats?.total} onClick={() => setClearOpen(true)}>
          {t('clearGallery')}
        </Button>
      </div>

      {isLoading && <Skeleton className="h-48 w-full" />}
      {isError && <ErrorState title={t('feedLoadFailed')} />}
      {!isLoading && !isError && sortedItems.length === 0 && (
        source === 'saved' ? (
          <EmptyState title={t('feedEmptySavedTitle')} description={t('feedEmptySavedHint')} />
        ) : q ? (
          <EmptyState title={t('noResult')} description={t('feedEmptySearchHint')} />
        ) : (
          <EmptyState title={t('emptyGallery')} description={t('galleryHint')} />
        )
      )}
      {sortedItems.length > 0 && (
        <div role="list" aria-label={t('feedGridLabel')} className="gap-3" style={GRID(5)}>
          {sortedItems.map((item) => {
            const first = item.images[0]
            const cardMeta = [item.provider, item.model, item.ts ? relativeTimeActive(item.ts) : ''].filter(Boolean).join(' · ')
            const checked = selectedIds.has(item.id)
            return (
              <div role="listitem" key={item.id} className={cn("group overflow-hidden rounded-xl border bg-(--ui-bg-elevated)", checked ? "border-(--ui-accent) ring-1 ring-(--ui-accent)" : "border-(--ui-stroke-secondary)")}>
              {(selecting || selectedCount > 0) && <div className="flex items-center justify-between gap-2 border-b border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 py-1">
                <label className="flex items-center gap-1.5 text-[11px] cursor-pointer">
                  <input
                    type="checkbox"
                    checked={checked}
                    aria-label={t('selectItem', { name: item.prompt || item.id })}
                    onChange={(e) => toggleSelected(item.id, e.target.checked)}
                    onClick={(e) => e.stopPropagation()}
                    className="h-3.5 w-3.5 accent-(--ui-accent)"
                  />
                  <span className={cn("truncate max-w-[90px]", checked ? "text-(--ui-accent) font-medium" : "text-(--ui-text-tertiary)")}>{checked ? t('selectedCount', { count: '✓' }) : ''}</span>
                </label>
                <span className="text-[9px] text-(--ui-text-tertiary) truncate">{item.provider || ''}</span>
              </div>}
              <button
                type="button"
                aria-label={t('feedItemName', { prompt: item.prompt || item.id, meta: cardMeta })}
                className="block w-full text-left"
                onClick={() => (selecting ? toggleSelected(item.id, !checked) : selectItem(item))}
              >
                <div className="relative aspect-square">
                  {first ? (
                    <ImagePreview item={first} className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105" alt={item.prompt || item.id} />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center">
                      <Thumb iconName="file-media" size={56} rounded="rounded-none" />
                    </div>
                  )}
                  <div className="absolute left-1.5 top-1.5">
                    <Badge variant={item.source === 'saved' ? 'muted' : 'outline'} className="text-[9px]">
                      {item.source === 'saved' ? t('feedSaved') : t('feedGenerated')}
                    </Badge>
                  </div>
                  {item.images.length > 1 && (
                    <span className="absolute right-1.5 top-1.5 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) px-1.5 py-0.5 text-[10px] font-medium text-(--ui-text-secondary)">
                      {item.images.length}
                    </span>
                  )}
                </div>
                <div className="space-y-0.5 border-t border-(--ui-stroke-secondary) px-2 py-1.5">
                  {item.prompt && <div className="if-tile-prompt">{item.prompt}</div>}
                  <div className="truncate text-[9px] text-(--ui-text-tertiary)">
                    {[modelName(item), item.ts ? relativeTimeActive(item.ts) : ''].filter(Boolean).join(' · ')}
                  </div>
                </div>
              </button>
              </div>
            )
          })}
        </div>
      )}

      {selected && (
        <div
          ref={panelRef}
          tabIndex={-1}
          role="region"
          aria-label={t('generationDetails')}
          className="if-pop grid gap-4 rounded-xl border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) p-4 outline-none focus-visible:ring-2 focus-visible:ring-(--ui-accent)"
          style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))' }}
        >
          <div className="space-y-2">
            <div className="if-checker overflow-hidden rounded-lg">
              {activeImage ? (
                <ImagePreview item={activeImage} className="w-full" alt={selected.prompt || selected.id} />
              ) : (
                <div className="flex h-40 items-center justify-center text-(--ui-text-tertiary)">{t('noResult')}</div>
              )}
            </div>
            {selected.images.length > 1 && (
              <div className="flex flex-wrap gap-1.5">
                {selected.images.map((image, index) => (
                  <button
                    type="button"
                    key={index}
                    aria-label={t('feedImageIndex', { n: String(index + 1), total: String(selected.images.length) })}
                    onClick={() => { setActiveIndex(index); setFolderError('') }}
                    className={cn(
                      'h-12 w-12 overflow-hidden rounded-md border',
                      index === activeIndex ? 'border-(--ui-accent)' : 'border-(--ui-stroke-secondary) opacity-70 hover:opacity-100'
                    )}
                  >
                    <ImagePreview item={image} className="h-full w-full object-cover" alt="" />
                  </button>
                ))}
              </div>
            )}
          </div>
          <div className="space-y-2.5 text-xs">
            <div className="flex items-center justify-between">
              <span className="font-medium">{t('generationDetails')}</span>
              <button type="button" aria-label={t('close')} className="text-(--ui-text-tertiary) hover:text-foreground" onClick={closeDetail}>
                <Codicon name="close" />
              </button>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {selected.kind && (
                <Badge variant="muted" className="text-[10px]">
                  {selected.kind}
                </Badge>
              )}
              <Badge variant={selected.source === 'saved' ? 'muted' : 'outline'} className="text-[10px]">
                {selected.source === 'saved' ? t('feedSaved') : t('feedGenerated')}
              </Badge>
              {selected.provider && (
                <Badge variant="outline" className="text-[10px]">
                  {selected.provider}
                </Badge>
              )}
              {selected.model && (
                <Badge variant="outline" className="text-[10px]" title={selected.model}>
                  {modelName(selected)}
                </Badge>
              )}
              {selected.ts ? (
                <Badge variant="outline" className="text-[10px]">
                  {relativeTimeActive(selected.ts)}
                </Badge>
              ) : null}
            </div>
            {selected.prompt && (
              <div className="max-h-40 overflow-y-auto rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg) p-2.5 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
                {selected.prompt}
              </div>
            )}
            <div className="flex flex-wrap gap-1.5 pt-1">
              <Button
                size="sm"
                className="h-7 gap-1 text-xs"
                disabled={!activeImage}
                onClick={() => onGoToTab('edit', { image: displayUrl(activeImage) })}
              >
                <Codicon name="edit" style={{ fontSize: 12 }} />
                {t('sendToEdit')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 gap-1 text-xs"
                disabled={!activeImage}
                onClick={() => void downloadFromUrl(displayUrl(activeImage), `imagegen-${selected.id}${selected.images.length > 1 ? `-${activeIndex + 1}` : ''}.png`)}
              >
                <Codicon name="download" style={{ fontSize: 12 }} />
                {t('download')}
              </Button>
              <DropdownMenu>
                <DropdownMenuTrigger type="button" className="if-menu-button">
                  <Codicon name="sparkle" style={{ fontSize: 12 }} />
                  {t('useAgain')}
                  <Codicon name="chevron-down" style={{ fontSize: 11 }} />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="imagegen-ui min-w-52">
                  <DropdownMenuItem onClick={() => { if (activeImage) onGoToTab('generate', { image: displayUrl(activeImage) }) }}>
                    <Codicon name="link" style={{ fontSize: 13 }} />
                    {t('useAgainAsRef')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => { onUseConfig(selected.config, selected.prompt); onGoToTab('generate') }}>
                    <Codicon name="history" style={{ fontSize: 13 }} />
                    {t('useInGenerator')}
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => openNewRecipe(selected.prompt || prompt)}>
                    <Codicon name="book" style={{ fontSize: 13 }} />
                    {t('saveRecipe')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <DropdownMenu>
                <DropdownMenuTrigger type="button" className="if-menu-button" aria-label={t('moreActions')} title={t('moreActions')}>
                  <Codicon name="more" style={{ fontSize: 13 }} />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="imagegen-ui min-w-48">
                  {selected.prompt && <DropdownMenuItem onClick={() => void copyPrompt()}>
                    <Codicon name="copy" style={{ fontSize: 13 }} />
                    {copied ? t('copied') : t('copyPrompt')}
                  </DropdownMenuItem>}
                  {galleryIdFor(selected) && <DropdownMenuItem onClick={() => void exportPack(selected)}>
                    <Codicon name="archive" style={{ fontSize: 13 }} />
                    {t('exportPack')}
                  </DropdownMenuItem>}
                  {activeImage?.localPath && <DropdownMenuItem onClick={() => void revealSelected()}>
                    <Codicon name="folder-opened" style={{ fontSize: 13 }} />
                    {t('viewInFolder')}
                  </DropdownMenuItem>}
                  <DropdownMenuItem onClick={() => setDeleteTarget(selected)}>
                    <Codicon name="trash" style={{ fontSize: 13 }} />
                    {t('delete')}
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
            {folderError && <div className="text-[10.5px] text-(--ui-error)">{folderError}</div>}
          </div>
        </div>
      )}

      {/* Compare 2-4 side-by-side modal */}
      <Dialog open={compareOpen} onOpenChange={setCompareOpen}>
        <DialogContent className="imagegen-ui max-w-5xl">
          <DialogHeader>
            <DialogTitle className="text-sm">{t('compareTitle')} — {selectedItems.length} {t('refsLabel')}</DialogTitle>
          </DialogHeader>
          {!canCompare ? (
            <div className="py-6 text-center text-xs text-(--ui-text-tertiary)">{t('compareNeeds')}</div>
          ) : (
            <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${Math.min(4, selectedItems.length)}, minmax(0,1fr))` }}>
              {selectedItems.map((item) => {
                const img = item.images[0]
                return (
                  <div key={item.id} className="space-y-1.5 rounded-lg border border-(--ui-stroke-secondary) p-2">
                    <div className="aspect-square overflow-hidden rounded bg-(--ui-bg)">
                      {img ? <ImagePreview item={img} className="h-full w-full object-cover" alt={item.prompt || item.id} /> : <div className="flex h-full items-center justify-center text-(--ui-text-tertiary)">{t('noResult')}</div>}
                    </div>
                    <div className="space-y-1">
                      <div className="flex flex-wrap gap-1">
                        <Badge variant="outline" className="text-[9px]">{item.provider || '—'}</Badge>
                        <Badge variant="muted" className="text-[9px]">{item.model || ''}</Badge>
                      </div>
                      <div className="line-clamp-3 text-[11px] leading-relaxed">{item.prompt || '—'}</div>
                      <div className="text-[10px] text-(--ui-text-tertiary)">{item.ts ? relativeTimeActive(item.ts) : ''}</div>
                      <div className="flex gap-1 pt-1">
                        <Button size="sm" variant="outline" className="h-6 px-2 text-[10px]" onClick={() => { setCompareOpen(false); selectItem(item) }}>{t('generationDetails')}</Button>
                        <Button size="sm" variant="ghost" className="h-6 px-2 text-[10px]" onClick={() => toggleSelected(item.id, false)}>{t('close')}</Button>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={deleteTarget !== null}
        title={t('delete')}
        description={t('confirmDeleteFeedName', { name: deleteTarget ? deleteTarget.prompt || deleteTarget.id : '' })}
        destructive
        confirmLabel={t('delete')}
        onConfirm={() => { if (deleteTarget) return del(deleteTarget) }}
        onClose={() => setDeleteTarget(null)}
      />

      <ConfirmDialog
        open={clearOpen}
        title={t('clearGallery')}
        description={t('confirmClear')}
        destructive
        confirmLabel={t('clearGallery')}
        onConfirm={() => clearGallery()}
        onClose={() => setClearOpen(false)}
      />

      <Dialog open={libraryOpen} onOpenChange={(value) => { if (!value) resetLibraryDialog() }}>
        <DialogContent className="imagegen-ui max-w-md">
          <DialogHeader>
            <DialogTitle className="text-sm">{libEditId ? t('edit') : t('saveRecipe')}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <p className="text-[11px] leading-relaxed text-(--ui-text-tertiary)">{t('recipeHint')}</p>
            <div className="space-y-1.5">
              <Input value={libName} placeholder={t('saveRecipe')} className="h-8 text-xs" onChange={(e) => setLibName(e.target.value)} />
              <Textarea value={libPrompt} rows={3} className="text-xs" onChange={(e) => setLibPrompt(e.target.value)} />
            </div>
            {libraryError && <div className="rounded-md border border-(--ui-error)/30 bg-(--ui-error)/10 px-2.5 py-2 text-[11px] text-(--ui-error)">{libraryError}</div>}
            {librarySaved && <div className="rounded-md border border-(--ui-ok)/30 bg-(--ui-ok)/10 px-2.5 py-2 text-[11px] text-(--ui-ok)">{t('recipeSaved')}</div>}
            <Button size="sm" onClick={() => void saveLibrary()} disabled={librarySaving}>
              {librarySaving ? t('saving') : libEditId ? t('overwrite') : t('saveRecipe')}
            </Button>
            {library?.length > 0 && (
              <div className="max-h-48 space-y-1 overflow-y-auto">
                {library.map((item) => (
                  <div key={item.id} className="flex items-center justify-between gap-2 rounded-lg border border-(--ui-stroke-secondary) p-2">
                    <div className="min-w-0">
                      <div className="truncate text-xs font-medium">{item.name || t('untitledRecipe')}</div>
                      <div className="truncate text-[11px] text-(--ui-text-tertiary)">{item.prompt}</div>
                    </div>
                    <div className="flex gap-1">
                      <Button size="sm" variant="outline" className="h-6 px-2 text-[11px]" onClick={() => applyLibrary(item)}>
                        {t('apply')}
                      </Button>
                      <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={() => editLibrary(item)}>
                        {t('edit')}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-6 px-2 text-[11px] text-(--ui-error)"
                        onClick={async () => {
                          await rest<{ ok: boolean }>(`/library/${item.id}`, 'DELETE')
                          queryClient.invalidateQueries({ queryKey: [ID, 'library'] })
                        }}
                      >
                        {t('delete')}
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
