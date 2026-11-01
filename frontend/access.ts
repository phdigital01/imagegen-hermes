/**
 * ImageGen — which access each provider needs and what it unlocks.
 * The interface never hides a function: one without access says what it needs and links to Settings.
 */

import type { Provider } from './types'

/** Providers paid through a subscription login; all others use an API key. */
const SUBSCRIPTION_PROVIDERS = ['openai-codex', 'nous']

export function isSubscription(provider: string): boolean {
  return SUBSCRIPTION_PROVIDERS.includes(provider)
}

export function providerReady(providers: Provider[], name: string): boolean {
  const provider = providers.find((item) => item.name === name)
  return !!provider && !!provider.configured && provider.available !== false
}

export function providerUnlocksKey(provider: string): string {
  if (provider === 'fal') return 'accessUnlocksFal'
  if (provider === 'magnific') return 'accessUnlocksMagnific'
  return 'accessUnlocksOther'
}
