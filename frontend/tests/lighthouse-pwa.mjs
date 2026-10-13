import { spawn } from 'node:child_process'
import { mkdir, rm } from 'node:fs/promises'
import { resolve } from 'node:path'
import { launch } from 'chrome-launcher'
import lighthouse from 'lighthouse'
import { chromium } from '@playwright/test'

const url = 'http://127.0.0.1:4173/'
const preview = spawn(process.execPath, ['node_modules/vite/bin/vite.js', 'preview', '--host', '127.0.0.1', '--port', '4173'], {
  stdio: ['ignore', 'pipe', 'pipe'],
  windowsHide: true
})

async function waitForPreview() {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch(url)
      if (response.ok) return
    } catch {
      // The preview server can take a moment to bind its port.
    }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  throw new Error('Vite preview did not become ready')
}

let chrome
const chromeProfile = resolve(`.lighthouse-profile-${process.pid}`)
try {
  await waitForPreview()
  await mkdir(chromeProfile, { recursive: true })
  chrome = await launch({ chromeFlags: ['--headless', '--no-sandbox', '--disable-gpu'], userDataDir: chromeProfile })
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${chrome.port}`)
  const page = await browser.contexts()[0].newPage()
  await page.goto(url)
  await page.evaluate(() => navigator.serviceWorker.ready)
  await page.reload()
  if (!await page.evaluate(() => Boolean(navigator.serviceWorker.controller))) throw new Error('Generated service worker does not control the app')
  await page.close()
  const options = {
    port: chrome.port,
    onlyCategories: ['pwa'],
    output: 'json',
    logLevel: 'error'
  }
  const result = await lighthouse(url, {
    ...options,
    disableStorageReset: true
  })
  if (!result) throw new Error('Lighthouse returned no result')

  const score = result.lhr.categories.pwa?.score
  const requiredAudits = ['installable-manifest', 'maskable-icon']
  const failedAudits = requiredAudits.filter(id => (result.lhr.audits[id]?.score ?? 0) < 1)
  if (score === undefined || score < 0.9 || failedAudits.length) {
    console.error(JSON.stringify(result.lhr.categories.pwa?.auditRefs.map(({ id }) => ({ id, score: result.lhr.audits[id]?.score })), null, 2))
    const details = failedAudits.map(id => `${id}: ${result.lhr.audits[id]?.displayValue || result.lhr.audits[id]?.title || 'failed'}`).join('; ')
    throw new Error(`PWA validation failed (score ${score ?? 'missing'}; ${details || 'category score'})`)
  }
  console.log(`Lighthouse PWA score: ${Math.round(score * 100)}`)
} finally {
  if (chrome) {
    try { chrome.kill() } catch { /* The process already exited. */ }
  }
  preview.kill()
  await rm(chromeProfile, { force: true, recursive: true, maxRetries: 5 }).catch(() => undefined)
}
