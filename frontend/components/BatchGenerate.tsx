import { jobFailureAdvice } from '../jobFailure'
import { Button, Dialog, DialogContent, DialogHeader, DialogTitle, Textarea, useQuery } from '@hermes/plugin-sdk'
import { useRef, useState } from 'react'
import { ID, invalidateFeed, invalidateGallery, queryClient, rest, resumeJob } from '../api'
import { useImageGenT } from '../i18n'
import { jobPollMs } from '../jobEvents'
import type { JobStatus } from '../types'
import { ServedImage, formatUsd, newId } from './ui-helpers'

type Item = Omit<Partial<JobStatus>, 'status'> & { prompt: string; status: JobStatus['status'] | 'unsent' | 'expired'; image?: string }
type Batch = { id: string; model: string; items: Item[] }
type Response = { batch: Batch | null }
const active = (item: Item) => ['queued', 'running', 'recovering'].includes(item.status)
const key = [ID, 'latest-batch']

/** Many prompts at once. `inline` shows the list in the composer ("Several ideas" mode) instead of a dialog. */
export function BatchGenerate({ model, aspect, refs, blocked, estimate, remaining, prepare, inline = false }: {
  model: string; aspect: string; refs: number; blocked: string; estimate: number | null; remaining: number | null
  prepare: () => Promise<Record<string, unknown>>; inline?: boolean
}) {
  const t = useImageGenT()
  const [dialogOpen, setOpen] = useState(false)
  const open = inline || dialogOpen
  const [newList, setNewList] = useState(false)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const locked = useRef(false)
  const attempt = useRef<Record<string, unknown> | null>(null)
  const latest = useQuery({
    queryKey: key, queryFn: () => rest<Response>('/batches/latest'), enabled: open,
    refetchInterval: (query) => open && query.state.data?.batch?.items.some(active) ? jobPollMs(1800, 8000) : false
  })
  const batch = latest.data?.batch
  const prompts = draft.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
  const cost = estimate === null ? null : estimate * prompts.length
  const overBudget = cost !== null && remaining !== null && cost > remaining
  const editing = !batch || newList
  const run = async (action: () => Promise<void>) => {
    if (locked.current) return
    locked.current = true
    setBusy(true)
    setError('')
    try { await action() }
    catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
      await latest.refetch()
    } finally { locked.current = false; setBusy(false) }
  }
  const start = () => run(async () => {
    if (!attempt.current) attempt.current = { id: newId(), previousId: batch?.id, prompts, settings: await prepare() }
    const response = await rest<Response>('/batches', 'POST', attempt.current)
    queryClient.setQueryData(key, response)
    attempt.current = null
    setNewList(false)
    setDraft('')
    invalidateGallery()
    invalidateFeed()
  })
  const retry = (item: Item, index: number) => run(async () => {
    if (item.recoverable && item.id) await resumeJob(item.id)
    else await rest(`/batches/${batch!.id}/items/${index}/retry`, 'POST', { jobId: item.id })
    await latest.refetch()
    invalidateGallery()
    invalidateFeed()
  })
  const total = batch?.items.length || 0
  const completed = batch?.items.filter(item => item.status === 'completed').length || 0
  const body = <>
        {latest.isError && <div role="alert">{String(latest.error)} <Button onClick={() => void latest.refetch()}>{t('retry')}</Button></div>}
        {latest.data && (editing ? <>
          <label className="space-y-1"><span>{t('batch.lines')}</span>
            <Textarea rows={6} value={draft} disabled={busy} onChange={event => { setDraft(event.target.value); attempt.current = null }} />
          </label>
          <p>{[model, aspect, t('batch.refs', { n: String(refs) })].filter(Boolean).join(' · ')}</p>
          <p aria-live="polite">{t('batch.count', { n: String(prompts.length) })}{cost !== null && ` · ~${formatUsd(cost)}`}</p>
          {blocked && <p role="status">{blocked}</p>}
          {overBudget && <p role="alert">{t('batch.budget')}</p>}
          <div className="flex flex-wrap gap-2">
            <Button disabled={busy || !!blocked || overBudget || prompts.length < 1 || prompts.length > 32 || prompts.some(p => p.length > 16000) || latest.isFetching && !batch} onClick={() => void start()}>{t('batch.start')}</Button>
            {batch && <Button variant="outline" disabled={busy} onClick={() => {setNewList(false); attempt.current = null}}>{t('cancel')}</Button>}
          </div>
        </> : <>
          <p aria-live="polite">{t('batch.progress', { n: String(completed), total: String(total) })} · {batch.model}</p>
          <ol className="if-batch-items">{batch.items.map((item, i) => {
            const advice = jobFailureAdvice(item)
            return <li key={i}>
            {item.image && <ServedImage src={item.image} alt={item.prompt} />}
            <div><strong>{i + 1}. {item.prompt}</strong>
              <p>{t('batch.' + item.status)}{item.error && ` · ${advice ? t(advice) : item.error}`}</p>
              {((item.retryable && advice !== 'job.moderated') || item.recoverable || item.status === 'unsent') && <Button size="sm" variant="outline" disabled={busy} onClick={() => void retry(item, i)}>{t(item.recoverable ? 'batch.recover' : 'retry')}</Button>}
            </div>
          </li>})}</ol>
          {!batch.items.some(active) && <Button variant="outline" onClick={() => { attempt.current = null; setNewList(true); setError('') }}>{t('batch.new')}</Button>}
        </>)}
        {!latest.data && !latest.isError && <p role="status">{t('batch.loading')}</p>}
        {error && <p role="alert">{error}</p>}
  </>
  if (inline) return <div className="if-batch-inline" onKeyDown={event => event.stopPropagation()}>{body}</div>
  return <>
    <Button variant="outline" onClick={() => { setOpen(true); setError('') }}>{t('batch.open')}</Button>
    <Dialog open={dialogOpen} onOpenChange={setOpen}>
      <DialogContent className="imagegen-ui if-batch-dialog" onKeyDown={event => event.stopPropagation()}>
        <DialogHeader><DialogTitle>{t('batch.open')}</DialogTitle></DialogHeader>
        {body}
      </DialogContent>
    </Dialog>
  </>
}
