/**
 * ImageGen — static presets and generation helpers.
 *
 * The backend keeps the source of truth for catalog values. These helpers
 * normalize old and new payload shapes so the bundled UI stays compatible.
 */

import type { DensityMode, ImageGenConfig, Presets, ProviderModel, ReferenceImage } from './types'
import { rest } from './api'
import { translateActive } from './i18n'

export const SUBJECT_ICONS: Record<string, string> = {
  livre: 'Starmap',
  pessoa: 'Users',
  objeto_produto: 'Package',
  food: 'Egg',
  moda: 'Palette',
  animal: 'PawPrint',
  ambiente_arquitetura: 'AppWindow',
  veiculo: 'SteeringWheel',
  abstrato: 'Palette',
  paisagem: 'Globe'
}

export const SUBJECT_FILES: Record<string, string> = {
  livre: 'subject-story',
  pessoa: 'subject-person',
  objeto_produto: 'subject-product',
  food: 'subject-food',
  animal: 'subject-animal',
  ambiente_arquitetura: 'subject-architecture',
  veiculo: 'subject-veiculo',
  abstrato: 'subject-abstrato',
  moda: 'subject-moda',
  paisagem: 'subject-landscape'
}

export const DEFAULT_CONFIG: ImageGenConfig = {
  densityMode: 'simple',
  creationMode: 'quick',
  subjectType: '',
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
  cleanZones: { enabled: false, zones: [], intensity: 'Fully clean', tone: 'Automatic' },
  outputGoal: 'generate',
  selectedModel: '',
  resolution: '1K',
  compositionIntent: null,
  provider: 'fal',
  genre: '',
  deepAnalyze: false
}

/** Migrate old persisted configs without changing their original meaning. */
export function migrateConfig(value: Partial<ImageGenConfig> | null | undefined): ImageGenConfig {
  const legacy = value?.creationMode
  const rawMode = value?.densityMode || (legacy === 'advanced' ? 'studio' : 'simple')
  // 'creative' was an early density tier; it maps to the studio surface.
  const densityMode: DensityMode = rawMode === 'creative' ? 'studio' : rawMode
  return { ...DEFAULT_CONFIG, ...(value || {}), densityMode, creationMode: legacy }
}

// `label` is a dictionary key; 'Story' reads the same in every UI language.
export const QUICK_RECIPES = [
  { subject: 'objeto_produto', label: 'product', ratio: '4:5' },
  { subject: 'pessoa', label: 'person', ratio: '4:5' },
  { subject: 'food', label: 'food', ratio: '4:5' },
  { subject: 'ambiente_arquitetura', label: 'architecture', ratio: '16:9' },
  { subject: 'livre', label: 'Story', ratio: '9:16' },
  { subject: 'paisagem', label: 'landscape', ratio: '16:9' }
] as const

export interface PresetOption {
  value: string
  label: string
  hint?: string
  description?: string
}

export function subjectOptions(presets: Presets | null): PresetOption[] {
  if (presets?.subject_types?.length) return presets.subject_types
  return presets?.subjectTypes?.map((value) => ({ value, label: value })) || []
}

export function aspectOptions(presets: Presets | null): PresetOption[] {
  if (presets?.aspect_ratios?.length) return presets.aspect_ratios.map((item) => ({ ...item, label: item.value }))
  return presets?.aspectRatios?.map((value) => ({ value, label: value })) || []
}

export function fieldOptions(presets: Presets | null, subjectType: string) {
  return presets?.structured_fields?.[subjectType] || []
}

export function referenceMeta(ref: ReferenceImage): Record<string, unknown> {
  const { imageDataUrl, ...meta } = ref
  return { ...meta, hasImage: !!(imageDataUrl || ref.localPath || ref.url) }
}

/**
 * Serialization-safe reference list for POST bodies. Drops image data URLs
 * (multi-MB base64) because ctx.rest structuredClones the body on the renderer
 * main thread — embedding blobs froze the UI. Keeps localPath (small string).
 */
export function refsToMeta(refs: ReferenceImage[]): Array<Record<string, unknown>> {
  return (refs || []).map((ref) => {
    const { imageDataUrl, ...meta } = ref
    return { ...meta, hasImage: !!(imageDataUrl || ref.localPath || ref.url) }
  })
}

export function configForPrompt(config: ImageGenConfig, extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    ...config,
    ...extra,
    referencesV4: (config.referencesV4 || []).map(referenceMeta)
  }
}

export function configForHistory(config: ImageGenConfig): Record<string, unknown> {
  return {
    ...config,
    // Keep the references so "use config" restores them too. refsToMeta
    // strips imageDataUrl (multi-MB base64 would bloat the stored snapshot)
    // while keeping the safe metadata: id, label, localPath, url, thumb, ...
    referencesV4: refsToMeta(config.referencesV4 || [])
  }
}

