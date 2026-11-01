/** Run Knip from a temporary root: the build package lives in scripts/ so the plugin root has no package.json. */
import { spawnSync } from 'node:child_process'
import { cpSync, mkdtempSync, rmSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const [knip, ...args] = process.argv.slice(2)
if (!knip) throw new Error('Usage: node scripts/knip.mjs <path to knip/bin/knip.js> [knip options]')

const temp = mkdtempSync(path.join(os.tmpdir(), 'imagegen-knip-'))
try {
  cpSync(path.join(root, 'frontend'), path.join(temp, 'frontend'), { recursive: true })
  cpSync(path.join(root, 'scripts'), path.join(temp, 'scripts'), {
    recursive: true,
    filter: source => !/(^|[\\/])(node_modules|package(-lock)?\.json)$/.test(source)
  })
  cpSync(path.join(root, 'knip.json'), path.join(temp, 'knip.json'))
  cpSync(path.join(root, 'scripts/package.json'), path.join(temp, 'package.json'))
  process.exitCode = spawnSync(process.execPath, [knip, ...args], { cwd: temp, stdio: 'inherit' }).status ?? 1
} finally {
  rmSync(temp, { recursive: true, force: true })
}
