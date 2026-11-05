/**
 * ImageGen — prompt panel (copy, optimize, translate, refine, diff).
 */

import { Button, cn, Codicon, Input, Textarea, host } from '@hermes/plugin-sdk'
import { useMemo, useState } from 'react'

import { promptHelper, rest } from '../api'
import { useImageGenT } from '../i18n'
import { copyText, fileToDataUrl, Spinner } from './ui-helpers'

export function PromptPanel({
  value,
  onChange,
  onOptimize,
  onResetAuto,
  promptTouched,
  optimizing,
  disabled,
  readOnly,
  onEditManual,
  copyLabel,
  copiedLabel,
  optimizeLabel,
  optimizingLabel,
  translateLabel,
  autoLabel,
  hideChanges,
  hideTranslation,
  placeholder,
  whatChanged,
  refinePlaceholder,
  chars,
  toolTarget,
  magnificHelpers
}: {
  value: string
  onChange: (v: string) => void
  onOptimize?: () => void
  onResetAuto?: () => void
  promptTouched: boolean
  optimizing?: boolean
  disabled?: boolean
  readOnly?: boolean
  onEditManual?: () => void
  copyLabel?: string
  copiedLabel?: string
  optimizeLabel?: string
  optimizingLabel?: string
  translateLabel?: string
  autoLabel?: string
  hideChanges?: string
  hideTranslation?: string
  placeholder?: string
  whatChanged?: string
  refinePlaceholder?: string
  chars?: string
  toolTarget?: string
  /** Show Magnific's describe-image and improve-prompt buttons. */
  magnificHelpers?: boolean
}) {
  const t = useImageGenT()
  const labels = {
    copy: copyLabel || t('copyPrompt'),
    copied: copiedLabel || t('copied'),
    optimize: optimizeLabel || t('optimize'),
    optimizing: optimizingLabel || t('analyzing'),
    translate: translateLabel || t('translate'),
    auto: autoLabel || t('resetAuto'),
    hideChanges: hideChanges || t('close'),
    hideTranslation: hideTranslation || t('close'),
    placeholder: placeholder || t('describeImageHint'),
    whatChanged: whatChanged || t('promptPreview'),
    refinePlaceholder: refinePlaceholder || t('refine'),
    chars: chars || t('chars')
  }
  const [showDiff, setShowDiff] = useState(false)
  const [prevValue, setPrevValue] = useState('')
  const [translation, setTranslation] = useState('')
  const [showTranslation, setShowTranslation] = useState(false)
  const [translating, setTranslating] = useState(false)
  const [refineInput, setRefineInput] = useState('')
  const [refining, setRefining] = useState(false)
  const [copied, setCopied] = useState(false)
  const [helping, setHelping] = useState<'' | 'describe' | 'improve'>('')

  const applyHelper = async (kind: 'describe' | 'improve', file?: File) => {
    setHelping(kind)
    try {
      const d = kind === 'describe' && file
        ? await promptHelper({ action: 'describe', image: await fileToDataUrl(file) })
        : await promptHelper({ action: 'improve', prompt: value })
      onEditManual?.()
      setPrevValue(value)
      onChange(d.text)
      setShowDiff(!!value)
    } catch (error) {
      host.notifyError(error, kind === 'describe' ? t('promptFromImage') : t('improvePrompt'))
    } finally {
      setHelping('')
    }
  }

  const diff = useMemo(() => {
    if (!showDiff || !prevValue) return null
    const before = new Set(prevValue.split(/\s+/))
    const addedWords = value.split(/\s+/)
    const added = addedWords.filter((w) => !before.has(w))
    const rem = prevValue.split(/\s+/).filter((w) => !addedWords.includes(w))
    return { removed: rem.slice(0, 20), added: added.slice(0, 20) }
  }, [showDiff, prevValue, value])

  const doTranslate = async () => {
    setTranslating(true)
    try {
      const d = await rest<{ result: string }>('/llm/translate', 'POST', { text: value, targetLang: t('translateTarget') })
      setTranslation(d.result)
      setShowTranslation(true)
    } catch (error) {
      host.notifyError(error, labels.translate)
    } finally {
      setTranslating(false)
    }
  }

  const doRefineNow = async () => {
    if (!refineInput.trim()) return
    setRefining(true)
    try {
      const d = await rest<{ result: string }>('/llm/refine', 'POST', {
        basePrompt: value,
        userChangeRequest: refineInput,
        toolTarget: toolTarget || 'generic'
      })
      setPrevValue(value)
      onChange(d.result)
      setShowDiff(true)
      setRefineInput('')
    } catch (error) {
      host.notifyError(error, labels.refinePlaceholder)
    } finally {
      setRefining(false)
    }
  }

  return (
    <div className="space-y-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs gap-1"
          disabled={!value}
          onClick={() => {
            copyText(value)
            setCopied(true)
            setTimeout(() => setCopied(false), 1500)
          }}
        >
          <Codicon name={copied ? 'check' : 'copy'} style={{ fontSize: 12 }} />
          {copied ? labels.copied : labels.copy}
        </Button>
        {onOptimize && <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs gap-1"
          disabled={disabled || !value || optimizing}
          onClick={onOptimize}
        >
          {optimizing ? <Spinner /> : <Codicon name="sparkle" style={{ fontSize: 12 }} />}
          {optimizing ? labels.optimizing : labels.optimize}
        </Button>}
        <Button size="sm" variant="ghost" className="h-7 text-xs gap-1" disabled={!value || translating} onClick={doTranslate}>
          {translating ? <Spinner /> : <Codicon name="globe" style={{ fontSize: 12 }} />}
          {labels.translate}
        </Button>
        {magnificHelpers && <>
          <Button size="sm" variant="ghost" className="h-7 text-xs gap-1" disabled={!value || !!helping || value.length > 2500} title={t('improvePromptHint')} onClick={() => void applyHelper('improve')}>
            {helping === 'improve' ? <Spinner /> : <Codicon name="lightbulb-sparkle" style={{ fontSize: 12 }} />}
            {t('improvePrompt')}
          </Button>
          <label className={cn('if-inline-upload inline-flex h-7 items-center gap-1 text-xs', !!helping && 'pointer-events-none opacity-50')} title={t('promptFromImageHint')}>
            {helping === 'describe' ? <Spinner /> : <Codicon name="eye" style={{ fontSize: 12 }} />}
            {t('promptFromImage')}
            <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" disabled={!!helping} onChange={(event) => {
              const file = event.target.files?.[0]
              event.target.value = ''
              if (file) void applyHelper('describe', file)
            }} />
          </label>
        </>}
        {promptTouched && onResetAuto && (
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-xs gap-1 text-(--ui-accent)"
            onClick={onResetAuto}
            title="Back to the automatic prompt from the fields"
          >
            <Codicon name="sync" style={{ fontSize: 12 }} />
            {labels.auto}
          </Button>
        )}
        {showDiff && diff && (diff.added.length > 0 || diff.removed.length > 0) && (
          <Button size="sm" variant="ghost" className="h-7 text-xs text-amber-500" onClick={() => setShowDiff(false)}>
            {labels.hideChanges}
          </Button>
        )}
        {showTranslation && (
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setShowTranslation(false)}>
            {labels.hideTranslation}
          </Button>
        )}
      </div>

      <div className="relative">
        <Textarea
          value={value}
          rows={Math.max(4, Math.min(10, value.split('\n').length + 1))}
          onChange={(e) => onChange(e.target.value)}
          readOnly={readOnly}
          className={cn('font-mono text-[11.5px] leading-relaxed bg-(--ui-bg) pr-16 resize-y', readOnly ? 'cursor-default opacity-80' : '')}
          placeholder={labels.placeholder}
        />
        {value && (
          <span className="absolute right-2 bottom-2 rounded bg-(--ui-bg-elevated) border border-(--ui-stroke-secondary) px-1.5 py-0.5 text-[9px] font-mono text-(--ui-text-quaternary)">
            {value.length} {labels.chars}
          </span>
        )}
      </div>

      {showDiff && diff && (diff.added.length > 0 || diff.removed.length > 0) && (
        <div className="if-fade-in rounded-lg border border-(--ui-stroke-secondary) p-2.5 space-y-1.5 text-[11px]">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-(--ui-text-tertiary)">{labels.whatChanged}</div>
          {diff.removed.length > 0 && (
            <div className="flex flex-wrap gap-1">
              <span className="text-red-500">−</span>
              {diff.removed.map((w, i) => (
                <span key={`r-${i}-${w}`} className="rounded bg-red-500/10 px-1 py-0.5 text-red-500 line-through">
                  {w}
                </span>
              ))}
            </div>
          )}
          {diff.added.length > 0 && (
            <div className="flex flex-wrap gap-1">
              <span className="text-emerald-500">+</span>
              {diff.added.map((w, i) => (
                <span
                  key={`a-${i}-${w}`}
                  className="rounded bg-emerald-500/10 px-1 py-0.5 text-emerald-600 dark:text-emerald-400"
                >
                  {w}
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {showTranslation && (
        <div className="if-fade-in rounded-lg bg-(--ui-bg) border border-(--ui-stroke-secondary) p-2.5 text-xs whitespace-pre-wrap">
          {translation}
        </div>
      )}

      {readOnly ? (
        onEditManual && (
          <Button size="sm" variant="outline" className="h-7 gap-1 text-xs" onClick={onEditManual}>
            <Codicon name="edit" style={{ fontSize: 12 }} />
            {t('editManually')}
          </Button>
        )
      ) : (
        <div className="flex gap-1.5">
          <Input
            value={refineInput}
            placeholder={labels.refinePlaceholder}
            className="h-8 text-xs flex-1"
            onChange={(e) => setRefineInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') doRefineNow()
            }}
          />
          <Button
            size="sm"
            variant="secondary"
            className="h-8 gap-1 text-xs"
            disabled={refining || !refineInput.trim() || !value}
            onClick={doRefineNow}
          >
            {refining ? <Spinner /> : <Codicon name="wand" style={{ fontSize: 13 }} />}
          </Button>
        </div>
      )}
    </div>
  )
}