export async function persistReferenceImage(image: string, label = 'reference.png'): Promise<{ imageDataUrl: string; localPath: string }> {
  if (!image) throw new Error('Reference image is empty')
  const localUrl =
    image.startsWith('data:') ||
    image.startsWith('file:') ||
    image.startsWith('blob:') ||
    image.startsWith('/api/') ||
    /https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//i.test(image)
  if (!localUrl) return { imageDataUrl: image, localPath: '' }
  const dataUrl = image.startsWith('data:') ? image : await urlToDataUrl(image)
  if (!dataUrl.startsWith('data:')) throw new Error('Could not prepare the reference image')
  const uploaded = await rest<{ url?: string; path?: string }>('/upload', 'POST', { image: dataUrl, name: label })
  return { imageDataUrl: uploaded.url || image, localPath: uploaded.path || '' }
}

/** Per-session cache of uploads keyed by image content, so repeated
 *  generations never re-upload (and re-duplicate) the same reference. */
const persistedReferenceCache = new Map<string, { imageDataUrl: string; localPath: string }>()

export async function prepareReferences(refs: ReferenceImage[]): Promise<{
  ready: ReferenceImage[]
  sources: string[]
  changed: boolean
}> {
  const ready: ReferenceImage[] = []
  const sources: string[] = []
  let changed = false
  for (const ref of refs || []) {
    let next = ref
    // A reference that already reached the backend (localPath or url set)
    // stays as-is; only bare data URLs need uploading, once per content.
    if (!ref.localPath && !ref.url && ref.imageDataUrl) {
      let persisted = persistedReferenceCache.get(ref.imageDataUrl)
      if (!persisted) {
        persisted = await persistReferenceImage(ref.imageDataUrl, `${ref.label || 'reference'}.png`)
        persistedReferenceCache.set(ref.imageDataUrl, persisted)
      }
      next = { ...ref, ...persisted }
      changed = changed || next.localPath !== ref.localPath || next.imageDataUrl !== ref.imageDataUrl
    }
    ready.push(next)
    const source = next.localPath || next.url || next.imageDataUrl
    if (source) sources.push(source)
  }
  return { ready, sources, changed }
}

export function deriveQuickDefaults(subjectType: string, description: string) {
  const desc = (description || '').toLowerCase()
  const photo = {
    style: 'Fotorrealista',
    lighting: ['Natural'],
    angle: 'Eye Level',
    lens: '50mm',
    aperture: 'f/5.6',
    subjectDistance: ''
  }
  const bySubject: Record<string, typeof photo> = {
    objeto_produto: { style: 'Fotorrealista', lighting: ['Studio Softbox'], angle: 'Frontal', lens: '50mm', aperture: 'f/5.6', subjectDistance: 'closeup' },
    food: { style: 'Fotorrealista', lighting: ['Natural'], angle: '3/4', lens: '105mm macro', aperture: 'f/2.8', subjectDistance: 'closeup' },
    pessoa: { style: 'Fotorrealista', lighting: ['Natural'], angle: 'Eye Level', lens: '85mm', aperture: 'f/2.8', subjectDistance: 'portrait' },
    moda: { style: 'Cinematográfico', lighting: ['Dramatic'], angle: '3/4', lens: '85mm', aperture: 'f/2.8', subjectDistance: 'full' },
    animal: { style: 'Fotorrealista', lighting: ['Natural'], angle: 'Eye Level', lens: '85mm', aperture: 'f/2.8', subjectDistance: 'portrait' },
    ambiente_arquitetura: { style: 'Fotorrealista', lighting: ['Natural'], angle: 'Eye Level', lens: '24mm', aperture: 'f/11', subjectDistance: 'wide' },
    veiculo: { style: 'Cinematográfico', lighting: ['Dramatic', 'Rim Light'], angle: '3/4', lens: '35mm', aperture: 'f/5.6', subjectDistance: 'american' },
    abstrato: { style: 'Ilustração Digital', lighting: ['Volumetric'], angle: 'Frontal', lens: '', aperture: '', subjectDistance: '' },
    paisagem: { style: 'Fotorrealista', lighting: ['Golden Hour'], angle: 'Eye Level', lens: '24mm', aperture: 'f/11', subjectDistance: 'wide' }
  }
  if (/minimal|clean|branco|white/.test(desc)) return { ...photo, style: 'Minimalista', lighting: ['High Key'], angle: 'Frontal', lens: '', aperture: '', subjectDistance: '' }
  if (/cinem|filme|dramat|neon|noir/.test(desc)) return { ...photo, style: 'Cinematográfico', lighting: ['Dramatic'], angle: 'Low Angle', lens: '35mm', aperture: 'f/2.8', subjectDistance: 'portrait' }
  if (/anime|manga|cartoon/.test(desc)) return { ...photo, style: 'Anime', lighting: ['Natural'], angle: 'Frontal', lens: '', aperture: '', subjectDistance: '' }
  if (/pixel|retro|8.?bit/.test(desc)) return { ...photo, style: 'Pixel Art', lighting: ['Natural'], angle: 'Frontal', lens: '', aperture: '', subjectDistance: '' }
  if (/aquarela|watercolor/.test(desc)) return { ...photo, style: 'Aquarela', lighting: ['Natural'], angle: 'Frontal', lens: '', aperture: '', subjectDistance: '' }
  if (/3d|render|isometric/.test(desc)) return { ...photo, style: '3D Render', lighting: ['Studio Softbox'], angle: 'Frontal', lens: '', aperture: '', subjectDistance: '' }
  if (/luxo|luxury|gold|ouro|premium/.test(desc)) return { ...photo, style: 'Luxo', lighting: ['Dramatic', 'Rim Light'], angle: '3/4', lens: '85mm', aperture: 'f/2.8', subjectDistance: 'closeup' }
  if (/flat|vetor|vector|ilustra/.test(desc)) return { ...photo, style: 'Flat/Vetor', lighting: ['Natural'], angle: 'Frontal', lens: '', aperture: '', subjectDistance: '' }
  return bySubject[subjectType] || photo
}

