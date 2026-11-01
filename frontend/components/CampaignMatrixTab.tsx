/**
 * ImageGen — Campaign matrix UI.
 * Product/subject × environments × text-safe zones → creative grid.
 * Uses POST /batch/matrix (not /jobs/submit generate).
 */
import { Badge, Button, Codicon, Input, Textarea, cn, queryClient, useQuery } from '@hermes/plugin-sdk'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { ImageGenConfig, Presets, SubjectLibraryEntry } from '../types'
import { ID, fetchSubjectLibrary, queryJobResult, rest, subjectAsRefs, getStored, setStored } from '../api'
import { useImageGenT } from '../i18n'
import { GRID, Chip, FieldLabel, ImagePreview, ServedImage, Spinner, SectionCard, newId, toggleIn, downloadFromUrl } from './ui-helpers'
import { JobProgress } from './ResultGrid'

const ZONE_PRESETS: Record<string, { id: string; label: string; prompt: string }> = {
  right: { id: 'right', label: 'right', prompt: 'leave the right area clean and empty for text overlay' },
  top: { id: 'top', label: 'top', prompt: 'leave the top area clean and empty for text overlay' },
  bottom: { id: 'bottom', label: 'bottom', prompt: 'leave the bottom area clean and empty for text overlay' },
  center: { id: 'center', label: 'center', prompt: 'leave the center area clean and empty for text overlay' },
  left: { id: 'left', label: 'left', prompt: 'leave the left area clean and empty for text overlay' },
  none: { id: 'none', label: 'none', prompt: '' }
}

interface MatrixScene {
  id: string
  title: string
  sceneText: string
}

interface MatrixCell {
  scene: string
  zone: string
  images?: string[]
  prompt?: string
  error?: string
}

const SCENE_PRESETS: Array<{ title: string; sceneText: string }> = [
  { title: 'Studio soft', sceneText: 'clean photography studio, softbox lighting, seamless light gray backdrop' },
  { title: 'Luxury home', sceneText: 'modern luxury living room with large windows, warm afternoon light, polished floor' },
  { title: 'Urban night', sceneText: 'city street at night, neon reflections on wet asphalt, cinematic mood' },
  { title: 'Outdoor day', sceneText: 'bright outdoor daylight, shallow depth of field, natural greenery background' },
  { title: 'Showroom', sceneText: 'premium retail showroom, spotlighted product podium, reflective floor' },
  { title: 'Minimal white', sceneText: 'minimal e-commerce white seamless background, soft shadow under subject' }
]

