/**
 * Open ImageGen on a given tab from outside its page (the chat card).
 * The page may not be mounted yet, so the request waits until it is taken.
 */
import { host } from '@hermes/plugin-sdk'

export interface OpenRequest {
  tab: 'edit' | 'gallery'
  image?: string
}

type Listener = (request: OpenRequest) => void

let pending: OpenRequest | null = null
const listeners = new Set<Listener>()

export function openInImageGen(request: OpenRequest): void {
  pending = request
  for (const listener of listeners) listener(request)
  host.navigate('/imagegen')
}

/** The request made before the page mounted, if any; taking it clears it. */
export function takePendingOpen(): OpenRequest | null {
  const request = pending
  pending = null
  return request
}

export function onOpenRequest(listener: Listener): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
