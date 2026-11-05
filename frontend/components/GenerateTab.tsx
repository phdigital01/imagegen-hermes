/**
 * ImageGen — generate tab.
 * Owns prompt construction, generation jobs, model actions, and composition entry points.
 */

import { Badge, Button, Codicon, Dialog, DialogContent, DialogHeader, DialogTitle, Input, KbdGroup, Textarea, cn, host, queryClient, useQuery } from '@hermes/plugin-sdk'
import { useEffect, useMemo, useRef, useState } from 'react'

import type { ImageGenConfig, JobResult, LibraryObject, Presets, Provider, ReferenceImage, SubjectLibraryEntry } from '../types'
import {
  ID,
  ImageGenApiError,
  clearPluginData,
  fetchBudget,
  fetchFalModel,
  fetchJobs,
  fetchLocalImagePath,
  fetchOutputFolder,
  fetchSubjectLibrary,
  importObjects,
  invalidateFeed,
  loadSessionPrompts,
  pushSessionPrompt,
  promptText,
  refineFromFeedback,
  resumeJob,
  rest,
  saveOutputFolder,
  subjectAsRefs,
  submitJob,
  queryJobResult
} from '../api'
import { imageRef, writeToChat } from '../chat'
import { jobPollMs } from '../jobEvents'
import { providerReady } from '../access'
import { useImageGenT } from '../i18n'
import {
  DEFAULT_CONFIG,
  aspectOptions,
  computeAlerts,
  configForHistory,
  configForPrompt,
  fieldOptions,
  persistReferenceImage,
  prepareReferences,
  referenceMeta,
  slugThumb,
  subjectOptions
} from '../presets'
import {
  GRID,
  Chip,
  FieldLabel,
  ImagePreview,
  ReferenceImage as ReferenceThumb,
  revealInFolder,
  SectionCard,
  Spinner,
  copyText,
  downloadFromUrl,
  fileToDataUrl,
  formatUsd,
  newId,
  toggleIn
} from './ui-helpers'
import { CompositionTab } from './CompositionTab'
import { PreGenSummary } from './PreGenSummary'
import { directionOptions, DirectionBoard, DirectionStudio, type DirectionTab } from './DirectionStudio'
import { ModelCatalogModal } from './ModelCatalogModal'
import { PromptPanel } from './PromptPanel'
import { BatchGenerate } from './BatchGenerate'
import { JobProgress, ResultGrid } from './ResultGrid'
import { TextSafeAreaPicker } from './TextSafeAreaPicker'
import { SubjectLibrary } from './SubjectLibrary'

interface GenerateTabProps {
  config: ImageGenConfig
  updateConfig: (partial: Partial<ImageGenConfig>) => void
  providers: Provider[]
  presets: Presets | null
  onGoToTab: (tab: string, options?: { image?: string }) => void
  prompt: string
  setPrompt: (value: string) => void
  promptTouched: boolean
  setPromptTouched: (value: boolean) => void
  promptManual: boolean
  setPromptManual: (value: boolean) => void
  skipConfirm: boolean
  setSkipConfirm: (value: boolean) => void
  lastResult: JobResult | null
  setLastResult: (result: JobResult | null) => void
  activeJobId: string | null
  setActiveJobId: (id: string | null) => void
  onOpenSettings?: () => void
}

type PendingAction = 'generate' | 'optimize'

function NativeSelect({ value, onChange, options, className = '' }: { value: string; onChange: (value: string) => void; options: string[]; className?: string }) {
  return (
    <select value={value} onChange={(event) => onChange(event.target.value)} className={cn('h-8 w-full rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 text-xs', className)}>
      {options.map((option) => <option key={option} value={option}>{option}</option>)}
    </select>
  )
}

/** Flat per-image preview only; pixel-priced totals require backend dimensions. */
function parseEstimateUsd(price: string | undefined, numImages: number): number | null {
  if (!price || /\/(mp|megapixel)/i.test(price)) return null
  const head = (price.replace('$', '').split('/')[0] || '').trim()
  const value = Number(head)
  if (!Number.isFinite(value)) return null
  return Math.round(value * numImages * 10000) / 10000
}

