/**
 * ImageGen — text safe-area picker.
 * 3x3 grid with 9 clickable zones (top, top-left, top-right, left, center,
 * right, bottom-left, bottom-right, bottom). Multiple zones can coexist.
 */

import { cn, Codicon } from '@hermes/plugin-sdk'

import { Chip, FieldLabel, toggleIn } from './ui-helpers'
import { useImageGenT } from '../i18n'

export interface CleanZonesState {
  enabled: boolean
  zones: string[]
  intensity: string
  tone: string
}

/** Zone id → display label. */
const SAFE_ZONE_LABELS: Record<string, string> = {
  top: 'Top',
  'top-left': 'Top left',
  'top-right': 'Top right',
  left: 'Left',
  center: 'Center',
  right: 'Right',
  'bottom-left': 'Bottom left',
  'bottom-right': 'Bottom right',
  bottom: 'Bottom'
}

/** Common multi-zone presets. */
const SAFE_ZONE_PRESETS = [
  { id: 'top-bottom', label: 'Top + Base (ad)', zones: ['top', 'bottom'] },
  { id: 'left-right', label: 'Left + Right (magazine)', zones: ['left', 'right'] },
  { id: 'top-only', label: 'Top (story)', zones: ['top'] },
  { id: 'right-only', label: 'Right (banner)', zones: ['right'] },
  { id: 'all-corners', label: 'All corners', zones: ['top-left', 'top-right', 'bottom-left', 'bottom-right'] }
]

/** The 9 grid slots with their grid positions (3x3, one cell each). */
const SLOT_POSITIONS: Array<{ zone: string; col: string; row: string }> = [
  { zone: 'top-left', col: '1', row: '1' },
  { zone: 'top', col: '2', row: '1' },
  { zone: 'top-right', col: '3', row: '1' },
  { zone: 'left', col: '1', row: '2' },
  { zone: 'center', col: '2', row: '2' },
  { zone: 'right', col: '3', row: '2' },
  { zone: 'bottom-left', col: '1', row: '3' },
  { zone: 'bottom', col: '2', row: '3' },
  { zone: 'bottom-right', col: '3', row: '3' }
]

