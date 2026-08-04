// The development server, replacing Vite.
//
// Serves `dist/` and proxies `/api` (including the SSE stream) to the Sentry
// backend or `tools/mock_sentry.py`, matching architecture §3.1: in production
// one FastAPI process serves both the API and these static files on
// SENTRY_HTTP_PORT.
//
// Rebuilds on change by re-running the same npm scripts the production build
// uses, so there is no second code path that only exists in development.

import { spawn } from 'node:child_process'
import { createServer } from 'node:http'
import { readFile } from 'node:fs/promises'
import { watch } from 'node:fs'
import { dirname, extname, join, normalize } from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)))
const distDirectory = join(frontendRoot, 'dist')

const PORT = Number(process.env.PORT ?? 3000)
// Overridable so a port clash with another local service cannot silently proxy
// the dev app at an unrelated backend (which looks identical to the API being
// down, but 404s instead of failing to connect).
const API_TARGET = process.env.SENTRY_API_PROXY_TARGET ?? 'http://127.0.0.1:8000'

const CONTENT_TYPES = new Map([
  ['.html', 'text/html; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.map', 'application/json; charset=utf-8'],
  ['.svg', 'image/svg+xml'],
  ['.woff2', 'font/woff2'],
  ['.json', 'application/json; charset=utf-8'],
])

function runBuild(label) {
  return new Promise((resolve) => {
    const child = spawn('npm', ['run', 'build'], { cwd: frontendRoot, stdio: 'inherit' })
    child.on('exit', (code) => {
      console.log(code === 0 ? `✓ ${label}` : `✗ ${label} failed (exit ${code})`)
      resolve(code)
    })
  })
}

async function proxyToApi(request, response) {
  const target = new URL(request.url, API_TARGET)
  try {
    const upstream = await fetch(target, {
      method: request.method,
      headers: { ...request.headers, host: target.host },
      // SSE and JSON bodies both stream through unchanged.
      body: ['GET', 'HEAD'].includes(request.method ?? 'GET') ? undefined : request,
      duplex: 'half',
      redirect: 'manual',
    })
    response.writeHead(upstream.status, Object.fromEntries(upstream.headers))
    if (upstream.body) {
      for await (const chunk of upstream.body) {
        response.write(chunk)
      }
    }
    response.end()
  } catch (error) {
    response.writeHead(502, { 'content-type': 'application/json' })
    response.end(JSON.stringify({ detail: { code: 'proxy_failed', message: String(error) } }))
  }
}

async function serveStatic(request, response) {
  const requestPath = new URL(request.url ?? '/', 'http://localhost').pathname
  const relativePath =
    requestPath === '/' ? 'index.html' : normalize(requestPath).replace(/^\/+/, '')
  const filePath = join(distDirectory, relativePath)

  // Containment check: `normalize` collapses `..`, but a crafted path could
  // still resolve outside dist without this.
  if (!filePath.startsWith(distDirectory)) {
    response.writeHead(403).end('Forbidden')
    return
  }

  try {
    const body = await readFile(filePath)
    response.writeHead(200, {
      'content-type': CONTENT_TYPES.get(extname(filePath)) ?? 'application/octet-stream',
      'cache-control': 'no-store',
    })
    response.end(body)
  } catch {
    // Unknown path: fall back to the shell, as the production static mount does.
    const shell = await readFile(join(distDirectory, 'index.html'))
    response.writeHead(200, { 'content-type': 'text/html; charset=utf-8' }).end(shell)
  }
}

await runBuild('initial build')

let rebuildScheduled = false
watch(join(frontendRoot, 'src'), { recursive: true }, () => {
  if (rebuildScheduled) {
    return
  }
  rebuildScheduled = true
  // Editors write several files in quick succession; one rebuild covers them.
  setTimeout(async () => {
    rebuildScheduled = false
    await runBuild('rebuild')
  }, 120)
})

createServer((request, response) => {
  if ((request.url ?? '').startsWith('/api')) {
    void proxyToApi(request, response)
    return
  }
  void serveStatic(request, response)
}).listen(PORT, () => {
  console.log(`Sentry UI on http://localhost:${PORT} — proxying /api to ${API_TARGET}`)
})