export function GenerateTab({
  config,
  updateConfig,
  providers,
  presets,
  onGoToTab,
  prompt,
  setPrompt,
  promptTouched,
  setPromptTouched,
  promptManual,
  setPromptManual,
  skipConfirm,
  setSkipConfirm,
  activeJobId,
  setActiveJobId,
  lastResult,
  setLastResult,
  onOpenSettings
}: GenerateTabProps) {
  const t = useImageGenT()
  const [modal, setModal] = useState<string | null>(null)
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [pasteError, setPasteError] = useState<string | null>(null)
  // Reference details (roles, fidelity, vision) collapse; the thumbnails stay
  // visible above them — the section itself never hides behind a closed card.
  const [refDetailsOpen, setRefDetailsOpen] = useState(false)
  const [objectFolder, setObjectFolder] = useState('')
  const [objectJob, setObjectJob] = useState<string | null>(null)
  const [objectRefLoading, setObjectRefLoading] = useState('')
  const [optimizing, setOptimizing] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const submittingRef = useRef(false)
  const [upscaleProvider, setUpscaleProvider] = useState(() => !providerReady(providers, 'fal') && providerReady(providers, 'magnific') ? 'magnific' : 'fal')
  const [accessNotice, setAccessNotice] = useState('')
  const [pendingAction, setPendingAction] = useState<PendingAction | null>(null)
  useEffect(() => { setPendingAction(null) }, [config])
  const [seed, setSeed] = useState('')
  const [numImages, setNumImages] = useState(config.numImages || 1)
  const [feedbackImage, setFeedbackImage] = useState<string | null>(null)
  const [feedback, setFeedback] = useState('')
  const [refinedPrompt, setRefinedPrompt] = useState('')
  const [refineDiagnosis, setRefineDiagnosis] = useState('')
  const [refining, setRefining] = useState(false)

  const provider = config.provider || 'fal'
  const model = config.selectedModel || ''
  const providerInfo = providers.find((item) => item.name === provider)
  const listedModel = providerInfo?.models.find((item) => item.id === model)
  const magnificReady = !!providers.find((item) => item.name === 'magnific')?.available
  // FAL catalog models are listed without schemas; their exact controls load on selection.
  const falModelQuery = useQuery({
    queryKey: [ID, 'fal-model', model],
    queryFn: () => fetchFalModel(model),
    enabled: provider === 'fal' && !!listedModel?.catalog,
    staleTime: Infinity,
    retry: false
  })
  const modelInfo = useMemo(() => listedModel && falModelQuery.data
    ? { ...listedModel, ...falModelQuery.data, capabilities: { ...listedModel.capabilities, ...falModelQuery.data.capabilities } }
    : listedModel, [listedModel, falModelQuery.data])
  const variationModel = provider === 'magnific' && !modelInfo?.capabilities?.edit ? 'flux-2-pro' : model
  const refs = config.referencesV4 || []
  const subjectList = subjectOptions(presets)
  const presetRatios = aspectOptions(presets)
  const ratios = modelInfo?.aspectRatios?.map((value) => presetRatios.find((ratio) => ratio.value === value) || { value, hint: value, label: value }) || presetRatios
  const resolutionOptions = modelInfo?.resolutionOptions ?? ['1K', '2K', '4K']
  useEffect(() => {
    const changes: Partial<ImageGenConfig> = {}
    if (modelInfo?.aspectRatios?.length && !modelInfo.aspectRatios.includes(config.aspectRatio)) changes.aspectRatio = modelInfo.aspectRatios[0]
    if (modelInfo?.resolutionOptions?.length && !modelInfo.resolutionOptions.includes(config.resolution)) changes.resolution = modelInfo.resolutionOptions[0]
    if (Object.keys(changes).length) updateConfig(changes)
  }, [modelInfo, config.aspectRatio, config.resolution, updateConfig])
  const alerts = useMemo(() => computeAlerts(config, modelInfo), [config, modelInfo])
  // An empty form is not an error: the Generate button already says a description is needed.
  const shownBlocking = alerts.blocking.filter((alert) => alert.id !== 'no-description')
  const cleanZonesSuppressed = useMemo(
    () => !!config.cleanZones?.enabled && config.compositionIntent?.status === 'confirmed' && (((config.compositionIntent as unknown as { sceneComplexity?: string })?.sceneComplexity === 'complex') || config.subjectType === 'ambiente_arquitetura'),
    [config.cleanZones, config.compositionIntent, config.subjectType]
  )
  const [builtFor, setBuiltFor] = useState<ImageGenConfig | null>(null)
  const hasPrompt = prompt.trim().length > 0 && (promptManual || promptTouched || builtFor === config)
  const palette = config.colorAccents || []
  const paletteEnabled = config.colorAccentsEnabled ?? palette.length > 0
  const fields = fieldOptions(presets, config.subjectType)
  const objectsQuery = useQuery({
    queryKey: [ID, 'objects'],
    queryFn: () => fetchSubjectLibrary(),
    staleTime: 30_000
  })
  const jobsQuery = useQuery({
    queryKey: [ID, 'jobs'],
    queryFn: fetchJobs,
    refetchInterval: activeJobId ? jobPollMs(2000, 10_000) : jobPollMs(8000, 60_000)
  })
  const objects = objectsQuery.data || []
  const maxRefs = modelInfo?.capabilities?.maxReferences || 0
  useEffect(() => { if (refsTooManyError) setRefsTooManyError(null) }, [refs.length])
  const refMismatch = maxRefs > 0 && refs.length > maxRefs
  const [sessionPrompts, setSessionPrompts] = useState<string[]>(() => loadSessionPrompts())
  const [seedLocked, setSeedLocked] = useState(false)
  const [importKind, setImportKind] = useState('product')
  const [refsOpen, setRefsOpen] = useState(false)
  const [studioTab, setStudioTab] = useState<DirectionTab | null>(null)
  const [refsTooManyError, setRefsTooManyError] = useState<string | null>(null)
  const [varyMenuFor, setVaryMenuFor] = useState<string | null>(null)
  const budgetQuery = useQuery({
    queryKey: [ID, 'budget'],
    queryFn: fetchBudget,
    staleTime: 30_000
  })
  const budgetLimit = budgetQuery.data?.monthlyLimit ?? null
  const spentThisMonth = budgetQuery.data?.spentThisMonth ?? 0
  const estimateUsd = parseEstimateUsd(modelInfo?.price, numImages)
  const budgetExceeded = budgetLimit !== null && estimateUsd !== null && spentThisMonth + estimateUsd > budgetLimit
  useEffect(() => {
    if (promptTouched || promptManual) return
    let stale = false
    const timer = setTimeout(() => {
      rest<{ formatted?: unknown; prompt?: string }>('/prompt/build', 'POST', { config: configForPrompt(config, { provider, selectedModel: model }) })
        .then((payload) => {
          if (stale) return
          setPrompt(promptText(payload.formatted) || promptText(payload.prompt))
          setBuiltFor(config)
        })
        .catch((error) => {
          if (stale) return
          // Fixed id: repeated background failures replace the same toast
          // instead of stacking a new one per keystroke.
          host.notify({ id: 'imagegen-prompt-build', kind: 'error', title: t('describeImage'), message: error instanceof Error ? error.message : String(error) })
        })
    }, 400)
    return () => { stale = true; clearTimeout(timer) }
  }, [config, model, promptManual, promptTouched, provider, setPrompt])

  const setDirection = (partial: Partial<ImageGenConfig['globalDirection']>) => {
    updateConfig({ globalDirection: { ...config.globalDirection, ...partial } })
  }

  const chooseSubject = (subject: string) => updateConfig({
    directionVersion: 1, subjectType: subject, structuredFields: {}
  })

  const attachImages = (files: File[]) => {
    const images = files.filter((file) => file.type.startsWith('image/'))
    if (!images.length) return false
    setPasteError(null)
    void Promise.all(images.map(async (image): Promise<ReferenceImage> => {
      const persisted = await persistReferenceImage(await fileToDataUrl(image), image.name)
      return { ...persisted, id: newId(), label: image.name, semanticRole: 'object_primary', authorityLevel: 'supporting', roleConfirmed: false, fidelity: 70, fixedProduct: false, purposes: [], keep: [], vary: [], granularWeights: {}, userNotes: '', instructions: '', inputMode: 'upload', isAnalyzing: false, analysisResult: null, origin: 'upload' }
    }))
      .then((added) => updateConfig({ referencesV4: [...refs, ...added] }))
      .catch((error) => {
        console.error('[IF-TAG] paste reference failed:', error)
        setPasteError(error instanceof Error ? error.message : String(error))
      })
    return true
  }

  const runImportObjects = async () => {
    if (!objectFolder.trim()) return
    setObjectJob('running')
    try {
      const payload = await importObjects(objectFolder.trim(), importKind)
      setObjectJob(payload.id)
    } catch (error) {
      setObjectJob(null)
      host.notifyError(error, t('import'))
    }
  }

  const onObjectJobDone = async (job: { id: string; status: string }) => {
    if (job.status === 'completed') {
      await objectsQuery.refetch()
      await jobsQuery.refetch()
    }
    setObjectJob(null)
  }

  const useObjectRef = async (object: LibraryObject | SubjectLibraryEntry): Promise<ReferenceImage[] | null> => {
    setObjectRefLoading(object.id)
    try {
      const max = modelInfo?.capabilities?.maxReferences || 4
      const { refs: nextRefs } = await subjectAsRefs(object.id, Math.max(1, max))
      const combined = [...refs, ...nextRefs]
      updateConfig({
        referencesV4: combined,
        subjectType: (object as SubjectLibraryEntry).kind || config.subjectType
      })
      return combined
    } catch (error) {
      host.notifyError(error, t('useAsFixedRef'))
      return null
    } finally {
      setObjectRefLoading('')
    }
  }

  const [suggestion, setSuggestion] = useState<{ source: ImageGenConfig; base: string; result: string; suggestedFormat: boolean; effective: ImageGenConfig } | null>(null)
  const preview = suggestion?.source === config && suggestion.base === prompt ? suggestion : null
  const aiEnabled = config.optimizeOnGenerate === true && !promptManual && !promptTouched
  const latestSource = useRef<{ config: ImageGenConfig; prompt: string } | null>(null)
  latestSource.current = { config, prompt }
  useEffect(() => () => { latestSource.current = null }, [])
  const [aiError, setAiError] = useState<{ source: ImageGenConfig; message: string } | null>(null)
  const optimizingRef = useRef(false)
  const getSuggestion = async () => {
    if (preview) return preview
    if (optimizingRef.current) return null
    setAiError(null)
    optimizingRef.current = true
    setOptimizing(true)
    setPendingAction(null)
    try {
      const visual = config.globalDirection
      const manual = Object.fromEntries(Object.entries({
        subject: config.subjectType === 'livre' ? '' : config.subjectType, style: visual.style,
        lighting: visual.lighting.join(', '), angle: visual.angle, distance: config.subjectDistance,
        lens: visual.lens, aperture: visual.aperture, mood: config.mood, format: config.manualFormat ? config.aspectRatio : ''
      }).filter(([, value]) => value))
      const groups = ['subject', 'style', 'lighting', 'angle', 'distance', 'lens', 'aperture', 'mood'] as const
      const choices = Object.fromEntries(groups.map(group => [group, directionOptions(presets, group)]))
      choices.format = ratios.map(ratio => ratio.value)
      const { result, direction: pick } = await rest<{ result: string; direction: Record<string, string> }>('/llm/optimize', 'POST', {
        prompt, description: config.description, toolTarget: model, directionOptions: choices, manual
      })
      if (latestSource.current?.config !== config || latestSource.current.prompt !== prompt) return null
      const effective = { ...config, subjectType: pick.subject || config.subjectType, mood: pick.mood || config.mood,
        aspectRatio: pick.format || config.aspectRatio, subjectDistance: pick.distance || config.subjectDistance,
        globalDirection: { ...visual, style: pick.style || visual.style, lighting: pick.lighting ? [pick.lighting] : visual.lighting,
          angle: pick.angle || visual.angle, lens: pick.lens || visual.lens, aperture: pick.aperture || visual.aperture } }
      const next = { source: config, base: prompt, result, suggestedFormat: !!pick.format, effective }
      setSuggestion(next)
      return next
    } catch (error) {
      if (latestSource.current?.config === config) setAiError({ source: config, message: error instanceof Error ? error.message : String(error) })
      return null
    } finally {
      optimizingRef.current = false
      setOptimizing(false)
    }
  }

  const startGenerate = async (promptOverride?: string, refsOverride?: ReferenceImage[]) => {
    let activePrompt = (promptOverride ?? prompt).trim()
    if ((!promptOverride && !hasPrompt) || !activePrompt || activeJobId || submittingRef.current) return
    submittingRef.current = true
    setSubmitting(true)
    setPendingAction(null)
    try {
      let effective = config
      if (!promptOverride && aiEnabled) {
        const suggestion = await getSuggestion()
        if (!suggestion || !suggestion.result.trim()) return
        activePrompt = suggestion.result.trim()
        effective = suggestion.effective
      }
      const sourceRefs = refsOverride ?? refs
      const prepared = await prepareReferences(sourceRefs)
      if (latestSource.current?.config !== config || latestSource.current.prompt !== prompt) return
      if (prepared.changed) updateConfig({ referencesV4: prepared.ready })
      const payload = {
        kind: 'generate',
        clientRequestId: newId(),
        provider,
        model,
        prompt: activePrompt,
        aspectRatio: effective.aspectRatio,
        seed: modelInfo?.supportsSeed === false ? undefined : seed ? Number(seed) : undefined,
        negativePrompt: config.negativePrompt,
        numImages,
        resolution: config.resolution || '1K',
        referenceImages: prepared.sources,
        saveToGallery: config.saveToGallery !== false,
        config: configForHistory({ ...effective, referencesV4: prepared.ready })
      }
      const response = await submitJob(payload)
      setActiveJobId(response.id)
      setSessionPrompts(pushSessionPrompt(activePrompt))
      void jobsQuery.refetch()
    } catch (error) {
      setActiveJobId(null)
      if (error instanceof ImageGenApiError && error.code === 'refs.too_many') setRefsTooManyError(error.message)
      else if (error instanceof Error && String(error.message).includes('refs.too_many')) setRefsTooManyError(String(error.message))
      host.notifyError(error, t('generateImage'))
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  const prepareBatch = async () => {
    const prepared = await prepareReferences(refs)
    if (prepared.changed) updateConfig({ referencesV4: prepared.ready })
    return {
      provider, model, aspectRatio: config.aspectRatio, resolution: config.resolution,
      negativePrompt: config.negativePrompt, referenceImages: prepared.sources,
      seed: seed && modelInfo?.supportsSeed !== false ? Number(seed) : undefined,
      config: configForHistory({ ...config, referencesV4: prepared.ready })
    }
  }
  const batchBlock = !providerReady(providers, provider) || !model
    ? t('batch.access')
    : alerts.blocking.find(alert => !['no-description', 'refs-without-intent'].includes(alert.id))?.message || ''

  const requestGenerate = () => {
    if (generateDisabled) return
    if (aiEnabled && !preview && !skipConfirm) {
      void getSuggestion().then(next => { if (next) setPendingAction('generate') })
    } else if (skipConfirm) {
      void startGenerate()
    } else {
      setPendingAction('generate')
    }
  }

  const onJobDone = async (job: { id: string; status: string; hasPartialResult?: boolean }) => {
    if (job.status === 'completed' || job.hasPartialResult) {
      const full = await queryJobResult(job.id)
      const result = full.result
      if (result.images?.length) {
        setLastResult({ images: result.images, gallery_ids: result.gallery_ids, warnings: result.warnings })
        queryClient.invalidateQueries({ queryKey: [ID, 'gallery'] })
        queryClient.invalidateQueries({ queryKey: [ID, 'history'] })
        invalidateFeed()
      }
    }
    setActiveJobId(null)
  }

  const runImageJob = async (path: string, body: Record<string, unknown>) => {
    if (activeJobId || submittingRef.current) return
    submittingRef.current = true
    setSubmitting(true)
    try {
      const response = await rest<{ id: string }>(path, 'POST', { ...body, clientRequestId: newId() })
      setActiveJobId(response.id)
    } catch (error) {
      host.notifyError(error, t('generateImage'))
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }
  const doVary = (image: string, intent: 'subtle' | 'angle' | 'light' | 'background' | 'fidelity' = 'subtle') => {
    const intentPrompt: Record<string, string> = {
      subtle: `Subtle variation of: ${prompt}. Keep subject, composition and style identical.`,
      angle: `Same subject and scene as: ${prompt}. Change only camera angle slightly.`,
      light: `Same subject and composition as: ${prompt}. Change only lighting setup.`,
      background: `Same subject as: ${prompt}. Change only the background environment.`,
      fidelity: `Higher product fidelity version of: ${prompt}. Preserve geometry, materials and labels exactly.`
    }
    const nextSeed = seedLocked && seed ? Number(seed) : undefined
    return runImageJob('/vary', {
      image,
      prompt: intentPrompt[intent],
      provider: provider === 'magnific' ? 'magnific' : 'fal',
      model: variationModel,
      aspectRatio: config.aspectRatio,
      resolution: variationModel === model ? config.resolution : '1K',
      seed: modelInfo?.supportsSeed === false ? undefined : nextSeed
    }).finally(() => setVaryMenuFor(null))
  }
  // "Ask agent" writes a ready message into the chat composer; the user reviews and sends it.
  const askAgent = async (image: string) => {
    const local = await fetchLocalImagePath(image).catch(() => '')
    const path = local || image
    // A local file goes in as an image attachment too, so the agent sees it.
    const message = (local ? `${imageRef(local)}\n\n` : '') + t('agentMessage', {
      path,
      model: modelInfo?.display || model,
      prompt,
      feedback: feedback.trim() ? t('agentFeedback', { feedback: feedback.trim() }) : ''
    })
    try {
      if (await writeToChat(message)) {
        host.notify({ id: 'imagegen-agent-brief', kind: 'success', message: t('agentSent') })
        return
      }
      await navigator.clipboard.writeText(message)
      host.notify({ id: 'imagegen-agent-brief', kind: 'info', message: t('agentNoChat') })
    } catch (error) {
      host.notifyError(error, t('refineFailed'))
    }
  }
  const requestRefine = async () => {
    if (!feedbackImage || !feedback.trim()) return
    setRefining(true)
    setRefineDiagnosis('')
    setRefinedPrompt('')
    try {
      const response = await refineFromFeedback({
        image: feedbackImage,
        prompt,
        feedback,
        provider,
        model,
        aspectRatio: config.aspectRatio
      })
      setRefineDiagnosis(response.diagnosis || '')
      setRefinedPrompt(response.newPrompt || '')
    } catch (error) {
      setRefineDiagnosis(t('refineFailed'))
      setRefinedPrompt('')
      host.notifyError(error, t('refineFailed'))
    } finally {
      setRefining(false)
    }
  }
  const confirmRefinedGenerate = () => {
    const next = refinedPrompt.trim()
    if (!next) return
    setPrompt(next)
    setPromptTouched(true)
    setPromptManual(true)
    setFeedbackImage(null)
    setFeedback('')
    setRefineDiagnosis('')
    setRefinedPrompt('')
    void startGenerate(next)
  }
  const needsAccess = (name: string) => {
    if (providerReady(providers, name)) return false
    setAccessNotice(name === 'magnific' ? 'Magnific' : 'FAL')
    return true
  }
  const doUpscale = (image: string) => needsAccess(upscaleProvider) ? undefined : runImageJob('/upscale', { image, provider: upscaleProvider, creativity: 0.35, scale: 2, mode: 'classic', prompt })
  const doBgRemove = (image: string) => needsAccess('fal') ? undefined : runImageJob('/bg-remove', { image }).catch((error) => host.notifyError(error, t('removeBg')))

  const useAsRef = async (image: string) => {
    try {
      const persisted = await persistReferenceImage(image, `result-${refs.length + 1}.png`)
      const reference: ReferenceImage = {
        id: newId(),
        label: `${t('refResult')} ${refs.length + 1}`,
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
        origin: 'history'
      }
      updateConfig({ referencesV4: [...refs, reference] })
    } catch (error) {
      host.notifyError(error, t('useAsRef'))
    }
  }

  const subjectLabel = subjectList.find((item) => item.value === config.subjectType)?.label || ''
  const styleLabel = config.globalDirection.style
  const costEstimate = modelInfo?.price ? `~${modelInfo.price}` : ''
  // A disabled Generate button must say why in visible text, not color alone;
  // the reason is associated to the button via aria-describedby.
  const generateDisabled = optimizing || (aiEnabled && preview !== null && !preview.result.trim()) || !providerReady(providers, provider) || alerts.blocking.length > 0 || !hasPrompt || submitting || !!activeJobId || refMismatch || budgetExceeded
  const generateDisabledReason = optimizing ? t('analyzing') : !hasPrompt
    ? config.description.trim() ? t('buildingPrompt') : t('describeToGenerate')
    : refMismatch
      ? t('refMismatch', { count: String(refs.length), max: String(maxRefs) })
      : budgetExceeded && budgetLimit !== null && estimateUsd !== null
        ? t('budget.exceeded', { spent: formatUsd(spentThisMonth), limit: formatUsd(budgetLimit), estimate: formatUsd(estimateUsd) })
        : activeJobId
          ? t('generating')
          : !providerReady(providers, provider) ? t('batch.access') : alerts.blocking[0]?.message || ''

  // References section — always visible (the user's standing request: the
  // reference surface must never hide behind a collapsed card). Thumbnails
  // stay on screen with per-thumb removal; only the detail editor
  // (roles/fidelity/vision) collapses. The campaign entry point lives in the
  // tab header and the object library is its own card below.
  // Sticky reference strip — card 0 large with padlock, persisted dot, grouping, passport snippet, reorder handle.
  function renderObjectLibrary() {
    return (
      <div className="space-y-2">
        <p className="text-[10.5px] leading-relaxed text-(--ui-text-tertiary)">{t('libraryReferenceHint')}</p>
        <div className="flex gap-2">
          <Input value={objectFolder} placeholder="C:\\Users\\you\\Pictures\\products" className="h-8 flex-1 text-xs font-mono" onChange={(event) => setObjectFolder(event.target.value)} />
          <select value={importKind} onChange={(event) => setImportKind(event.target.value)} className="h-8 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 text-xs">
            {['product', 'person', 'object', 'vehicle', 'animal', 'food', 'place', 'character', 'other'].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
          <Button size="sm" className="h-8 gap-1 text-xs" onClick={() => void runImportObjects()} disabled={!!objectJob}>
            {objectJob === 'running' ? <Spinner /> : <Codicon name="cloud-download" />}
            {objectJob ? t('importing') : t('import')}
          </Button>
        </div>
        {objectJob && objectJob !== 'running' && <JobProgress jobId={objectJob} modelLabel={t('objectLibrary')} onDone={onObjectJobDone} />}
        {objects.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {objects.map((object) => (
              <div key={object.id} className="w-20 overflow-hidden rounded-lg border border-(--ui-stroke-secondary)">
                <ImagePreview item={object} className="h-16 w-full object-cover" alt={object.name} />
                <div className="flex items-center justify-between gap-0.5 px-1 py-1">
                  <span className="truncate text-[9.5px] font-medium" title={object.name}>{object.name}</span>
                  <button type="button" title={t('useAsFixedRef')} className="text-(--ui-text-tertiary) hover:text-(--ui-accent)" disabled={objectRefLoading === object.id} onClick={() => void useObjectRef(object)}>
                    {objectRefLoading === object.id ? <Spinner size={11} /> : <Codicon name="link" style={{ fontSize: 11 }} />}
                  </button>
                  <button type="button" title={t('viewInFolder')} className="text-(--ui-text-tertiary) hover:text-(--ui-accent)" disabled={!object.localPath} onClick={() => void revealInFolder(object.localPath)}>
                    <Codicon name="folder-opened" style={{ fontSize: 11 }} />
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="mt-3 border-t border-(--ui-stroke-secondary) pt-3">
          <SubjectLibrary
            entries={objects as SubjectLibraryEntry[]}
            presets={presets}
            onUseAsRef={async (entry) => { await useObjectRef(entry) }}
            onGenerateWith={(entry, kind, subjectPrompt) => {
              updateConfig({ subjectType: kind, description: subjectPrompt || config.description })
              if (subjectPrompt) {
                setPrompt(subjectPrompt)
                setPromptTouched(true)
                setPromptManual(true)
              }
              void useObjectRef(entry)
            }}
          />
        </div>
      </div>
    )
  }

  const openJobs = (jobsQuery.data || []).filter((job) => ['running', 'queued', 'failed', 'interrupted'].includes(job.status)).slice(0, 4)
  const refsHash = refs.map((r) => `${r.id}:${r.localPath || r.url || ''}`).join('|')
  const visionStale = config.compositionIntent?.status === 'confirmed' && (config.compositionIntent.snapshotDescription !== (config.description || '') || config.compositionIntent.snapshotRefsHash !== refsHash)
  const currentProviderInfo = providers.find((item) => item.name === provider)
  const stageIsEmpty = !activeJobId && !lastResult?.images?.length && !feedbackImage && !pendingAction

  return (
    <div
      className="if-generate"
      onKeyDown={(event) => {
        if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !activeJobId) {
          event.preventDefault()
          requestGenerate()
        }
      }}
    >
      <section className="if-composer" aria-label={t('describeImage')}>
        <div className="if-composer-scroll">
          <div
            className="if-describe"
            onDragOver={(event) => { if (event.dataTransfer.types.includes('Files')) event.preventDefault() }}
            onDrop={(event) => { if (attachImages(Array.from(event.dataTransfer.files))) event.preventDefault() }}
          >
            <Textarea value={config.description} rows={5} aria-label={t('describeImage')} className="min-h-28 resize-y rounded-none border-0 bg-transparent px-3 py-3 text-sm leading-relaxed focus-visible:ring-0" placeholder={t('describeImageHint')} onPaste={(event) => {
              if (attachImages(Array.from(event.clipboardData.files))) event.preventDefault()
            }} onChange={(event) => {
              setPrompt('')
              setPromptManual(false)
              setPromptTouched(false)
              setPendingAction(null)
              const legacy = !config.directionVersion
              updateConfig({ ...(legacy ? {
                globalDirection: { ...config.globalDirection, style: '', angle: '', lens: '', aperture: '', lighting: [] },
                mood: '', subjectDistance: '', subjectType: '', structuredFields: {}, manualFormat: false,
                negativePrompt: config.negativePrompt === presets?.default_negatives?.[config.subjectType] ? '' : config.negativePrompt,
                aspectRatio: modelInfo?.aspectRatios?.[0] || DEFAULT_CONFIG.aspectRatio
              } : {}), directionVersion: 1, description: event.target.value, compositionIntent: null })
            }} />
            <div className="if-describe-refs">
              <button type="button" className="if-refs-add" onClick={() => setRefsOpen(true)}>
                <Codicon name="add" style={{ fontSize: 12 }} />
                {t('addReferences')}
              </button>
              {refs.length === 0 && <small>{t('referencePasteHint')}</small>}
              {refs.map((reference) => (
                <button key={reference.id} type="button" className="if-ref-thumb" title={reference.label} aria-label={reference.label} onClick={() => setRefsOpen(true)}>
                  <ReferenceThumb reference={reference} className="h-full w-full object-cover" alt={reference.label} />
                </button>
              ))}
              {refs.length > 0 && maxRefs > 0 && <small>{refs.length}/{maxRefs}</small>}
            </div>
          </div>
          {pasteError && <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/8 p-2 text-xs"><Codicon name="error" className="mt-0.5 text-red-500" style={{ fontSize: 13 }} /><span className="text-red-600 dark:text-red-400">{t('uploadFailed')}: {pasteError}</span></div>}

          <div className="if-ai-controls">
            <label><input type="checkbox" checked={aiEnabled} disabled={promptManual || promptTouched} onChange={event => updateConfig({ optimizeOnGenerate: event.target.checked })} /> {t('ai.optimize')}</label>
            {aiEnabled && <Button size="sm" variant="ghost" disabled={!hasPrompt || optimizing || !presets} onClick={() => void getSuggestion()}>{optimizing ? t('analyzing') : t('ai.preview')}</Button>}
          </div>
          {aiEnabled && aiError?.source === config && <p role="alert" className="text-xs">{aiError.message} {t('ai.failure')}</p>}
          {aiEnabled && preview && <label className="space-y-1 text-xs">{t('ai.result')}
            <Textarea value={preview.result} rows={4} onChange={event => setSuggestion({ ...preview, result: event.target.value })} />
          </label>}
          <DirectionBoard manual={aiEnabled && preview ? config : undefined} config={aiEnabled && preview ? preview.effective : config} autoFormat={!config.manualFormat && !(aiEnabled && preview?.suggestedFormat)} onOpen={setStudioTab} />

          <SectionCard title={t('moreOptions')} defaultOpen={false}>
            <div className="if-advanced-grid gap-3">
              <div className="space-y-1"><FieldLabel>{t('quality')}</FieldLabel><div className="flex flex-wrap gap-1">{([['draft', t('draft')], ['standard', t('standard')], ['max', t('max')]] as const).map(([value, label]) => <Chip key={value} active={(config.qualityTier || 'standard') === value} onClick={() => updateConfig({ qualityTier: value, qualityLevel: value })}>{label}</Chip>)}</div></div>
              <div className="space-y-1"><FieldLabel>{t('variants')}</FieldLabel><div className="flex gap-1">{[1, 2, 4].map((value) => <Chip key={value} active={numImages === value} onClick={() => setNumImages(value)}>{value}</Chip>)}</div></div>
              {resolutionOptions.length > 0 && <div className="space-y-1"><FieldLabel>{t('resolution')}</FieldLabel><NativeSelect value={config.resolution || '1K'} onChange={(value) => updateConfig({ resolution: value })} options={resolutionOptions} /></div>}
              {modelInfo?.supportsSeed !== false && <div className="space-y-1"><FieldLabel>Seed ({t('optional')})</FieldLabel><div className="flex gap-1"><Input value={seed} className="h-8 min-w-0 flex-1 text-xs font-mono" placeholder={t('automatic')} onChange={(event) => setSeed(event.target.value.replace(/\D/g, '').slice(0, 10))} /><Chip active={seedLocked} onClick={() => setSeedLocked(!seedLocked)}>{seedLocked ? t('seedLocked') : t('lockSeed')}</Chip></div></div>}
              <div className="space-y-1" style={{ gridColumn: '1 / -1' }}><FieldLabel>{t('fidelity')}</FieldLabel><div className="flex flex-wrap gap-1">{[['faithful', t('skinMode.faithful')], ['balanced', t('balancedFidelity')], ['creative', t('creative')]].map(([value, label]) => <Chip key={value} active={config.globalDirection.fidelityMode === value} onClick={() => setDirection({ fidelityMode: value })}>{label}</Chip>)}</div></div>
              <div className="space-y-1" style={{ gridColumn: '1 / -1' }}><FieldLabel hint={t('negativePromptHint')}>{t('negativePrompt')}</FieldLabel><Textarea value={config.negativePrompt} rows={2} className="text-xs" onChange={(event) => updateConfig({ negativePrompt: event.target.value })} /></div>
              <div className="space-y-2" style={{ gridColumn: '1 / -1' }}>
                <label className="flex items-center gap-2 text-xs">
                  <input type="checkbox" checked={paletteEnabled} onChange={(event) => {
                    updateConfig({ colorAccentsEnabled: event.target.checked, colorAccents: palette.length ? palette : ['#7c3aed'] })
                  }} />
                  {t('colorAccents')}
                </label>
                {paletteEnabled && <div className="flex flex-wrap items-center gap-2">
                  {palette.map((color, index) => <div key={index} className="flex items-center gap-1">
                    <input type="color" aria-label={`${t('colorAccents')} ${index + 1}`} value={color} onChange={(event) => {
                      updateConfig({ colorAccents: palette.map((value, i) => i === index ? event.target.value : value) })
                    }} />
                    <button type="button" aria-label={`${t('remove')} ${color}`} onClick={() => {
                      const next = palette.filter((_, i) => i !== index)
                      updateConfig({ colorAccents: next, colorAccentsEnabled: next.length > 0 })
                    }}>×</button>
                  </div>)}
                  {palette.length < 5 && <Button size="sm" variant="outline" onClick={() => updateConfig({ colorAccents: [...palette, '#7c3aed'] })}>{t('add')}</Button>}
                </div>}
              </div>
            </div>
            <SectionCard title={t('reserveSpace')} subtitle={config.cleanZones.enabled ? `${config.cleanZones.zones.length} ${t('zonesCount')}` : undefined} defaultOpen={config.cleanZones.enabled}>
              <TextSafeAreaPicker value={config.cleanZones} ratio={config.aspectRatio} onChange={(cleanZones) => updateConfig({ cleanZones })} subjectType={config.subjectType} sceneComplexity={(config.compositionIntent as unknown as { sceneComplexity?: string })?.sceneComplexity} suppressed={cleanZonesSuppressed} />
            </SectionCard>
            {fields.length > 0 && <SectionCard title={t('subjectDetails')} subtitle={t('subjectDetailsHint')} defaultOpen={false}>
              <div className="gap-3" style={GRID(2)}>{fields.map((field) => {
                const current = config.structuredFields[field.key]
                const values = Array.isArray(current) ? current : []
                return <div key={field.key} className="space-y-1"><FieldLabel>{field.label}</FieldLabel>{field.type === 'chips' ? <div className="flex flex-wrap gap-1">{(field.options || []).map((option) => <Chip key={option} active={values.includes(option)} onClick={() => updateConfig({ structuredFields: { ...config.structuredFields, [field.key]: toggleIn(values, option) } })}>{option}</Chip>)}</div> : <Input value={typeof current === 'string' ? current : ''} className="h-8 text-xs" placeholder={field.placeholder || '…'} onChange={(event) => updateConfig({ structuredFields: { ...config.structuredFields, [field.key]: event.target.value } })} />}</div>
              })}</div>
            </SectionCard>}
          </SectionCard>

          <SectionCard title={t('finalPrompt')} subtitle={promptManual ? undefined : t('autoPromptHint')} defaultOpen={false}>
            {sessionPrompts.length > 0 && (
              <div className="flex flex-wrap items-center gap-1">
                <span className="text-[10px] uppercase tracking-wider text-(--ui-text-quaternary)">{t('sessionPrompts')}:</span>
                {sessionPrompts.slice(0, 5).map((item) => (
                  <button key={item.slice(0, 24)} type="button" className="max-w-[160px] truncate rounded border border-(--ui-stroke-secondary) px-1.5 py-0.5 text-[10px] hover:bg-(--chrome-action-hover)" title={item} onClick={() => { setPrompt(item); setPromptTouched(true); setPromptManual(true) }}>{item}</button>
                ))}
              </div>
            )}
            {aiEnabled && preview ? <Textarea aria-label={t('finalPrompt')} value={preview.result} rows={5}
              onChange={event => setSuggestion({ ...preview, result: event.target.value })} /> : <PromptPanel value={prompt} onChange={(value) => { setPromptTouched(true); setPrompt(value) }} onOptimize={promptManual || promptTouched ? () => {
              if (optimizingRef.current) return
              optimizingRef.current = true
              setOptimizing(true)
              void rest<{ result: string }>('/llm/optimize', 'POST', { prompt, description: config.description, toolTarget: model, aspectRatio: config.aspectRatio, references: refs.map(referenceMeta) })
                .then(data => { if (latestSource.current?.config === config && latestSource.current.prompt === prompt) setPrompt(data.result) }).catch(error => host.notifyError(error, t('optimizePrompt')))
                .finally(() => { optimizingRef.current = false; setOptimizing(false) })
            } : undefined} onResetAuto={() => { setPromptTouched(false); setPromptManual(false); setPrompt('') }} promptTouched={promptTouched} optimizing={optimizing} disabled={alerts.blocking.length > 0} toolTarget={model || 'generic'} magnificHelpers={magnificReady} readOnly={!promptManual} onEditManual={() => { setPromptManual(true); setPromptTouched(true) }} />}
          </SectionCard>
        </div>

        <div className="if-composer-footer">
          {(promptManual || promptTouched) && <div className="flex flex-wrap items-center justify-between gap-1 text-xs">
            <span>{t('manualPromptActive')}</span>
            <button type="button" onClick={() => { setPrompt(''); setPromptManual(false); setPromptTouched(false) }}>{t('resetAuto')}</button>
          </div>}
          <Button onClick={requestGenerate} disabled={generateDisabled} aria-describedby={generateDisabled && generateDisabledReason ? 'if-generate-disabled-reason' : undefined} className="h-10 w-full gap-1.5 font-semibold">{activeJobId ? <Spinner /> : <Codicon name={lastResult ? 'refresh' : 'sparkle'} style={{ fontSize: 14 }} />}{activeJobId ? t('generating') : lastResult ? t('generateAgain') : t('generateImage')}</Button>
          <BatchGenerate model={modelInfo?.display || model} aspect={config.aspectRatio} refs={refs.length}
            blocked={batchBlock} estimate={parseEstimateUsd(modelInfo?.price, 1)}
            remaining={budgetLimit === null ? null : budgetLimit - spentThisMonth} prepare={prepareBatch} />
          {generateDisabled && generateDisabledReason && <p id="if-generate-disabled-reason" className="text-[10.5px] text-(--ui-text-tertiary)">{generateDisabledReason}</p>}
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-(--ui-text-tertiary)">
            {costEstimate && <span>{costEstimate}</span>}
            {budgetLimit !== null && <span className="tabular-nums">{t('budgetUsage', { spent: formatUsd(spentThisMonth), limit: formatUsd(budgetLimit) })}</span>}
            {config.outputGoal === 'prompt' && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => copyText(aiEnabled && preview ? preview.result : prompt)}>{t('copyPrompt')}</Button>}
            <span className="ml-auto"><KbdGroup keys={['Ctrl', 'Enter']} size="sm" /></span>
          </div>
          {budgetExceeded && budgetLimit !== null && estimateUsd !== null && (
            <div className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/8 p-2 text-[11px]">
              <Codicon name="error" className="mt-0.5 shrink-0 text-red-500" style={{ fontSize: 13 }} />
              <span className="text-red-600 dark:text-red-400">{t('budget.exceeded', { spent: formatUsd(spentThisMonth), limit: formatUsd(budgetLimit), estimate: formatUsd(estimateUsd) })}</span>
            </div>
          )}
        </div>
      </section>

      <section className="if-stage" aria-label={t('result')}>
        {(shownBlocking.length > 0 || alerts.warnings.length > 0) && <div className="if-alerts space-y-1.5">
          {shownBlocking.map((alert) => <div key={alert.id} className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/8 p-2 text-xs"><Codicon name="error" className="mt-0.5 text-red-500" style={{ fontSize: 13 }} /><span className="text-red-600 dark:text-red-400">{alert.message}</span></div>)}
          {alerts.warnings.map((alert) => <div key={alert.id} className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/8 p-2 text-xs"><Codicon name="info" className="mt-0.5 text-amber-500" style={{ fontSize: 13 }} /><span className="text-amber-700 dark:text-amber-400">{alert.message}</span></div>)}
        </div>}
        {currentProviderInfo && !providerReady(providers, provider) && (
          <div className="if-access-notice" role="status">
            <Codicon name="lock" style={{ fontSize: 14 }} />
            <div><p>{t('accessProviderMissing', { provider: currentProviderInfo.display_name || provider })}</p></div>
            {onOpenSettings && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onOpenSettings}>{t('accessConfigure')}</Button>}
          </div>
        )}
        {accessNotice && (
          <div className="if-access-notice" role="status">
            <Codicon name="lock" style={{ fontSize: 14 }} />
            <div><p>{t('accessNeeded', { provider: accessNotice })}</p></div>
            {onOpenSettings && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onOpenSettings}>{t('accessConfigure')}</Button>}
            <button type="button" className="if-icon-button" aria-label={t('close')} onClick={() => setAccessNotice('')}><Codicon name="close" style={{ fontSize: 13 }} /></button>
          </div>
        )}
        {visionStale && <div className="flex items-center gap-1 text-[10.5px] text-amber-600"><Codicon name="warning" style={{ fontSize: 11 }} />{t('staleWarning')}</div>}
        {(refsTooManyError || refMismatch) && (
          <div className="flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/8 p-2 text-xs">
            <Codicon name="warning" className="mt-0.5 text-amber-500" style={{ fontSize: 13 }} />
            <span className="text-amber-700 dark:text-amber-400">{refsTooManyError || t('refMismatch', { count: String(refs.length), max: String(maxRefs) })}</span>
          </div>
        )}
        {openJobs.length > 0 && (
          <div className="space-y-1 rounded-lg border border-(--ui-stroke-secondary) p-2 text-[11px]">
            <div className="font-medium text-(--ui-text-secondary)">{t('jobQueue')}</div>
            {openJobs.map((job) => (
              <div key={job.id} className="flex items-center justify-between gap-2">
                <span className="truncate">{job.kind} · {job.status}{job.message ? ` · ${job.message}` : ''}</span>
                {job.status === 'failed' && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-6 text-[10px]"
                    onClick={() => {
                      void rest<{ id?: string }>(`/jobs/${job.id}/retry`, 'POST')
                        .then((payload) => { if (payload.id) setActiveJobId(payload.id) })
                        .catch((error) => host.notifyError(error, t('retry')))
                    }}
                  >
                    {t('retry')}
                  </Button>
                )}
                {job.status === 'interrupted' && job.remote && (
                  <Button
                    size="sm"
                    className="h-6 text-[10px]"
                    onClick={() => {
                      // Recovery talks to the provider, so it can fail (expired
                      // request, revoked key). Never swallow it: a dead button
                      // is how a paid result silently disappears.
                      void resumeJob(job.id)
                        .then(() => { void jobsQuery.refetch(); invalidateFeed() })
                        .catch((error) => host.notifyError(error, t('jobResume')))
                    }}
                  >
                    {t('jobResume')}
                  </Button>
                )}
              </div>
            ))}
          </div>
        )}
        {pendingAction && <PreGenSummary action={pendingAction} onConfirm={() => void startGenerate()} onCancel={() => setPendingAction(null)} modelLabel={modelInfo?.display || model} promptPreview={aiEnabled && preview ? preview.result : prompt} refCount={refs.length} aspectRatio={aiEnabled && preview ? preview.effective.aspectRatio : config.aspectRatio} warnings={alerts.warnings.length} skipConfirm={skipConfirm} onSkipChange={setSkipConfirm} title={t('confirmGeneration')} optimizeTitle={t('optimizePrompt')} cancel={t('cancel')} generate={t('generate')} optimize={t('optimize')} dontAskAgain={t('dontAskAgain')} refsLabel={t('refsLabel')} warningsLabel={t('warnings')} cleanZones={config.cleanZones} cleanZonesSuppressed={cleanZonesSuppressed} />}
        {lastResult?.warnings?.map((warning) => <p key={warning} role="status" className="text-xs text-(--ui-yellow)">{warning}</p>)}
        {activeJobId && <JobProgress jobId={activeJobId} modelLabel={modelInfo?.display || model} onJobReplaced={setActiveJobId} onDismiss={() => setActiveJobId(null)} onDone={onJobDone} />}
        {stageIsEmpty && (
          <div className="if-stage-empty">
            <div className="if-stage-frame" style={{ aspectRatio: config.aspectRatio.replace(':', ' / ') }}>
              <Codicon name="sparkle" style={{ fontSize: 22 }} />
              <strong>{t('stageEmptyTitle')}</strong>
              <span>{t('stageEmptyHint')}</span>
            </div>
          </div>
        )}
        {lastResult?.images?.length ? (
          <div className="space-y-2 pt-1">
            <div className="flex items-center gap-2">
              <Codicon name="check" className="text-emerald-500" style={{ fontSize: 13 }} />
              <span className="text-[11px] font-medium">{t('result')} ({lastResult.images.length})</span>
              {lastResult.gallery_ids?.length ? <Badge variant="outline" className="text-[9px] text-emerald-500">{t('savedGallery')}</Badge> : null}
              {seed && <Chip active={seedLocked} onClick={() => setSeedLocked(!seedLocked)}>seed {seed}</Chip>}
            </div>
            <label className="flex items-center gap-2 text-xs">
              {t('upscale')}
              <select value={upscaleProvider} onChange={(event) => setUpscaleProvider(event.target.value)} disabled={!!activeJobId || submitting}>
                <option value="fal" disabled={!providerReady(providers, 'fal')}>FAL Clarity 2×{providerReady(providers, 'fal') ? '' : ` · ${t('accessNone')}`}</option>
                <option value="magnific" disabled={!providerReady(providers, 'magnific')}>Magnific Precision{providerReady(providers, 'magnific') ? '' : ` · ${t('accessNone')}`}</option>
              </select>
            </label>
            <ResultGrid
              images={lastResult.images}
              onDownload={(image) => downloadFromUrl(image, `imagegen-${Date.now()}.png`)}
              onVary={(image) => setVaryMenuFor(image)}
              onUpscale={(image) => void doUpscale(image)}
              upscaleLabel={upscaleProvider === 'magnific' ? 'Magnific Precision' : 'FAL Clarity 2×'}
              onBgRemove={(image) => void doBgRemove(image)}
              onEdit={(image) => onGoToTab('edit', { image })}
              onUseAsRef={(image) => void useAsRef(image)}
              onNotGood={(image) => { setFeedbackImage(image); setFeedback('') }}
              onAskAgent={(image) => void askAgent(image)}
            />
            {varyMenuFor && (
              <div className="flex flex-wrap gap-1 rounded-lg border border-(--ui-stroke-secondary) p-2">
                <span className="text-[10px] text-(--ui-text-tertiary)">{t('vary')}:</span>
                <span className="text-[10px] text-(--ui-text-tertiary)">{provider === 'magnific' ? `Magnific · ${providerInfo?.models.find((item) => item.id === variationModel)?.display || variationModel}` : 'FAL · FLUX.2 Pro Edit'}</span>
                {([['subtle', t('varySubtle')], ['angle', t('varyAngle')], ['light', t('varyLight')], ['background', t('varyBackground')], ['fidelity', t('varyFidelity')]] as const).map(([value, label]) => (
                  <Button key={value} size="sm" variant="outline" className="h-7 text-[10px]" onClick={() => void doVary(varyMenuFor, value)}>{label}</Button>
                ))}
                <Button size="sm" variant="ghost" className="h-7 text-[10px]" onClick={() => setVaryMenuFor(null)}>{t('close')}</Button>
              </div>
            )}
            {lastResult.gallery_ids?.[0] && (
              <Button size="sm" variant="outline" className="h-8 text-xs" onClick={() => void rest<{ url?: string }>(`/gallery/${lastResult.gallery_ids![0]}/export-pack`).then((payload) => { if (payload.url) window.open(payload.url, '_blank') })}>{t('exportPack')}</Button>
            )}
          </div>
        ) : null}
        {feedbackImage && (
          <div className="rounded-xl border border-(--ui-accent)/30 bg-(--ui-accent)/6 p-3 space-y-2">
            <div className="flex items-center justify-between">
              <strong className="text-xs">{t('notGood')}</strong>
              <button type="button" aria-label={t('close')} onClick={() => { setFeedbackImage(null); setRefineDiagnosis(''); setRefinedPrompt('') }}>
                <Codicon name="close" />
              </button>
            </div>
            <Textarea value={feedback} rows={2} placeholder={t('feedbackPlaceholder')} onChange={(event) => setFeedback(event.target.value)} />
            <Button size="sm" variant="outline" onClick={() => void requestRefine()} disabled={!feedback.trim() || refining}>
              {refining ? <Spinner /> : null}
              {t('proposePrompt')}
            </Button>
            {refineDiagnosis && (
              <div className="rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg) p-2 text-[11px] text-(--ui-text-secondary)">
                <div className="mb-1 font-medium text-(--ui-text-primary)">{t('diagnosis')}</div>
                {refineDiagnosis}
              </div>
            )}
            {refinedPrompt && (
              <div className="space-y-2 rounded-lg border border-(--ui-stroke-secondary) bg-(--ui-bg) p-2">
                <Textarea value={refinedPrompt} rows={3} onChange={(event) => setRefinedPrompt(event.target.value)} />
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" variant="outline" onClick={() => { setFeedbackImage(null); setRefineDiagnosis(''); setRefinedPrompt('') }}>{t('cancel')}</Button>
                  <Button size="sm" onClick={confirmRefinedGenerate} disabled={!refinedPrompt.trim() || !!activeJobId}>{t('generateWithPrompt')}</Button>
                </div>
              </div>
            )}
          </div>
        )}
      </section>

      <ModelCatalogModal open={catalogOpen} onClose={() => setCatalogOpen(false)} onOpenSettings={onOpenSettings} providers={providers} selectedModel={model} providerName={provider} onSelect={(selected) => updateConfig({ selectedModel: selected })} onProviderChange={(selectedProvider) => { const chosen = providers.find((item) => item.name === selectedProvider); const first = chosen?.default_model || chosen?.models[0]?.id || ''; updateConfig({ provider: selectedProvider, selectedModel: first }) }} />
      <DirectionStudio tab={studioTab} onTab={setStudioTab} onClose={() => setStudioTab(null)} config={config} presets={presets} updateConfig={partial => updateConfig({ directionVersion: 1, ...partial })} onSubject={chooseSubject} ratios={ratios} allowedRatios={modelInfo?.aspectRatios} />
      <Dialog open={refsOpen} onOpenChange={setRefsOpen}>
        <DialogContent className="imagegen-ui if-refs-dialog">
          <DialogHeader>
            <DialogTitle className="text-sm">{t('referencesAndObjects')}</DialogTitle>
          </DialogHeader>
          <div className="if-refs-body">
            <CompositionTab config={config} updateConfig={updateConfig} providers={providers} presets={presets} prompt={prompt} setPrompt={setPrompt} promptTouched={promptTouched} setPromptTouched={setPromptTouched} promptManual={promptManual} setPromptManual={setPromptManual} />
            <SectionCard title={t('objectLibrary')} subtitle={`${objects.length} ${t('entries')}`} defaultOpen={false}>
              {renderObjectLibrary()}
            </SectionCard>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
