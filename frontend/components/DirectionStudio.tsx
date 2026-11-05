/**
 * ImageGen — visual picker for subject, style, light, angle, framing, camera, mood and format.
 *
 * Every option of a series shows the same scene, so the picture shows what the option changes.
 * The board sits in the composer; the studio window opens from it on the chosen group.
 */

import { Button, Codicon, cn, Dialog, DialogContent, DialogHeader, DialogTitle } from '@hermes/plugin-sdk'
import { useState } from 'react'

import { directionText, type DirectionGroup } from '../directionText'
import { useImageGenT } from '../i18n'
import { SUBJECT_FILES, slugThumb, subjectOptions } from '../presets'
import type { ImageGenConfig, Presets } from '../types'
import { Chip, bundledThumbUrl } from './ui-helpers'

export type DirectionTab = 'subject' | 'style' | 'lighting' | 'angle' | 'framing' | 'camera' | 'mood' | 'format'

type RatioOption = { value: string; label?: string; hint?: string }

const APERTURE_FILES: Record<string, string> = {
  'f/1.4': 'aperture-f14',
  'f/2.8': 'aperture-f28',
  'f/5.6': 'aperture-f56',
  'f/11': 'aperture-f11'
}

/** The subject that means "no subject chosen". */
const FREE_SUBJECT = 'livre'

function thumbFile(group: DirectionGroup, value: string): string {
  if (group === 'subject') return SUBJECT_FILES[value] || ''
  if (group === 'style') return slugThumb(value).startsWith('style-') ? slugThumb(value) : `style-${slugThumb(value)}`
  if (group === 'lens') return `lens-${slugThumb(value)}`
  if (group === 'aperture') return APERTURE_FILES[value] || ''
  if (group === 'mood') return `mood-${slugThumb(value)}`
  return slugThumb(value)
}

/** Format has no direction groups: it draws shapes instead of scenes. */
const TAB_GROUPS: Record<DirectionTab, DirectionGroup[]> = {
  subject: ['subject'],
  style: ['style'],
  lighting: ['lighting'],
  angle: ['angle'],
  framing: ['distance'],
  camera: ['lens', 'aperture'],
  mood: ['mood'],
  format: []
}

const TAB_LABEL: Record<DirectionTab, string> = {
  subject: 'subjectTab',
  style: 'style',
  lighting: 'lighting',
  angle: 'angle',
  framing: 'chooseFraming',
  camera: 'camera',
  mood: 'mood',
  format: 'formatTab'
}

/** The picture a group shows while nothing is chosen: the most neutral option of its series. */
const TAB_SAMPLE: Record<DirectionTab, string> = {
  subject: SUBJECT_FILES.objeto_produto || '',
  style: 'style-fotorrealista',
  lighting: 'natural',
  angle: '3-4',
  framing: 'portrait',
  camera: 'lens-50mm',
  mood: 'mood-calmo',
  format: ''
}

function chosen(config: ImageGenConfig, group: DirectionGroup): string[] {
  const direction = config.globalDirection
  if (group === 'lighting') return direction.lighting
  if (group === 'subject') return config.subjectType && config.subjectType !== FREE_SUBJECT ? [config.subjectType] : []
  const single = { style: direction.style, angle: direction.angle, distance: config.subjectDistance, lens: direction.lens, aperture: direction.aperture, mood: config.mood }
  return single[group] ? [single[group]] : []
}

function choose(config: ImageGenConfig, group: DirectionGroup, values: string[]): Partial<ImageGenConfig> {
  const first = values[0] || ''
  if (group === 'distance') return { subjectDistance: first }
  if (group === 'mood') return { mood: first }
  const partial = group === 'lighting' ? { lighting: values } : { [group]: first }
  return { globalDirection: { ...config.globalDirection, ...partial } }
}

