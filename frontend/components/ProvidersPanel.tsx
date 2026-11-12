/**
 * ImageGen — provider configuration panel.
 * Lists provider status (configured/available) and tests the connection. Keys and the local
 * server address are Hermes plugin settings, edited in Settings > Plugins > ImageGen; keys never reach this UI.
 */

import { Badge, Button, Codicon, host, Input, pluginSettingsHref, useMutation, useQuery } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'

import { fetchBudget, queryClient, rest, saveBudget } from '../api'
import { accessLabelKey, isLocal, providerLabel, providerUnlocksKey } from '../access'
import { useImageGenT } from '../i18n'
import { formatUsd, Spinner } from './ui-helpers'

// ImageGen registers no Desktop settings page, so its keys and address are on the page Hermes
// builds from the plugin's config_schema, which the `agent` parameter addresses.
const SETTINGS_HREF = `${pluginSettingsHref()}&agent=imagegen`

interface ProviderStatus {
  name: string
  display_name?: string
  configured: boolean
  available: boolean
}

export function ProvidersPanel() {
  const t = useImageGenT()
  const [testResult, setTestResult] = useState<{ provider: string; ok: boolean; models?: number; detail?: string } | null>(null)
  const [budgetInput, setBudgetInput] = useState('')
  const [budgetError, setBudgetError] = useState('')

  const statusQuery = useQuery({
    queryKey: ['imagegen', 'providers-status'],
    queryFn: () => rest<{ providers: ProviderStatus[] }>('/providers/status').then((d) => d.providers || []),
    staleTime: 30_000
  })
  const providers = statusQuery.data || []

  const budgetQuery = useQuery({
    queryKey: ['imagegen', 'budget'],
    queryFn: fetchBudget,
    staleTime: 30_000
  })
  const budget = budgetQuery.data

  useEffect(() => {
    if (budgetQuery.data) {
      setBudgetInput(budgetQuery.data.monthlyLimit !== null ? String(budgetQuery.data.monthlyLimit) : '')
    }
  }, [budgetQuery.data])

  const saveBudgetMutation = useMutation({
    mutationFn: (monthlyLimit: number | null) => saveBudget(monthlyLimit),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['imagegen', 'budget'] })
      setBudgetError('')
    },
    onError: (error) => {
      setBudgetError(error instanceof Error ? error.message : String(error))
    }
  })

  const applyBudget = () => {
    const raw = budgetInput.trim()
    if (!raw) {
      saveBudgetMutation.mutate(null)
      return
    }
    const value = Number(raw)
    if (!Number.isFinite(value) || value < 0) {
      setBudgetError(t('budgetInvalid'))
      return
    }
    saveBudgetMutation.mutate(value)
  }

  const testConnection = async (provider: string = 'fal') => {
    try {
      const r = await rest<{ ok: boolean; models?: number; detail?: string }>('/providers/test', 'POST', { provider })
      setTestResult({ provider, ok: r.ok, models: r.models, detail: r.detail })
      // The local server may have come up or gone down since the list was read.
      if (isLocal(provider)) queryClient.invalidateQueries({ queryKey: ['imagegen', 'providers-status'] })
    } catch {
      setTestResult({ provider, ok: false })
    }
  }

  const fal = providers.find((p) => p.name === 'fal')
  const nous = providers.find((p) => p.name === 'nous')

  return (
    <div className="space-y-3">
      {[...providers].sort((a, b) => Number(b.configured) - Number(a.configured)).map((p) => (
        <div key={p.name} className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-(--ui-stroke-secondary) p-2.5">
          <div className="min-w-0">
            <div className="truncate text-xs font-medium">{providerLabel(t, p)}</div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              {isLocal(p.name) && p.configured && !p.available
                ? <Badge variant="outline" className="text-amber-600 dark:text-amber-400">{t('localNotAnswering')}</Badge>
                : <Badge variant={p.configured ? 'outline' : 'muted'} className={p.configured ? 'text-emerald-500' : ''}>
                    {p.configured ? t('providerConfigured') : t('providerNotConfigured')}
                  </Badge>}
              <Badge variant="muted">{t(accessLabelKey(p.name))}</Badge>
            </div>
            <p className="mt-1 text-[11px] text-(--ui-text-tertiary)">{t(providerUnlocksKey(p.name))}</p>
            {testResult?.provider === p.name && (
              <div aria-live="polite" className={`mt-1 text-[11px] ${testResult.ok ? 'text-emerald-500' : 'text-red-500'}`}>
                {testResult.ok
                  ? testResult.models !== undefined ? t('localTestOk', { n: String(testResult.models) }) : t('testOk')
                  : testResult.detail ? `${t('testFail')}: ${testResult.detail}` : t('testFail')}
              </div>
            )}
          </div>
          {isLocal(p.name) && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" onClick={() => host.navigate(SETTINGS_HREF)}>
                <Codicon name="server" style={{ fontSize: 12 }} />
                {t('localAddressSettings')}
              </Button>
              {p.configured && <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" onClick={() => void testConnection('local')}>
                <Codicon name="plug" style={{ fontSize: 12 }} />
                {t('testConnection')}
              </Button>}
            </div>
          )}
          {(p.name === 'fal' || p.name === 'magnific') && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" onClick={() => host.navigate(SETTINGS_HREF)}>
                <Codicon name="key" style={{ fontSize: 12 }} />
                {t('keySettings')}
              </Button>
              {p.name === 'fal' && <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" onClick={() => void testConnection('fal')}>
                <Codicon name="plug" style={{ fontSize: 12 }} />
                {t('testConnection')}
              </Button>}
            </div>
          )}
          {p.name === 'nous' && (
            <div className="flex flex-wrap items-center gap-1.5">
              <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" onClick={() => void testConnection('nous')}>
                <Codicon name="plug" style={{ fontSize: 12 }} />
                {t('testConnection')}
              </Button>
            </div>
          )}
        </div>
      ))}
      {fal && !fal.configured && !(nous && nous.configured) && !providers.some((p) => (p.name === 'magnific' || isLocal(p.name)) && p.configured) && (
        <div className="rounded-lg border border-amber-500/30 bg-amber-500/8 p-2.5 text-xs text-amber-700 dark:text-amber-400">
          {t('configureFalHint')}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-(--ui-stroke-secondary) p-2.5">
        <div className="min-w-0 flex-1">
          <div className="text-xs font-medium">{t('chatImagesTitle')}</div>
          <p className="mt-1 text-xs text-(--ui-text-tertiary)">{t('chatImagesBody')}</p>
        </div>
        <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" onClick={() => host.navigate('/capabilities?tab=toolsets')}>
          <Codicon name="tools" style={{ fontSize: 12 }} />
          {t('chatImagesOpen')}
        </Button>
      </div>
      <div className="rounded-lg border border-(--ui-stroke-secondary) p-2.5">
        <div className="text-xs font-medium">{t('budgetTitle')}</div>
        <p className="mt-1 text-xs text-(--ui-text-tertiary)">{t('budgetEstimateNote')}</p>
        <div className="mt-1 text-[10.5px] text-(--ui-text-tertiary)">
          {t('budgetSpentThisMonth')}: <span className="tabular-nums">{formatUsd(budget?.spentThisMonth ?? 0)}</span>
          {budget?.monthlyLimit != null
            ? ` · ${t('budgetUsage', { spent: formatUsd(budget.spentThisMonth), limit: formatUsd(budget.monthlyLimit) })}`
            : ` · ${t('budgetNoLimit')}`}
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <Input type="number" min={0} step="0.01" value={budgetInput} placeholder={t('budgetMonthlyLimit')} className="h-8 w-40 text-xs" onChange={(event) => { setBudgetInput(event.target.value); setBudgetError('') }} />
          <Button size="sm" className="h-8 gap-1 text-xs" disabled={saveBudgetMutation.isPending} onClick={applyBudget}>
            {saveBudgetMutation.isPending ? <Spinner /> : <Codicon name="check" style={{ fontSize: 12 }} />}
            {t('budgetSave')}
          </Button>
          {budget?.monthlyLimit != null && (
            <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" disabled={saveBudgetMutation.isPending} onClick={() => saveBudgetMutation.mutate(null)}>
              {t('budgetClear')}
            </Button>
          )}
        </div>
        {budgetError && <div className="mt-1 text-[10.5px] text-red-500">{budgetError}</div>}
      </div>
    </div>
  )
}
