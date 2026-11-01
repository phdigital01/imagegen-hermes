/** Build the Git-installable package without reading or changing a Hermes checkout. */
import { createHash } from 'node:crypto'
import { mkdir, readFile, readdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'
import { compile, optimize } from '@tailwindcss/node'
import { Scanner } from '@tailwindcss/oxide'
import { build } from 'esbuild'
import postcss from 'postcss'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const frontend = path.join(root, 'frontend')
const output = path.join(root, 'desktop')
const external = ['@hermes/plugin-sdk', 'react', 'react/jsx-runtime']
const readText = async file => (await readFile(file, 'utf8')).replaceAll('\r\n', '\n')
const version = JSON.parse(await readText(path.join(root, 'scripts/package.json'))).version
const manifest = await readText(path.join(root, 'backend/plugin.yaml'))
const dashboardManifest = await readText(path.join(root, 'backend/dashboard/manifest.json'))
if (manifest.match(/^version:\s*(.+)$/m)?.[1] !== version || JSON.parse(dashboardManifest).version !== version) {
  throw new Error('Package, backend, and dashboard versions must agree')
}

async function sourceFiles(directory) {
  const files = []
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name)
    if (entry.isDirectory()) files.push(...await sourceFiles(full))
    else if (/\.(tsx?|css)$/.test(entry.name) && !/\.test\./.test(entry.name)) files.push(full)
  }
  return files.sort()
}

const files = await sourceFiles(frontend)
const source = await Promise.all(files.map(async file => ({
  file,
  content: await readText(file),
  extension: path.extname(file).slice(1)
})))
const candidates = new Scanner({}).scanFiles(source
  .filter(item => item.extension !== 'css')
  .map(({ content, extension }) => ({ content, extension })))
if (!candidates.includes('flex')) throw new Error('Tailwind did not scan the frontend class names')
const compiler = await compile(await readText(path.join(frontend, 'standalone.css')), {
  base: frontend,
  // Build packages live in scripts/, outside frontend/'s module lookup path.
  customCssResolver: async id => (id.startsWith('.') ? undefined : createRequire(import.meta.url).resolve(id)),
  onDependency() {}
})
const compiledCss = compiler.build(candidates)
if (!compiledCss.includes('.flex')) throw new Error('Tailwind did not emit the frontend utilities')
const styles = postcss.parse(compiledCss)
// Scope whole selector trees, including responsive/hover variants, to ImageGen.
// Theme defaults are inherited from each scope root, including portalled dialogs.
// Keep @property and @keyframes declarations outside @scope (not style rules).
styles.walkRules(rule => {
  for (let parent = rule.parent; parent; parent = parent.parent) {
    if (parent.type === 'rule' || (parent.type === 'atrule' && /keyframes$/.test(parent.name))) return
  }
  if (rule.selector === ':root, :host') rule.selector = ':scope'
  const scope = postcss.atRule({ name: 'scope', params: '(.imagegen-ui)' })
  rule.replaceWith(scope)
  scope.append(rule)
})
const css = optimize(`${styles}\n${await readText(path.join(frontend, 'imagegen.css'))}`, {
  minify: true
}).code
if (!css.includes('@scope') || !css.includes(':scope') || !css.includes('.flex')) {
  throw new Error('CSS optimization discarded scoped utilities or theme defaults')
}

// Picker thumbnails ship inside the bundle as data URLs; the disk loader serves one file.
const thumbsDir = path.join(frontend, 'assets/thumbs')
const thumbs = {}
for (const file of (await readdir(thumbsDir, { recursive: true })).sort()) {
  if (!file.endsWith('.webp')) continue
  const name = path.basename(file, '.webp')
  if (thumbs[name]) throw new Error(`Two picker thumbnails share the name ${name}`)
  thumbs[name] = `data:image/webp;base64,${(await readFile(path.join(thumbsDir, file))).toString('base64')}`
}
if (!Object.keys(thumbs).length) throw new Error('No picker thumbnails found')

const result = await build({
  absWorkingDir: root,
  entryPoints: ['frontend/standalone.ts'],
  outfile: 'desktop/plugin.js',
  bundle: true,
  format: 'esm',
  platform: 'browser',
  target: 'es2022',
  jsx: 'automatic',
  external,
  minify: true,
  legalComments: 'eof',
  metafile: true,
  write: false,
  plugins: [{
    name: 'imagegen-inline-styles',
    setup(builder) {
      builder.onResolve({ filter: /^imagegen:(styles|thumbs)$/ }, args => ({ path: args.path.slice(9), namespace: 'imagegen' }))
      builder.onLoad({ filter: /.*/, namespace: 'imagegen' }, args => ({
        contents: `export default ${JSON.stringify(args.path === 'thumbs' ? thumbs : css)}`, loader: 'js'
      }))
      // The standalone entry embeds this stylesheet; the bundled entry still imports it.
      builder.onLoad({ filter: /[\\/]imagegen\.css$/ }, () => ({ contents: '', loader: 'js' }))
    }
  }]
})
for (const artifact of Object.values(result.metafile.outputs)) {
  for (const specifier of artifact.imports) {
    if (!specifier.external || !external.includes(specifier.path)) {
      throw new Error(`Disk loader cannot resolve ${specifier.path}`)
    }
  }
}
if (result.outputFiles.length !== 1) throw new Error('The disk package must contain exactly one ESM bundle')
const bundle = result.outputFiles[0].contents
// Vite-only syntax survives esbuild untouched and throws when the Desktop loads the file.
if (result.outputFiles[0].text.includes('import.meta.glob')) throw new Error('The bundle still uses import.meta.glob')
if (bundle.byteLength > 16 * 1024 * 1024) throw new Error('Plugin exceeds the Hermes Desktop 16 MiB read limit')
await mkdir(output, { recursive: true })
await writeFile(path.join(output, 'plugin.js'), bundle)
// Root files are generated from canonical backend metadata; do not maintain duplicates by hand.
await writeFile(path.join(root, 'plugin.yaml'), '# Generated from backend/plugin.yaml by npm run build.\n' + manifest)
await writeFile(path.join(root, '__init__.py'), '# Generated from backend/__init__.py by npm run build.\n' + await readText(path.join(root, 'backend/__init__.py')))
await mkdir(path.join(root, 'dashboard'), { recursive: true })
await writeFile(path.join(root, 'dashboard/manifest.json'), dashboardManifest)
await writeFile(path.join(output, 'build.json'), JSON.stringify({
  version,
  sha256: createHash('sha256').update(bundle).digest('hex'),
  bytes: bundle.byteLength,
  imports: external,
  sources: Object.fromEntries(source.map(item => [
    path.relative(root, item.file).replaceAll('\\', '/'),
    createHash('sha256').update(item.content).digest('hex')
  ]))
}, null, 2) + '\n')
console.log(`Built desktop/plugin.js (${Math.ceil(bundle.byteLength / 1024)} KiB) and native plugin manifests.`)
console.log('Commit the package with its sources before installing from Git.')
