/**
 * ImageGen — provider and model catalog controls.
 */

import { Badge, Button, Codicon, Dialog, DialogContent, DialogHeader, DialogTitle, Input } from '@hermes/plugin-sdk'
import { useMemo, useState } from 'react'

import type { Provider, ProviderModel } from '../types'
import { cn } from '@hermes/plugin-sdk'
import { useImageGenT } from '../i18n'
import { accessLabelKey, providerReady } from '../access'

export function ModelCatalogModal({
  open,
  onClose,
  providers,
  selectedModel,
  onSelect,
  providerName,
  onProviderChange,
  onOpenSettings
}: {
  open: boolean
  onClose: () => void
  providers: Provider[]
  selectedModel: string
  onSelect: (model: string) => void
  providerName: string
  onProviderChange: (provider: string) => void
  onOpenSettings?: () => void
}) {
  const t = useImageGenT()
  const [query, setQuery] = useState('')
  const provider = providers.find((item) => item.name === providerName) || providers[0]
  const models = provider?.models || []
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return models
    return models.filter((model) => `${model.display || ''} ${model.id} ${model.strengths || ''}`.toLowerCase().includes(normalized))
  }, [models, query])

  return (
    <Dialog open={open} onOpenChange={(value) => !value && onClose()}>
      <DialogContent className="imagegen-ui max-w-2xl max-h-[80vh] overflow-hidden">
        <div className="flex min-h-0 flex-col gap-3">
          <DialogHeader>
            <DialogTitle className="text-sm">{t('modelCatalog')}</DialogTitle>
          </DialogHeader>
          <div className="flex gap-2">
            <select
              value={providerName}
              onChange={(event) => onProviderChange(event.target.value)}
              className="h-8 w-44 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 text-xs"
            >
              {providers.map((item) => (
                <option key={item.name} value={item.name}>
                  {(item.configured && item.available !== false ? '● ' : '○ ')}{item.display_name || item.name} · {t(accessLabelKey(item.name))}
                </option>
              ))}
            </select>
            <div className="relative flex-1">
              <Codicon name="search" className="absolute left-2 top-1/2 -translate-y-1/2 text-(--ui-text-tertiary)" style={{ fontSize: 13 }} />
              <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`${t('model')}…`} className="h-8 pl-7 text-xs" />
            </div>
          </div>
          {!providerReady(providers, providerName) && (
            <div className="if-access-notice" role="status">
              <Codicon name="lock" style={{ fontSize: 14 }} />
              <div><p>{t('accessProviderMissing', { provider: providers.find((item) => item.name === providerName)?.display_name || providerName })}</p></div>
              {onOpenSettings && <Button size="sm" variant="outline" className="h-7 text-xs" onClick={() => { onClose(); onOpenSettings() }}>{t('accessConfigure')}</Button>}
            </div>
          )}
          <div className="min-h-0 flex-1 overflow-y-auto space-y-1.5">
            {filtered.length === 0 && <div className="p-4 text-center text-xs text-(--ui-text-tertiary)">{t('noResult')}</div>}
            {filtered.map((model) => (
              <ModelOption key={model.id} model={model} active={model.id === selectedModel} onSelect={() => { onSelect(model.id); onClose() }} />
            ))}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ModelOption({ model, active, onSelect }: { model: ProviderModel; active: boolean; onSelect: () => void }) {
  return (
    <button
      type="button"
      className={cn(
        'w-full rounded-lg border p-3 text-left transition-colors',
        active ? 'border-(--ui-accent) bg-(--ui-accent)/8' : 'border-(--ui-stroke-secondary) hover:bg-(--chrome-action-hover)'
      )}
      onClick={onSelect}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate text-xs font-semibold">{model.display || model.id.split('/').pop()}</span>
          {model.speed && <Badge variant="muted" className="text-[9px]">{model.speed}</Badge>}
          {model.capabilities?.referenceImages && <Badge variant="outline" className="text-[9px] text-emerald-500">refs ×{model.capabilities.maxReferences || 1}</Badge>}
        </div>
        {model.price && <span className="flex-shrink-0 font-mono text-[10px] text-(--ui-text-tertiary)">{model.price}</span>}
      </div>
      {model.strengths && <div className="mt-1.5 text-[11px] leading-relaxed text-(--ui-text-secondary)">{model.strengths}</div>}
      <div className="mt-1 truncate font-mono text-[10px] text-(--ui-text-quaternary)">{model.id}</div>
    </button>
  )
}

export function ModelSelector({
  providers,
  provider,
  model,
  onOpenCatalog
}: {
  providers: Provider[]
  provider: string
  model: string
  onOpenCatalog: () => void
}) {
  const t = useImageGenT()
  const currentProvider = providers.find((item) => item.name === provider)
  const currentModel = currentProvider?.models.find((item) => item.id === model)
  return (
    <div className="flex items-center gap-1.5">
      <Button size="sm" variant="outline" className="h-8 max-w-[300px] gap-1.5" onClick={onOpenCatalog}>
        <Codicon name="sparkle" className="text-(--ui-accent)" style={{ fontSize: 13 }} />
        <span className="truncate text-xs">{currentModel?.display || model.split('/').pop() || t('model')}</span>
        <Codicon name="chevron-down" className="text-(--ui-text-tertiary)" style={{ fontSize: 11 }} />
      </Button>
      {currentProvider && <span title={currentProvider.configured && currentProvider.available !== false ? t('providerConnected') : t('providerNotReady')}><span className={cn('inline-block h-2 w-2 rounded-full', currentProvider.configured && currentProvider.available !== false ? 'bg-emerald-500' : currentProvider.available === false ? 'bg-red-500' : 'bg-amber-500')} /></span>}
    </div>
  )
}
