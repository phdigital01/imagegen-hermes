/**
 * ImageGen — reference image manager.
 *
 * Single surface for adding (drag & drop, paste, file picker), reordering
 * (drag + accessible arrows), and editing reference images. The order
 * matters: the backend uses refs[0] as the main/edit source image and the
 * rest as composition guidance, so the UI says so explicitly.
 *
 * P0 sticky strip: the reference list is position:sticky top:0 so the primary
 * stays visible while scrolling prompt/generate, card 0 is large with padlock,
 * passport snippet (80 chars) + expand, fidelity token mapping and persisted
 * dot (green/amber/red) plus multi-angle grouping and always-visible handle.
 */
import { cn, Codicon, host, Input, useQuery } from '@hermes/plugin-sdk'
import { useRef, useState, type ClipboardEvent, type DragEvent, type JSX } from 'react'

import type { ReferenceImage } from '../types'
import { fetchPresets, ID } from '../api'
import { useImageGenT } from '../i18n'
import { Chip, FieldLabel, IconButton, ReferenceImage as RefImage, Spinner, fileToDataUrl, newId } from './ui-helpers'
import { persistReferenceImage } from '../presets'

export interface ReferencesPanelProps {
  references: ReferenceImage[]
  onChange: (next: ReferenceImage[]) => void
  maxReferences: number
  supportsReferences: boolean
  modelLabel: string
}

type PersistedState = 'green' | 'amber' | 'red'

function persistedState(r: ReferenceImage): PersistedState {
  const anyR = r as ReferenceImage & { localPath?: string | null; url?: string | null; imageDataUrl?: string | null }
  if (anyR.localPath && String(anyR.localPath).trim()) return 'green'
  if ((anyR.imageDataUrl && String(anyR.imageDataUrl).trim()) || (anyR.url && String(anyR.url).trim())) return 'amber'
  return 'red'
}

function persistedMeta(state: PersistedState): { color: string; label: string; title: string } {
  if (state === 'green') return { color: 'bg-emerald-500', label: 'persisted', title: 'Persisted ✓ — localPath ready' }
  if (state === 'amber') return { color: 'bg-amber-500', label: 'pending', title: 'Pending upload — will upload on generate' }
  return { color: 'bg-red-500', label: 'missing', title: 'Missing image' }
}

function getPassportText(r: ReferenceImage): string {
  const anyR = r as ReferenceImage & { passport?: string | null; subjectId?: string | null }
  const raw = (anyR.passport || (r as unknown as { userNotes?: string }).userNotes || r.instructions || '') as string
  if (raw && String(raw).trim()) return String(raw).trim()
  const analysis = r.analysisResult as Record<string, unknown> | null
  if (analysis && typeof analysis === 'object' && typeof (analysis as { passport?: unknown }).passport === 'string') {
    return String((analysis as { passport: string }).passport).trim()
  }
  return ''
}

function fidelityTokens(fidelity: number): { iw: string; guidance: string; authority: string } {
  // Map 50-95 to the prompt tokens the backend will emit.
  // --iw (Midjourney) and guidance (FLUX/SD) plus the authority noun used in prompt_builder.
  let iw: string
  let guidance: string
  let authority: string
  if (fidelity >= 95) { iw = '2.0'; guidance = '9.5'; authority = 'authoritative' }
  else if (fidelity >= 90) { iw = '1.5'; guidance = '8.5'; authority = 'authoritative' }
  else if (fidelity >= 85) { iw = '1.2'; guidance = '7.5'; authority = 'strong' }
  else if (fidelity >= 75) { iw = '1.0'; guidance = '6.5'; authority = 'balanced' }
  else if (fidelity >= 65) { iw = '0.8'; guidance = '5.5'; authority = 'supporting' }
  else { iw = '0.5'; guidance = '4.0'; authority = 'supporting' }
  return { iw, guidance, authority }
}

