/**
 * Subject Library foundation.
 *
 * This deliberately sits on top of the legacy /objects contract. Subject kinds
 * remain open strings so a future backend can add passports, angles, or new
 * subject families without changing the object API or this surface.
 *
 * The action sheet here is "use as reference" (it configures the subject kind
 * and applies the references) — it does NOT generate. Generation stays with
 * the explicit generate button, so labels never promise something they do not
 * do.
 */
import { Badge, Button, Codicon, Dialog, DialogContent, DialogHeader, DialogTitle, Input, cn } from '@hermes/plugin-sdk'
import { useMemo, useState } from 'react'

import type { Presets, SubjectKind, SubjectLibraryEntry } from '../types'
import { useImageGenT } from '../i18n'
import { ImagePreview, Spinner } from './ui-helpers'

interface SubjectLibraryProps {
  entries: SubjectLibraryEntry[]
  presets: Presets | null
  isLoading?: boolean
  onUseAsRef: (entry: SubjectLibraryEntry) => Promise<void>
  onGenerateWith: (entry: SubjectLibraryEntry, kind: SubjectKind, prompt: string) => void
}

function slugify(value: string): string {
  return value.toLowerCase().trim().normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 64)
}

function angleItems(entry: SubjectLibraryEntry, primaryLabel: string) {
  const supplied = entry.angles || entry.variants || []
  if (supplied.length) return supplied.map((angle) => ({ ...angle, localPath: angle.localPath || angle.file }))
  return [{ id: entry.id, label: primaryLabel, localPath: entry.localPath || entry.file, thumb: entry.thumb, url: entry.url }]
}

