/** ImageGen — the summary shown before a generation that asks for confirmation. */

import { Badge, Button, Codicon } from '@hermes/plugin-sdk'

/** Pre-generation summary panel. */
export function PreGenSummary({
  action,
  onConfirm,
  onCancel,
  modelLabel,
  promptPreview,
  refCount,
  aspectRatio,
  warnings,
  skipConfirm,
  onSkipChange,
  title = 'Confirm generation',
  optimizeTitle = 'Optimize prompt?',
  cancel = 'Cancel',
  generate = 'Generate',
  optimize = 'Optimize',
  dontAskAgain = 'Do not ask again',
  refsLabel = 'reference(s)',
  warningsLabel = 'warning(s)',
  cleanZones,
  cleanZonesSuppressed
}: {
  action: string
  onConfirm: () => void
  onCancel: () => void
  modelLabel?: string
  promptPreview?: string
  refCount: number
  aspectRatio?: string
  warnings: number
  skipConfirm: boolean
  onSkipChange: (v: boolean) => void
  title?: string
  optimizeTitle?: string
  cancel?: string
  generate?: string
  optimize?: string
  dontAskAgain?: string
  refsLabel?: string
  warningsLabel?: string
  cleanZones?: { enabled: boolean; zones: string[]; intensity?: string }
  cleanZonesSuppressed?: boolean
}) {
  return (
    <div className="if-pop rounded-xl border border-(--ui-accent)/40 bg-(--ui-accent)/6 p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Codicon name="info" className="text-(--ui-accent)" style={{ fontSize: 15 }} />
          <span className="text-xs font-semibold">{action === 'optimize' ? optimizeTitle : title}</span>
        </div>
        <Button size="sm" variant="ghost" className="h-6 px-1.5" onClick={onCancel}>
          <Codicon name="close" style={{ fontSize: 13 }} />
        </Button>
      </div>
      {action !== 'optimize' && (
        <div className="flex flex-wrap gap-1.5 text-[11px]">
          <Badge variant="muted" className="text-[10px]">
            {modelLabel || 'model'}
          </Badge>
          {aspectRatio && (
            <Badge variant="outline" className="text-[10px]">
              {aspectRatio}
            </Badge>
          )}
          {refCount > 0 && (
            <Badge variant="outline" className="text-[10px]">
              {refCount} {refsLabel}
            </Badge>
          )}
          {cleanZones?.enabled && cleanZonesSuppressed ? (
            <Badge variant="outline" className="text-[10px] border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400">
              No text suppressed
            </Badge>
          ) : cleanZones?.enabled && (cleanZones.zones?.length || 0) > 0 ? (
            <Badge variant="outline" className="text-[10px]">
              Text-safe: {cleanZones.zones.join('+')}
            </Badge>
          ) : null}
          {warnings > 0 && (
            <Badge variant="outline" className="text-[10px] text-amber-500">
              {warnings} {warningsLabel}
            </Badge>
          )}
        </div>
      )}
      {promptPreview && (
        <div className="max-h-24 overflow-y-auto rounded-md bg-(--ui-bg) border border-(--ui-stroke-secondary) p-2 text-[10.5px] font-mono leading-relaxed whitespace-pre-wrap">
          {promptPreview}
        </div>
      )}
      <div className="flex items-center justify-between gap-2 pt-1">
        <label className="flex cursor-pointer items-center gap-1.5 text-[10px] text-(--ui-text-tertiary)">
          <input
            type="checkbox"
            checked={!!skipConfirm}
            className="accent-(--ui-accent)"
            onChange={(e) => onSkipChange(e.target.checked)}
          />
          {dontAskAgain}
        </label>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={onCancel}>
            {cancel}
          </Button>
          <Button size="sm" className="h-7 text-xs gap-1" onClick={() => onConfirm()}>
            {action === 'optimize' ? optimize : generate}
            <Codicon name="arrow-right" style={{ fontSize: 12 }} />
          </Button>
        </div>
      </div>
    </div>
  )
}