export function TextSafeAreaPicker({
  value,
  onChange,
  ratio = '1:1',
  noTextLabel,
  reserveLabel,
  shortcutsLabel,
  clickHint,
  multiZoneHint,
  preserveLabel,
  toneLabel,
  intensityOptions,
  toneOptions,
  subjectType,
  sceneComplexity,
  suppressed: suppressedProp
}: {
  value: CleanZonesState | null | undefined
  onChange: (v: CleanZonesState) => void
  ratio?: string
  noTextLabel?: string
  reserveLabel?: string
  shortcutsLabel?: string
  clickHint?: string
  multiZoneHint?: string
  preserveLabel?: string
  toneLabel?: string
  intensityOptions?: string[]
  toneOptions?: string[]
  subjectType?: string
  sceneComplexity?: string
  suppressed?: boolean
}) {
  const t = useImageGenT()
  const labels = {
    noText: noTextLabel || t('noText'),
    reserve: reserveLabel || t('reserveText'),
    shortcuts: shortcutsLabel || t('shortcuts'),
    clickHint: clickHint || t('safeZoneHint'),
    multiZoneHint: multiZoneHint || t('safeZoneHint'),
    preserve: preserveLabel || t('preserveHowMuch'),
    tone: toneLabel || t('zoneTone'),
    intensityValues: intensityOptions || ['Fully clean', 'Moderately clean', 'Lightly clean'],
    intensityLabels: [t('fullyClean'), t('moderatelyClean'), t('lightlyClean')],
    toneValues: toneOptions || ['Automatic', 'Neutral', 'Warm', 'Cold'],
    toneLabels: [t('automatic'), t('neutral'), t('warm'), t('cold')]
  }
  const clean: CleanZonesState = value || { enabled: false, zones: [], intensity: 'Fully clean', tone: 'Automatic' }
  const zones = clean.zones || []
  const [rw, rh] = String(ratio || '1:1').split(':').map(Number)
  const aspect = Number.isFinite(rw) && Number.isFinite(rh) && rh > 0 ? `${rw} / ${rh}` : '1 / 1'
  const suppressed =
    typeof suppressedProp === 'boolean'
      ? suppressedProp
      : !!clean.enabled && (sceneComplexity === 'complex' || subjectType === 'ambiente_arquitetura')
  const promptSnippet =
    clean.enabled && zones.length > 0
      ? `Leave the ${zones.join(', ')} area(s) ${clean.intensity || 'Fully clean'}. Zone tone: ${clean.tone || 'Automatic'}.`
      : ''

  const setEnabled = (enabled: boolean) =>
    onChange({ ...clean, enabled, zones: enabled && zones.length === 0 ? ['right'] : zones })

  const toggleZone = (zone: string) => {
    const next = toggleIn(zones, zone)
    onChange({ ...clean, enabled: next.length > 0, zones: next })
  }

  const applyPreset = (presetZones: string[]) => {
    onChange({ ...clean, enabled: true, zones: presetZones })
  }

  const slot = (zone: string) => (
    <button
      type="button"
      key={zone}
      aria-pressed={zones.includes(zone)}
      className={cn(
        'flex h-full w-full min-h-11 items-center justify-center border text-[10px] font-semibold transition-colors',
        zones.includes(zone)
          ? 'border-(--ui-accent) bg-(--ui-accent)/18 text-(--ui-accent)'
          : 'border-(--ui-stroke-secondary) bg-(--ui-bg-elevated)/75 text-(--ui-text-tertiary) hover:border-(--ui-text-quaternary) hover:text-(--ui-text-secondary)'
      )}
      onClick={() => toggleZone(zone)}
    >
      {zone === 'top' ? t('top') : zone === 'bottom' ? t('bottom') : zone === 'left' ? t('left') : zone === 'right' ? t('right') : zone === 'center' ? t('center') : SAFE_ZONE_LABELS[zone]}
    </button>
  )

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Chip active={!clean.enabled} onClick={() => setEnabled(false)}>
          {labels.noText}
        </Chip>
        <Chip active={!!clean.enabled} onClick={() => setEnabled(true)}>
          {labels.reserve}
        </Chip>
        {clean.enabled && zones.length > 0 && (
          <span className="inline-flex items-center gap-1 rounded-md border border-(--ui-accent)/30 bg-(--ui-accent)/8 px-2 py-0.5 text-[10px] font-medium text-(--ui-accent)">
            <Codicon name="layers" style={{ fontSize: 11 }} />
            {zones.length} {zones.length > 1 ? t('zones') : t('zone')}: {zones.map((z) => z === 'top' ? t('top') : z === 'bottom' ? t('bottom') : z === 'left' ? t('left') : z === 'right' ? t('right') : z === 'center' ? t('center') : SAFE_ZONE_LABELS[z]).join(' + ')}
          </span>
        )}
      </div>

      {clean.enabled && (
        <div className="flex flex-wrap gap-1.5 if-fade-in">
          <span className="text-[10px] uppercase tracking-wider text-(--ui-text-quaternary) self-center">
            {labels.shortcuts}
          </span>
          {SAFE_ZONE_PRESETS.map((p) => {
            const active = p.zones.every((z) => zones.includes(z)) && p.zones.length === zones.length
            return (
              <Chip key={p.id} active={active} onClick={() => applyPreset(p.zones)}>
                {p.id === 'top-bottom' ? t('topBase') : p.id === 'left-right' ? t('leftRight') : p.id === 'top-only' ? t('topStory') : p.id === 'right-only' ? t('rightBanner') : t('allCorners')}
              </Chip>
            )
          })}
        </div>
      )}

      {suppressed && clean.enabled && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs leading-relaxed">
          <Codicon name="warning" className="mt-0.5 shrink-0 text-amber-500" style={{ fontSize: 14 }} />
          <div className="space-y-1">
            <div className="font-medium text-amber-700 dark:text-amber-300">
              {sceneComplexity === 'complex'
                ? 'Text-safe area suppressed — complex scene keeps full detail.'
                : subjectType === 'ambiente_arquitetura'
                  ? 'Text-safe area suppressed — architecture fills the frame.'
                  : 'Text-safe area suppressed for this scene.'}
            </div>
            <div className="text-[11px] text-amber-700/80 dark:text-amber-300/80">
              Backend will ignore clean zones for complex/architecture. Disable the toggle to remove clutter.
            </div>
          </div>
        </div>
      )}

      {clean.enabled && (
        <div className={cn('if-safe-zone-layout if-fade-in', suppressed && 'opacity-50')}>
          <div className="space-y-2">
            <div className="text-[11px] text-(--ui-text-secondary)">{labels.clickHint}</div>
            <div
              className="mx-auto w-full overflow-hidden rounded-xl border-2 border-(--ui-stroke-secondary) bg-(--ui-bg) p-2 shadow-inner"
              style={{ aspectRatio: aspect, maxHeight: 260 }}
            >
              <div
                className="h-full w-full gap-1"
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                  gridTemplateRows: 'repeat(3, minmax(0, 1fr))'
                }}
              >
                {SLOT_POSITIONS.map((s) => (
                  <div key={s.zone} style={{ gridColumn: s.col, gridRow: s.row }}>
                    {slot(s.zone)}
                  </div>
                ))}
              </div>
            </div>
            <div className="text-[10px] leading-relaxed text-(--ui-text-quaternary)">{labels.multiZoneHint}</div>
          </div>

          <div className="space-y-3">
            <div className="space-y-1">
              <FieldLabel>{labels.preserve}</FieldLabel>
              <select
                value={clean.intensity || 'Fully clean'}
                onChange={(e) => onChange({ ...clean, intensity: e.target.value })}
                className="h-8 w-full rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 text-xs"
                disabled={suppressed}
              >
                {labels.intensityValues.map((opt, index) => (
                  <option key={opt} value={opt}>
                    {labels.intensityLabels[index] || opt}
                  </option>
                ))}
              </select>
              {promptSnippet && (
                <div
                  className={cn(
                    'rounded-md border px-2 py-1.5 font-mono text-[10px] leading-relaxed',
                    suppressed
                      ? 'border-amber-500/30 bg-amber-500/5 text-amber-700/70 line-through dark:text-amber-300/60'
                      : 'border-(--ui-stroke-secondary) bg-(--ui-bg-elevated) text-(--ui-text-tertiary)'
                  )}
                >
                  {promptSnippet}
                  {suppressed && <span className="ml-1 font-sans font-semibold no-underline">[suppressed]</span>}
                </div>
              )}
            </div>
            <div className="space-y-1">
              <FieldLabel>{labels.tone}</FieldLabel>
              <select
                value={clean.tone || 'Automatic'}
                onChange={(e) => onChange({ ...clean, tone: e.target.value })}
                className="h-8 w-full rounded-md border border-(--ui-stroke-secondary) bg-(--ui-bg) px-2 text-xs"
                disabled={suppressed}
              >
                {labels.toneValues.map((opt, index) => (
                  <option key={opt} value={opt}>
                    {labels.toneLabels[index] || opt}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}