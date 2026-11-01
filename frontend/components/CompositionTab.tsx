/**
 * ImageGen — composition section (references, roles, fidelity, vision analysis).
 *
 * Reference management lives in <ReferencesPanel /> (drop/paste/reorder,
 * per-reference metadata, model capability enforcement). The campaign matrix
 * is the sole responsibility of CampaignMatrixTab — this file no longer
 * carries a second, diverging copy of it.
 *
 * 2-step confirm gate P0:
 *  Analyze → preview (status preview) → Preview Card (brief editable +
 *  suggestedPrompt + badges) → [Edit brief] [Regenerate] [Confirm & Use] [Cancel]
 *  Confirm → status confirmed + promptManual + prompt = suggestedPrompt
 *  Stale warning when description/refs change after confirm.
 *  Auto deep=true for objeto_produto + fixedProduct.
 */

import { Badge, Button, Codicon, Textarea, host } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'

import type { ImageGenConfig, Presets, Provider } from '../types'
import { rest } from '../api'
import { useImageGenT } from '../i18n'
import { SectionCard, Spinner } from './ui-helpers'
import { refsToMeta } from '../presets'
import { ReferencesPanel } from './ReferencesPanel'
import type { ReferenceImage as ReferenceImageType } from '../types'

function refsHash(refs: ReferenceImageType[]): string {
  return refs.map((r) => `${r.id}:${r.localPath || r.url || (r.imageDataUrl || '').slice(0, 32) || ''}`).join('|')
}

