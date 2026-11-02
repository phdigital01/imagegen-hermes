/**
 * ImageGen — shared UI primitives.
 * SectionCard, FieldLabel, Chip, Spinner, GRID, Thumb, ReferenceImage.
 */

import { cn, Codicon, icons, Skeleton, Button } from '@hermes/plugin-sdk'
import { useEffect, useId, useState, type ComponentType, type ReactNode } from 'react'

// Resolved by scripts/build_plugin.mjs: thumbnail name -> embedded data URL.
import BUNDLED_THUMBS from 'imagegen:thumbs'

import { fetchImageDataUrl, revealPath } from '../api'


export function bundledThumbUrl(file: string): string {
  return BUNDLED_THUMBS[file] || ''
}

/** CSS grid helper: build a repeat(n, minmax(0,1fr)) style. */
export const GRID = (n: number): React.CSSProperties => ({
  display: 'grid',
  gridTemplateColumns: `repeat(${n}, minmax(0, 1fr))`
})

/** Collapsible section wrapper. */
export function SectionCard({
  title,
  subtitle,
  right,
  children,
  className,
  defaultOpen = true
}: {
  title: string
  subtitle?: string
  right?: ReactNode
  children: ReactNode
  className?: string
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const headerId = useId()
  const panelId = useId()
  return (
    <div className={cn('rounded-xl border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated)', className)}>
      <button
        type="button"
        id={headerId}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left transition-colors hover:bg-(--chrome-action-hover)"
      >
        <div className="flex flex-col min-w-0">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-(--ui-text-tertiary)">{title}</span>
          {subtitle && <span className="truncate text-[11px] text-(--ui-text-quaternary)">{subtitle}</span>}
        </div>
        <div className="flex items-center gap-1.5 flex-shrink-0">
          {right}
          <Codicon name={open ? 'chevron-down' : 'chevron-right'} className="text-(--ui-text-tertiary)" />
        </div>
      </button>
      {open && <div id={panelId} role="region" aria-labelledby={headerId} className="px-3.5 py-3 space-y-3">{children}</div>}
    </div>
  )
}

/** Field label with optional hint. */
export function FieldLabel({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[11px] font-medium text-(--ui-text-secondary)">{children}</span>
      {hint && <span className="text-[10px] text-(--ui-text-quaternary)">{hint}</span>}
    </div>
  )
}

/** Chip / toggle button. */
export function Chip({
  active,
  onClick,
  children,
  color,
  className,
  disabled
}: {
  active?: boolean
  onClick?: () => void
  children: ReactNode
  color?: string
  className?: string
  disabled?: boolean
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={cn(
        'rounded-lg border px-2.5 py-1.5 text-xs font-medium transition-colors',
        active
          ? 'border-(--ui-accent) bg-(--ui-accent)/15 text-(--ui-accent)'
          : 'border-(--ui-stroke-secondary) text-(--ui-text-secondary) hover:bg-(--chrome-action-hover)',
        color === 'purple' && active && '!bg-violet-500 !border-violet-500 !text-white',
        className
      )}
    >
      {children}
    </button>
  )
}

/** Small spinner. */
export function Spinner({ size = 14, className }: { size?: number; className?: string }) {
  return <Skeleton className={cn('rounded-full', className)} style={{ width: size, height: size }} />
}

/** Display a thumbnail image via the plugin backend. */
export function Thumb({ file, iconName, size = 40, rounded = 'rounded-lg', label = '' }: {
  file?: string
  iconName?: string
  size?: number
  rounded?: string
  label?: string
}) {
  const src = file ? bundledThumbUrl(file) : ''
  if (src) {
    return (
      <img
        src={src}
        alt={label || file || ''}
        style={{ width: size, height: size }}
        className={cn('object-cover', rounded)}
        onError={(e) => {
          ;(e.currentTarget as HTMLImageElement).style.display = 'none'
        }}
      />
    )
  }
  const Icon = iconName ? (icons as unknown as Record<string, ComponentType<{ size?: number; className?: string }>>)[iconName] : undefined
  if (Icon) {
    return (
      <div
        style={{ width: size, height: size }}
        className={cn('flex items-center justify-center bg-(--ui-bg-elevated)', rounded)}
      >
        <Icon size={size * 0.5} className="text-(--ui-text-tertiary)" />
      </div>
    )
  }
  return <div style={{ width: size, height: size }} className={cn('bg-(--ui-bg-elevated)', rounded)} />
}

function localPathToUrl(localPath: string): string {
  if (localPath.startsWith('file://')) return localPath
  return `file:///${localPath.replace(/\\/g, '/')}`
}

function isLocalPath(value: string): boolean {
  return /^[a-zA-Z]:[\\/]/.test(value) || value.startsWith('\\\\')
}

/**
 * Anything that can point at an image. Backend payloads use `null` for an
 * absent path while local state uses `undefined`, so both are accepted.
 */
export interface ImageSource {
  imageDataUrl?: string | null
  localPath?: string | null
  url?: string | null
  thumb?: string | null
}

/** One of our served images. The Desktop guards plugin URLs, so a refused address loads through the API. */
export function ServedImage({ src, ...props }: React.ImgHTMLAttributes<HTMLImageElement> & { src: string }) {
  const [inline, setInline] = useState('')

  useEffect(() => setInline(''), [src])

  return (
    <img
      {...props}
      src={inline || src}
      onError={() => {
        if (!inline) void fetchImageDataUrl(src).then(setInline).catch(() => undefined)
      }}
    />
  )
}

/** Image preview with an HTTP-first strategy and local-file fallback. */
export function ImagePreview({
  item,
  className,
  alt
}: {
  item: ImageSource
  className?: string
  alt?: string
}) {
  const primary = displayUrl(item)
  const fallback = item?.localPath ? localPathToUrl(item.localPath) : ''
  const [src, setSrc] = useState(primary || fallback)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    setSrc(primary || fallback)
    setFailed(false)
  }, [fallback, primary])

  if (failed || !src) {
    return (
      <div className={cn('flex items-center justify-center bg-(--ui-bg-elevated) text-(--ui-text-quaternary)', className)}>
        <Codicon name="warning" style={{ fontSize: 16 }} />
      </div>
    )
  }

  return (
    <img
      src={src}
      alt={alt || ''}
      className={className}
      loading="lazy"
      onError={() => {
        if (fallback && src !== fallback) {
          setSrc(fallback)
          return
        }
        setFailed(true)
      }}
    />
  )
}

