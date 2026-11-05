/**
 * ImageGen — desktop page shell (bundled and disk delivery).
 * Owns persisted UI state and connects the feature tabs to the backend queries.
 */

import './imagegen.css'

import { Codicon, cn, Dialog, DialogContent, DialogHeader, DialogTitle, host, queryClient, ROUTES_AREA, SIDEBAR_NAV_AREA, PALETTE_AREA, STATUSBAR_AREAS, TRANSCRIPT_DIRECTIVE_AREA, useI18n, useQuery, type HermesPlugin } from '@hermes/plugin-sdk'
import { useCallback, useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'

import type { ImageGenConfig, JobResult } from './types'
import { ID, bindApi, invalidateFeed, invalidateGallery, fetchLibrary, fetchPresets, fetchProviderStatus, fetchProviders, getStored, setStored, promptText } from './api'
import { emitJobChanged, type JobChange } from './jobEvents'
import { onOpenRequest, takePendingOpen, type OpenRequest } from './navigation'
import { DEFAULT_CONFIG, migrateConfig, newRequestConfig, prepareReferences, referenceFromImage } from './presets'
import { IMAGEGEN_LANGS, ImageGenI18nProvider, resolveLang, useImageGenI18n, type ImageGenLang, type ImageGenLangChoice } from './i18n'
import { EditTab } from './components/EditTab'
import { GenerateTab } from './components/GenerateTab'
import { GalleryTab } from './components/GalleryTab'
import { CampaignMatrixTab } from './components/CampaignMatrixTab'
import { ModelCatalogModal, ModelSelector } from './components/ModelCatalogModal'

import { ActiveJobPill } from './components/ActiveJobPill'
import { ChatImageCard } from './components/ChatImageCard'
import { openSidePane } from './components/SidePane'
import { PreferencesPanel } from './components/PreferencesPanel'


const VALID_TABS = ['generate', 'edit', 'campaign', 'gallery'] as const
type ImageGenTab = (typeof VALID_TABS)[number]

/** Tab ids retired by past refactors, mapped to their current home. */
const RETIRED_TABS: Record<string, ImageGenTab> = { inpaint: 'edit', history: 'gallery' }

function useStoredState<T>(key: string, fallback: T): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() => {
    const stored = getStored<T | undefined>(key, undefined)
    if (stored === undefined || stored === null) return fallback
    if (key === 'prompt') return promptText(stored) as T
    if (typeof fallback === 'boolean' && typeof stored !== 'boolean') return fallback
    if (typeof fallback === 'string' && typeof stored !== 'string') return fallback
    if (typeof stored === 'object' && typeof fallback === 'object' && !Array.isArray(stored) && !Array.isArray(fallback)) {
      return { ...fallback, ...stored } as T
    }
    return stored
  })
  const setAndStore: Dispatch<SetStateAction<T>> = useCallback((next) => {
    setValue((previous) => {
      const resolved = typeof next === 'function' ? (next as (previous: T) => T)(previous) : next
      setStored(key, resolved)
      return resolved
    })
  }, [key])
  return [value, setAndStore]
}

