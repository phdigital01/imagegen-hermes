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

/** The image server at the address in the plugin settings: no key and no cost. */
export function isLocal(provider: string): boolean {
  return provider === 'local'
}

/** Translation key for the kind of access a provider takes. */
export function accessLabelKey(provider: string): string {
  if (isLocal(provider)) return 'accessLocal'
  return isSubscription(provider) ? 'accessSubscription' : 'accessApiKey'
}

/** Provider names come from the backend in English; only the local server has a translated one. */
export function providerLabel(t: (key: string) => string, provider: { name: string; display_name?: string }): string {
  return isLocal(provider.name) ? t('providerLocal') : provider.display_name || provider.name
}

export function providerReady(providers: Provider[], name: string): boolean {
  const provider = providers.find((item) => item.name === name)
  return !!provider && !!provider.configured && provider.available !== false
}

/** Ready providers other than FAL and Magnific with a model that takes references: the Edit tab can use them. */
export function editEngines(providers: Provider[]): Provider[] {
  return providers.filter((item) => item.name !== 'fal' && item.name !== 'magnific'
    && providerReady(providers, item.name) && item.models.some((model) => (model.capabilities?.maxReferences || 0) > 0))
}

export function providerUnlocksKey(provider: string): string {
  if (provider === 'fal') return 'accessUnlocksFal'
  if (provider === 'magnific') return 'accessUnlocksMagnific'
  if (isLocal(provider)) return 'accessUnlocksLocal'
  return 'accessUnlocksOther'
}