/** Reference image with a served URL and local-file fallback. */
export function ReferenceImage({
  reference,
  className,
  alt
}: {
  reference: ImageSource & { label?: string }
  className?: string
  alt?: string
}) {
  return <ImagePreview item={reference} alt={alt || reference?.label || ''} className={className} />
}

/** Display a URL for desktop (prefer data URL, then http, then file). */
export function displayUrl(item: ImageSource | null | undefined): string {
  if (!item) return ''
  if (item.imageDataUrl) return isLocalPath(item.imageDataUrl) ? localPathToUrl(item.imageDataUrl) : item.imageDataUrl
  if (item.url) return item.url
  if (item.thumb) return item.thumb
  if (item.localPath) return localPathToUrl(String(item.localPath))
  return ''
}

export async function revealInFolder(path?: string): Promise<boolean> {
  const target = (path || '').trim()
  if (!target) return false
  return revealPath(target)
}

/** Download a URL (handles data: URLs via blob). */
export async function downloadFromUrl(url: string, filename: string): Promise<void> {
  if (url.includes('/api/plugins/imagegen/')) url = await fetchImageDataUrl(url).catch(() => url)
  const a = document.createElement('a')
  if (url.startsWith('data:')) {
    const res = await fetch(url)
    const blob = await res.blob()
    const objUrl = URL.createObjectURL(blob)
    a.href = objUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    setTimeout(() => URL.revokeObjectURL(objUrl), 1000)
    return
  }
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}

/** Copy text to clipboard. */
export async function copyText(text: string): Promise<void> {
  try {
    await navigator.clipboard.writeText(text)
    // notify is handled by the caller if needed
  } catch {
    /* ignore */
  }
}

/** Format elapsed seconds as m:ss. */
export function fmtElapsed(sec: number): string {
  if (sec < 60) return `${Math.floor(sec)}s`
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  return `${m}m${String(s).padStart(2, '0')}s`
}

/**
 * Money for display, symbol included.
 *
 * Per-image prices are routinely sub-cent (FLUX 2 Klein is ~$0.006/MP), so a
 * flat `toFixed(2)` renders a real budget as "$0.00" and the whole message
 * turns into nonsense. Keep four decimals until the value reaches a cent.
 */
export function formatUsd(value: number): string {
  const abs = Math.abs(value)
  return `$${value.toFixed(abs > 0 && abs < 0.01 ? 4 : 2)}`
}

/** Toggle a value in an array. */
export function toggleIn<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v]
}

/** Read a File as a data URL. */
export function fileToDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader()
    r.onload = () => resolve(r.result as string)
    r.onerror = reject
    r.readAsDataURL(file)
  })
}

/** Convert a URL to a data URL (falls back to the original URL on failure). */
export async function urlToDataUrl(url: string): Promise<string> {
  try {
    const r = await fetch(url)
    if (!r.ok) return url
    const blob = await r.blob()
    return await new Promise<string>((resolve) => {
      const fr = new FileReader()
      fr.onload = () => resolve(fr.result as string)
      fr.onerror = () => resolve(url)
      fr.readAsDataURL(blob)
    })
  } catch {
    return url
  }
}

/** Generate a stable unique id. */
export function newId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID()
  return `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

/** Small icon button. */
export function IconButton({
  icon,
  onClick,
  title,
  className,
  disabled,
  'aria-label': ariaLabel
}: {
  icon: string
  onClick?: () => void
  title?: string
  className?: string
  disabled?: boolean
  'aria-label'?: string
}) {
  return (
    <Button
      size="sm"
      variant="ghost"
      disabled={disabled}
      title={title}
      aria-label={ariaLabel}
      onClick={onClick}
      className={cn('h-6 w-6 p-0 text-(--ui-text-tertiary)', className)}
    >
      <Codicon name={icon} />
    </Button>
  )
}