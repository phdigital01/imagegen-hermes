/**
 * ImageGen — result grid and job progress.
 */

import { Codicon, Button, Skeleton, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, cn } from '@hermes/plugin-sdk'
import { useEffect, useRef, useState } from 'react'

import type { JobStatus } from '../types'
import { fetchJob, cancelJob, retryJob, resumeJob, invalidateFeed } from '../api'
import { useImageGenT } from '../i18n'
import { jobPollMs, onJobChanged } from '../jobEvents'
import { GRID, ServedImage, fmtElapsed } from './ui-helpers'

/** Grid of generated images with action buttons (always visible). */
export function ResultGrid({
  images,
  onVary,
  onEdit,
  onUseAsRef,
  onAnimate,
  onUpscale,
  onBgRemove,
  onDownload,
  downloadLabel,
  varyLabel,
  upscaleLabel,
  removeBgLabel,
  editLabel,
  useAsRefLabel,
  animateLabel,
  onNotGood,
  onAskAgent
}: {
  images: string[]
  onVary?: (img: string, i: number) => void
  onEdit?: (img: string) => void
  onUseAsRef?: (img: string) => void
  onAnimate?: (img: string, i: number) => void
  onUpscale?: (img: string) => void
  onBgRemove?: (img: string) => void
  onDownload?: (img: string, i: number) => void
  downloadLabel?: string
  varyLabel?: string
  upscaleLabel?: string
  removeBgLabel?: string
  editLabel?: string
  useAsRefLabel?: string
  animateLabel?: string
  onNotGood?: (img: string) => void
  onAskAgent?: (img: string) => void
}) {
  const t = useImageGenT()
  const [lightbox, setLightbox] = useState<number | null>(null)
  const labels = {
    download: downloadLabel || t('download'),
    vary: varyLabel || t('vary'),
    upscale: upscaleLabel || t('upscale'),
    removeBg: removeBgLabel || t('removeBg'),
    edit: editLabel || t('editImage'),
    useAsRef: useAsRefLabel || t('useAsRef'),
    animate: animateLabel || t('animate')
  }
  const columns = Math.max(1, Math.min(2, (images || []).length))
  return (
    <div className="gap-3" style={GRID(columns)}>
      {(images || []).map((img, i) => {
        // The four primary actions stay one click away; everything else moves
        // into a "more actions" menu so the overlay never exceeds the card width.
        const moreActions: Array<{ key: string; icon: string; label: string; run: () => void }> = [
          ...(onUpscale ? [{ key: 'upscale', icon: 'zoom-in', label: labels.upscale, run: () => onUpscale(img) }] : []),
          ...(onBgRemove ? [{ key: 'removeBg', icon: 'clear-all', label: labels.removeBg, run: () => onBgRemove(img) }] : []),
          ...(onAnimate ? [{ key: 'animate', icon: 'play', label: labels.animate, run: () => onAnimate(img, i) }] : []),
          ...(onNotGood ? [{ key: 'notGood', icon: 'thumbsdown', label: t('notGood'), run: () => onNotGood(img) }] : []),
          ...(onAskAgent ? [{ key: 'askAgent', icon: 'comment-discussion', label: t('askAgent'), run: () => onAskAgent(img) }] : [])
        ]
        const name = t('resultImageName', { n: String(i + 1) })
        return (
        <div
          key={`result-${i}-${img.slice(-12)}`}
          className="if-pop group relative overflow-hidden rounded-xl border border-(--ui-stroke-secondary) bg-(--ui-bg-elevated)"
        >
          <div className={cn('if-checker relative', columns === 1 ? 'if-result-single' : 'aspect-square')}>
            <button type="button" aria-label={name} className={cn('w-full', columns === 1 ? 'block' : 'h-full')} onClick={() => setLightbox(i)}><ServedImage src={img} alt={name} className={columns === 1 ? undefined : 'h-full w-full object-contain'} loading="lazy" /></button>
          </div>
          <div className="absolute inset-x-0 bottom-0 flex items-center justify-center gap-1 bg-black/65 p-2 opacity-60 transition-opacity group-hover:opacity-100">
            {onDownload && (
              <button
                type="button"
                title={labels.download}
                aria-label={`${labels.download}, ${name}`}
                className="rounded-md bg-white/15 p-1.5 text-white hover:bg-white/30 transition-colors"
                onClick={() => onDownload(img, i)}
              >
                <Codicon name="download" style={{ fontSize: 14 }} />
              </button>
            )}
            {onEdit && (
              <button
                type="button"
                title={labels.edit}
                aria-label={`${labels.edit}, ${name}`}
                className="rounded-md bg-white/15 p-1.5 text-white hover:bg-white/30 transition-colors"
                onClick={() => onEdit(img)}
              >
                <Codicon name="edit" style={{ fontSize: 14 }} />
              </button>
            )}
            {onVary && (
              <button
                type="button"
                title={labels.vary}
                aria-label={`${labels.vary}, ${name}`}
                className="rounded-md bg-white/15 p-1.5 text-white hover:bg-white/30 transition-colors"
                onClick={() => onVary(img, i)}
              >
                <Codicon name="refresh" style={{ fontSize: 14 }} />
              </button>
            )}
            {onUseAsRef && (
              <button
                type="button"
                title={labels.useAsRef}
                aria-label={`${labels.useAsRef}, ${name}`}
                className="rounded-md bg-white/15 p-1.5 text-white hover:bg-white/30 transition-colors"
                onClick={() => onUseAsRef(img)}
              >
                <Codicon name="link" style={{ fontSize: 14 }} />
              </button>
            )}
            {moreActions.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger
                  type="button"
                  title={t('moreActions')}
                  aria-label={`${t('moreActions')}, ${name}`}
                  className="rounded-md bg-white/15 p-1.5 text-white hover:bg-white/30 transition-colors"
                >
                  <Codicon name="more" style={{ fontSize: 14 }} />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="imagegen-ui min-w-40">
                  {moreActions.map((action) => (
                    <DropdownMenuItem key={action.key} onClick={action.run}>
                      <Codicon name={action.icon} style={{ fontSize: 13 }} />
                      {action.label}
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            )}
          </div>
          {i === 0 && images.length > 1 && (
            <span className="absolute left-2 top-2 rounded bg-black/60 px-1.5 py-0.5 text-[9px] font-semibold text-white">
              {i + 1}/{images.length}
            </span>
          )}
        </div>
        )
      })}
      {lightbox !== null && images[lightbox] && <div className="if-lightbox" role="dialog" aria-modal="true" aria-label={t('resultImageName', { n: String(lightbox + 1) })} onClick={() => setLightbox(null)}><button type="button" aria-label={t('close')} onClick={() => setLightbox(null)}><Codicon name="close" /></button><ServedImage src={images[lightbox]} alt={t('resultImageName', { n: String(lightbox + 1) })} onClick={(event) => event.stopPropagation()} /></div>}
    </div>
  )
}

/** Live job status with explicit recovery, retrieval, and paid retry actions. */
export function JobProgress({ jobId, onDone, onDismiss, onJobReplaced, modelLabel, generatingLabel, failedLabel,
  unknownError, gotIt, cancelledLabel, close, cancel, processing }: {
  jobId: string
  onDone?: (job: JobStatus) => void | Promise<void>
  onDismiss?: () => void
  onJobReplaced?: (id: string) => void
  modelLabel?: string
  generatingLabel?: string
  failedLabel?: string
  unknownError?: string
  gotIt?: string
  cancelledLabel?: string
  close?: string
  cancel?: string
  processing?: string
}) {
  const t = useImageGenT()
  const [trackedId, setTrackedId] = useState(jobId)
  const [job, setJob] = useState<JobStatus | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const doneRef = useRef(onDone)
  doneRef.current = onDone
  const actionRef = useRef(false)
  useEffect(() => { setTrackedId(jobId) }, [jobId])
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    setJob(null)
    setError('')
    const poll = async () => {
      try {
        const current = await fetchJob(trackedId)
        if (!alive) return
        setJob(current)
        if (current.status === 'completed') {
          await doneRef.current?.(current)
          return
        }
        if (['failed', 'cancelled', 'interrupted'].includes(current.status)) return
        timer = setTimeout(poll, jobPollMs(1500, 8000))
      } catch (cause) {
        if (alive) setError(cause instanceof Error ? cause.message : String(cause))
      }
    }
    // A pushed change for this job refetches at once instead of waiting for the timer.
    const stopEvents = onJobChanged((change) => {
      if (change.id !== trackedId || !alive) return
      if (timer) clearTimeout(timer)
      void poll()
    })
    void poll()
    return () => { alive = false; stopEvents(); if (timer) clearTimeout(timer) }
  }, [trackedId, revision])
  useEffect(() => {
    setElapsed(job?.elapsed || 0)
    if (!job || !['running', 'queued', 'recovering'].includes(job.status)) return
    const timer = setInterval(() => setElapsed((value) => value + 1), 1000)
    return () => clearInterval(timer)
  }, [job?.status])

  const act = async (operation: () => Promise<void>) => {
    if (actionRef.current) return
    actionRef.current = true
    setBusy(true)
    setError('')
    try { await operation() } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { actionRef.current = false; setBusy(false) }
  }
  const terminal = !!job && ['failed', 'cancelled', 'interrupted', 'completed'].includes(job.status)
  const errorArgs = Object.fromEntries(Object.entries(job?.errorParams || {}).map(([key, value]) => [key, String(value)]))
  const translatedError = job?.errorCode ? t(job.errorCode, errorArgs) : ''
  const detail = translatedError && translatedError !== job?.errorCode ? translatedError : job?.error || unknownError

  if (!job && !error) return <Skeleton className="h-16 w-full" />
  return <div role="status" aria-live="polite" className="rounded-xl border border-(--ui-stroke-secondary) p-3 space-y-2 if-fade-in">
    <div className="flex items-center gap-2 text-xs">
      <Codicon name={terminal ? job?.status === 'completed' ? 'check' : 'warning' : 'sync'} />
      <strong>{job?.status === 'failed' ? failedLabel || t('jobFailed') : job?.status === 'interrupted' ? t('job.interrupted') : job?.status === 'cancelled' ? cancelledLabel || t('cancel') : job?.status === 'completed' ? t('jobCompleted') : generatingLabel || t('jobRunning')}</strong>
      {!terminal && <span className="ml-auto font-mono">{fmtElapsed(elapsed)}</span>}
    </div>
    {terminal && detail && <p className="text-xs whitespace-pre-wrap">{detail}</p>}
    {!terminal && <p className="text-xs text-(--ui-text-tertiary)">{job?.message || modelLabel || processing}</p>}
    {error && <p role="alert" className="text-xs text-(--ui-error)">{error}</p>}
    {!terminal && job?.progress != null && <progress className="w-full" max={1} value={job.progress} />}
    <div className="flex flex-wrap gap-2">
      {error && <Button size="sm" disabled={busy} onClick={() => setRevision((value) => value + 1)}>{t('jobReconnect')}</Button>}
      {error && onDismiss && <Button size="sm" variant="outline" disabled={busy} onClick={onDismiss}>{close || t('close')}</Button>}
      {terminal && job?.recoverable && <Button size="sm" disabled={busy} onClick={() => void act(async () => {
        const response = await resumeJob(trackedId)
        if (!response.ok) throw new Error(t('jobFailed'))
        invalidateFeed()
        setRevision((value) => value + 1)
      })}>{t('jobResume')}</Button>}
      {terminal && job?.retryable && <Button size="sm" disabled={busy} onClick={() => void act(async () => {
        const next = await retryJob(trackedId)
        setTrackedId(next.id)
        onJobReplaced?.(next.id)
      })}>{t('jobRetryPaid')}</Button>}
      {terminal && job && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { await doneRef.current?.(job) })}>{job.hasPartialResult ? t('jobViewResult') : gotIt || close || t('close')}</Button>}
      {!terminal && job?.status !== 'recovering' && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => {
        if (!(await cancelJob(trackedId)).ok) throw new Error(t('jobFailed'))
        setRevision((value) => value + 1)
      })}>{cancel || t('cancel')}</Button>}
      {!job && error && <Button size="sm" variant="outline" onClick={() => void act(async () => { await doneRef.current?.({ id: trackedId, kind: 'generate', status: 'failed' }) })}>{close || t('close')}</Button>}
    </div>
  </div>
}
