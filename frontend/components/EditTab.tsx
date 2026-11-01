/** Image editing with explicit operation and provider selection. */
import { Button, Codicon, Input, Textarea, cn, useQuery } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'
import type { EditMode, ImageGenConfig, Provider } from '../types'
import { ID, fetchFalModel, fetchImageDataUrl, invalidateGallery, rest, queryJobResult, getStored, setStored } from '../api'
import { isSubscription, providerReady } from '../access'
import { useImageGenT } from '../i18n'
import { fileToDataUrl, newId, Spinner, downloadFromUrl, urlToDataUrl } from './ui-helpers'
import { MaskCanvas, type MaskCanvasApi } from './MaskCanvas'
import { JobProgress, ResultGrid } from './ResultGrid'
import { ModelCatalogModal } from './ModelCatalogModal'

interface EditFile { id: string; dataUrl: string; name: string }
interface EditMerge { merged: boolean; reason?: string; changedShare?: number | null }
interface EditResult { images?: string[]; warnings?: string[]; merge?: EditMerge }
/** One state of the image; `redraws` counts how many times the model's whole answer was used on the way here. */
interface EditVersion { id: string; dataUrl: string; prompt: string; redraws: number }

const MODES: EditMode[] = ['global', 'region', 'expand', 'background', 'relight', 'style-transfer', 'upscale', 'camera', 'skin']
const MAGNIFIC_ONLY: EditMode[] = ['relight', 'style-transfer', 'camera', 'skin']
/** The modes a generation provider that takes references (GPT Image, say) can do. */
const REFERENCE_MODES: EditMode[] = ['global', 'region', 'expand', ...MAGNIFIC_ONLY]
const REDRAW_WARNING = 3
const FAL_DEFAULT_EDIT = 'fal-ai/flux-2-pro/edit'
const EXPAND_MODELS = [['flux-pro', 'Flux Pro'], ['ideogram', 'Ideogram'], ['seedream-v4-5', 'Seedream 4.5']]
const SKIN_TARGETS = ['enhance_skin', 'improve_lighting', 'enhance_everything', 'transform_to_real', 'no_make_up'] as const
const UPSCALE_FLAVORS = ['sublime', 'photo', 'photo_denoiser'] as const

const MODE_ICON: Record<EditMode, string> = {
  global: 'edit',
  region: 'paintcan',
  expand: 'screen-full',
  background: 'clear-all',
  relight: 'lightbulb',
  'style-transfer': 'symbol-color',
  upscale: 'zoom-in',
  camera: 'device-camera',
  skin: 'person'
}

async function toDataUrl(image: string): Promise<string> {
  if (image.startsWith('data:')) return image
  const direct = await urlToDataUrl(image).catch(() => image)
  if (direct.startsWith('data:')) return direct
  return fetchImageDataUrl(image).catch(() => image)
}