export function SubjectLibrary({ entries, presets, isLoading, onUseAsRef, onGenerateWith }: SubjectLibraryProps) {
  const t = useImageGenT()
  const [query, setQuery] = useState('')
  const [kindFilter, setKindFilter] = useState('all')
  const [selected, setSelected] = useState<SubjectLibraryEntry | null>(null)
  const [kind, setKind] = useState<SubjectKind>('')
  const [customKind, setCustomKind] = useState('')
  const [prompt, setPrompt] = useState('')
  const [refLoading, setRefLoading] = useState('')

  const kindOptions = useMemo(() => {
    const configured = (presets?.subject_types || []).map((item) => item.value)
    const legacy = presets?.subjectTypes || []
    return Array.from(new Set([...configured, ...legacy, ...entries.map((entry) => entry.kind).filter(Boolean) as string[]]))
  }, [entries, presets])

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return entries.filter((entry) => {
      const haystack = [entry.name, entry.id, entry.slug, entry.kind, entry.passport].filter(Boolean).join(' ').toLowerCase()
      return (!needle || haystack.includes(needle)) && (kindFilter === 'all' || entry.kind === kindFilter)
    })
  }, [entries, kindFilter, query])

  const openGenerateSheet = (entry: SubjectLibraryEntry) => {
    setSelected(entry)
    setKind(entry.kind || kindOptions[0] || '')
    setCustomKind('')
    setPrompt('')
  }

  const chosenKind = slugify(customKind) || slugify(kind) || slugify(selected?.kind || '') || 'general'

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold">{t('objectLibrary')}</h2>
          <p className="text-[11px] text-(--ui-text-tertiary)">{t('subjectsSubtitle')}</p>
        </div>
        <Badge variant="outline" className="text-[10px]">{filtered.length} {t('entries')}</Badge>
      </div>
      <div className="flex flex-wrap gap-2">
        <label className="relative min-w-[220px] flex-1">
          <Codicon name="search" className="absolute left-2 top-1/2 -translate-y-1/2 text-(--ui-text-tertiary)" style={{ fontSize: 13 }} />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`${t('objectLibrary')}…`} className="h-8 pl-7 text-xs" />
        </label>
        <select value={kindFilter} onChange={(event) => setKindFilter(event.target.value)} className="h-8 min-w-36 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 text-xs">
          <option value="all">{t('allKinds')}</option>
          {kindOptions.map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </div>
      {isLoading && <div className="flex items-center gap-2 text-xs text-(--ui-text-tertiary)"><Spinner size={14} /> {t('importing')}</div>}
      {!isLoading && filtered.length === 0 && <div className="rounded-xl border border-dashed border-(--ui-stroke-secondary) p-8 text-center text-xs text-(--ui-text-tertiary)">{t('emptyLibrary')}</div>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {filtered.map((entry) => {
          const angles = angleItems(entry, t('primaryAngle'))
          return (
            <article key={entry.id} className="overflow-hidden rounded-xl border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated)">
              <div className="grid grid-cols-3 gap-1 bg-(--ui-bg) p-1">
                {angles.slice(0, 6).map((angle, index) => <ImagePreview key={angle.id || `${entry.id}-${index}`} item={angle} alt={`${entry.name} ${angle.label || angle.angle || ''}`} className={cn('aspect-square w-full object-cover', index === 0 && angles.length === 1 ? 'col-span-3 aspect-video' : '')} />)}
              </div>
              <div className="space-y-2 p-2.5">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0"><div className="truncate text-xs font-medium">{entry.name}</div><div className="truncate text-[10px] text-(--ui-text-tertiary)">{entry.kind || entry.slug || t('generalKind')}</div></div>
                  <Badge variant="outline" className="shrink-0 text-[9px]">{t('anglesCount', { count: String(angles.length) })}</Badge>
                </div>
                {entry.passport && <p className="line-clamp-2 text-[10px] text-(--ui-text-tertiary)">{entry.passport}</p>}
                <div className="flex gap-1.5">
                  <Button size="sm" variant="outline" className="h-7 flex-1 gap-1 text-[10px]" disabled={refLoading === entry.id} onClick={() => { setRefLoading(entry.id); void onUseAsRef(entry).finally(() => setRefLoading('')) }}>
                    {refLoading === entry.id ? <Spinner size={11} /> : <Codicon name="link" />} {t('useAsRef')}
                  </Button>
                  <Button size="sm" variant="outline" className="h-7 flex-1 gap-1 text-[10px]" onClick={() => openGenerateSheet(entry)}><Codicon name="settings-gear" /> {t('useAsRefWithOptions')}</Button>
                </div>
              </div>
            </article>
          )
        })}
      </div>
      <Dialog open={Boolean(selected)} onOpenChange={(open) => !open && setSelected(null)}>
        <DialogContent className="imagegen-ui max-w-md">
          <DialogHeader><DialogTitle className="text-sm">{t('useAsRefTitle', { name: selected?.name || '' })}</DialogTitle></DialogHeader>
          <div className="space-y-3">
            <div className="space-y-1"><label className="text-[11px] font-medium">{t('subjectKindLabel')}</label><select value={kind} onChange={(event) => setKind(event.target.value)} className="h-8 w-full rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 text-xs"><option value="">{t('generalKind')}</option>{kindOptions.map((value) => <option key={value} value={value}>{value}</option>)}</select></div>
            <div className="space-y-1"><label className="text-[11px] font-medium">{t('customKindSlug')}</label><Input value={customKind} onChange={(event) => setCustomKind(event.target.value)} placeholder={t('customKindPlaceholder')} className="h-8 text-xs" /><span className="text-[10px] text-(--ui-text-tertiary)">{t('openStringLabel', { value: chosenKind })}</span></div>
            <div className="space-y-1"><label className="text-[11px] font-medium">{t('promptDirection')}</label><Input value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={t('describeImage')} className="h-8 text-xs" /></div>
            <div className="flex justify-end gap-2"><Button variant="outline" size="sm" onClick={() => setSelected(null)}>{t('close')}</Button><Button size="sm" onClick={() => { if (selected) onGenerateWith(selected, chosenKind, prompt.trim()); setSelected(null) }}><Codicon name="sparkle" /> {t('applyAsRef')}</Button></div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