export function directionOptions(presets: Presets | null, group: DirectionGroup): string[] {
  if (group === 'subject') return subjectOptions(presets).map((item) => item.value).filter((value) => value !== FREE_SUBJECT)
  if (!presets) return []
  if (group === 'distance') return presets.distances.map((item) => item.value)
  const lists = { style: presets.styles, lighting: presets.lighting, angle: presets.angles, lens: presets.lenses, aperture: presets.apertures, mood: presets.moods }
  return lists[group] || []
}

function tabSummary(config: ImageGenConfig, tab: DirectionTab): { file: string; text: string } {
  if (tab === 'format') return { file: '', text: config.aspectRatio }
  const picks = TAB_GROUPS[tab].flatMap((group) => chosen(config, group).map((value) => ({ group, value })))
  if (!picks.length) return { file: TAB_SAMPLE[tab], text: '' }
  const names = picks.map((pick) => directionText(pick.group, pick.value).label)
  return { file: thumbFile(picks[0].group, picks[0].value), text: names.join(' + ') }
}

function SceneImage({ file, alt = '' }: { file: string; alt?: string }) {
  const src = bundledThumbUrl(file)
  return src ? <img src={src} alt={alt} draggable={false} /> : <span className="if-scene-blank" />
}

/** The proportion of a format, drawn inside a box that sets its largest size. */
function RatioShape({ ratio }: { ratio: string }) {
  const [width, height] = ratio.split(':').map(Number)
  const known = width > 0 && height > 0
  const wide = !known || width >= height
  return (
    <span className="if-ratio-box">
      <span className={cn('if-ratio-shape', !known && 'if-ratio-shape-auto')} style={{ width: wide ? '100%' : undefined, height: wide ? undefined : '100%', aspectRatio: known ? `${width} / ${height}` : '1' }} />
    </span>
  )
}

type ChipState = 'you' | 'ai' | 'auto'

/** Who decided each group: the person, the AI suggestion, or nobody yet (the model decides). */
export function directionStates(config: ImageGenConfig, suggested?: { effective: ImageGenConfig; suggestedFormat: boolean } | null): Record<DirectionTab, { state: ChipState; file: string; text: string; ratio: string }> {
  return Object.fromEntries((Object.keys(TAB_GROUPS) as DirectionTab[]).map((tab) => {
    if (tab === 'format') {
      if (config.manualFormat) return [tab, { state: 'you', file: '', text: config.aspectRatio, ratio: config.aspectRatio }]
      if (suggested?.suggestedFormat) return [tab, { state: 'ai', file: '', text: suggested.effective.aspectRatio, ratio: suggested.effective.aspectRatio }]
      return [tab, { state: 'auto', file: '', text: '', ratio: '' }]
    }
    const own = tabSummary(config, tab)
    if (own.text) return [tab, { state: 'you', ...own, ratio: '' }]
    const ai = suggested ? tabSummary(suggested.effective, tab) : null
    if (ai?.text) return [tab, { state: 'ai', ...ai, ratio: '' }]
    return [tab, { state: 'auto', file: '', text: '', ratio: '' }]
  })) as Record<DirectionTab, { state: ChipState; file: string; text: string; ratio: string }>
}

/**
 * The eight groups in the composer as one compact line of labels. A label with a picture is decided
 * ("Your pick" or "AI"); a dashed one is automatic. Tapping a label opens the pictures of that group.
 */