export function ReferencesPanel({
  references,
  onChange,
  maxReferences,
  supportsReferences,
  modelLabel
}: ReferencesPanelProps): JSX.Element {
  const t = useImageGenT()
  const presetsQuery = useQuery({ queryKey: [ID, 'presets'], queryFn: fetchPresets, staleTime: 10 * 60_000 })
  const presets = presetsQuery.data || null
  const roles = presets?.semantic_roles || []
  const keepVary = presets?.keep_vary || []

  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [fileDragOver, setFileDragOver] = useState(false)
  const [draggedId, setDraggedId] = useState<string | null>(null)
  const [overIndex, setOverIndex] = useState<number | null>(null)
  const [expandedPassport, setExpandedPassport] = useState<Record<string, boolean>>({})
  const [adjustingId, setAdjustingId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const dragDepth = useRef(0)

  const disabled = !supportsReferences
  const atLimit = maxReferences > 0 && references.length >= maxReferences
  const room = maxReferences > 0 ? Math.max(0, maxReferences - references.length) : Number.MAX_SAFE_INTEGER
  const addDisabled = disabled || atLimit || uploading

  // Group detection: same subjectId (from subject_as_refs) → multi-angle product.
  const groupCounts = (() => {
    const m = new Map<string, number>()
    for (const r of references) {
      const sid = (r as ReferenceImage & { subjectId?: string }).subjectId
      if (sid) m.set(sid, (m.get(sid) || 0) + 1)
    }
    return m
  })()
  const isGrouped = (r: ReferenceImage) => {
    const sid = (r as ReferenceImage & { subjectId?: string }).subjectId
    return !!(sid && (groupCounts.get(sid) || 0) >= 2)
  }
  const groupedLabel = (() => {
    for (const n of groupCounts.values()) if (n >= 2) return `${n} angles · same product`
    return ''
  })()

  const updateRef = (id: string, partial: Partial<ReferenceImage>) =>
    onChange(references.map((r) => (r.id === id ? { ...r, ...partial } : r)))
  const removeRef = (id: string) => onChange(references.filter((r) => r.id !== id))

  const moveRef = (from: number, to: number) => {
    if (from === to || to < 0 || to >= references.length) return
    const next = [...references]
    const [item] = next.splice(from, 1)
    next.splice(to, 0, item)
    onChange(next)
  }

  const notifyRefused = (count: number) => {
    host.notify({
      kind: 'warning',
      title: t('refsLimitReached'),
      message: t('refsSkipped', { count: String(count), model: modelLabel, max: String(maxReferences) })
    })
  }

  const addFiles = async (fileList: FileList | File[] | null) => {
    if (disabled || uploading) return
    const files = Array.from(fileList || []).filter((f) => f.type.startsWith('image/'))
    if (!files.length) return
    // Enforce the model cap at add time: keep the files that fit, never
    // silently drop the rest — the user is told how many were refused.
    if (atLimit) {
      notifyRefused(files.length)
      return
    }
    const accepted = files.slice(0, room)
    const refused = files.length - accepted.length
    if (!accepted.length) {
      notifyRefused(files.length)
      return
    }
    setUploading(true)
    setUploadError(null)
    try {
      const created: ReferenceImage[] = []
      for (const file of accepted) {
        const dataUrl = await fileToDataUrl(file)
        const persisted = await persistReferenceImage(dataUrl, file.name)
        created.push({
          id: newId(),
          label: file.name.replace(/\.[^.]+$/, '') || 'Reference',
          ...persisted,
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
          origin: 'upload'
        })
      }
      onChange([...references, ...created])
      if (refused > 0) notifyRefused(refused)
    } catch (error) {
      setUploadError(error instanceof Error ? error.message : String(error))
      host.notifyError(error, t('uploadFailed'))
    } finally {
      setUploading(false)
    }
  }

  const onZoneDragEnter = (e: DragEvent<HTMLDivElement>) => {
    if (addDisabled) return
    if (Array.from(e.dataTransfer.types || []).includes('Files')) {
      e.preventDefault()
      dragDepth.current += 1
      setFileDragOver(true)
    }
  }
  const onZoneDragOver = (e: DragEvent<HTMLDivElement>) => {
    if (addDisabled) return
    if (Array.from(e.dataTransfer.types || []).includes('Files')) {
      e.preventDefault()
      e.dataTransfer.dropEffect = 'copy'
    }
  }
  const onZoneDragLeave = () => {
    dragDepth.current = Math.max(0, dragDepth.current - 1)
    if (dragDepth.current === 0) setFileDragOver(false)
  }
  const onZoneDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    dragDepth.current = 0
    setFileDragOver(false)
    void addFiles(e.dataTransfer.files)
  }
  const onPaste = (e: ClipboardEvent<HTMLDivElement>) => {
    const files = Array.from(e.clipboardData?.files || [])
    if (files.length) {
      e.preventDefault()
      void addFiles(files)
    }
  }

  const onCardDragStart = (e: DragEvent<HTMLElement>, id: string) => {
    e.dataTransfer.setData('text/plain', id)
    e.dataTransfer.effectAllowed = 'move'
    setDraggedId(id)
    setOverIndex(null)
  }
  const onCardDragOver = (e: DragEvent<HTMLElement>, idx: number) => {
    if (!draggedId) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (overIndex !== idx) setOverIndex(idx)
  }
  const onCardDrop = (e: DragEvent<HTMLElement>, idx: number) => {
    e.preventDefault()
    if (draggedId) {
      const from = references.findIndex((r) => r.id === draggedId)
      if (from >= 0) moveRef(from, idx)
    }
    setDraggedId(null)
    setOverIndex(null)
  }
  const clearDrag = () => {
    setDraggedId(null)
    setOverIndex(null)
  }

  return (
    <div className="space-y-2" onPaste={onPaste}>
      {!supportsReferences && (
        <div aria-live="polite" className="flex items-start gap-2 rounded-lg border border-(--ui-yellow)/30 bg-(--ui-yellow)/8 p-2 text-xs">
          <Codicon name="warning" className="mt-0.5 text-(--ui-yellow)" style={{ fontSize: 13 }} />
          <span className="text-(--ui-text-secondary)">
            {t('refsNotSupported', { model: modelLabel })} — {t('refsNotSupportedHint')}
          </span>
        </div>
      )}
      {uploadError && (
        <div className="flex items-start gap-2 rounded-lg border border-(--ui-red)/30 bg-(--ui-red)/8 p-2 text-xs">
          <Codicon name="error" className="mt-0.5 text-(--ui-red)" style={{ fontSize: 13 }} />
          <span className="text-(--ui-text-secondary)">{t('uploadFailed')}: {uploadError}</span>
          <button type="button" className="ml-auto text-(--ui-text-tertiary) hover:text-(--ui-text-secondary)" aria-label={t('close')} onClick={() => setUploadError(null)}>
            <Codicon name="close" style={{ fontSize: 12 }} />
          </button>
        </div>
      )}

      {supportsReferences && (
        <div
          role="button"
          tabIndex={addDisabled ? -1 : 0}
          aria-disabled={addDisabled}
          aria-label={atLimit ? t('refsLimitReached') : t('dropRefsHere')}
          onClick={() => { if (!addDisabled) fileInputRef.current?.click() }}
          onKeyDown={(e) => { if ((e.key === 'Enter' || e.key === ' ') && !addDisabled) fileInputRef.current?.click() }}
          onDragEnter={onZoneDragEnter}
          onDragOver={onZoneDragOver}
          onDragLeave={onZoneDragLeave}
          onDrop={onZoneDrop}
          className={cn(
            'flex min-h-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed px-3 py-4 text-center text-xs transition-colors',
            fileDragOver ? 'border-(--ui-accent) bg-(--ui-accent)/8 text-(--ui-accent)' : 'border-(--ui-stroke-secondary) text-(--ui-text-tertiary)',
            addDisabled ? 'cursor-not-allowed opacity-60' : 'hover:bg-(--chrome-action-hover) focus-visible:border-(--ui-accent) focus-visible:bg-(--ui-accent)/8'
          )}
        >
          <span className="flex items-center gap-1.5">
            {uploading ? <Spinner /> : <Codicon name="cloud-upload" style={{ fontSize: 15 }} />}
            {atLimit ? t('refsLimitReached') : t('dropRefsHere')}
          </span>
          {atLimit && (
            <span className="text-[10px]">{t('refsLimitDetail', { model: modelLabel, max: String(maxReferences) })}</span>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            disabled={addDisabled}
            className="hidden"
            onChange={(e) => { void addFiles(e.target.files); e.target.value = '' }}
          />
        </div>
      )}

      {/* Sticky reference strip — keeps the primary visible while scrolling. */}
      <div className="sticky top-0 z-10 -mx-1 px-1 py-1 bg-(--ui-bg-elevated)/95 backdrop-blur supports-[backdrop-filter]:bg-(--ui-bg-elevated)/80">
        <div className="flex flex-wrap items-center justify-between gap-2 text-[10.5px] text-(--ui-text-tertiary)">
          <span className="flex items-center gap-1">
            <Codicon name="info" style={{ fontSize: 11 }} />
            {t('refsMainHint')}
          </span>
          <span aria-live="polite" role="status" className="flex items-center gap-2">
            {maxReferences > 0 && (
              <span>
                {t('refsUsedOf', { used: String(references.length), max: String(maxReferences) })}
                {atLimit && <> — {t('refsLimitReached')}</>}
              </span>
            )}
            {references.length > 1 && <span className="hidden sm:inline">{t('refsReorderHint')}</span>}
            {groupedLabel && (
              <span className="hidden sm:inline rounded bg-(--ui-accent)/10 px-1 py-px text-[10px] font-medium text-(--ui-accent)">{groupedLabel}</span>
            )}
          </span>
        </div>
      </div>

      {references.length > 0 && (
        <ul className={cn('space-y-2', disabled && 'opacity-60')} aria-label={t('references')}>
          {references.map((r, idx) => {
            const isFirst = idx === 0
            const pState = persistedState(r)
            const pMeta = persistedMeta(pState)
            const passport = getPassportText(r)
            const snippet = passport.slice(0, 80)
            const hasMore = passport.length > 80
            const expanded = !!expandedPassport[r.id]
            const showPassport = passport.length > 0
            const tokens = fidelityTokens(r.fidelity)
            const grouped = isGrouped(r)
            // One card shows its settings at a time, so a long list stays a short list.
            const adjusting = references.length === 1 || adjustingId === r.id

            return (
            <li
              key={r.id}
              aria-label={t('refCard', { n: String(idx + 1), label: r.label })}
              draggable={!disabled && references.length > 1}
              onDragStart={(e) => onCardDragStart(e, r.id)}
              onDragOver={(e) => onCardDragOver(e, idx)}
              onDrop={(e) => onCardDrop(e, idx)}
              onDragEnd={clearDrag}
              onKeyDown={(e) => {
                // Arrow-key reorder for keyboard users; never hijack typing
                // or caret movement inside text fields.
                if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement || e.target instanceof HTMLSelectElement) return
                if (disabled || references.length <= 1) return
                if (e.key === 'ArrowUp') {
                  e.preventDefault()
                  moveRef(idx, idx - 1)
                } else if (e.key === 'ArrowDown') {
                  e.preventDefault()
                  moveRef(idx, idx + 1)
                }
              }}
              className={cn(
                'rounded-xl border bg-(--ui-bg-elevated) p-2.5 space-y-2 transition-colors',
                isFirst ? 'border-(--ui-accent)/50 ring-1 ring-(--ui-accent)/20' : 'border-(--ui-stroke-secondary)',
                grouped && 'border-violet-400/60 ring-1 ring-violet-400/20',
                !disabled && references.length > 1 && 'cursor-grab',
                draggedId && draggedId !== r.id && overIndex === idx && 'border-(--ui-accent)'
              )}
            >
              <div className="flex items-center gap-2">
                {/* Always-visible reorder handle */}
                <button
                  type="button"
                  aria-label={t('moveUpRef', { n: String(idx + 1) }) + ' / drag'}
                  className={cn('flex h-6 w-6 shrink-0 items-center justify-center rounded text-(--ui-text-quaternary) hover:bg-(--chrome-action-hover) hover:text-(--ui-text-secondary)', references.length <= 1 && 'opacity-30 pointer-events-none')}
                  tabIndex={references.length <= 1 ? -1 : 0}
                  draggable={false}
                  onClick={(e) => { e.stopPropagation() }}
                  title={t('refsReorderHint')}
                >
                  <Codicon name="gripper" style={{ fontSize: 12 }} />
                </button>
                <div className={cn('relative shrink-0 overflow-hidden rounded object-cover', isFirst ? 'h-20 w-20' : 'h-14 w-14')}>
                  <RefImage reference={r} className="h-full w-full object-cover" alt={r.label} />
                  {/* Persisted dot: green/amber/red */}
                  <span
                    title={pMeta.title}
                    aria-label={pMeta.title}
                    className={cn('absolute bottom-1 right-1 h-2.5 w-2.5 rounded-full border border-white shadow-sm', pMeta.color)}
                  />
                  {isFirst && r.fixedProduct && (
                    <span className="absolute left-1 top-1 flex h-5 w-5 items-center justify-center rounded-full bg-(--ui-accent) text-white shadow">
                      <Codicon name="lock" style={{ fontSize: 10 }} />
                    </span>
                  )}
                  {grouped && (
                    <span className="absolute left-1 bottom-1 rounded bg-violet-600 px-1 py-px text-[8px] font-bold text-white shadow">GROUP</span>
                  )}
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                  <Input
                    value={r.label}
                    disabled={disabled}
                    onChange={(e) => updateRef(r.id, { label: e.target.value })}
                    className="h-7 text-xs"
                    aria-label={`${t('references')} ${idx + 1}`}
                  />
                  <div className="flex flex-wrap items-center gap-1.5">
                    {idx === 0 && (
                      <span className="rounded bg-(--ui-accent)/10 px-1 py-px text-[9px] font-medium text-(--ui-accent)">
                        {t('mainImage')}
                      </span>
                    )}
                    {isFirst && r.fixedProduct && (
                      <span className="inline-flex items-center gap-1 rounded bg-(--ui-accent) px-1 py-px text-[9px] font-bold text-white">
                        <Codicon name="lock" style={{ fontSize: 9 }} /> fixed
                      </span>
                    )}
                    {grouped && (
                      <span className="rounded border border-violet-400/40 bg-violet-500/10 px-1 py-px text-[9px] font-medium text-violet-600 dark:text-violet-300">{groupedLabel || 'multi-angle'}</span>
                    )}
                    <span className="truncate text-[10px] text-(--ui-text-tertiary)">
                      {roles.find((role: { value: string; label: string }) => role.value === r.semanticRole)?.label || r.semanticRole} · {r.fidelity}%
                    </span>
                    <span className="inline-flex items-center gap-1 text-[10px]">
                      <span title={pMeta.title} className={cn('h-2 w-2 rounded-full', pMeta.color)} />
                      <span className="text-(--ui-text-quaternary)">{pMeta.label}</span>
                    </span>
                  </div>
                  {/* Inline passport snippet (80 chars) + expand */}
                  {showPassport && (
                    <div className="rounded bg-(--ui-bg) px-1.5 py-1 text-[10.5px] leading-snug text-(--ui-text-secondary)">
                      <span className="font-medium text-(--ui-text-tertiary)">passport: </span>
                      <span>{expanded ? passport : snippet + (hasMore ? '…' : '')}</span>
                      {hasMore && (
                        <button type="button" className="ml-1 text-(--ui-accent) hover:underline" onClick={() => setExpandedPassport((m) => ({ ...m, [r.id]: !m[r.id] }))}>
                          {expanded ? t('close') : 'expand'}
                        </button>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 items-center gap-0.5">
                  {references.length > 1 && (
                    <button type="button" aria-expanded={adjusting} className="mr-1 rounded px-1.5 py-1 text-[11px] text-(--ui-text-secondary) hover:bg-(--chrome-action-hover)" onClick={() => setAdjustingId(adjusting ? null : r.id)}>
                      {adjusting ? t('close') : t('adjustReference')}
                    </button>
                  )}
                  <IconButton icon="arrow-up" title={t('moveUp')} aria-label={t('moveUpRef', { n: String(idx + 1) })} disabled={disabled || idx === 0} onClick={() => moveRef(idx, idx - 1)} />
                  <IconButton icon="arrow-down" title={t('moveDown')} aria-label={t('moveDownRef', { n: String(idx + 1) })} disabled={disabled || idx === references.length - 1} onClick={() => moveRef(idx, idx + 1)} />
                  <button
                    type="button"
                    className="p-1 text-(--ui-text-tertiary) hover:text-(--ui-red)"
                    aria-label={t('deleteRef', { n: String(idx + 1), label: r.label })}
                    onClick={() => removeRef(r.id)}
                  >
                    <Codicon name="close" style={{ fontSize: 12 }} />
                  </button>
                </div>
              </div>

              {adjusting && (
              <>
              <div className="space-y-1">
                <FieldLabel>{t('semanticRole')}</FieldLabel>
                <div className="flex flex-wrap gap-1">
                  {roles.map((role: { value: string; label: string; fidelity?: number }) => (
                    <Chip
                      key={role.value}
                      disabled={disabled}
                      active={r.semanticRole === role.value}
                      onClick={() => updateRef(r.id, { semanticRole: role.value, fidelity: role.fidelity || r.fidelity })}
                    >
                      {role.label}
                    </Chip>
                  ))}
                </div>
              </div>

              <div className="space-y-1">
                <div className="flex items-center justify-between">
                  <FieldLabel>{`${t('fidelity')}: ${r.fidelity}%`}</FieldLabel>
                  <label className="flex cursor-pointer items-center gap-1.5 text-[11px]">
                    <input
                      type="checkbox"
                      checked={r.fixedProduct}
                      disabled={disabled}
                      className="accent-(--ui-accent)"
                      onChange={(e) => updateRef(r.id, { fixedProduct: e.target.checked, fidelity: e.target.checked ? 95 : r.fidelity })}
                    />
                    {t('fixedProduct')}
                  </label>
                </div>
                <input
                  type="range"
                  min={50}
                  max={95}
                  step={5}
                  value={r.fidelity}
                  disabled={disabled}
                  className="w-full accent-(--ui-accent)"
                  onChange={(e) => updateRef(r.id, { fidelity: Number(e.target.value) })}
                />
                <div className="flex flex-wrap gap-1 text-[10px] text-(--ui-text-quaternary)">
                  <span className="rounded bg-(--ui-bg) px-1.5 py-0.5">--iw {tokens.iw}</span>
                  <span className="rounded bg-(--ui-bg) px-1.5 py-0.5">guidance {tokens.guidance}</span>
                  <span className={cn('rounded px-1.5 py-0.5', tokens.authority === 'authoritative' ? 'bg-(--ui-accent)/15 text-(--ui-accent)' : 'bg-(--ui-bg)')}>{tokens.authority}</span>
                </div>
              </div>

              {(keepVary || []).length > 0 && (
                <div className="flex flex-wrap gap-x-4 gap-y-1">
                  <div className="space-y-1">
                    <FieldLabel>{t('preserve')}</FieldLabel>
                    <div className="flex flex-wrap gap-1">
                      {keepVary.map((k: string) => (
                        <Chip key={k} color="green" disabled={disabled} active={(r.keep || []).includes(k)} onClick={() => updateRef(r.id, { keep: (r.keep || []).includes(k) ? (r.keep || []).filter((x) => x !== k) : [...(r.keep || []), k] })}>
                          {k}
                        </Chip>
                      ))}
                    </div>
                  </div>
                  <div className="space-y-1">
                    <FieldLabel>{t('varyChip')}</FieldLabel>
                    <div className="flex flex-wrap gap-1">
                      {keepVary.map((k: string) => (
                        <Chip key={k} color="amber" disabled={disabled} active={(r.vary || []).includes(k)} onClick={() => updateRef(r.id, { vary: (r.vary || []).includes(k) ? (r.vary || []).filter((x) => x !== k) : [...(r.vary || []), k] })}>
                          {k}
                        </Chip>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              <div className="space-y-1">
                <FieldLabel>{t('additionalInstructions')}</FieldLabel>
                <Input
                  value={r.userNotes || ''}
                  disabled={disabled}
                  placeholder={t('instructionsPlaceholder')}
                  className="h-8 text-xs"
                  onChange={(e) => updateRef(r.id, { userNotes: e.target.value })}
                />
              </div>
              </>
              )}
            </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
