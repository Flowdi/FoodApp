import { expect, test, type Page } from '@playwright/test'

const product = { id: 'product-1', name: 'Milch', default_unit: 'l', default_location_id: 'location-1', barcodes: [] }
const line = { id: 'line-1', raw_text: 'H-MILCH 3,5%', quantity: '1', unit: 'l', total_price: '1.29', line_kind: 'food', status: 'mapped', confidence: '0.96', product_id: product.id, product_name: product.name, location_id: 'location-1', version: 1 }
const baseReceipt = { id: 'receipt-1', merchant: 'Testmarkt', purchased_at: '2026-10-14T10:20:00Z', total: '1.29', status: 'review', progress: 100, image_count: 0, uploaded_by_name: 'Test', created_at: '2026-10-14T10:21:00Z', lines: [line] }

async function mockApi(page: Page) {
  let receipt = { ...baseReceipt, lines: [{ ...line }] }
  await page.addInitScript(() => {
    localStorage.setItem('access_token', 'test-token')
    localStorage.setItem('refresh_token', 'test-refresh')
    localStorage.setItem('household_id', 'household-1')
  })
  await page.route('**/api/v1/**', async route => {
    const request = route.request(); const path = new URL(request.url()).pathname
    const json = (value: unknown) => route.fulfill({ json: value })
    if (path === '/api/v1/stock' || path === '/api/v1/movements' || path === '/api/v1/shopping-list' || path === '/api/v1/notifications' || path === '/api/v1/households/members' || path === '/api/v1/recipes/recommendations') return json([])
    if (path === '/api/v1/products') return json([product])
    if (path === '/api/v1/locations') return json([{ id: 'location-1', name: 'Kühlschrank' }])
    if (path === '/api/v1/households/current') return json({ id: 'household-1', name: 'Zuhause', timezone: 'Europe/Berlin', expiry_warning_days: 3, shopping_check_mode: 'instant' })
    if (path === '/api/v1/notifications/preferences') return json({ channels: ['in_app'] })
    if (path === '/api/v1/recipes/preferences') return json({ preferred_tags: [], excluded_tags: [] })
    if (path === '/api/v1/voice/preferences') return json({ auto_confirm_shopping: false, speech_output: false, start_listening_on_launch: false })
    if (path === '/api/v1/receipts/config') return json({ ocr_mode: 'vision_llm', images_sent_to_cloud: true, cloud_processing: 'images', image_retention_days: 30 })
    if (path === '/api/v1/receipts' && request.method() === 'GET') return json([])
    if (path === '/api/v1/receipts' && request.method() === 'POST') return json(receipt)
    if (path === '/api/v1/receipts/receipt-1/confirm') { receipt = { ...receipt, status: 'confirmed', confirmed_at: '2026-10-14T10:22:00Z', lines: receipt.lines.map(item => ({ ...item, status: 'booked', version: 2 })) }; return json(receipt) }
    if (path === '/api/v1/receipts/receipt-1') return json(receipt)
    if (path === '/api/v1/events') return route.fulfill({ status: 204 })
    return json({})
  })
}

test.beforeEach(async ({ page }) => {
  await mockApi(page); await page.goto('/'); await page.getByRole('button', { name: /Bon/ }).click()
})

test('mobile receipt capture reviews and books a line', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-pixel-7')
  const picker = page.locator('.receipt-camera-picker')
  await picker.setInputFiles('public/icon-192.png')
  const upload = page.getByRole('button', { name: /Bondatei analysieren/ })
  const box = await upload.boundingBox(); expect(box?.height).toBeGreaterThanOrEqual(48)
  await upload.click()
  await expect(page.getByRole('heading', { name: 'Testmarkt' })).toBeVisible()
  await expect(page.getByText('H-MILCH 3,5%')).toBeVisible()
  await page.getByRole('button', { name: '1 Positionen einbuchen' }).click()
  await expect(page.getByText('Bon wurde vollständig eingebucht')).toBeVisible()
})

test('desktop receipt upload offers drag and drop with history column', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-1440')
  await expect(page.getByText('Am PC kannst du Dateien auch hierher ziehen.')).toBeVisible()
  const main = await page.locator('.receipt-main').boundingBox(); const history = await page.locator('.receipt-history').boundingBox()
  expect(history?.x).toBeGreaterThan(main?.x || 0)
  await expect(page.getByText(/Bonbilder werden an den konfigurierten Cloud-Anbieter übertragen/)).toBeVisible()
  await page.locator('.receipt-upload').evaluate(async element => {
    const blob = await fetch('/icon-192.png').then(response => response.blob())
    const transfer = new DataTransfer(); transfer.items.add(new File([blob], 'bon.png', { type: 'image/png' }))
    element.dispatchEvent(new DragEvent('drop', { bubbles: true, cancelable: true, dataTransfer: transfer }))
  })
  await expect(page.getByRole('button', { name: /1 Bondatei analysieren/ })).toBeEnabled()
})
