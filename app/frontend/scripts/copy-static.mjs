// Copies the static assets the build does not transform — `index.html` and
// everything under `public/` (fonts, favicon) — into `dist/`.
//
// This is the whole of what a bundler used to do here beyond compiling. It runs
// last in `npm run build`, after tsc has written `dist/js` and the Tailwind CLI
// has written `dist/app.css`, so it never races them.

import { cp, mkdir, rm } from 'node:fs/promises'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)))
const distDirectory = join(frontendRoot, 'dist')

await mkdir(distDirectory, { recursive: true })

// Stale font/icon files would otherwise accumulate across renames.
await rm(join(distDirectory, 'fonts'), { recursive: true, force: true })

await cp(join(frontendRoot, 'public'), distDirectory, { recursive: true })
await cp(join(frontendRoot, 'index.html'), join(distDirectory, 'index.html'))

console.log('Copied index.html and public/ into dist/')