export function CampaignMatrixTab({
  config,
  updateConfig,
  presets,
  onGoToTab
}: {
  config: ImageGenConfig
  updateConfig: (partial: Partial<ImageGenConfig>) => void
  presets: Presets | null
  onGoToTab: (tab: string, options?: { image?: string }) => void
}) {
  const t = useImageGenT()
  const provider = config.provider || 'fal'
  const model = config.selectedModel || ''
  const refs = config.referencesV4 || []

  const subjectsQuery = useQuery({
    queryKey: [ID, 'objects'],
    queryFn: fetchSubjectLibrary,
    staleTime: 30_000
  })
  const subjects = subjectsQuery.data || []

  const [subjectId, setSubjectId] = useState('')
  const [scenes, setScenes] = useState<MatrixScene[]>(() =>
    SCENE_PRESETS.slice(0, 3).map((item) => ({ id: newId(), title: item.title, sceneText: item.sceneText }))
  )
  const [zones, setZones] = useState<string[]>(['bottom', 'right'])
  const [aspectRatio, setAspectRatio] = useState(config.aspectRatio || '4:5')
  const [fidelity, setFidelity] = useState(90)
  const [jobId, setJobId] = useState<string | null>(() => getStored('campaignJobId', null))
  useEffect(() => { setStored('campaignJobId', jobId) }, [jobId])
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<{ matrix?: MatrixCell[]; scenes?: string[]; zones?: string[] } | null>(null)
  const [busySubject, setBusySubject] = useState(false)

  const selectedSubject = useMemo(
    () => subjects.find((item) => item.id === subjectId) || null,
    [subjectId, subjects]
  )

  const primaryImage = useMemo(() => {
    if (selectedSubject?.localPath) return selectedSubject.localPath
    const fixed = refs.find((item) => item.fixedProduct) || refs[0]
    return fixed?.localPath || fixed?.imageDataUrl || fixed?.url || ''
  }, [refs, selectedSubject])

  const cellCount = scenes.filter((s) => s.title.trim()).length * Math.max(1, zones.length)

  const useSubject = async (entry: SubjectLibraryEntry) => {
    setBusySubject(true)
    setError('')
    try {
      setSubjectId(entry.id)
      const { refs: nextRefs } = await subjectAsRefs(entry.id, 4)
      updateConfig({
        referencesV4: nextRefs,
        subjectType: entry.kind || config.subjectType
      })
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusySubject(false)
    }
  }

  const addPresetScene = (preset: { title: string; sceneText: string }) => {
    if (scenes.length >= 6) return
    if (scenes.some((s) => s.title === preset.title)) return
    setScenes([...scenes, { id: newId(), title: preset.title, sceneText: preset.sceneText }])
  }

  const startCampaign = async () => {
    if (jobId || submittingRef.current) return
    const readyScenes = scenes.filter((s) => s.title.trim())
    if (!primaryImage) {
      setError(t('campaignNeedSubject'))
      return
    }
    if (!readyScenes.length) {
      setError(t('campaignNeedScenes'))
      return
    }
    const zonePayload = (zones.length ? zones : ['none']).map((z) => ZONE_PRESETS[z] || ZONE_PRESETS.none)
    setError('')
    setResult(null)
    submittingRef.current = true
    setSubmitting(true)
    try {
      const response = await rest<{ id: string }>('/batch/matrix', 'POST', {
        clientRequestId: newId(),
        image: primaryImage,
        scenes: readyScenes.map((s) => ({ title: s.title.trim(), sceneText: s.sceneText.trim() || s.title.trim() })),
        zones: zonePayload,
        provider,
        model,
        aspectRatio,
        subjectType: config.subjectType || 'objeto_produto',
        genre: config.genre || 'ad_product',
        fidelity,
        resolution: config.resolution || '1K'
      })
      setJobId(response.id)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  const onJobDone = async (job: { id: string; status: string; hasPartialResult?: boolean }) => {
    if (job.status === 'completed' || job.hasPartialResult) {
      try {
        const full = await queryJobResult(job.id) as unknown as {
          result?: { matrix?: MatrixCell[]; scenes?: string[]; zones?: string[] }
          matrix?: MatrixCell[]
          scenes?: string[]
          zones?: string[]
        }
        const payload = full.result || full
        setResult({
          matrix: payload.matrix || [],
          scenes: payload.scenes,
          zones: payload.zones
        })
        queryClient.invalidateQueries({ queryKey: [ID, 'gallery'] })
        queryClient.invalidateQueries({ queryKey: [ID, 'history'] })
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : String(cause))
        throw cause
      }
    } else if (job.status === 'failed') {
      setError(t('jobFailed'))
    }
    setJobId(null)
  }

  const ratios = (presets?.aspect_ratios || []).map((item) => item.value).filter(Boolean)
  const aspectOptions = ratios.length ? ratios : ['1:1', '4:5', '9:16', '16:9', '3:2']

  return (
    <div className="space-y-4">
      <p className="text-[11px] leading-relaxed text-(--ui-text-tertiary)">{t('campaignHint')}</p>

      <SectionCard title={`1. ${t('campaignSubject')}`} subtitle={selectedSubject?.name || t('campaignSubjectHint')} defaultOpen>
        {subjects.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {subjects.slice(0, 24).map((entry) => (
              <button
                key={entry.id}
                type="button"
                disabled={busySubject}
                className={cn(
                  'w-24 overflow-hidden rounded-lg border text-left transition-colors',
                  subjectId === entry.id ? 'border-(--ui-accent) bg-(--ui-accent)/10' : 'border-(--ui-stroke-secondary) hover:bg-(--chrome-action-hover)'
                )}
                onClick={() => void useSubject(entry)}
              >
                <ImagePreview item={entry} className="h-16 w-full object-cover" alt={entry.name} />
                <div className="truncate px-1.5 py-1 text-[10px] font-medium">{entry.name}</div>
              </button>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-(--ui-stroke-secondary) p-4 text-xs text-(--ui-text-tertiary)">
            {t('emptyLibrary')}
          </div>
        )}
        {refs.length > 0 && (
          <div className="mt-3 space-y-1">
            <FieldLabel>{t('references')}</FieldLabel>
            <div className="flex flex-wrap gap-2">
              {refs.slice(0, 6).map((ref) => (
                <div key={ref.id} className="h-14 w-14 overflow-hidden rounded-md border border-(--ui-stroke-secondary)">
                  <ImagePreview item={ref} className="h-full w-full object-cover" alt={ref.label} />
                </div>
              ))}
            </div>
            {!selectedSubject && <div className="text-[10px] text-(--ui-text-tertiary)">{t('campaignUsingActiveRefs')}</div>}
          </div>
        )}
      </SectionCard>

      <SectionCard title={`2. ${t('campaignScenes')}`} subtitle={`${scenes.length}/6`} defaultOpen>
        <div className="mb-2 flex flex-wrap gap-1">
          {SCENE_PRESETS.map((preset) => (
            <Chip key={preset.title} active={scenes.some((s) => s.title === preset.title)} onClick={() => addPresetScene(preset)}>
              + {preset.title}
            </Chip>
          ))}
        </div>
        <div className="space-y-2">
          {scenes.map((scene, index) => (
            <div key={scene.id} className="grid gap-2 rounded-lg border border-(--ui-stroke-secondary) p-2 md:grid-cols-[140px_1fr_auto]">
              <Input
                value={scene.title}
                className="h-8 text-xs"
                placeholder={`${t('campaignSceneTitle')} ${index + 1}`}
                onChange={(event) => setScenes(scenes.map((item) => (item.id === scene.id ? { ...item, title: event.target.value } : item)))}
              />
              <Textarea
                value={scene.sceneText}
                rows={2}
                className="min-h-14 text-xs"
                placeholder={t('campaignSceneText')}
                onChange={(event) => setScenes(scenes.map((item) => (item.id === scene.id ? { ...item, sceneText: event.target.value } : item)))}
              />
              <Button
                size="sm"
                variant="ghost"
                className="h-8 w-8 px-0 text-red-500"
                disabled={scenes.length <= 1}
                onClick={() => setScenes(scenes.filter((item) => item.id !== scene.id))}
              >
                <Codicon name="trash" />
              </Button>
            </div>
          ))}
        </div>
        <Button
          size="sm"
          variant="outline"
          className="mt-2 h-8 text-xs"
          disabled={scenes.length >= 6}
          onClick={() => setScenes([...scenes, { id: newId(), title: '', sceneText: '' }])}
        >
          <Codicon name="add" /> {t('campaignAddScene')}
        </Button>
      </SectionCard>

      <SectionCard title={`3. ${t('campaignZones')}`} subtitle={zones.join(', ') || t('campaignNoZone')} defaultOpen>
        <div className="flex flex-wrap gap-1.5">
          {Object.keys(ZONE_PRESETS).filter((key) => key !== 'none').map((zone) => (
            <Chip key={zone} active={zones.includes(zone)} onClick={() => setZones(toggleIn(zones, zone))}>
              {{ right: t('zone_right'), left: t('zone_left'), top: t('zone_top'), bottom: t('zone_bottom'), center: t('zone_center') }[zone] || zone}
            </Chip>
          ))}
        </div>
        <div className="mt-2 text-[10px] text-(--ui-text-tertiary)">{t('campaignZonesHint')}</div>
      </SectionCard>

      <SectionCard title={`4. ${t('campaignSettings')}`} defaultOpen>
        <div className="gap-3" style={GRID(3)}>
          <div className="space-y-1">
            <FieldLabel>{t('aspectRatio')}</FieldLabel>
            <div className="flex flex-wrap gap-1">
              {aspectOptions.slice(0, 8).map((ratio) => (
                <Chip key={ratio} active={aspectRatio === ratio} onClick={() => setAspectRatio(ratio)}>{ratio}</Chip>
              ))}
            </div>
          </div>
          <div className="space-y-1">
            <FieldLabel>{t('fidelity')}</FieldLabel>
            <div className="flex flex-wrap gap-1">
              {[80, 90, 95].map((value) => (
                <Chip key={value} active={fidelity === value} onClick={() => setFidelity(value)}>{value}%</Chip>
              ))}
            </div>
          </div>
          <div className="space-y-1">
            <FieldLabel>{t('model')}</FieldLabel>
            <div className="truncate text-xs text-(--ui-text-secondary)">{model || provider}</div>
            <div className="text-[10px] text-(--ui-text-quaternary)">{t('campaignModelHint')}</div>
          </div>
        </div>
      </SectionCard>

      <div className="flex flex-wrap items-center gap-2">
        <Button className="h-9 gap-1.5 px-4 font-semibold" disabled={submitting || !!jobId || !primaryImage || cellCount < 1} onClick={() => void startCampaign()}>
          {jobId ? <Spinner /> : <Codicon name="table" />}
          {jobId ? t('generating') : t('generateMatrix', { envs: String(scenes.filter((s) => s.title.trim()).length), zones: String(Math.max(1, zones.length)) })}
        </Button>
        <Badge variant="outline" className="text-[10px]">{cellCount} {t('campaignCells')}</Badge>
        {error && <span className="text-xs text-red-500">{error}</span>}
      </div>

      {jobId && <JobProgress jobId={jobId} modelLabel={model || provider} onDismiss={() => setJobId(null)} onDone={onJobDone} />}

      {result?.matrix?.length ? (
        <SectionCard title={t('matrixDone', { cells: String(result.matrix.length) })} defaultOpen>
          <div className="gap-3" style={GRID(Math.min(3, Math.max(1, result.zones?.length || 2)))}>
            {result.matrix.map((cell, index) => (
              <article key={`${cell.scene}-${cell.zone}-${index}`} className="overflow-hidden rounded-xl border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated)">
                <div className="if-checker relative aspect-square bg-(--ui-bg)">
                  {cell.images?.[0] ? (
                    <ServedImage src={cell.images[0]} alt={`${cell.scene} ${cell.zone}`} className="h-full w-full object-contain" loading="lazy" />
                  ) : (
                    <div className="flex h-full items-center justify-center p-3 text-center text-[11px] text-red-500">
                      {cell.error || t('noResult')}
                    </div>
                  )}
                </div>
                <div className="space-y-1.5 p-2">
                  <div className="flex flex-wrap gap-1">
                    <Badge variant="muted" className="text-[9px]">{cell.scene || '—'}</Badge>
                    <Badge variant="outline" className="text-[9px]">{cell.zone || '—'}</Badge>
                  </div>
                  {cell.images?.[0] && (
                    <div className="flex flex-wrap gap-1">
                      <Button size="sm" variant="outline" className="h-7 text-[10px]" onClick={() => downloadFromUrl(cell.images![0], `campaign-${index + 1}.png`)}>
                        <Codicon name="download" /> {t('download')}
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 text-[10px]" onClick={() => onGoToTab('edit', { image: cell.images![0] })}>
                        <Codicon name="edit" /> {t('edit')}
                      </Button>
                      <Button size="sm" variant="outline" className="h-7 text-[10px]" onClick={() => onGoToTab('generate', { image: cell.images![0] })}>
                        <Codicon name="sparkle" /> {t('generate')}
                      </Button>
                    </div>
                  )}
                </div>
              </article>
            ))}
          </div>
        </SectionCard>
      ) : null}
    </div>
  )
}
