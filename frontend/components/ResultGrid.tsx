import { jobFailureAdvice, jobIsFree } from '../jobFailure'
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

/** Grid of generated images. Edit, Variations and Download carry their names; the rest sit in the more menu. */
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
  onAskAgent,
  extraActions,
  locked
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
  /** More-menu items beyond the built-in ones (export pack, copy prompt). */
  extraActions?: Array<{ key: string; icon: string; label: string; run: (img: string) => void }>
  /** Actions that cannot run yet, each with the provider it needs. They show a lock and still answer the click. */
  locked?: Partial<Record<'edit' | 'vary' | 'upscale' | 'removeBg', string>>
}) {
  const t = useImageGenT()
  const [lightbox, setLightbox] = useState<number | null>(null)
  const needs = (key: keyof NonNullable<typeof locked>) => locked?.[key] ? t('accessNeeded', { provider: locked[key] || '' }) : ''
  const menuLabel = (key: keyof NonNullable<typeof locked>, label: string) => locked?.[key] ? `${label} · ${t('needsProvider', { provider: locked[key] || '' })}` : label
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
          ...(onUseAsRef ? [{ key: 'useAsRef', icon: 'link', label: labels.useAsRef, run: () => onUseAsRef(img) }] : []),
          ...(onUpscale ? [{ key: 'upscale', icon: locked?.upscale ? 'lock' : 'zoom-in', label: menuLabel('upscale', labels.upscale), run: () => onUpscale(img) }] : []),
          ...(onBgRemove ? [{ key: 'removeBg', icon: locked?.removeBg ? 'lock' : 'clear-all', label: menuLabel('removeBg', labels.removeBg), run: () => onBgRemove(img) }] : []),
          ...(onAnimate ? [{ key: 'animate', icon: 'play', label: labels.animate, run: () => onAnimate(img, i) }] : []),
          ...(onNotGood ? [{ key: 'notGood', icon: 'thumbsdown', label: t('notGood'), run: () => onNotGood(img) }] : []),
          ...(onAskAgent ? [{ key: 'askAgent', icon: 'comment-discussion', label: t('askAgent'), run: () => onAskAgent(img) }] : []),
          ...(extraActions || []).map((action) => ({ ...action, run: () => action.run(img) }))
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
          <div className="if-result-actions">
            {onEdit && <Button size="sm" className="h-8 gap-1 text-xs" title={needs('edit') || undefined} aria-label={[labels.edit, name, needs('edit')].filter(Boolean).join(', ')} onClick={() => onEdit(img)}><Codicon name={locked?.edit ? 'lock' : 'edit'} style={{ fontSize: 13 }} />{labels.edit}</Button>}
            {onVary && <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" title={needs('vary') || undefined} aria-label={[labels.vary, name, needs('vary')].filter(Boolean).join(', ')} onClick={() => onVary(img, i)}><Codicon name={locked?.vary ? 'lock' : 'refresh'} style={{ fontSize: 13 }} />{labels.vary}</Button>}
            {onDownload && <Button size="sm" variant="outline" className="h-8 gap-1 text-xs" aria-label={`${labels.download}, ${name}`} onClick={() => onDownload(img, i)}><Codicon name="download" style={{ fontSize: 13 }} />{labels.download}</Button>}
            {moreActions.length > 0 && (
              <DropdownMenu>
                <DropdownMenuTrigger
                  type="button"
                  title={t('moreActions')}
                  aria-label={`${t('moreActions')}, ${name}`}
                  className="if-more-button"
                >
                  <Codicon name="more" style={{ fontSize: 14 }} />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="imagegen-ui min-w-48">
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
export function JobProgress({ jobId, onDone, onStatus, onDismiss, onJobReplaced, modelLabel, generatingLabel, failedLabel,
  unknownError, gotIt, cancelledLabel, close, cancel, processing }: {
  jobId: string
  onDone?: (job: JobStatus) => void | Promise<void>
  /** Every read of the job, so the screen around the panel knows when it stopped running. */
  onStatus?: (job: JobStatus) => void
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
  const statusRef = useRef(onStatus)
  statusRef.current = onStatus
  const actionRef = useRef(false)
  useEffect(() => { setTrackedId(jobId) }, [jobId])
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    setJob(null)
    setError('')
    let polling = false
    let failures = 0
    let finished = false
    const poll = async () => {
      if (!alive || polling || finished) return
      polling = true
      if (timer) clearTimeout(timer)
      try {
        const current = await fetchJob(trackedId)
        if (!alive) return
        setJob(current)
        statusRef.current?.(current)
        if (current.status === 'completed') {
          await doneRef.current?.(current)
          finished = true
          if (alive) setError('')
          return
        }
        failures = 0
        setError('')
        if (['failed', 'cancelled', 'interrupted'].includes(current.status)) { finished = true; return }
        timer = setTimeout(poll, jobPollMs(1500, 8000))
      } catch (cause) {
        if (!alive) return
        setError(cause instanceof Error ? cause.message : String(cause))
        // Re-read this job only; never resubmit a generation on a transport error.
        if (++failures <= 3) timer = setTimeout(poll, 1500 * 2 ** (failures - 1))
      } finally {
        polling = false
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
  // The job could not be read at all (another profile's job, or a backend that does not answer).
  const unreachable = !job && !!error
  const errorArgs = Object.fromEntries(Object.entries(job?.errorParams || {}).map(([key, value]) => [key, String(value)]))
  const translatedError = job?.errorCode ? t(job.errorCode, errorArgs) : ''
  const advice = job && jobFailureAdvice(job)
  const detail = advice ? t(advice) : translatedError && translatedError !== job?.errorCode ? translatedError : job?.error || unknownError
  // A retry sends only the images that are missing; with none delivered it is the whole request again.
  const free = !!job && jobIsFree(job)
  const retryLabel = job?.hasPartialResult ? t(free ? 'jobRetryRemaining' : 'jobRetryPaid') : t(free ? 'retry' : 'jobRetryAgainPaid')

  if (!job && !error) return <Skeleton className="h-16 w-full" />
  return <div role="status" aria-live="polite" className="rounded-xl border border-(--ui-stroke-secondary) p-3 space-y-2 if-fade-in">
    <div className="flex items-center gap-2 text-xs">
      <Codicon name={unreachable ? 'warning' : terminal ? job?.status === 'completed' ? 'check' : 'warning' : 'sync'} />
      <strong>{unreachable ? t('job.unreachable') : job?.status === 'failed' ? failedLabel || t('jobFailed') : job?.status === 'interrupted' ? t('job.interrupted') : job?.status === 'cancelled' ? cancelledLabel || t('cancel') : job?.status === 'completed' ? t('jobCompleted') : generatingLabel || t('jobRunning')}</strong>
      {!terminal && !unreachable && <span className="ml-auto font-mono">{fmtElapsed(elapsed)}</span>}
    </div>
    {terminal && job?.status !== 'completed' && detail && <p className="text-xs whitespace-pre-wrap">{detail}</p>}
    {!terminal && !unreachable && <p className="text-xs text-(--ui-text-tertiary)">{job?.message || modelLabel || processing}</p>}
    {error && <p role="alert" className="text-xs text-(--ui-error)">{error}</p>}
    {!terminal && job?.progress != null && <progress className="w-full" max={1} value={job.progress} />}
    <div className="flex flex-wrap gap-2">
      {error && <Button size="sm" disabled={busy} onClick={() => setRevision((value) => value + 1)}>{t('jobReconnect')}</Button>}
      {error && job && onDismiss && <Button size="sm" variant="outline" disabled={busy} onClick={onDismiss}>{close || t('close')}</Button>}
      {terminal && job?.recoverable && <Button size="sm" disabled={busy} onClick={() => void act(async () => {
        const response = await resumeJob(trackedId)
        if (!response.ok) throw new Error(t('jobFailed'))
        invalidateFeed()
        setRevision((value) => value + 1)
      })}>{t('jobResume')}</Button>}
      {terminal && job?.retryable && advice !== 'job.moderated' && <Button size="sm" disabled={busy} onClick={() => void act(async () => {
        const next = await retryJob(trackedId)
        setTrackedId(next.id)
        onJobReplaced?.(next.id)
      })}>{retryLabel}</Button>}
      {terminal && job && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { await doneRef.current?.(job) })}>{job.hasPartialResult ? t('jobViewResult') : gotIt || close || t('close')}</Button>}
      {job && !terminal && job.status !== 'recovering' && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => {
        if (!(await cancelJob(trackedId)).ok) throw new Error(t('jobFailed'))
        setRevision((value) => value + 1)
      })}>{cancel || t('cancel')}</Button>}
      {!job && error && <Button size="sm" variant="outline" onClick={() => void act(async () => { await doneRef.current?.({ id: trackedId, kind: 'generate', status: 'failed' }) })}>{close || t('close')}</Button>}
    </div>
  </div>
}
