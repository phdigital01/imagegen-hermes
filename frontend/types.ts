/**
 * ImageGen — shared types.
 * Part of the bundled migration (TSX, official format).
 */

/** Clean zones: which areas of the image must stay free of text. */
interface CleanZones {
  enabled: boolean
  zones: string[]
  intensity: string
  tone: string
}

/** Global direction settings (style, lighting, camera). */
interface GlobalDirection {
  style: string
  lighting: string[]
  angle: string
  lens: string
  aperture: string
  useReferenceAngle: boolean
  fidelityMode: string
}

/** A reference image with semantic role and fidelity. */
export interface ReferenceImage {
  id: string
  label: string
  semanticRole: string
  authorityLevel: string
  roleConfirmed: boolean
  fidelity: number
  fixedProduct: boolean
  purposes: string[]
  keep: string[]
  vary: string[]
  granularWeights: Record<string, number>
  userNotes: string
  instructions: string
  inputMode: string
  isAnalyzing: boolean
  analysisResult: unknown
  origin: string
  imageDataUrl?: string
  localPath?: string
  url?: string
  thumb?: string
  passport?: string
  subjectId?: string
  kind?: string
}

/** Composition intent from the vision analysis — 2-step confirm gate. */
interface CompositionIntent {
  status: 'preview' | 'confirmed' | string
  userIntent: string
  suggestedPrompt?: string
  brief?: string
  genre?: string
  deep?: boolean
  /** Snapshot of refs at analysis time for stale detection. */
  snapshotRefsHash?: string
  /** Snapshot of description at analysis time for stale detection. */
  snapshotDescription?: string
  confirmedAt?: number
}

/** The full generation config, persisted in storage. */
export interface ImageGenConfig {
  /** New density control. `creationMode` is retained for persisted payload compatibility. */
  densityMode: DensityMode
  creationMode?: string
  subjectType: string
  description: string
  structuredFields: Record<string, string | string[]>
  globalDirection: GlobalDirection
  optimizeOnGenerate?: boolean
  manualFormat?: boolean
  directionVersion?: number
  subjectDistance: string
  aspectRatio: string
  qualityLevel: string
  mood: string
  negativePrompt: string
  referencesV4: ReferenceImage[]
  cleanZones: CleanZones
  outputGoal: string
  selectedModel: string
  resolution: string
  compositionIntent: CompositionIntent | null
  provider?: string
  genre?: string
  deepAnalyze?: boolean
  saveToGallery?: boolean
  qualityTier?: QualityTier
  numImages?: number
  seed?: number | string
  colorAccentsEnabled?: boolean
  colorAccents?: string[]
}

export type DensityMode = 'simple' | 'creative' | 'studio'
type QualityTier = 'draft' | 'standard' | 'max'

export type EditMode = 'global' | 'region' | 'expand' | 'background' | 'relight' | 'style-transfer' | 'upscale' | 'camera' | 'skin'

export interface RefineFeedbackRequest {
  image: string
  prompt: string
  feedback: string
  provider?: string
  model?: string
  aspectRatio?: string
}

export interface RefineFeedbackResponse {
  autoGenerate: false
  diagnosis: string
  newPrompt: string
  before?: string
  after?: string
  suggestions?: string[]
}

/** A generation job result. */
export interface JobResult {
  warnings?: string[]
  id?: string
  images: string[]
  gallery_ids?: string[]
  prompt?: string
  provider?: string
  model?: string
  [key: string]: unknown
}

/** A single job status. */
export interface JobStatus {
  id: string
  kind: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'interrupted' | 'recovering'
  progress?: number
  message?: string
  elapsed?: number
  recoverable?: boolean
  retryable?: boolean
  hasPartialResult?: boolean
  result?: JobResult
  error?: string
  /** Stable backend error code; maps to an i18n key (e.g. 'refs.too_many'). */
  errorCode?: string
  /** Interpolation values for the localized error message. */
  errorParams?: Record<string, string | number>
  /** Provider checkpoint; present when the job can be resumed after a restart. */
  remote?: {
    provider: string
    model: string
    requestId: string
    endpoint: string
  }
}

/**
 * Unified feed item — the single read model over the two stores (history
 * entries and standalone gallery entries). `GET /feed` joins them so the UI
 * has one surface instead of the redundant History/Gallery pair.
 */
export type FeedSource = 'generated' | 'saved'

export interface FeedImage {
  url: string
  galleryId?: string | null
  localPath?: string | null
}

