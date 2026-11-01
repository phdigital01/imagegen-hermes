/**
 * ImageGen — small pane beside the chat: the generation in progress and the
 * latest images, each one a click away from the chat composer or the editor.
 */

import { Codicon, host, useQuery } from '@hermes/plugin-sdk'

import { ID, fetchFeed, fetchJobs, fetchLocalImagePath } from '../api'
import { imageRef, writeToChat } from '../chat'
import { useImageGenT } from '../i18n'
import { jobPollMs } from '../jobEvents'
import { openInImageGen } from '../navigation'
import type { FeedImage } from '../types'
import { ImagePreview, displayUrl } from './ui-helpers'

const RECENT = 12
const PANE_ID = 'imagegen-side'

/** Open the pane beside the chat. Desktops without `openWorkspace` get the full page. */
export function openSidePane(title: string): void {
  if (typeof host.openWorkspace !== 'function') {
    host.navigate('/imagegen')
    return
  }
  host.openWorkspace(PANE_ID, {
    title,
    dock: { pane: 'workspace', pos: 'right' },
    minWidth: '15rem',
    render: () => <SidePane />
  })
}

function SidePane() {
  const t = useImageGenT()
  const jobs = useQuery({
    queryKey: [ID, 'jobs'],
    queryFn: fetchJobs,
    refetchInterval: (query) => (query.state.data || []).some(isActive) ? jobPollMs(3_000, 15_000) : jobPollMs(30_000, 120_000)
  })
  const feed = useQuery({
    queryKey: [ID, 'feed', { limit: RECENT }],
    queryFn: () => fetchFeed({ limit: RECENT }),
    staleTime: 30_000
  })

  const active = (jobs.data || []).filter(isActive)
  const images = (feed.data?.items || []).flatMap((item) => item.images.slice(0, 1).map((image) => ({ image, model: item.model }))).slice(0, RECENT)

  const sendToChat = async (image: FeedImage) => {
    try {
      const path = image.localPath || await fetchLocalImagePath(displayUrl(image))
      const sent = await writeToChat(imageRef(path))
      host.notify({ id: 'imagegen-side-send', kind: sent ? 'success' : 'info', message: t(sent ? 'sidePaneSent' : 'agentNoChat') })
    } catch (error) {
      host.notifyError(error, t('sidePaneSendFailed'))
    }
  }

  return (
    <div className="imagegen-ui flex h-full flex-col overflow-hidden text-xs">
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Codicon name="paintcan" size="0.85rem" />
        <span className="flex-1 font-semibold">ImageGen</span>
        <button type="button" className="rounded px-1.5 py-0.5 text-muted-foreground hover:bg-(--chrome-action-hover) hover:text-foreground" onClick={() => host.navigate('/imagegen')}>
          {t('sidePaneFull')}
        </button>
      </div>

      {active.length > 0 && (
        <div className="space-y-1 border-b border-border px-3 py-2">
          {active.map((job) => (
            <div key={job.id} className="flex items-center gap-2">
              <Codicon name="loading" className="animate-spin" size="0.75rem" />
              <span className="min-w-0 flex-1 truncate">{job.message || t('generating')}</span>
              {typeof job.progress === 'number' && <span className="tabular-nums text-muted-foreground">{Math.round(job.progress * 100)}%</span>}
            </div>
          ))}
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-2">
        <div className="mb-1.5 px-1 text-[0.6875rem] font-medium text-muted-foreground">{t('sidePaneRecent')}</div>
        {!images.length && !feed.isLoading && <p className="px-1 text-muted-foreground">{t('sidePaneEmpty')}</p>}
        <div className="grid grid-cols-2 gap-1.5">
          {images.map(({ image, model }) => (
            <div key={image.galleryId || image.url} className="group relative aspect-square overflow-hidden rounded border border-border">
              <ImagePreview item={image} className="h-full w-full object-cover" alt={model} />
              <div className="absolute inset-x-0 bottom-0 flex gap-1 bg-black/60 p-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
                <button type="button" title={t('sidePaneSend')} className="flex flex-1 items-center justify-center gap-1 rounded bg-white/15 py-1 text-[0.625rem] text-white hover:bg-white/25" onClick={() => void sendToChat(image)}>
                  <Codicon name="comment" size="0.7rem" /> {t('sidePaneSend')}
                </button>
                <button type="button" title={t('chatCardEdit')} aria-label={t('chatCardEdit')} className="rounded bg-white/15 px-1.5 text-white hover:bg-white/25" onClick={() => openInImageGen({ tab: 'edit', image: displayUrl(image) })}>
                  <Codicon name="edit" size="0.7rem" />
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function isActive(job: { status: string }): boolean {
  return job.status === 'running' || job.status === 'queued'
}