export function DirectionStrip({ config, suggested, onOpen }: {
  config: ImageGenConfig
  suggested?: { effective: ImageGenConfig; suggestedFormat: boolean } | null
  onOpen: (tab: DirectionTab) => void
}) {
  const t = useImageGenT()
  const states = directionStates(config, suggested)
  return (
    <div className="if-strip" role="group" aria-label={t('direction.title')}>
      {(Object.keys(TAB_GROUPS) as DirectionTab[]).map((tab) => {
        const { state, file, text, ratio } = states[tab]
        const label = t(TAB_LABEL[tab])
        if (state === 'auto') {
          return <button key={tab} type="button" className="if-dchip if-dchip-auto" onClick={() => onOpen(tab)} aria-label={`${label}: ${t('automatic')}`}>＋ {label}</button>
        }
        const thumb = bundledThumbUrl(file)
        return (
          <button key={tab} type="button" className={cn('if-dchip', state === 'you' ? 'if-dchip-you' : 'if-dchip-ai')} onClick={() => onOpen(tab)}
            aria-label={`${label}: ${text} (${state === 'you' ? t('direction.yours') : t('direction.ai')})`}>
            {tab === 'format' ? <span className="if-dchip-ratio">{ratio}</span> : thumb ? <img src={thumb} alt="" draggable={false} /> : null}
            <span className="if-dchip-text">{label}: <b>{text}</b></span>
            <span className="if-dchip-who">{state === 'you' ? t('direction.yoursShort') : t('direction.aiShort')}</span>
          </button>
        )
      })}
    </div>
  )
}

