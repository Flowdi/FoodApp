export type Product = { id: string; name: string; brand?: string; category?: string; default_unit: string; image_url?: string; barcodes: { barcode: string }[] }
export type Batch = { id: string; product_id: string; location_id: string; quantity: string; unit: string; best_before?: string; version: number; product: Product }
export type Location = { id: string; name: string }
export type MovementResult = { movement: { id: string }; batch: Batch; replayed: boolean }
export type Movement = { id: string; batch_id: string; user_id: string; movement_type: string; quantity_delta: string; note?: string; client_info?: string; created_at: string }
export type ShoppingItem = { product_id: string; product_name: string; current_quantity: string; minimum_quantity: string; missing_quantity: string; unit: string }
export type InventoryCount = { batch_id: string; expected_quantity: string; counted_quantity: string }
export type InventoryDetail = { session: { id: string; location_id?: string; status: string; created_at: string }; counts: InventoryCount[] }
export type Notification = { id: string; kind: string; message: string; read_at?: string; resolved_at?: string; created_at: string }

const state = { token: localStorage.getItem('access_token') || '', refresh: localStorage.getItem('refresh_token') || '', household: localStorage.getItem('household_id') || '' }
let refreshPromise: Promise<boolean> | null = null

async function renewAccessToken(): Promise<boolean> {
  if (!state.refresh) return false
  if (!refreshPromise) refreshPromise = fetch('/api/v1/auth/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: state.refresh }) }).then(async response => {
    if (!response.ok) return false
    const tokens = await response.json(); state.token = tokens.access_token; state.refresh = tokens.refresh_token
    localStorage.setItem('access_token', state.token); localStorage.setItem('refresh_token', state.refresh); return true
  }).finally(() => { refreshPromise = null })
  return refreshPromise
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(state.token && { Authorization: `Bearer ${state.token}` }), ...(state.household && { 'X-Household-ID': state.household }), ...init.headers }
  })
  if (response.status === 401 && path !== '/auth/refresh' && await renewAccessToken()) return request<T>(path, init)
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: 'Netzwerkfehler' }))
    throw new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message || 'Aktion fehlgeschlagen')
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

export const api = {
  authenticated: () => Boolean(state.token),
  async login(email: string, password: string) {
    const tokens = await request<{ access_token: string; refresh_token: string }>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) })
    state.token = tokens.access_token; state.refresh = tokens.refresh_token; localStorage.setItem('access_token', state.token); localStorage.setItem('refresh_token', state.refresh)
    const boot = await request<{ memberships: { household_id: string }[] }>('/auth/bootstrap')
    state.household = boot.memberships[0].household_id; localStorage.setItem('household_id', state.household)
  },
  async register(email: string, display_name: string, password: string, household_name: string | null, invitation_token: string | null) {
    const tokens = await request<{ access_token: string; refresh_token: string }>('/auth/register', { method: 'POST', body: JSON.stringify({ email, display_name, password, household_name, invitation_token }) })
    state.token = tokens.access_token; state.refresh = tokens.refresh_token; localStorage.setItem('access_token', state.token); localStorage.setItem('refresh_token', state.refresh)
    const boot = await request<{ memberships: { household_id: string }[] }>('/auth/bootstrap')
    state.household = boot.memberships[0].household_id; localStorage.setItem('household_id', state.household)
  },
  async logout() { if (state.refresh) await request('/auth/logout', { method: 'POST', body: JSON.stringify({ refresh_token: state.refresh }) }).catch(() => undefined); localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token'); localStorage.removeItem('household_id'); state.token = ''; state.refresh = ''; state.household = '' },
  requestPasswordReset: (email: string) => request<{ message: string }>('/auth/password-reset/request', { method: 'POST', body: JSON.stringify({ email }) }),
  async confirmPasswordReset(token: string, password: string) { await request<void>('/auth/password-reset/confirm', { method: 'POST', body: JSON.stringify({ token, password }) }); localStorage.removeItem('access_token'); localStorage.removeItem('refresh_token'); localStorage.removeItem('household_id'); state.token = ''; state.refresh = ''; state.household = '' },
  createInvitation: (email: string, role: string) => request<{ invitation_url: string }>('/households/invitations', { method: 'POST', body: JSON.stringify({ email: email || null, role }) }),
  async acceptInvitation(token: string) { const accepted = await request<{ household_id: string }>('/households/invitations/accept', { method: 'POST', body: JSON.stringify({ token }) }); state.household = accepted.household_id; localStorage.setItem('household_id', state.household) },
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
