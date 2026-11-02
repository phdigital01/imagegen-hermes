/**
 * ImageGen — the settings window: language, where images are saved, providers and budget.
 * These rarely change, so they stay out of the screens where images are made.
 */

import { Button, Input, queryClient, useQuery } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'

import { ID, clearPluginData, fetchOutputFolder, saveOutputFolder } from '../api'
import { IMAGEGEN_LANGS, useImageGenT, type ImageGenLang, type ImageGenLangChoice } from '../i18n'
import type { ImageGenConfig } from '../types'
import { ProvidersPanel } from './ProvidersPanel'
import { FieldLabel } from './ui-helpers'

const LANG_NAMES: Record<ImageGenLang, string> = { pt: 'Português', en: 'English', es: 'Español', zh: '中文' }

export function PreferencesPanel({ config, updateConfig, langChoice, onLang, onDataCleared }: {
  config: ImageGenConfig
  updateConfig: (partial: Partial<ImageGenConfig>) => void
  langChoice: ImageGenLangChoice
  onLang: (choice: ImageGenLangChoice) => void
  onDataCleared: () => void
}) {
  const t = useImageGenT()
  const outputFolderQuery = useQuery({ queryKey: [ID, 'output-folder'], queryFn: fetchOutputFolder, staleTime: 30_000 })
  const [outputFolder, setOutputFolder] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [clearBusy, setClearBusy] = useState(false)

  useEffect(() => {
    if (outputFolderQuery.data) setOutputFolder(outputFolderQuery.data.path || '')
  }, [outputFolderQuery.data])

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      await saveOutputFolder(outputFolder.trim())
      await outputFolderQuery.refetch()
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : t('outputFolderSaveFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="if-settings">
      <section>
        <h3>{t('languageTitle')}</h3>
        <select value={langChoice} aria-label={t('languageTitle')} onChange={(event) => onLang(event.target.value as ImageGenLangChoice)} className="h-8 rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 text-xs">
          <option value="auto">{t('languageAuto')}</option>
          {IMAGEGEN_LANGS.map((value) => <option key={value} value={value}>{LANG_NAMES[value]}</option>)}
        </select>
      </section>

      <section>
        <h3>{t('storage')}</h3>
        <label className="flex items-center gap-2 text-xs">
          <input type="checkbox" checked={config.saveToGallery !== false} className="accent-(--ui-accent)" onChange={(event) => updateConfig({ saveToGallery: event.target.checked })} />
          {t('saveToGallery')}
        </label>
        <FieldLabel hint={t('outputFolderHint')}>{t('outputFolder')}</FieldLabel>
        <div className="flex gap-2">
          <Input value={outputFolder} placeholder="C:\Users\you\Pictures\ImageGen" className="h-8 flex-1 text-xs font-mono" onChange={(event) => setOutputFolder(event.target.value)} />
          <Button size="sm" className="h-8 text-xs" disabled={saving} onClick={() => void save()}>{saving ? t('saving') : t('saveFolder')}</Button>
        </div>
        {error && <div className="text-[10.5px] text-red-500">{error}</div>}
        {!error && outputFolderQuery.data?.path && <div className={`text-[10.5px] ${outputFolderQuery.data.writable ? 'text-emerald-500' : 'text-amber-500'}`}>{outputFolderQuery.data.writable ? t('outputFolderReady') : t('outputFolderUnavailable')}</div>}
      </section>

      <section>
        <h3>{t('providersTitle')}</h3>
        <ProvidersPanel />
      </section>

      <section>
        <h3>{t('clearPluginData')}</h3>
        <Button size="sm" variant="outline" className="h-8 self-start text-xs" disabled={clearBusy} onClick={() => {
          if (!window.confirm(t('clearPluginDataConfirm'))) return
          setClearBusy(true)
          void clearPluginData({ gallery: true, handoffs: true, subjects: false })
            .then(() => { queryClient.invalidateQueries({ queryKey: [ID] }); onDataCleared() })
            .finally(() => setClearBusy(false))
        }}>{clearBusy ? t('saving') : t('clearPluginData')}</Button>
      </section>
    </div>
  )
}
