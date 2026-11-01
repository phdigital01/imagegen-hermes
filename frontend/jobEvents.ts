/**
 * Job change events pushed by the backend (`plugin.imagegen.job.changed`).
 * Screens refetch when a job changes instead of polling fast; polling stays as
 * a slow safety net for hosts or processes that cannot deliver the event.
 */

export interface JobChange {
  id: string
  kind?: string
  status?: string
}

type Listener = (change: JobChange) => void

const listeners = new Set<Listener>()
let live = false

export function emitJobChanged(change: JobChange): void {
  live = true
  for (const listener of listeners) listener(change)
}

export function onJobChanged(listener: Listener): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}

/** `fast` until the first pushed event proves the channel works, then `slow`. */
export function jobPollMs(fast: number, slow: number): number {
  return live ? slow : fast
}