export function EditTab({
  config,
  initialImage,
  providers,
  onOpenSettings
}: {
  config: ImageGenConfig
  updateConfig: (partial: Partial<ImageGenConfig>) => void
  initialImage: { image: string; ts: number } | null
  providers: Provider[]
  onOpenSettings?: () => void
}) {
  const t = useImageGenT()
  const [mode, setMode] = useState<EditMode>('global')
  const [files, setFiles] = useState<EditFile[]>([])
  const [prompt, setPrompt] = useState('')
  const [mask, setMask] = useState('')
  const [brushSize, setBrushSize] = useState(32)
  const [erase, setErase] = useState(false)
  const [direction, setDirection] = useState('all')
  const [expandPx, setExpandPx] = useState(256)
  const falReady = providerReady(providers, 'fal')
  const magnificReady = providerReady(providers, 'magnific')
  const referenceEngines = providers.filter((item) => item.name !== 'fal' && item.name !== 'magnific'
    && providerReady(providers, item.name) && item.models.some((model) => (model.capabilities?.maxReferences || 0) > 0))
  const referenceMode = REFERENCE_MODES.includes(mode)
  const [pickedEngine, setEngine] = useState(config.provider)
  const falFits = falReady && !MAGNIFIC_ONLY.includes(mode)
  const pickedFits = pickedEngine === 'fal' ? falFits : pickedEngine === 'magnific' ? magnificReady
    : referenceMode && referenceEngines.some((item) => item.name === pickedEngine)
  const engine = pickedFits ? pickedEngine : falFits ? 'fal' : magnificReady ? 'magnific' : referenceMode && referenceEngines[0]?.name || (MAGNIFIC_ONLY.includes(mode) ? 'magnific' : 'fal')
  const referenceEngine = referenceEngines.find((item) => item.name === engine)
  const referenceModels = referenceEngine?.models.filter((model) => (model.capabilities?.maxReferences || 0) > 0) || []
  const [pickedReferenceModel, setReferenceModel] = useState(config.selectedModel)
  const referenceModel = referenceModels.find((model) => model.id === pickedReferenceModel)
    || referenceModels.find((model) => model.id === referenceEngine?.default_model) || referenceModels[0]
  const [keepUnchanged, setKeepUnchanged] = useState(true)
  const [versions, setVersions] = useState<EditVersion[]>([])
  const [activeVersion, setActiveVersion] = useState('')
  const [editModel, setEditModel] = useState('flux-2-pro')
  const [editRatio, setEditRatio] = useState(config.aspectRatio)
  const [editResolution, setEditResolution] = useState(config.resolution)
  const [imageUrl, setImageUrl] = useState('')
  const [strength, setStrength] = useState(60)
  const [structureStrength, setStructureStrength] = useState(80)
  const [changeBackground, setChangeBackground] = useState(false)
  const [upscaleMode, setUpscaleMode] = useState('classic')
  const [scale, setScale] = useState(2)
  const [creativity, setCreativity] = useState(0.4)
  const [flavor, setFlavor] = useState('')
  const [expandModel, setExpandModel] = useState('flux-pro')
  const [horizontalAngle, setHorizontalAngle] = useState(0)
  const [verticalAngle, setVerticalAngle] = useState(0)
  const [zoom, setZoom] = useState(5)
  const [skinMode, setSkinMode] = useState('faithful')
  const [sharpen, setSharpen] = useState(0)
  const [smartGrain, setSmartGrain] = useState(2)
  const [skinDetail, setSkinDetail] = useState(80)
  const [optimizedFor, setOptimizedFor] = useState<string>('enhance_skin')
  const [falEditModel, setFalEditModel] = useState(FAL_DEFAULT_EDIT)
  const [catalogOpen, setCatalogOpen] = useState(false)
  const operationProvider = engine
  const modeLocked = (value: EditMode) => !(REFERENCE_MODES.includes(value) && referenceEngines.length)
    && (MAGNIFIC_ONLY.includes(value) ? !magnificReady : !falReady && !magnificReady)
  const locked = modeLocked(mode)
  const onlySubscription = !falReady && !magnificReady && providers.some((item) => isSubscription(item.name) && providerReady(providers, item.name))
  const editModels = providers.find((item) => item.name === 'magnific')?.models.filter((item) => item.capabilities?.edit) || []
  const modelInfo = editModels.find((item) => item.id === editModel)
  const falEditModels = providers.find((item) => item.name === 'fal')?.edit_models || []
  const falEditDisplay = falEditModel === FAL_DEFAULT_EDIT ? 'FLUX.2 Pro Edit' : falEditModels.find((item) => item.id === falEditModel)?.display || falEditModel
  // The pinned FLUX.2 Pro Edit takes 9 references; other catalog models report their own limit.
  const falEditQuery = useQuery({
    queryKey: [ID, 'fal-model', falEditModel],
    queryFn: () => fetchFalModel(falEditModel),
    enabled: falEditModel !== FAL_DEFAULT_EDIT,
    staleTime: Infinity,
    retry: false
  })
  const falEditMax = falEditModel === FAL_DEFAULT_EDIT ? 9 : falEditQuery.data?.capabilities?.maxReferences || 1
  const maxImages = mode === 'global' ? referenceEngine ? referenceModel?.capabilities?.maxReferences || 1 : (operationProvider === 'magnific' ? modelInfo?.capabilities?.maxReferences || 4 : falEditMax) : mode === 'relight' || mode === 'style-transfer' ? 2 : 1
  const invalidImages = files.length > maxImages
  const promptRequired = mode === 'global' || mode === 'region' || (mode === 'relight' && files.length < 2)
  const showPrompt = mode !== 'background' && mode !== 'camera' && mode !== 'skin'
  const selectedRatio = modelInfo?.aspectRatios?.includes(editRatio) ? editRatio : modelInfo?.aspectRatios?.[0] || editRatio
  const selectedResolution = modelInfo?.resolutionOptions?.includes(editResolution) ? editResolution : modelInfo?.resolutionOptions?.[0] || '1K'
  const [submitting, setBusy] = useState(false)
  const submittingRef = useRef(false)
  const [jobId, setJobId] = useState<string | null>(() => getStored('editJobId', null))
  useEffect(() => { setStored('editJobId', jobId) }, [jobId])
  const busy = submitting || !!jobId
  const [result, setResult] = useState<EditResult | null>(null)
  const [error, setError] = useState('')
  const maskApi = useRef<MaskCanvasApi | null>(null)

  const startVersions = (dataUrl: string) => {
    const id = newId()
    setVersions([{ id, dataUrl, prompt: '', redraws: 0 }])
    setActiveVersion(id)
  }
  const openVersion = (version: EditVersion) => {
    setFiles((current) => [{ id: newId(), dataUrl: version.dataUrl, name: 'source.png' }, ...current.slice(1)])
    setActiveVersion(version.id)
    setMask('')
    setResult(null)
  }
  /** A finished edit becomes the next source, so every later edit starts from what was kept here. */
  const addVersion = async (data: EditResult) => {
    const image = data.images?.[0]
    const parent = versions.find((item) => item.id === activeVersion)
    if (!image || !parent || data.merge?.reason === 'no-change') return
    const dataUrl = await toDataUrl(image)
    const version = { id: newId(), dataUrl, prompt, redraws: parent.redraws + (data.merge?.merged === false ? 1 : 0) }
    setVersions((current) => [...current, version])
    setFiles((current) => [{ id: newId(), dataUrl, name: 'source.png' }, ...current.slice(1)])
    setActiveVersion(version.id)
    setMask('')
    setPrompt('')
  }

  // The versions, the prompt and the image fit one screen; a finished edit brings them into view.
  const versionsRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (versions.length > 1) versionsRef.current?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }, [versions.length])
  const activeImage = mode === 'global' ? versions.find((item) => item.id === activeVersion)?.dataUrl : undefined
  const shownImages = result?.images?.length ? result.images : activeImage ? [activeImage] : []

  useEffect(() => {
    if (!initialImage?.image) return
    let alive = true
    void toDataUrl(initialImage.image).then((dataUrl) => {
      if (!alive) return
      setFiles([{ id: newId(), dataUrl, name: 'source.png' }])
      startVersions(dataUrl)
      setResult(null)
      setMask('')
    })
    return () => { alive = false }
  }, [initialImage])

  const onFiles = async (list: FileList | null) => {
    if (busy) return
    const accepted: EditFile[] = []
    for (const file of Array.from(list || [])) {
      if (file.type.startsWith('image/')) accepted.push({ id: newId(), dataUrl: await fileToDataUrl(file), name: file.name })
    }
    if (!accepted.length) return
    if (!files.length || maxImages <= 1) startVersions(accepted[0].dataUrl)
    setFiles((current) => maxImages > 1 ? [...current, ...accepted].slice(0, maxImages) : accepted.slice(0, 1))
    setMask('')
    setResult(null)
  }

  const run = async () => {
    if (busy || submittingRef.current || !files.length || invalidImages || (mode === 'style-transfer' && files.length < 2)) return
    if (mode === 'region' && !mask) return
    if (promptRequired && !prompt.trim()) return
    submittingRef.current = true
    setBusy(true)
    setError('')
    setResult(null)
    try {
      const uploads: string[] = []
      for (const file of files) {
        uploads.push(file.dataUrl.startsWith('https://') ? file.dataUrl : (await rest<{ path: string }>('/upload', 'POST', { image: file.dataUrl, name: file.name })).path)
      }
      let data: { id: string }
      if (mode === 'global') {
        data = await rest<{ id: string }>('/edit', 'POST', {
          images: uploads,
          prompt,
          provider: operationProvider,
          model: referenceEngine ? referenceModel?.id : operationProvider === 'magnific' ? editModel : falEditModel,
          keepUnchanged,
          aspectRatio: operationProvider === 'magnific' ? selectedRatio : config.aspectRatio,
          resolution: selectedResolution
        })
      } else if (mode === 'region') {
        data = await rest<{ id: string }>('/inpaint', 'POST', {
          baseImage: uploads[0],
          maskImage: mask,
          prompt,
          provider: operationProvider,
          aspectRatio: config.aspectRatio,
          model: referenceEngine ? referenceModel?.id : 'fal-ai/flux-pro/v1/fill'
        })
      } else if (mode === 'expand') {
        data = await rest<{ id: string }>('/outpaint', 'POST', {
          image: uploads[0],
          provider: operationProvider,
          model: referenceModel?.id,
          // Ideogram and Seedream describe the scene themselves when the prompt is empty.
          prompt: prompt.trim() || (operationProvider === 'magnific' && expandModel !== 'flux-pro' ? '' : 'continue the scene seamlessly'),
          direction,
          expandPx,
          ...(operationProvider === 'magnific' ? { expandModel } : {})
        })
      } else if (mode === 'upscale') {
        const precisionV2 = operationProvider === 'magnific' && upscaleMode === 'precision-v2'
        data = await rest<{ id: string }>('/upscale', 'POST', {
          provider: operationProvider, image: uploads[0], prompt, mode: precisionV2 || operationProvider === 'magnific' || upscaleMode !== 'precision-v2' ? upscaleMode : 'classic', scale: precisionV2 ? scale : Math.min(scale, 4), creativity,
          ...(precisionV2 && flavor ? { flavor } : {})
        })
      } else if (mode === 'camera') {
        data = await rest<{ id: string }>('/camera', 'POST', {
          provider: operationProvider, model: referenceModel?.id, image: uploads[0], horizontalAngle, verticalAngle, zoom
        })
      } else if (mode === 'skin') {
        data = await rest<{ id: string }>('/skin', 'POST', {
          provider: operationProvider, model: referenceModel?.id, image: uploads[0], skinMode, sharpen, smartGrain, skinDetail, optimizedFor
        })
      } else if (mode === 'relight' || mode === 'style-transfer') {
        data = await rest<{ id: string }>(`/${mode}`, 'POST', {
          provider: operationProvider, model: referenceModel?.id, image: uploads[0], referenceImage: uploads[1],
          prompt, strength, structureStrength, changeBackground
        })
      } else {
        data = await rest<{ id: string }>('/bg-remove', 'POST', { image: uploads[0], provider: operationProvider })
      }
      setJobId(data.id)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      submittingRef.current = false
      setBusy(false)
    }
  }

  const source = files[0]?.dataUrl
  const redraws = versions.find((item) => item.id === activeVersion)?.redraws || 0
  const merge = result?.merge
  const mergeNote = !merge ? '' : merge.reason === 'no-change' ? t('editMergeNoChange')
    : merge.reason === 'whole-image' ? t('editMergeWhole')
    : merge.reason === 'different-shape' ? t('editMergeShape')
    : merge.merged ? t('editMergeKept', { percent: String(Math.max(1, Math.round((merge.changedShare || 0) * 100))) }) : ''
  const labels: Record<EditMode, string> = {
    global: t('editGlobal'),
    region: t('editRegion'),
    expand: t('editExpand'),
    background: t('editBackground'),
    relight: t('editRelight'),
    'style-transfer': t('editStyleTransfer'),
    upscale: t('upscale'),
    camera: t('editCamera'),
    skin: t('editSkin')
  }
  const hints: Record<EditMode, string> = {
    global: t('editGlobalHint'),
    region: t('editRegionHint'),
    expand: t('editExpandHint'),
    background: t('editBackgroundHint'),
    relight: t('editRelightHint'),
    'style-transfer': t('editStyleTransferHint'),
    upscale: t('magnificUpscaleHint'),
    camera: t('editCameraHint'),
    skin: t('editSkinHint')
  }

  return (
    <div className="if-edit-surface space-y-4">
      <div className="if-mode-row" role="group" aria-label={t('edit')}>
        {MODES.map((value) => (
          <button
            key={value}
            type="button"
            aria-pressed={mode === value}
            title={hints[value]}
            className={cn('if-mode', mode === value && 'if-mode-active')}
            disabled={busy}
            onClick={() => {
              setMode(value)
              if (value !== 'global' && value !== 'relight' && value !== 'style-transfer') setFiles((current) => current.slice(0, 1))
              if (value === 'upscale' && upscaleMode !== 'precision-v2' && scale > 4) setScale(2)
              setMask('')
              setResult(null)
            }}
          >
            <Codicon name={modeLocked(value) ? 'lock' : MODE_ICON[value]} />
            <span>{labels[value]}</span>
          </button>
        ))}
      </div>
      <p className="if-mode-hint">{hints[mode]}</p>
      {locked && (
        <div className="if-access-notice" role="status">
          <Codicon name="lock" style={{ fontSize: 14 }} />
          <div>
            <p>{t('accessNeeded', { provider: MAGNIFIC_ONLY.includes(mode) ? 'Magnific' : 'FAL / Magnific' })}</p>
            {onlySubscription && <p>{t('accessSubscriptionEdit')}</p>}
          </div>
          {onOpenSettings && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={onOpenSettings}>{t('accessConfigure')}</Button>}
        </div>
      )}

      <div className="if-edit-controls">
        {(!MAGNIFIC_ONLY.includes(mode) || referenceEngines.length > 0) && <label>
          {t('provider')}
          <select value={engine} disabled={busy} onChange={(event) => setEngine(event.target.value)}>
            {!MAGNIFIC_ONLY.includes(mode) && <option value="fal" disabled={!falReady}>{falReady ? 'FAL' : `FAL · ${t('accessNone')}`}</option>}<option value="magnific" disabled={!magnificReady}>{magnificReady ? 'Magnific API' : `Magnific API · ${t('accessNone')}`}</option>
            {referenceMode && referenceEngines.map((item) => <option key={item.name} value={item.name}>{item.display_name || item.name}</option>)}
          </select>
        </label>}
        {referenceEngine && <label>
          {t('model')}
          <select value={referenceModel?.id} disabled={busy} onChange={(event) => setReferenceModel(event.target.value)}>
            {referenceModels.map((item) => <option key={item.id} value={item.id}>{item.display || item.id}</option>)}
          </select>
        </label>}
        {mode === 'global' && operationProvider === 'fal' && <label>
          {t('model')}
          <Button variant="outline" size="sm" className="h-8 justify-between gap-2 text-xs" disabled={busy} onClick={() => setCatalogOpen(true)}>
            <span className="truncate">{falEditDisplay}</span><Codicon name="chevron-down" />
          </Button>
        </label>}
        {mode === 'expand' && operationProvider === 'magnific' && <label>
          {t('model')}
          <select value={expandModel} disabled={busy} onChange={(event) => setExpandModel(event.target.value)}>
            {EXPAND_MODELS.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
          </select>
        </label>}
        {mode === 'global' && operationProvider === 'magnific' && <label>
          {t('model')}
          <select value={editModel} disabled={busy} onChange={(event) => setEditModel(event.target.value)}>
            {editModels.map((item) => <option key={item.id} value={item.id}>{item.display || item.id}</option>)}
          </select>
        </label>}
        {mode === 'global' && operationProvider === 'magnific' && !!modelInfo?.aspectRatios?.length && <label>
          {t('aspectRatio')}<select value={selectedRatio} disabled={busy} onChange={(event) => setEditRatio(event.target.value)}>
            {modelInfo.aspectRatios.map((ratio) => <option key={ratio} value={ratio}>{ratio}</option>)}
          </select>
        </label>}
        {mode === 'global' && operationProvider === 'magnific' && !!modelInfo?.resolutionOptions?.length && <label>
          {t('resolution')}<select value={selectedResolution} disabled={busy} onChange={(event) => setEditResolution(event.target.value)}>
            {modelInfo.resolutionOptions.map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </label>}
      </div>
      {mode === 'upscale' && <div className="if-edit-controls">
        {operationProvider === 'magnific' && <label>{t('model')}
          <select value={upscaleMode} disabled={busy} onChange={(event) => { setUpscaleMode(event.target.value); if (event.target.value !== 'precision-v2' && scale > 4) setScale(2) }}>
            <option value="classic">Magnific Precision</option><option value="precision-v2">Magnific Precision v2</option><option value="creative">Magnific Creative</option>
          </select>
        </label>}
        {operationProvider === 'magnific' && upscaleMode === 'precision-v2' && <>
          <label>{t('upscale')}<select value={scale} disabled={busy} onChange={(event) => setScale(Number(event.target.value))}>
            {[2, 4, 8, 16].map((value) => <option key={value} value={value}>{value}×</option>)}
          </select></label>
          <label>{t('upscaleFlavor')}<select value={flavor} disabled={busy} onChange={(event) => setFlavor(event.target.value)}>
            <option value="">{t('upscaleFlavor.auto')}</option>
            {UPSCALE_FLAVORS.map((value) => <option key={value} value={value}>{t(`upscaleFlavor.${value}`)}</option>)}
          </select></label>
        </>}
        {(operationProvider !== 'magnific' || upscaleMode === 'creative') && <>
          <label>{t('upscale')}<select value={scale} disabled={busy} onChange={(event) => setScale(Number(event.target.value))}>
            <option value={2}>2×</option><option value={4}>4×</option>
          </select></label>
          <label>{t('magnificCreativity')} {Math.round(creativity * 100)}%
            <input type="range" min={0} max={1} step={0.05} disabled={busy} value={creativity} onChange={(event) => setCreativity(Number(event.target.value))} />
          </label>
        </>}
      </div>}
      {mode !== 'region' && <div className="flex gap-2">
        <Input value={imageUrl} disabled={busy} placeholder={t('magnificImageUrl')} aria-label={t('magnificImageUrl')} onChange={(event) => setImageUrl(event.target.value)} />
        <Button variant="outline" disabled={busy || !imageUrl.trim().startsWith('https://') || files.length >= maxImages} onClick={() => {
          setFiles((current) => [...current, { id: newId(), dataUrl: imageUrl.trim(), name: 'reference' }])
          setImageUrl('')
        }}>{t('add')}</Button>
      </div>}

      {!source && (
        <label className="if-edit-dropzone">
          <Codicon name="cloud-upload" style={{ fontSize: 22 }} />
          <span>{t('pasteOrDrop')}</span>
          <input type="file" accept="image/*" disabled={busy} multiple={maxImages > 1} className="hidden" onChange={(event) => void onFiles(event.target.files)} />
        </label>
      )}

      {source && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs text-(--ui-text-tertiary)">{maxImages > 1 ? t('maxRefsDetail', { max: String(maxImages) }) : t('baseImage')}</span>
            <label className="if-inline-upload">
              {t('add')}
              <input type="file" accept="image/*" disabled={busy} multiple={maxImages > 1} className="hidden" onChange={(event) => void onFiles(event.target.files)} />
            </label>
          </div>
          {mode === 'region' ? (
            <>
              <MaskCanvas baseImage={source} brushSize={brushSize} erase={erase} apiRef={maskApi} onMaskChange={setMask} />
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <button type="button" className={cn('if-mini-toggle', !erase && 'if-mini-toggle-active')} onClick={() => setErase(false)}>{t('brush')}</button>
                <button type="button" className={cn('if-mini-toggle', erase && 'if-mini-toggle-active')} onClick={() => setErase(true)}>{t('eraser')}</button>
                <input type="range" min={8} max={120} value={brushSize} onChange={(event) => setBrushSize(Number(event.target.value))} aria-label={t('brush')} />
                <button type="button" onClick={() => maskApi.current?.clear()}>{t('clearAll')}</button>
              </div>
            </>
          ) : (
            <div className="flex flex-wrap gap-2">
              {files.map((file) => (
                <div key={file.id} className="relative h-16 w-16 overflow-hidden rounded-lg border border-(--ui-stroke-secondary)">
                  <img src={file.dataUrl} alt={file.name} className="h-full w-full object-cover" />
                  <button type="button" disabled={busy} aria-label={t('remove')} className="absolute right-0 top-0 bg-black/60 px-1 text-white" onClick={() => {
                    if (file.id === files[0].id) { setVersions([]); setActiveVersion('') }
                    setFiles(files.filter((item) => item.id !== file.id))
                  }}>
                    <Codicon name="close" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {versions.length > 1 && (
        <div ref={versionsRef} className="if-edit-versions" role="group" aria-label={t('editVersions')}>
          <span>{t('editVersions')}</span>
          {versions.map((version, index) => (
            <button key={version.id} type="button" disabled={busy} title={version.prompt || t('editOriginal')} aria-pressed={version.id === activeVersion}
              className={cn('if-edit-version', version.id === activeVersion && 'if-edit-version-active')} onClick={() => openVersion(version)}>
              <img src={version.dataUrl} alt="" />
              <small>{index ? index : t('editOriginal')}</small>
            </button>
          ))}
        </div>
      )}
      {redraws >= REDRAW_WARNING && <p role="status" className="text-xs text-(--ui-yellow)">{t('editManyRedraws', { count: String(redraws) })}</p>}

      {mode === 'global' && (
        <label className="flex items-center gap-2 text-xs" title={t('editKeepUnchangedHint')}>
          <input type="checkbox" checked={keepUnchanged} disabled={busy} className="accent-(--ui-accent)" onChange={(event) => setKeepUnchanged(event.target.checked)} />
          {t('editKeepUnchanged')}
        </label>
      )}

      {(mode === 'relight' || mode === 'style-transfer') && <div className="space-y-2">
        <p className="text-xs text-(--ui-text-tertiary)">{t('magnificReferenceOrder')}</p>
        {!referenceEngine && <label className="flex items-center gap-2 text-xs">{t('magnificStrength')} {strength}%
          <input type="range" min={0} max={100} value={strength} disabled={busy} onChange={(event) => setStrength(Number(event.target.value))} />
        </label>}
        {referenceEngine ? null : mode === 'style-transfer' ? <label className="flex items-center gap-2 text-xs">{t('magnificStructure')} {structureStrength}%
          <input type="range" min={0} max={100} value={structureStrength} disabled={busy} onChange={(event) => setStructureStrength(Number(event.target.value))} />
        </label> : <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={changeBackground} disabled={busy} onChange={(event) => setChangeBackground(event.target.checked)} />{t('magnificChangeBackground')}
        </label>}
      </div>}
      {mode === 'camera' && <div className="space-y-2">
        <label className="flex items-center gap-2 text-xs">{t('cameraHorizontal')} {horizontalAngle}°
          <input type="range" min={0} max={360} value={horizontalAngle} disabled={busy} onChange={(event) => setHorizontalAngle(Number(event.target.value))} />
        </label>
        <label className="flex items-center gap-2 text-xs">{t('cameraVertical')} {verticalAngle}°
          <input type="range" min={-30} max={90} value={verticalAngle} disabled={busy} onChange={(event) => setVerticalAngle(Number(event.target.value))} />
        </label>
        <label className="flex items-center gap-2 text-xs">{t('cameraZoom')} {zoom}
          <input type="range" min={0} max={10} value={zoom} disabled={busy} onChange={(event) => setZoom(Number(event.target.value))} />
        </label>
      </div>}
      {mode === 'skin' && !referenceEngine && <div className="space-y-2">
        <div className="if-edit-controls">
          <label>{t('skinMode')}<select value={skinMode} disabled={busy} onChange={(event) => setSkinMode(event.target.value)}>
            {['faithful', 'creative', 'flexible'].map((value) => <option key={value} value={value}>{t(`skinMode.${value}`)}</option>)}
          </select></label>
          {skinMode === 'flexible' && <label>{t('skinTarget')}<select value={optimizedFor} disabled={busy} onChange={(event) => setOptimizedFor(event.target.value)}>
            {SKIN_TARGETS.map((value) => <option key={value} value={value}>{t(`skinTarget.${value}`)}</option>)}
          </select></label>}
        </div>
        {skinMode === 'faithful' && <label className="flex items-center gap-2 text-xs">{t('skinDetail')} {skinDetail}%
          <input type="range" min={0} max={100} value={skinDetail} disabled={busy} onChange={(event) => setSkinDetail(Number(event.target.value))} />
        </label>}
        <label className="flex items-center gap-2 text-xs">{t('skinSharpen')} {sharpen}%
          <input type="range" min={0} max={100} value={sharpen} disabled={busy} onChange={(event) => setSharpen(Number(event.target.value))} />
        </label>
        <label className="flex items-center gap-2 text-xs">{t('skinGrain')} {smartGrain}%
          <input type="range" min={0} max={100} value={smartGrain} disabled={busy} onChange={(event) => setSmartGrain(Number(event.target.value))} />
        </label>
      </div>}
      {invalidImages && <p role="alert" className="text-xs text-red-500">{t('maxRefsDetail', { max: String(maxImages) })}</p>}

      {showPrompt && (
        <Textarea
          value={prompt}
          rows={3}
          placeholder={mode === 'expand' ? t('expandPrompt') : t('editPrompt')}
          onChange={(event) => setPrompt(event.target.value)}
        />
      )}

      {mode === 'expand' && (
        <div className="if-edit-controls">
          <label>
            {t('chooseAngle')}
            <select value={direction} onChange={(event) => setDirection(event.target.value)}>
              <option value="all">{t('all')}</option>
              <option value="left">{t('left')}</option>
              <option value="right">{t('right')}</option>
              <option value="top">{t('top')}</option>
              <option value="bottom">{t('bottom')}</option>
            </select>
          </label>
          <label>
            {t('expand')}
            <Input value={String(expandPx)} onChange={(event) => setExpandPx(Number(event.target.value.replace(/\D/g, '')) || 0)} />
          </label>
        </div>
      )}

      <Button
        onClick={() => void run()}
        disabled={busy || locked || !source || invalidImages || (mode === 'region' && !mask) || (promptRequired && !prompt.trim()) || (mode === 'style-transfer' && files.length < 2)}
        className="gap-2"
      >
        <span>{busy ? <Spinner /> : <Codicon name="wand" />}</span>
        {busy ? t('jobRunning') : labels[mode]}
      </Button>

      <p className="text-xs text-(--ui-text-tertiary)">{referenceEngine ? `${referenceEngine.display_name || referenceEngine.name} · ${referenceModel?.display || referenceModel?.id || ''}` : `${operationProvider === 'magnific' ? 'Magnific API' : 'FAL'} · ${mode === 'global' ? operationProvider === 'magnific' ? modelInfo?.display || editModel : falEditDisplay : labels[mode]}`}</p>
      <ModelCatalogModal
        open={catalogOpen}
        onClose={() => setCatalogOpen(false)}
        providers={[{ name: 'fal', display_name: 'FAL', available: true, configured: true,
          models: falEditModels.some((item) => item.id === FAL_DEFAULT_EDIT) ? falEditModels : [{ id: FAL_DEFAULT_EDIT, display: 'FLUX.2 Pro Edit' }, ...falEditModels] }]}
        selectedModel={falEditModel}
        onSelect={setFalEditModel}
        providerName="fal"
        onProviderChange={() => undefined}
      />
      {jobId && <JobProgress jobId={jobId} onJobReplaced={setJobId} onDismiss={() => setJobId(null)} onDone={async (job) => {
        if (job.status === 'queued' || job.status === 'running') { setJobId(job.id); return }
        if (job.status === 'completed' || job.hasPartialResult) {
          const data = await queryJobResult(job.id)
          setResult(data.result)
          invalidateGallery()
          await addVersion(data.result)
        }
        setJobId(null)
      }} />}
      {result?.warnings?.map((warning) => <p key={warning} role="status" className="text-xs text-(--ui-yellow)">{warning}</p>)}
      {mergeNote && <p role="status" className="text-xs text-(--ui-text-tertiary)">{mergeNote}</p>}
      {error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-2 text-xs text-red-500">{error}</div>}

      {shownImages.length ? (
        <div className="if-edit-result">
          <ResultGrid
            images={shownImages}
            onDownload={(image) => downloadFromUrl(image, `imagegen-edit-${Date.now()}.png`)}
          />
        </div>
      ) : null}
    </div>
  )
}
