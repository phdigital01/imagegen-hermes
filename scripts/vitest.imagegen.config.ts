// Copied into apps/desktop of a Hermes checkout by check_frontend.py; the packages resolve from there.
import path from 'node:path'

import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const virtualModules: Record<string, string> = {
  'imagegen:styles': 'export default ""',
  'imagegen:thumbs': 'export default {}'
}

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'imagegen-virtual-modules',
      resolveId: id => (id in virtualModules ? `\0${id}` : undefined),
      load: id => (id.startsWith('\0') ? virtualModules[id.slice(1)] : undefined)
    }
  ],
  resolve: {
    alias: [
      { find: '@hermes/plugin-sdk', replacement: path.resolve(import.meta.dirname, 'src/sdk/index.ts') },
      { find: '@hermes/shared', replacement: path.resolve(import.meta.dirname, '../shared/src/index.ts') },
      { find: '@', replacement: path.resolve(import.meta.dirname, 'src') }
    ]
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/plugins/imagegen/**/*.test.{ts,tsx}']
  }
})
