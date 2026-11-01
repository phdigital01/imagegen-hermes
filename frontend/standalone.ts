/** Disk entry: all code and CSS ship in one ESM file; React stays host-owned. */
import type { HermesPlugin } from '@hermes/plugin-sdk'

import plugin from './plugin'
// Resolved by scripts/build_plugin.mjs after compiling the plugin's utilities.
import css from 'imagegen:styles'

const standalone: HermesPlugin = {
  ...plugin,
  register(ctx) {
    const style = document.createElement('style')
    style.dataset.imagegenStyles = 'standalone'
    style.textContent = css
    document.head.appendChild(style)
    ctx.onDispose(() => style.remove())
    try {
      plugin.register(ctx)
    } catch (error) {
      style.remove()
      throw error
    }
  }
}

export default standalone
