import { expect, test, type Page } from '@playwright/test'

async function mockApi(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem('access_token', 'test-token')
    localStorage.setItem('refresh_token', 'test-refresh')
    localStorage.setItem('household_id', 'household-1')
  })
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = (value: unknown) => route.fulfill({ json: value })
    if (path === '/api/v1/products') return json([{ id: 'product-1', name: 'Milch', category: 'Kühlregal', default_unit: 'l', barcodes: [] }])
    if (path === '/api/v1/locations') return json([{ id: 'location-1', name: 'Kühlschrank' }])
    if (path === '/api/v1/stock' || path === '/api/v1/movements' || path === '/api/v1/shopping-list' || path === '/api/v1/notifications' || path === '/api/v1/households/members' || path === '/api/v1/recipes/recommendations') return json([])
    if (path === '/api/v1/households/current') return json({ id: 'household-1', name: 'Zuhause', timezone: 'Europe/Berlin', expiry_warning_days: 3, shopping_check_mode: 'instant' })
    if (path === '/api/v1/notifications/preferences') return json({ channels: ['in_app'] })
    if (path === '/api/v1/recipes/preferences') return json({ preferred_tags: [], excluded_tags: [] })
    if (path === '/api/v1/voice/preferences') {
      if (route.request().method() === 'PUT') return json(JSON.parse(route.request().postData() || '{}'))
      return json({ auto_confirm_shopping: false, speech_output: false, start_listening_on_launch: true })
    }
    if (path === '/api/v1/voice/interpret') return json({ transcript: 'Setze zwei Milch auf die Einkaufsliste', parser: 'rules', actions: [{ intent: 'add_to_shopping', product_id: 'product-1', product_name: 'Milch', quantity: '2', unit: 'l', confidence: .96, choices: [], expected_versions: {}, requires_confirmation: true }] })
    if (path === '/api/v1/voice/execute') return json({ message: 'Milch steht auf der Einkaufsliste', result_type: 'shopping' })
    if (path === '/api/v1/events') return route.fulfill({ status: 204 })
    return json({})
  })
}

test.beforeEach(async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await page.locator('.voice-nav').click()
})

test('voice draft remains editable and requires confirmation', async ({ page }) => {
  await page.getByLabel('Erkannter oder eingegebener Text').fill('Setze zwei Milch auf die Einkaufsliste')
  await page.getByRole('button', { name: 'Befehl prüfen' }).click()
  await expect(page.getByText('Auf die Einkaufsliste', { exact: true })).toBeVisible()
  await page.getByLabel('Menge').fill('3')
  const confirm = page.getByRole('button', { name: 'Bestätigen' })
  const box = await confirm.boundingBox()
  expect(box?.height).toBeGreaterThanOrEqual(44)
  await confirm.click()
  await expect(page.getByText(/Milch steht auf der Einkaufsliste/)).toBeVisible()
})

test('voice layout adapts to desktop', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-1440')
  const capture = await page.locator('.voice-capture').boundingBox()
  const results = await page.locator('.voice-results').boundingBox()
  expect(results?.x).toBeGreaterThan(capture?.x || 0)
})

test('direct voice route shows tap fallback when microphone permission is denied', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('voice_permission_explained', 'true')
    const denied = () => Promise.reject(new DOMException('Permission denied', 'NotAllowedError'))
    if (navigator.mediaDevices) Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { configurable: true, value: denied })
    else Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: denied } })
  })
  await page.goto('/voice')

  await expect(page.getByRole('heading', { name: 'Sprechen' })).toBeVisible()
  const fallback = page.getByRole('button', { name: 'Tippen zum Sprechen' })
  await expect(fallback).toBeVisible()
  const box = await fallback.boundingBox()
  expect(box?.height).toBeGreaterThanOrEqual(44)
})

test('first direct voice start explains microphone access', async ({ page }) => {
  await page.addInitScript(() => localStorage.removeItem('voice_permission_explained'))
  await page.goto('/?mode=voice')

  await expect(page.getByRole('heading', { name: 'Mikrofon für den Sprachstart' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Mikrofon erlauben und sprechen' })).toBeVisible()
})