export interface AlertItem {
  id: string
  type: 'blocking' | 'warning'
  message: string
}

export function computeAlerts(config: ImageGenConfig, modelInfo?: ProviderModel): { blocking: AlertItem[]; warnings: AlertItem[] } {
  // The provider mirrors the resolved UI language, so the pure helper matches
  // it without changing its signature.
  const t = translateActive
  const blocking: AlertItem[] = []
  const warnings: AlertItem[] = []
  const hasDescription = (config.description || '').trim().length > 0
  const intent = config.compositionIntent
  const hasIntent = (intent?.userIntent || '').trim().length > 0
  const hasConfirmed = intent?.status === 'confirmed' && !!intent.suggestedPrompt
  if (!hasDescription && !hasIntent && !hasConfirmed) {
    blocking.push({ id: 'no-description', type: 'blocking', message: t('describeToGenerate') })
  }
  const refs = config.referencesV4 || []
  const hasFixed = refs.some((ref) => ref.fixedProduct)
  const hasProductImage = refs.some((ref) => ref.fixedProduct && (ref.imageDataUrl || ref.localPath || ref.url))
  if (hasFixed && !hasProductImage) {
    blocking.push({ id: 'fixed-no-image', type: 'blocking', message: t('fixedNoImage') })
  }
  const hasReferenceImages = refs.some((ref) => ref.imageDataUrl || ref.localPath || ref.url)
  if (hasReferenceImages && !hasIntent && !hasDescription) {
    blocking.push({ id: 'refs-without-intent', type: 'blocking', message: t('refsWithoutIntent') })
  }
  const capabilities = modelInfo?.capabilities || {}
  if (capabilities.referenceImages === false && refs.length > 0) {
    blocking.push({ id: 'model-no-references', type: 'blocking', message: t('modelNoRefs') })
  }
  if (capabilities.maxReferences && refs.length > capabilities.maxReferences) {
    blocking.push({ id: 'refs-above-limit', type: 'blocking', message: t('maxRefsDetail', { max: String(capabilities.maxReferences) }) })
  }
  if (capabilities.negativeMode === 'unsupported' && config.negativePrompt) {
    warnings.push({ id: 'negative-prompt-ignored', type: 'warning', message: t('negativePromptIgnored') })
  }
  if (refs.filter((ref) => ref.semanticRole === 'object_primary').length > 1) {
    warnings.push({ id: 'multiple-primary-objects', type: 'warning', message: t('multiplePrimary') })
  }
  const emptyRefs = refs.filter((ref) => !ref.imageDataUrl && !ref.localPath && !ref.url && !(ref.instructions || '').trim())
  if (emptyRefs.length > 0) {
    warnings.push({ id: 'empty-refs', type: 'warning', message: `${emptyRefs.length} ${t('emptyRefs')}` })
  }
  return { blocking, warnings }
}

async function urlToDataUrl(url: string): Promise<string> {
  try {
    const response = await fetch(url)
    if (!response.ok) return url
    const blob = await response.blob()
    return await new Promise<string>((resolve) => {
      const reader = new FileReader()
      reader.onload = () => resolve(reader.result as string)
      reader.onerror = () => resolve(url)
      reader.readAsDataURL(blob)
    })
  } catch {
    return url
  }
}

export function slugThumb(value: string): string {
  const key = (value || '').toLowerCase().trim()
  const overrides: Record<string, string> = {
    "worm's eye": 'worm-s-eye',
    'pixel art': 'style-pixel-art',
    'pintura a óleo': 'style-pintura-a-oleo',
    'pintura a oleo': 'style-pintura-a-oleo'
  }
  if (overrides[key]) return overrides[key]
  return key.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

