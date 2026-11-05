/**
 * ImageGen — data layer.
 * All calls go through ctx.rest to the plugin backend namespace
 * `/api/plugins/imagegen/*`. Uses React Query for caching and polling.
 */

import { queryClient, type PluginOs, type PluginRestOptions, type PluginStorage } from '@hermes/plugin-sdk'
import { translateActive } from './i18n'

export { queryClient }

import type {
  FeedParams,
  FeedResponse,
  JobResult,
  JobStatus,
  LibraryEntry,
  ReferenceImage,
  SubjectLibraryEntry,
  Presets,
  OutputFolderSettings,
  BudgetStatus,
  Provider,
  ProviderModel,
  ProviderStatus,
  RefineFeedbackRequest,
  RefineFeedbackResponse
} from './types'

export const ID = 'imagegen'

/** Cache key prefix for all ImageGen queries. */
const QK = [ID]

/** Accept legacy tool payloads while keeping text controls strictly strings. */
export function promptText(value: unknown): string {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object' && 'prompt' in value) {
    return typeof value.prompt === 'string' ? value.prompt : ''
  }
  return ''
}

/** Bridge to the plugin's Python backend. */
let restFn: ((path: string, opts?: PluginRestOptions) => Promise<unknown>) | null = null

/** Namespaced storage for the plugin. */
let storage: PluginStorage | null = null

/** OS capabilities of the Desktop SDK (reveal in the file manager). */
let os: PluginOs | null = null

/** Bind the ctx.rest, ctx.storage and ctx.os handles at plugin register time. */
export function bindApi(
  rest: (path: string, opts?: PluginRestOptions) => Promise<unknown>,
  store: PluginStorage,
  osHandle: PluginOs
): void {
  restFn = rest
  storage = store
  os = osHandle
}

/** Show a file in Explorer / Finder; false when the shell cannot. */
export async function revealPath(path: string): Promise<boolean> {
  if (!os) return false
  try {
    return Boolean(await os.revealPath(path))
  } catch {
    return false
  }
}

/** A backend failure that carried a stable code; `message` is already localized. */
export class ImageGenApiError extends Error {
  constructor(message: string, readonly code: string, readonly params: Record<string, unknown>) {
    super(message)
    this.name = 'ImageGenApiError'
  }
}

function toImageGenError(code: string, message: string, rawParams: Record<string, unknown>): ImageGenApiError {
  const args: Record<string, string> = {}
  for (const [key, value] of Object.entries(rawParams || {})) args[key] = String(value)
  const localized = translateActive(code, args)
  const fallback = message || code
  return new ImageGenApiError(localized === code ? fallback : localized, code, { ...rawParams })
}

function localizeRestFailure(error: unknown): unknown {
  if (typeof error === 'object' && error !== null) {
    const obj = error as Record<string, unknown>
    const direct = (obj.error as Record<string, unknown>) || null
    if (direct && typeof direct.code === 'string' && direct.code) {
      const rawParams = (direct.params && typeof direct.params === 'object' ? direct.params : {}) as Record<string, unknown>
      const message = typeof direct.message === 'string' ? direct.message : String(error)
      return toImageGenError(direct.code, message, rawParams)
    }
    if (obj.ok === false && obj.error && typeof obj.error === 'object') {
      const info2 = obj.error as Record<string, unknown>
      if (typeof info2.code === 'string' && info2.code) {
        const rawParams = (info2.params && typeof info2.params === 'object' ? info2.params : {}) as Record<string, unknown>
        const message = typeof info2.message === 'string' ? info2.message : String(error)
        return toImageGenError(info2.code, message, rawParams)
      }
    }
    if (typeof obj.code === 'string' && obj.code && obj.code.includes('.')) {
      const rawParams = (obj.params && typeof obj.params === 'object' ? obj.params : {}) as Record<string, unknown>
      const message = typeof obj.message === 'string' ? obj.message : String(error)
      return toImageGenError(obj.code, message, rawParams)
    }
  }
  const raw = error instanceof Error ? error.message : String(error)
  const start = raw.indexOf('{')
  if (start < 0) return error
  let parsed: unknown
  try {
    parsed = JSON.parse(raw.slice(start))
  } catch {
    return error
  }
  if (typeof parsed !== 'object' || parsed === null || !('error' in parsed)) return error
  const info = (parsed as Record<string, unknown>).error
  if (typeof info !== 'object' || info === null || !('code' in info)) return error
  const code = (info as Record<string, unknown>).code
  if (typeof code !== 'string' || !code) return error
  const rawParams = 'params' in (info as Record<string, unknown>) && typeof (info as Record<string, unknown>).params === 'object' && (info as Record<string, unknown>).params !== null ? ((info as Record<string, unknown>).params as Record<string, unknown>) : {}
  const message = 'message' in (info as Record<string, unknown>) && typeof (info as Record<string, unknown>).message === 'string' ? ((info as Record<string, unknown>).message as string) : raw
  return toImageGenError(code, message, rawParams)
}

