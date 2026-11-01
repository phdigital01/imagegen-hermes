/**
 * ImageGen — statusbar pill showing active generation jobs.
 * Mirrors the kanban plugin's statusbar pattern: a small live count that
 * navigates to /imagegen on click. Refetches on pushed job events; polls slowly as a fallback.
 */

import { cn, Codicon, host, Tip, useQuery } from '@hermes/plugin-sdk'

import { rest } from '../api'
import { useImageGenT } from '../i18n'
import { jobPollMs } from '../jobEvents'

export function ActiveJobPill() {
  const t = useImageGenT()
  const { data } = useQuery({
    queryKey: ['imagegen', 'jobs-active'],
    queryFn: () => rest<{ jobs?: Array<{ id: string; status: string }> }>('/jobs').then((d) => d.jobs || []),
    // Idle costs one call per 30s; while something is generating the pill has
    // to keep up with a job that usually finishes inside a minute.
    refetchInterval: (query) => {
      const jobs = query.state.data || []
      return jobs.some((job) => job.status === 'running' || job.status === 'queued') ? jobPollMs(3_000, 15_000) : jobPollMs(30_000, 120_000)
    }
  })

  const active = (data || []).filter((j) => j.status === 'running' || j.status === 'queued').length
  if (active === 0) return null

  return (
    <Tip label={t('generating')}>
      <button
        type="button"
        className={cn(
          'imagegen-ui inline-flex h-full items-center gap-1 rounded-none px-1.5 text-[0.6875rem] tabular-nums transition-colors',
          'text-(--ui-accent) hover:bg-(--chrome-action-hover) hover:text-foreground'
        )}
        onClick={() => host.navigate('/imagegen')}
      >
        <Codicon name="sparkle" size="0.7rem" />
        <span>{active}</span>
      </button>
    </Tip>
  )
}
