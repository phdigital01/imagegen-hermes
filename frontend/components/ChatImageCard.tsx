/**
 * ImageGen — action strip the agent puts under an image it made through
 * ImageGen (`::imagegen-image{id="..."}`). Hermes already shows the image
 * itself, so this only adds a small thumbnail and the ImageGen actions.
 */

import { Codicon, useQuery } from '@hermes/plugin-sdk'

import { rest } from '../api'
import { useImageGenT } from '../i18n'
import { openInImageGen } from '../navigation'
import { ImagePreview } from './ui-helpers'

// Directive attributes come from model output: accept only gallery ids.
const SAFE_ID = /^[A-Za-z0-9_-]{1,80}$/

interface GalleryItem {
  id: string
  provider?: string
  model?: string
  prompt?: string
  url: string
  localPath?: string
}

export function ChatImageCard({ id, streaming }: { id?: string; streaming: boolean }) {
  const t = useImageGenT()
  const valid = !!id && SAFE_ID.test(id)
  const { data, isError } = useQuery({
    queryKey: ['imagegen', 'gallery-item', id],
    queryFn: () => rest<GalleryItem>(`/gallery/item/${encodeURIComponent(id || '')}`),
    enabled: valid && !streaming,
    staleTime: 5 * 60_000,
    retry: false
  })

  if (!valid || streaming) return null
  if (isError) return <p className="imagegen-ui my-1 text-xs text-muted-foreground">{t('chatCardMissing')}</p>
  if (!data) return null

  return (
    // `not-prose`: the chat's typography gives every image a 2em margin, which doubled the card's height.
    <div className="imagegen-ui not-prose my-2 flex max-w-md items-center gap-3 rounded-md border border-border bg-(--ui-bg-elevated,transparent) p-2">
      <ImagePreview item={{ url: data.url, localPath: data.localPath }} className="size-10 shrink-0 rounded object-cover" />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1 text-xs font-medium">
          <Codicon name="paintcan" size="0.75rem" /> {t('chatCardSaved')}
        </div>
        {data.model && <div className="truncate text-[0.6875rem] text-muted-foreground">{data.model}</div>}
      </div>
      <button
        type="button"
        className="inline-flex h-7 items-center gap-1 rounded border border-border px-2 text-xs hover:bg-(--chrome-action-hover)"
        onClick={() => openInImageGen({ tab: 'edit', image: data.url })}
      >
        <Codicon name="edit" size="0.75rem" /> {t('chatCardEdit')}
      </button>
      <button
        type="button"
        className="inline-flex h-7 items-center gap-1 rounded px-2 text-xs text-muted-foreground hover:bg-(--chrome-action-hover) hover:text-foreground"
        onClick={() => openInImageGen({ tab: 'gallery' })}
      >
        {t('chatCardGallery')}
      </button>
    </div>
  )
}