/** REST call to the plugin backend. Throws on non-OK response. */
export function rest<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  if (!restFn) {
    return Promise.reject(new Error('ImageGen backend not bound'))
  }
  return (restFn(path, { method, body }) as Promise<T>).catch((error: unknown) => {
    throw localizeRestFailure(error)
  })
}

/** Persisted key-value store (survives reloads). */
export function getStored<T>(key: string, fallback: T): T {
  if (!storage) return fallback
  try {
    const v = storage.get(key, undefined)
    return v === undefined ? fallback : (v as T)
  } catch {
    return fallback
  }
}

export function setStored(key: string, value: unknown): void {
  try {
    storage?.set(key, value)
  } catch {
    /* ignore storage errors */
  }
}

// ---------------------------------------------------------------------------
// Data fetchers (for useQuery)
// ---------------------------------------------------------------------------

export function fetchPresets(): Promise<Presets> {
  return rest<Presets>('/presets')
}

export function fetchProviders(): Promise<Provider[]> {
  return rest<{ providers: Provider[] }>('/providers').then((d) => d.providers)
}

/** Exact controls of one FAL catalog model, read from its schema on first use. */
export function fetchFalModel(id: string): Promise<ProviderModel> {
  return rest<ProviderModel>(`/providers/fal/model?id=${encodeURIComponent(id)}`)
}

/** Magnific prompt helpers: describe an image as a prompt, or improve a written one. */
export function promptHelper(body: { action: 'describe'; image: string } | { action: 'improve'; prompt: string; language?: string }): Promise<{ text: string }> {
  return rest<{ text: string }>('/prompt-helper', 'POST', body)
}

export function fetchProviderStatus(): Promise<ProviderStatus[]> {
  return rest<{ providers: ProviderStatus[] }>('/providers/status').then((d) => d.providers || [])
}

export function fetchOutputFolder(): Promise<OutputFolderSettings> {
  return rest<OutputFolderSettings>('/settings/output-folder')
}

export function saveOutputFolder(path: string): Promise<OutputFolderSettings> {
  return rest<OutputFolderSettings>('/settings/output-folder', 'POST', { path })
}

export function fetchBudget(): Promise<BudgetStatus> {
  return rest<BudgetStatus>('/settings/budget')
}

export function saveBudget(monthlyLimit: number | null): Promise<BudgetStatus> {
  return rest<BudgetStatus>('/settings/budget', 'POST', { monthlyLimit })
}

export function fetchFeedStats(): Promise<{ stats: { total: number; saved: number; generated: number; bytes: number; providers: string[] }; providers: string[] }> {
  return rest<{ stats: { total: number; saved: number; generated: number; bytes: number; providers: string[] }; providers: string[] }>('/feed/stats')
    .catch(() => ({ stats: { total: 0, saved: 0, generated: 0, bytes: 0, providers: [] }, providers: [] }))
}

/**
 * Unified feed — the single read model joining generated (history) and saved
 * (gallery-only) entries. Replaces the redundant /history + /gallery pair in
 * the UI; both routes stay available for the agent bridge.
 */
export function fetchFeed(params: FeedParams = {}): Promise<FeedResponse> {
  const query = new URLSearchParams()
  if (params.source && params.source !== 'all') query.set('source', params.source)
  if (params.provider) query.set('provider', params.provider)
  if (params.q) query.set('q', params.q)
  if (params.limit) query.set('limit', String(params.limit))
  if (params.sort) query.set('sort', params.sort)
  const suffix = query.size ? `?${query.toString()}` : ''
  return rest<FeedResponse>(`/feed${suffix}`).then((data) => ({
    items: data.items || [],
    stats: data.stats || { total: 0, saved: 0, generated: 0, bytes: 0, providers: [] }
  }))
}

/** Cascade delete: drops the history entry and every gallery file it owns. */
export function deleteFeedEntry(id: string): Promise<{ ok: boolean }> {
  return rest<{ ok: boolean }>(`/feed/${encodeURIComponent(id)}`, 'DELETE')
}

export function fetchLibrary(): Promise<LibraryEntry[]> {
  return rest<{ entries: LibraryEntry[] }>('/library').then((d) => d.entries || [])
}

/** Subject Library prefers /subjects, falls back to /objects. */
export function fetchSubjectLibrary(): Promise<SubjectLibraryEntry[]> {
  return rest<{ subjects?: SubjectLibraryEntry[]; objects?: SubjectLibraryEntry[] } | SubjectLibraryEntry[]>('/subjects')
    .catch(() => rest<{ subjects?: SubjectLibraryEntry[]; objects?: SubjectLibraryEntry[] } | SubjectLibraryEntry[]>('/objects'))
    .then((payload) => {
      if (Array.isArray(payload)) return payload
      return payload.subjects || payload.objects || []
    })
}

