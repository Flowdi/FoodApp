import { expect, test, type Page } from '@playwright/test'

const product = {
  id: 'product-1',
  name: 'Milch',
  brand: 'Hofgut',
  category: 'Kühlregal',
  default_unit: 'l',
  default_location_id: 'location-1',
  barcodes: [],
}

const shoppingItem = {
  id: 'shopping-1',
  product_id: product.id,
  product_name: product.name,
  category: product.category,
  quantity: '2.000',
  unit: 'l',
  source: 'manual',
  status: 'open',
  version: 1,
  created_at: '2026-10-13T10:00:00Z',
}

async function mockApi(page: Page) {
  let items = [{ ...shoppingItem }]
  await page.addInitScript(() => {
    localStorage.setItem('access_token', 'test-token')
    localStorage.setItem('refresh_token', 'test-refresh')
    localStorage.setItem('household_id', 'household-1')
  })
  await page.route('**/api/v1/**', async route => {
    const path = new URL(route.request().url()).pathname
    const json = (value: unknown) => route.fulfill({ json: value })
    if (path === '/api/v1/stock') return json([])
    if (path === '/api/v1/products') return json([product])
    if (path === '/api/v1/locations') return json([{ id: 'location-1', name: 'Kühlschrank' }])
    if (path === '/api/v1/movements') return json([])
    if (path === '/api/v1/shopping-list' && route.request().method() === 'GET') return json(items)
    if (path === '/api/v1/shopping-list' && route.request().method() === 'POST') {
      const body = route.request().postDataJSON()
      const item = { ...shoppingItem, id: 'shopping-2', product_id: undefined, product_name: body.free_text, category: undefined, quantity: String(body.quantity), unit: body.unit }
      items.push(item)
      return json(item)
    }
    if (path.endsWith('/check')) {
      items = items.map(item => item.id === 'shopping-1' ? { ...item, status: 'checked', version: 2, checked_by_name: 'Test' } : item)
      return json({ item: items[0] })
    }
    if (path === '/api/v1/notifications') return json([])
    if (path === '/api/v1/households/current') return json({ id: 'household-1', name: 'Zuhause', timezone: 'Europe/Berlin', expiry_warning_days: 3, shopping_check_mode: 'instant' })
    if (path === '/api/v1/households/members') return json([])
    if (path === '/api/v1/notifications/preferences') return json({ channels: ['in_app'] })
    if (path === '/api/v1/recipes/recommendations') return json([])
    if (path === '/api/v1/recipes/preferences') return json({ preferred_tags: [], excluded_tags: [] })
    if (path === '/api/v1/events') return route.fulfill({ status: 204 })
    return json({})
  })
}

test.beforeEach(async ({ page }) => {
  await mockApi(page)
  await page.goto('/')
  await page.getByRole('button', { name: /Einkaufsliste/ }).click()
})

test('shopping flow is touch friendly on mobile', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'mobile-pixel-7')
  await expect(page.getByRole('heading', { name: 'Kühlregal' })).toBeVisible()
  const checkButton = page.getByRole('button', { name: 'Milch abhaken' })
  const box = await checkButton.boundingBox()
  expect(box?.width).toBeGreaterThanOrEqual(48)
  expect(box?.height).toBeGreaterThanOrEqual(48)
  await expect(page.locator('nav')).toHaveCSS('position', 'fixed')
  await checkButton.click()
  await expect(page.getByText('von Test')).toBeVisible()
})

test('shopping list uses sidebar and columns on desktop', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-1440')
  const nav = await page.locator('nav').boundingBox()
  const navButtons = await page.locator('nav button').all()
  const firstNavButton = await navButtons[0].boundingBox()
  const secondNavButton = await navButtons[1].boundingBox()
  const form = await page.locator('.shopping-add-panel').boundingBox()
  const list = await page.locator('.shopping-list-panel').boundingBox()
  expect(nav?.x).toBe(0)
  expect(nav?.height).toBe(900)
  expect(secondNavButton?.y).toBeGreaterThan(firstNavButton?.y || 0)
  expect(Math.abs((secondNavButton?.x || 0) - (firstNavButton?.x || 0))).toBeLessThan(2)
  expect(form?.x).toBeGreaterThan(list?.x || 0)
  await expect(page.getByText(/Tastatur: N neuer Eintrag/)).toBeVisible()
  await page.keyboard.press('n')
  await expect(page.locator('#shopping-product')).toBeFocused()
})