export interface FeedItem {
  id: string
  source: FeedSource
  ts: number
  prompt: string
  provider: string
  model: string
  kind: string
  images: FeedImage[]
  config: Partial<ImageGenConfig>
  historyId?: string | null
  galleryIds: string[]
}

interface FeedStats {
  total: number
  saved: number
  generated: number
  bytes: number
  providers?: string[]
}

export interface FeedResponse {
  items: FeedItem[]
  stats: FeedStats
}

export type FeedSort = 'newest' | 'oldest' | 'prompt_az'

/** Query parameters accepted by `GET /feed`. */
export interface FeedParams {
  source?: 'all' | FeedSource
  provider?: string
  q?: string
  limit?: number
  sort?: FeedSort
}

/** A library (recipe) entry. */
export interface LibraryEntry {
  id: string
  name: string
  prompt: string
  config: Record<string, unknown>
  refs: ReferenceImage[]
  genre?: string
  negativePrompt?: string
  ts: number
}

/** A library object (product photo with passport). Kept stable for the legacy object API. */
export interface LibraryObject {
  id: string
  name: string
  file: string
  passport?: string
  localPath?: string
  thumb?: string
  url?: string
}

/** Subject kinds are intentionally open strings: presets are suggestions, not a closed enum. */
export type SubjectKind = string

/** A Subject Library entry. Backend additions are optional so old /objects entries remain valid. */
export interface SubjectLibraryEntry extends LibraryObject {
  kind?: SubjectKind
  slug?: string
  angles?: Array<{
    id?: string
    label?: string
    angle?: string
    file?: string
    imageDataUrl?: string
    localPath?: string
    thumb?: string
    url?: string
  }>
  variants?: Array<{
    id?: string
    label?: string
    angle?: string
    file?: string
    imageDataUrl?: string
    localPath?: string
    thumb?: string
    url?: string
  }>
}

/** A provider model with capabilities. */
export interface ProviderModel {
  id: string
  display?: string
  price?: string
  speed?: string
  strengths?: string
  resolutionOptions?: string[]
  aspectRatios?: string[]
  supportsSeed?: boolean
  referenceInput?: 'base64' | 'public-url'
  /** Listed from FAL's public catalog; exact controls come from /providers/fal/model. */
  catalog?: boolean
  capabilities?: {
    negativePromptMode?: string
    negativeMode?: string
    referenceImages?: boolean
    maxReferences?: number
    edit?: boolean
    inpaint?: boolean
    outpaint?: boolean
    bgRemove?: boolean
    vary?: boolean
    upscale?: boolean
    animate?: boolean
    strengthTags?: string[]
    resolutions?: string[]
  }
}

/** A provider. */
export interface Provider {
  name: string
  models: ProviderModel[]
  /** Image-to-image models for the Edit tab (FAL catalog). */
  edit_models?: ProviderModel[]
  display_name?: string
  available?: boolean
  configured?: boolean
  /** Model a new user starts with on this provider. */
  default_model?: string
  /** The provider a new user starts with: Hermes' image provider, else the first one they can use. */
  recommended?: boolean
}

export interface ProviderStatus {
  name: string
  display_name?: string
  configured: boolean
  available: boolean
}

export interface OutputFolderSettings {
  path: string
  exists: boolean
  writable: boolean
}

/** Monthly spend limit and the amount already spent this month. */
export interface BudgetStatus {
  monthlyLimit: number | null
  spentThisMonth: number
  currency: string
}

/** The presets payload from the backend. */
export interface Presets {
  styles: string[]
  lighting: string[]
  angles: string[]
  distances: Array<{ value: string; label: string; prompt_phrase: string }>
  cameras?: Array<{ value: string; label: string; prompt_phrase: string }>
  lenses: string[]
  apertures: string[]
  moods: string[]
  subjectTypes: string[]
  aspectRatios: string[]
  qualityLevels: string[]
  resolutions: string[]
  platforms: string[]
  recipes: string[]
  semantic_roles?: Array<{ value: string; label: string; description?: string; fidelity?: number }>
  keep_vary?: string[]
  structured_fields?: Record<string, Array<{ key: string; label: string; placeholder?: string; type?: string; options?: string[] }>>
  subject_types?: Array<{ value: string; label: string }>
  aspect_ratios?: Array<{ value: string; hint?: string }>
  platform_presets?: Record<string, { label: string; aspect_ratio: string }>
  default_negatives?: Record<string, string>
  generic_negative?: string
  style_descriptions?: Record<string, string>
}