export function fetchJob(jobId: string): Promise<JobStatus> {
  return rest<JobStatus>(`/jobs/${jobId}`)
}

export function fetchJobs(): Promise<JobStatus[]> {
  return rest<{ jobs?: JobStatus[] } | JobStatus[]>('/jobs').then((payload) => Array.isArray(payload) ? payload : (payload.jobs || []))
}

export function invalidateGallery(): void {
  queryClient.invalidateQueries({ queryKey: [...QK, 'gallery'] })
}

/** Invalidate the unified feed after any mutation that changes stored images. */
export function invalidateFeed(): void {
  queryClient.invalidateQueries({ queryKey: [...QK, 'feed'] })
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

export function submitJob(payload: Record<string, unknown>): Promise<{ id: string }> {
  return rest<{ id: string }>('/jobs/submit', 'POST', payload)
}

export function cancelJob(jobId: string): Promise<{ ok: boolean }> {
  return rest<{ ok: boolean }>(`/jobs/${jobId}/cancel`, 'POST').catch(() => ({ ok: false }))
}

export function retryJob(jobId: string): Promise<{ id: string }> {
  return rest<{ id: string }>(`/jobs/${jobId}/retry`, 'POST')
}

/** Re-fetch the remote result of an interrupted job after a restart. */
export function resumeJob(jobId: string): Promise<{ ok: boolean; result?: JobResult }> {
  return rest<{ ok: boolean; result?: JobResult }>(`/jobs/${jobId}/resume`, 'POST')
}

function objectAsRef(id: string): Promise<ReferenceImage> {
  return rest<ReferenceImage>(`/objects/${id}/as-ref`, 'POST')
}

export function subjectAsRefs(id: string, maxRefs = 4): Promise<{ refs: ReferenceImage[] }> {
  return rest<{ refs: ReferenceImage[] }>(`/subjects/${id}/as-refs`, 'POST', { maxRefs }).catch(async () => {
    const primary = await objectAsRef(id)
    return { refs: [primary] }
  })
}

export function importObjects(folder: string, kind = 'object'): Promise<{ id: string }> {
  return rest<{ id: string }>('/objects/import', 'POST', { folder, kind })
}

export function queryJobResult(jobId: string): Promise<JobStatus & { result: JobResult }> {
  return rest<JobStatus & { result: JobResult }>(`/jobs/${jobId}/result`)
}

export function refineFromFeedback(request: RefineFeedbackRequest): Promise<RefineFeedbackResponse> {
  return rest<RefineFeedbackResponse>('/refine-from-feedback', 'POST', request)
}

/** File on disk behind one of our served image URLs (the agent opens it by path). */
export function fetchLocalImagePath(url: string): Promise<string> {
  return rest<{ path: string }>(`/media/local-path?url=${encodeURIComponent(url)}`).then((d) => d.path)
}

/** One of our served images as a data URL (plugin URLs need the Desktop's credentials). */
export function isPluginImageUrl(value: string): boolean {
  if (value.startsWith('/api/plugins/imagegen/')) return true
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) &&
      // `plugin-host` is the base URL Hermes gives a secondary profile's plugin host.
      ['localhost', '127.0.0.1', '[::1]', 'plugin-host'].includes(url.hostname) &&
      url.pathname.startsWith('/api/plugins/imagegen/')
  } catch {
    return false
  }
}

export function fetchImageDataUrl(url: string): Promise<string> {
  return rest<{ dataUrl: string }>(`/media/data-url?url=${encodeURIComponent(url)}`).then((d) => d.dataUrl)
}

export function exportGalleryPack(id: string): Promise<{ url?: string; path?: string; ok?: boolean }> {
  return rest<{ url?: string; path?: string; ok?: boolean }>(`/gallery/${id}/export-pack`)
}

export function exportFeedZip(ids: string[]): Promise<{ url?: string; path?: string; filename?: string }> {
  return rest<{ url?: string; path?: string; filename?: string }>('/feed/export-zip', 'POST', { ids })
}

export function clearPluginData(options: { gallery?: boolean; handoffs?: boolean; subjects?: boolean }): Promise<{ ok: boolean; deleted: Record<string, number> }> {
  return rest<{ ok: boolean; deleted: Record<string, number> }>('/settings/clear-data', 'POST', { ...options, confirm: 'CLEAR' })
}

const SESSION_PROMPTS_KEY = 'session-prompts'

export function loadSessionPrompts(): string[] {
  const value = getStored<string[]>(SESSION_PROMPTS_KEY, [])
  return Array.isArray(value) ? value.filter((item) => typeof item === 'string' && item.trim()) : []
}

export function pushSessionPrompt(prompt: string): string[] {
  const cleaned = prompt.trim()
  if (!cleaned) return loadSessionPrompts()
  const next = [cleaned, ...loadSessionPrompts().filter((item) => item !== cleaned)].slice(0, 15)
  setStored(SESSION_PROMPTS_KEY, next)
  return next
}
