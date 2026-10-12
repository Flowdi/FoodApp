export type Product = { id: string; name: string; brand?: string; category?: string; default_unit: string; image_url?: string; barcodes: { barcode: string }[] }
export type Batch = { id: string; product_id: string; location_id: string; quantity: string; unit: string; best_before?: string; version: number; product: Product }
export type Location = { id: string; name: string }
export type MovementResult = { movement: { id: string }; batch: Batch; replayed: boolean }
export type Movement = { id: string; batch_id: string; user_id: string; movement_type: string; quantity_delta: string; note?: string; client_info?: string; created_at: string }
export type ShoppingItem = { product_id: string; product_name: string; current_quantity: string; minimum_quantity: string; missing_quantity: string; unit: string }
export type InventoryCount = { batch_id: string; expected_quantity: string; counted_quantity: string }
export type InventoryDetail = { session: { id: string; location_id?: string; status: string; created_at: string }; counts: InventoryCount[] }
export type Notification = { id: string; kind: string; message: string; read_at?: string; resolved_at?: string; created_at: string }

const state = { token: localStorage.getItem('access_token') || '', household: localStorage.getItem('household_id') || '' }

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(state.token && { Authorization: `Bearer ${state.token}` }), ...(state.household && { 'X-Household-ID': state.household }), ...init.headers }
  })
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'Netzwerkfehler' }))
    throw new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message || 'Aktion fehlgeschlagen')
  }
  return response.json()
}

export const api = {
  authenticated: () => Boolean(state.token),
  async login(email: string, password: string) {
    const tokens = await request<{ access_token: string }>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
    state.token = tokens.access_token; localStorage.setItem('access_token', state.token)
    const boot = await request<{ memberships: { household_id: string }[] }>('/auth/bootstrap')
    state.household = boot.memberships[0].household_id; localStorage.setItem('household_id', state.household)
  },
  logout() { localStorage.clear(); state.token = ''; state.household = '' },
  products: () => request<Product[]>('/products'),
  locations: () => request<Location[]>('/locations'),
  stock: () => request<Batch[]>('/stock'),
  barcode: (code: string) => request<Product>(`/products/barcode/${code}`),
  lookup: (code: string) => request<{ found: boolean; name?: string; brand?: string; image_url?: string }>(`/lookup/${code}`),
  createProduct: (body: object) => request<Product>('/products', { method: 'POST', body: JSON.stringify(body) }),
  purchase: (body: object) => request<MovementResult>('/stock/purchase', { method: 'POST', body: JSON.stringify(body) }),
  consume: (batch: Batch, quantity: number, idempotency_key = crypto.randomUUID()) => request<MovementResult>(`/stock/${batch.id}/consume`, { method: 'POST', body: JSON.stringify({ quantity, expected_version: batch.version, idempotency_key, client_info: navigator.userAgent }) }),
  transfer: (batch: Batch, target_location_id: string, quantity: number) => request<MovementResult[]>('/stock/transfer', { method: 'POST', body: JSON.stringify({ batch_id: batch.id, target_location_id, quantity, expected_version: batch.version, idempotency_key: crypto.randomUUID(), client_info: navigator.userAgent }) }),
  reverse: (movementId: string, version: number) => request<MovementResult>(`/movements/${movementId}/reverse`, { method: 'POST', body: JSON.stringify({ expected_version: version, idempotency_key: crypto.randomUUID() }) })
  ,movements: () => request<Movement[]>('/movements')
  ,shoppingList: () => request<ShoppingItem[]>('/shopping-list')
  ,notifications: () => request<Notification[]>('/notifications')
  ,checkNotifications: () => request<{ created: number }>('/notifications/check', { method: 'POST' })
  ,markNotificationRead: (id: string) => request<Notification>(`/notifications/${id}/read`, { method: 'POST' })
  ,setMinStock: (productId: string, minimum_quantity: number, unit: string) => request(`/products/${productId}/min-stock`, { method: 'PUT', body: JSON.stringify({ minimum_quantity, unit, active: true }) })
  ,updateProduct: (productId: string, body: object) => request<Product>(`/products/${productId}`, { method: 'PATCH', body: JSON.stringify(body) })
  ,startInventory: (location_id?: string) => request<InventoryDetail>('/inventory-sessions', { method: 'POST', body: JSON.stringify({ location_id: location_id || null }) })
  ,recordCount: (sessionId: string, batch_id: string, counted_quantity: number) => request<InventoryCount>(`/inventory-sessions/${sessionId}/counts`, { method: 'PUT', body: JSON.stringify({ batch_id, counted_quantity }) })
  ,confirmInventory: (sessionId: string) => request<MovementResult[]>(`/inventory-sessions/${sessionId}/confirm`, { method: 'POST', body: JSON.stringify({ idempotency_key: crypto.randomUUID() }) })
  ,async downloadHistory() {
    const response = await fetch('/api/v1/movements/export.csv', { headers: { Authorization: `Bearer ${state.token}`, 'X-Household-ID': state.household } })
    if (!response.ok) throw new Error('CSV-Export fehlgeschlagen')
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'vorrat-buchungen.csv'; anchor.click(); URL.revokeObjectURL(url)
  }
}