export function CompositionTab({
  config,
  updateConfig,
  providers,
  setPrompt,
  setPromptTouched,
  setPromptManual
}: {
  config: ImageGenConfig
  updateConfig: (partial: Partial<ImageGenConfig>) => void
  providers: Provider[]
  presets: Presets | null
  prompt: string
  setPrompt: (v: string) => void
  promptTouched: boolean
  setPromptTouched: (v: boolean) => void
  promptManual: boolean
  setPromptManual: (v: boolean) => void
}) {
  const t = useImageGenT()
  const [analyzing, setAnalyzing] = useState(false)
  const [genres, setGenres] = useState<Array<{ id: string; label: string }>>([])
  const briefRef = useRef<HTMLTextAreaElement | null>(null)

  useEffect(() => {
    rest<{ genres: Array<{ id: string; label: string }> }>('/genres')
      .then((d) => setGenres(d.genres || []))
      .catch(() => {})
  }, [])

  const provider = config.provider || 'fal'
  const model = config.selectedModel || ''
  const providerInfo = (providers || []).find((p) => p.name === provider)
  const modelInfo = providerInfo?.models?.find((m) => m.id === model)
  const modelLabel = modelInfo?.display || model
  const capabilities = modelInfo?.capabilities || {}
  const supportsReferences = capabilities.referenceImages !== false
  const maxReferences = capabilities.maxReferences || 0
  const refs = config.referencesV4 || []
  const intent = config.compositionIntent
  const isPreview = intent?.status === 'preview'
  const isConfirmed = intent?.status === 'confirmed'
  const currentHash = refsHash(refs)
  const autoDeep = config.subjectType === 'objeto_produto' && refs.some((r) => r.fixedProduct)
  const effectiveDeep = autoDeep || !!config.deepAnalyze
  const isStale =
    isConfirmed &&
    (intent.snapshotDescription !== (config.description || '') || intent.snapshotRefsHash !== currentHash)

  const updateRefs = (next: ReferenceImageType[]) => updateConfig({ referencesV4: next })

  const doAnalyze = async () => {
    if (!refs.length) return
    setAnalyzing(true)
    try {
      const d = await rest<{ brief?: string; prompt?: string; result?: string }>('/llm/composition-analyze', 'POST', {
        scene: config.description || 'Compose the scene with the provided references',
        images: refs.map((r) => r.localPath || r.url || r.imageDataUrl).filter(Boolean).slice(0, 4),
        subjectType: config.subjectType || 'general',
        aspectRatio: config.aspectRatio || '1:1',
        refsMeta: refsToMeta(refs),
        genre: config.genre || '',
        deep: effectiveDeep
      })
      const brief = d.brief || ''
      const suggested = d.prompt || d.result || ''
      updateConfig({
        compositionIntent: {
          status: 'preview',
          userIntent: config.description || '',
          suggestedPrompt: suggested,
          brief,
          genre: config.genre || '',
          deep: effectiveDeep,
          snapshotRefsHash: currentHash,
          snapshotDescription: config.description || ''
        }
      })
    } catch (error) {
      host.notifyError(error, t('analyzeFailed'))
    } finally {
      setAnalyzing(false)
    }
  }

  const handleConfirm = () => {
    if (!intent || intent.status !== 'preview') return
    const finalPrompt = intent.suggestedPrompt || ''
    setPrompt(finalPrompt)
    setPromptManual(true)
    setPromptTouched(true)
    updateConfig({
      compositionIntent: {
        ...(intent as NonNullable<typeof intent>),
        status: 'confirmed',
        suggestedPrompt: finalPrompt,
        snapshotRefsHash: currentHash,
        snapshotDescription: config.description || '',
        confirmedAt: Date.now()
      }
    })
  }

  const handleCancel = () => {
    updateConfig({ compositionIntent: null })
  }

  const handleEditBrief = () => {
    briefRef.current?.focus()
  }

  const handleBriefChange = (v: string) => {
    if (!intent) return
    updateConfig({ compositionIntent: { ...intent, brief: v } })
  }

  const handlePromptEdit = (v: string) => {
    if (!intent) return
    updateConfig({ compositionIntent: { ...intent, suggestedPrompt: v } })
  }

  return (
    <div className="space-y-2">
      <ReferencesPanel
        references={refs}
        onChange={updateRefs}
        maxReferences={maxReferences}
        supportsReferences={supportsReferences}
        modelLabel={modelLabel}
      />

      <SectionCard title={t('vision')} defaultOpen={!!(intent?.status === 'preview' || intent?.status === 'confirmed')}>
        {genres.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={config.genre || ''}
              onChange={(e) => updateConfig({ genre: e.target.value })}
              className="h-8 w-52 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 text-xs"
            >
              <option value="">{t('genreAuto')}</option>
              {genres.map((g) => (
                <option key={g.id} value={g.id}>
                  {g.label}
                </option>
              ))}
            </select>
            <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-(--ui-text-secondary)">
              <input
                type="checkbox"
                checked={effectiveDeep}
                disabled={autoDeep}
                title={autoDeep ? t('autoDeepEnabled') : undefined}
                onChange={(e) => updateConfig({ deepAnalyze: e.target.checked })}
                className="accent-(--ui-accent)"
              />
              {t('deepAnalysis')}
              {autoDeep && <span className="text-[10px] text-(--ui-accent)">· {t('autoDeepEnabled')}</span>}
            </label>
          </div>
        )}

        {/* Preview Card — status preview */}
        {isPreview && intent && (
          <div className="space-y-2 rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-1.5 text-[11px] font-semibold text-amber-700 dark:text-amber-400">
                <Codicon name="eye" style={{ fontSize: 12 }} />
                {t('previewCardTitle')}
                <Badge variant="outline" className="text-[9px] border-amber-500/30 text-amber-600">
                  {t('visionPreview')}
                </Badge>
              </div>
              <span className="text-[10px] text-(--ui-text-quaternary)">{t('previewCardHint')}</span>
            </div>

            {/* badges */}
            <div className="flex flex-wrap gap-1">
              {intent.genre && <Badge variant="muted" className="text-[9px]">{intent.genre}</Badge>}
              {effectiveDeep && <Badge variant="muted" className="text-[9px]">deep</Badge>}
              <Badge variant="outline" className="text-[9px]">{refs.length} ref(s)</Badge>
              <Badge variant="outline" className="text-[9px]">{config.aspectRatio}</Badge>
              {autoDeep && <Badge variant="outline" className="text-[9px]">auto-deep</Badge>}
            </div>

            {/* brief editable */}
            <div className="space-y-1">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-(--ui-text-tertiary)">
                {t('briefLabel')}
              </div>
              <Textarea
                ref={briefRef as never}
                value={intent.brief || ''}
                rows={4}
                placeholder={t('productionBrief')}
                onChange={(e) => handleBriefChange(e.target.value)}
                className="min-h-20 font-mono text-[11px] leading-relaxed bg-(--ui-bg)"
              />
            </div>

            {/* suggestedPrompt */}
            <div className="space-y-1">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-(--ui-text-tertiary)">
                {t('suggestedPromptLabel')}
              </div>
              <Textarea
                value={intent.suggestedPrompt || ''}
                rows={4}
                onChange={(e) => handlePromptEdit(e.target.value)}
                className="min-h-20 font-mono text-[11px] leading-relaxed bg-(--ui-bg) border-amber-500/30"
              />
            </div>

            {/* actions */}
            <div className="flex flex-wrap gap-1.5">
              <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={handleEditBrief}>
                <Codicon name="edit" style={{ fontSize: 11 }} />
                {t('editBrief')}
              </Button>
              <Button
                size="sm"
                variant="outline"
                className="h-7 gap-1 text-xs"
                onClick={doAnalyze}
                disabled={analyzing}
              >
                {analyzing ? <Spinner /> : <Codicon name="sync" style={{ fontSize: 11 }} />}
                {t('regenerate')}
              </Button>
              <Button size="sm" className="h-7 gap-1 text-xs" onClick={handleConfirm}>
                <Codicon name="check" style={{ fontSize: 12 }} />
                {t('confirmUse')}
              </Button>
              <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={handleCancel}>
                {t('cancelPreview')}
              </Button>
            </div>
          </div>
        )}

        {/* Confirmed state */}
        {isConfirmed && intent && (
          <div className="space-y-2">
            <div className="flex items-center gap-1.5 text-[11px] font-medium text-emerald-600 dark:text-emerald-400">
              <Codicon name="check" style={{ fontSize: 12 }} />
              {t('compositionAnalyzed')}
              <Badge variant="outline" className="text-[9px] border-emerald-500/30 text-emerald-600">
                {t('visionConfirmed')}
              </Badge>
            </div>
            {intent.brief && (
              <div className="rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg) p-2.5">
                <div className="mb-1 flex items-center gap-1.5 text-[10.5px] font-medium uppercase tracking-wide text-(--ui-text-tertiary)">
                  <Codicon name="note" style={{ fontSize: 11 }} />
                  {t('productionBrief')}
                </div>
                <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap font-mono text-[10.5px] leading-relaxed text-(--ui-text-secondary)">
                  {intent.brief}
                </pre>
              </div>
            )}
          </div>
        )}

        {/* Stale warning */}
        {isStale && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/8 p-2 text-[11px] text-amber-700 dark:text-amber-400">
            <Codicon name="warning" className="mt-0.5 shrink-0" style={{ fontSize: 13 }} />
            <span>{t('staleWarning')}</span>
          </div>
        )}

        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" onClick={doAnalyze} disabled={analyzing || !refs.length}>
            {analyzing ? <Spinner /> : <Codicon name="sparkle" style={{ fontSize: 12 }} />}
            {analyzing ? t('analyzing') : t('analyze')}
          </Button>
        </div>
      </SectionCard>
    </div>
  )
}