function ImageGenPage() {
  const [tab, setTab] = useStoredState<ImageGenTab>('tab', 'generate')
  const [config, setConfig] = useStoredState<ImageGenConfig>('config', DEFAULT_CONFIG)
  const [prompt, setPrompt] = useStoredState('prompt', '')
  const [promptTouched, setPromptTouched] = useStoredState('promptTouched', false)
  const [promptManual, setPromptManual] = useStoredState('promptManual', false)
  const [skipConfirm, setSkipConfirm] = useStoredState('skipConfirm', false)
  const [langChoice, setLangChoice] = useStoredState<ImageGenLangChoice>('lang', 'auto')
  const { locale } = useI18n()
  const lang = resolveLang(langChoice, locale)
  const [editInitialImage, setEditInitialImage] = useState<{ image: string; ts: number } | null>(null)
  // The active job lives here, not inside GenerateTab: switching tabs unmounts
  // the tab body, and a running generation must survive that.
  const [activeJobId, setActiveJobId] = useStoredState<string | null>('activeJobId', null)
  const [catalogOpen, setCatalogOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  // Clearing the plugin data remounts the composer, so a deleted result leaves the screen.
  const [lastResult, setLastResult] = useState<JobResult | null>(null)
  const [dataEpoch, setDataEpoch] = useState(0)
  const [migrationStarted, setMigrationStarted] = useState(false)
  const t = useImageGenI18n(lang)

  const presetsQuery = useQuery({ queryKey: [ID, 'presets'], queryFn: fetchPresets, staleTime: 10 * 60_000 })
  const providersQuery = useQuery({ queryKey: [ID, 'providers'], queryFn: fetchProviders, staleTime: 30_000 })
  const providerStatusQuery = useQuery({ queryKey: [ID, 'providers-status'], queryFn: fetchProviderStatus, staleTime: 30_000 })
  const libraryQuery = useQuery({ queryKey: [ID, 'library'], queryFn: fetchLibrary })


  const presets = presetsQuery.data || null
  const providers = useMemo(() => {
    const statuses = providerStatusQuery.data || []
    return (providersQuery.data || []).map((provider) => {
      const status = statuses.find((item) => item.name === provider.name)
      return status ? { ...provider, configured: status.configured, available: status.available } : provider
    })
  }, [providerStatusQuery.data, providersQuery.data])
  const library = libraryQuery.data || []


  const updateConfig = useCallback((partial: Partial<ImageGenConfig>) => {
    setConfig((previous) => ({ ...previous, ...partial }))
  }, [setConfig])

  useEffect(() => {
    const stored = getStored<string>('tab', 'generate')
    const retired = RETIRED_TABS[stored]
    if (retired) {
      setTab(retired)
      return
    }
    const migrated = migrateConfig(config)
    if (migrated.densityMode !== config.densityMode) setConfig(migrated)
  }, [])

  useEffect(() => {
    if (!VALID_TABS.includes(tab)) setTab('generate')
  }, [setTab, tab])

  useEffect(() => {
    if (migrationStarted) return
    const legacy = (config.referencesV4 || []).some((reference) => !reference.localPath && reference.imageDataUrl?.startsWith('data:'))
    if (!legacy) return
    setMigrationStarted(true)
    prepareReferences(config.referencesV4)
      .then((prepared) => {
        if (prepared.changed) updateConfig({ referencesV4: prepared.ready })
      })
      .catch(() => {})
  }, [config.referencesV4, migrationStarted, updateConfig])

  useEffect(() => {
    if (!providers.length) return
    const currentProvider = config.provider || 'fal'
    const currentModel = config.selectedModel || ''
    const providerExists = providers.some((item) => item.name === currentProvider)
    const modelExists = providers.find((item) => item.name === currentProvider)?.models.some((item) => item.id === currentModel)
    if (!providerExists || !modelExists) {
      const first = providers.find((item) => item.recommended)
        || providers.find((item) => item.available !== false && item.models.length) || providers.find((item) => item.models.length)
      if (first) updateConfig({ provider: first.name, selectedModel: first.default_model || first.models[0].id })
    }
  }, [config.provider, config.selectedModel, providers, updateConfig])

  // Each destination gets the image its own way: Edit opens it, Generate adds it as a reference
  // of the open request. Before, every image went to Edit's state, even when Generate was asked.
  const goToTab = useCallback((nextTab: string, options?: { image?: string }) => {
    const image = options?.image
    if (image && nextTab === 'generate') {
      void referenceFromImage(image, t('refResult'))
        .then((reference) => setConfig((previous) => ({ ...previous, referencesV4: [...(previous.referencesV4 || []), reference] })))
        .then(() => host.notify({ id: 'imagegen-reference-added', kind: 'success', message: t('referenceAdded') }))
        .catch((error) => host.notifyError(error, t('useAsRef')))
    } else if (image) {
      setEditInitialImage({ image, ts: Date.now() })
    }
    if (VALID_TABS.includes(nextTab as ImageGenTab)) setTab(nextTab as ImageGenTab)
  }, [setConfig, setTab, t])

  /** Start a request from zero, keeping the person's provider, model and preferences. */
  const startNewRequest = useCallback(() => {
    setConfig((previous) => newRequestConfig(previous))
    setPrompt('')
    setPromptTouched(false)
    setPromptManual(false)
    setLastResult(null)
  }, [setConfig, setPrompt, setPromptTouched, setPromptManual])

  // The chat card opens this page on a given tab, before or after it mounts.
  useEffect(() => {
    const open = (request: OpenRequest) => goToTab(request.tab, { image: request.image })
    const pending = takePendingOpen()
    if (pending) open(pending)
    return onOpenRequest((request) => {
      takePendingOpen()
      open(request)
    })
  }, [goToTab])

  /** Reload a stored generation's settings into the composer: only what the recipe saved, nothing of the open request. */
  const applyStoredConfig = useCallback((entryConfig: Partial<ImageGenConfig>, entryPrompt?: string) => {
    setConfig((previous) => migrateConfig({ ...newRequestConfig(previous), ...entryConfig, provider: entryConfig.provider || previous.provider, selectedModel: entryConfig.selectedModel || previous.selectedModel }))
    setLastResult(null)
    setPrompt(entryPrompt || '')
    setPromptTouched(!!entryPrompt)
    setPromptManual(!!entryPrompt)
    setTab('generate')
  }, [setConfig, setTab, setPrompt, setPromptTouched, setPromptManual])

  const currentProvider = config.provider || 'fal'
  const currentModel = config.selectedModel || ''
  const tabs: Array<{ id: ImageGenTab; label: string; icon: string }> = [
    { id: 'generate', label: t('generate'), icon: 'sparkle' },
    { id: 'edit', label: t('edit'), icon: 'edit' },
    { id: 'campaign', label: t('campaign'), icon: 'table' },
    { id: 'gallery', label: t('gallery'), icon: 'file-media' },
  ]

  return (
    <ImageGenI18nProvider lang={lang}>
      <div className="imagegen-ui if-shell">
        <header className="if-topbar">
          <nav className="if-tabs" aria-label={t('nav')}>
            {tabs.map((item) => <button key={item.id} type="button" aria-current={tab === item.id ? 'page' : undefined} className={cn('if-tab', tab === item.id && 'if-tab-active')} onClick={() => setTab(item.id)}><Codicon name={item.icon} style={{ fontSize: 14 }} /><span>{item.label}</span></button>)}
          </nav>
          <div className="if-topbar-actions">
            {tab !== 'edit' && <ModelSelector providers={providers} provider={currentProvider} model={currentModel} onOpenCatalog={() => setCatalogOpen(true)} />}
            <button type="button" title={t('sidePaneOpen')} aria-label={t('sidePaneOpen')} className="if-icon-button" onClick={() => openSidePane('ImageGen')}><Codicon name="layout-sidebar-right" style={{ fontSize: 15 }} /></button>
            <button type="button" title={t('settings')} aria-label={t('settings')} className="if-icon-button" onClick={() => setSettingsOpen(true)}><Codicon name="settings-gear" style={{ fontSize: 15 }} /></button>
          </div>
        </header>
        {providersQuery.isError && (
          <div className="mx-3 mt-2 flex items-center gap-2 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-3 py-2 text-[11px] text-(--ui-text-secondary)">
            <Codicon name="warning" className="text-(--ui-accent)" style={{ fontSize: 13 }} />
            <span>{t('backendDown')}</span>
          </div>
        )}
        <main className={cn('if-main', tab === 'generate' && 'if-main-fill')}>
          {tab === 'generate' && <GenerateTab lastResult={lastResult} setLastResult={setLastResult} key={dataEpoch} config={config} updateConfig={updateConfig} providers={providers} presets={presets} onGoToTab={goToTab} prompt={prompt} setPrompt={setPrompt} promptTouched={promptTouched} setPromptTouched={setPromptTouched} promptManual={promptManual} setPromptManual={setPromptManual} skipConfirm={skipConfirm} setSkipConfirm={setSkipConfirm} activeJobId={activeJobId} setActiveJobId={setActiveJobId} onOpenSettings={() => setSettingsOpen(true)} onNewRequest={startNewRequest} onOpenCatalog={() => setCatalogOpen(true)} />}
          {tab === 'edit' && <EditTab config={config} updateConfig={updateConfig} initialImage={editInitialImage} providers={providers} onOpenSettings={() => setSettingsOpen(true)} />}
          {tab === 'campaign' && <CampaignMatrixTab config={config} updateConfig={updateConfig} presets={presets} onGoToTab={goToTab} />}
          {tab === 'gallery' && <GalleryTab config={config} updateConfig={updateConfig} onGoToTab={goToTab} onUseConfig={applyStoredConfig} library={library} prompt={prompt} providers={providers} />}
        </main>
        <ModelCatalogModal open={catalogOpen} onClose={() => setCatalogOpen(false)} onOpenSettings={() => setSettingsOpen(true)} providers={providers} selectedModel={currentModel} providerName={currentProvider} onSelect={(model) => updateConfig({ selectedModel: model })} onProviderChange={(provider) => { const first = providers.find((item) => item.name === provider)?.models[0]?.id || ''; updateConfig({ provider, selectedModel: first }) }} />
        <Dialog open={settingsOpen} onOpenChange={(value) => !value && setSettingsOpen(false)}>
          <DialogContent className="imagegen-ui if-settings-dialog">
            <DialogHeader>
              <DialogTitle className="text-sm">{t('settings')}</DialogTitle>
            </DialogHeader>
            <PreferencesPanel config={config} updateConfig={updateConfig} langChoice={langChoice} onLang={setLangChoice} onDataCleared={() => { setLastResult(null); setDataEpoch((value) => value + 1) }} />
          </DialogContent>
        </Dialog>
      </div>
    </ImageGenI18nProvider>
  )
}

const plugin: HermesPlugin = {
  id: ID,
  name: 'ImageGen',
  defaultEnabled: true,
  register(ctx) {
    bindApi(ctx.rest, ctx.storage, ctx.os)
    ctx.onEvent('plugin.imagegen.job.changed', (event) => {
      const change = (event as { payload?: JobChange }).payload
      if (!change?.id) return
      emitJobChanged(change)
      void queryClient.invalidateQueries({ queryKey: [ID, 'jobs'] })
      void queryClient.invalidateQueries({ queryKey: [ID, 'jobs-active'] })
    })
    // Images the agent generates through the ImageGen provider land in the gallery.
    // FAL's catalog refreshes in the background; reload the model lists when it lands.
    ctx.onEvent('plugin.imagegen.providers.changed', () => {
      void queryClient.invalidateQueries({ queryKey: [ID, 'providers'] })
    })
    ctx.onEvent('plugin.imagegen.gallery.changed', () => {
      invalidateGallery()
      invalidateFeed()
    })

    ctx.registerMany([
      {
        id: 'page',
        area: ROUTES_AREA,
        data: { path: '/imagegen' },
        render: () => <ImageGenPage />
      },
      {
        id: 'nav',
        area: SIDEBAR_NAV_AREA,
        order: 100,
        data: { path: '/imagegen', label: 'ImageGen', codicon: 'paintcan' }
      },
      {
        id: 'open',
        area: PALETTE_AREA,
        data: {
          id: 'imagegen.open',
          label: 'ImageGen: Open',
          keywords: ['image', 'imagegen', 'generate', 'edit', 'gallery'],
          run: () => host.navigate('/imagegen')
        }
      },
      {
        id: 'open-side',
        area: PALETTE_AREA,
        data: {
          id: 'imagegen.openSide',
          label: 'ImageGen: Open beside chat',
          keywords: ['image', 'imagegen', 'pane', 'panel', 'side', 'recent'],
          run: () => openSidePane('ImageGen')
        }
      },
      {
        id: 'active-job',
        area: STATUSBAR_AREAS.right,
        order: 90,
        render: () => <ActiveJobPill />
      },
      {
        id: 'chat-image',
        area: TRANSCRIPT_DIRECTIVE_AREA,
        data: {
          name: 'imagegen-image',
          render: ({ attrs, streaming }: { attrs: Readonly<Record<string, string>>; streaming: boolean }) => (
            <ChatImageCard id={attrs.id} streaming={streaming} />
          )
        }
      }
    ])
  }
}

export default plugin