/** The window with every option as a picture, and a larger view of the one under the pointer. */
export function DirectionStudio({ tab, onTab, onClose, config, presets, updateConfig, onSubject, ratios, allowedRatios }: {
  tab: DirectionTab | null
  onTab: (tab: DirectionTab) => void
  onClose: () => void
  config: ImageGenConfig
  presets: Presets | null
  updateConfig: (partial: Partial<ImageGenConfig>) => void
  onSubject: (subject: string) => void
  ratios: RatioOption[]
  allowedRatios?: string[]
}) {
  const t = useImageGenT()
  const [focus, setFocus] = useState<{ group: DirectionGroup; value: string } | null>(null)
  const [focusRatio, setFocusRatio] = useState<string | null>(null)
  const groups = tab ? TAB_GROUPS[tab] : []
  const firstPick = groups.flatMap((group) => chosen(config, group).map((value) => ({ group, value })))[0]
  const firstOption = groups[0] ? { group: groups[0], value: directionOptions(presets, groups[0])[0] || '' } : null
  const shown = focus && groups.includes(focus.group) ? focus : firstPick || firstOption
  const shownText = shown ? directionText(shown.group, shown.value) : null
  const hasPick = groups.some((group) => chosen(config, group).length > 0)
  const shownRatio = focusRatio || config.aspectRatio
  const shownRatioOption = ratios.find((ratio) => ratio.value === shownRatio)
  const platforms = Object.entries(presets?.platform_presets || {}).filter(([, item]) => !allowedRatios || allowedRatios.includes(item.aspect_ratio))

  const toggle = (group: DirectionGroup, value: string) => {
    const current = chosen(config, group)
    const active = current.includes(value)
    if (group === 'subject') {
      onSubject(active ? FREE_SUBJECT : value)
      return
    }
    // Light is the only group that mixes: "Rim Light + Neon" is a real choice.
    const next = group === 'lighting'
      ? (active ? current.filter((item) => item !== value) : [...current, value])
      : (active ? [] : [value])
    updateConfig(choose(config, group, next))
  }

  const clearTab = () => {
    if (tab === 'format') { updateConfig({ manualFormat: false, aspectRatio: allowedRatios?.[0] || '1:1' }); return }
    if (tab === 'subject') {
      onSubject(FREE_SUBJECT)
      return
    }
    updateConfig(groups.reduce<Partial<ImageGenConfig>>((partial, group) => {
      const next = choose({ ...config, ...partial }, group, [])
      return { ...partial, ...next }
    }, {}))
  }

  return (
    <Dialog open={!!tab} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="imagegen-ui if-studio">
        <div className="if-studio-inner">
        <DialogHeader>
          <DialogTitle className="text-sm">{t('sceneDirection')}</DialogTitle>
        </DialogHeader>
        <div className="if-studio-tabs" role="tablist" aria-label={t('sceneDirection')}>
          {(Object.keys(TAB_GROUPS) as DirectionTab[]).map((item) => {
            const summary = tabSummary(config, item)
            return (
              <button key={item} type="button" role="tab" aria-selected={tab === item} className={cn('if-studio-tab', tab === item && 'if-studio-tab-active')} onClick={() => { setFocus(null); setFocusRatio(null); onTab(item) }}>
                <span>{t(TAB_LABEL[item])}</span>
                <small>{item === 'format' && !config.manualFormat ? t('automatic') : summary.text || t('automatic')}</small>
              </button>
            )
          })}
        </div>
        {tab === 'format' ? (
          <div className="if-studio-body">
            <div className="if-studio-grid-scroll" role="tabpanel">
              <div className="if-format-grid">
                {ratios.map((ratio) => {
                  const active = config.aspectRatio === ratio.value
                  return (
                    <button
                      key={ratio.value}
                      type="button"
                      aria-pressed={active}
                      className={cn('if-format-option', active && 'if-studio-option-active')}
                      onMouseEnter={() => setFocusRatio(ratio.value)}
                      onFocus={() => setFocusRatio(ratio.value)}
                      onClick={() => updateConfig({ aspectRatio: ratio.value, manualFormat: true })}
                    >
                      <RatioShape ratio={ratio.value} />
                      <span>{ratio.value}</span>
                    </button>
                  )
                })}
              </div>
              {platforms.length > 0 && (
                <div className="if-studio-group">
                  <div className="if-studio-group-title">{t('platform')}</div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    {platforms.map(([key, item]) => <Chip key={key} active={config.aspectRatio === item.aspect_ratio} onClick={() => updateConfig({ aspectRatio: item.aspect_ratio, manualFormat: true })}>{item.label}</Chip>)}
                  </div>
                </div>
              )}
            </div>
            <aside className="if-studio-preview">
              <div className="if-format-preview"><RatioShape ratio={shownRatio} /></div>
              <strong>{shownRatio}</strong>
              <p>{shownRatioOption?.hint && shownRatioOption.hint !== shownRatio ? shownRatioOption.hint : ''}</p>
            </aside>
          </div>
        ) : (
          <div className="if-studio-body">
            <div className="if-studio-grid-scroll" role="tabpanel">
              {groups.map((group) => (
                <div key={group} className="if-studio-group">
                  {groups.length > 1 && <div className="if-studio-group-title">{t(group)}</div>}
                  <div className="if-studio-grid">
                    {directionOptions(presets, group).map((value) => {
                      const active = chosen(config, group).includes(value)
                      return (
                        <button
                          key={value}
                          type="button"
                          aria-pressed={active}
                          className={cn('if-studio-option', active && 'if-studio-option-active')}
                          onMouseEnter={() => setFocus({ group, value })}
                          onFocus={() => setFocus({ group, value })}
                          onClick={() => toggle(group, value)}
                        >
                          <SceneImage file={thumbFile(group, value)} />
                          {active && <span className="if-studio-check"><Codicon name="check" style={{ fontSize: 12 }} /></span>}
                          <span className="if-studio-option-label">{directionText(group, value).label}</span>
                        </button>
                      )
                    })}
                  </div>
                </div>
              ))}
            </div>
            {shown && shownText && (
              <aside className="if-studio-preview">
                <SceneImage file={thumbFile(shown.group, shown.value)} alt={shownText.label} />
                <strong>{shownText.label}</strong>
                <p>{shown.group === 'subject' ? t('subjectSuggests') : shownText.hint}</p>
              </aside>
            )}
          </div>
        )}
        <div className="if-studio-footer">
          <Button size="sm" variant="ghost" disabled={tab === 'format' ? !config.manualFormat : !hasPick} onClick={clearTab}>{t('useAutomatic')}</Button>
          <Button size="sm" onClick={onClose}>{t('done')}</Button>
        </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}
