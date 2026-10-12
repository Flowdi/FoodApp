export type Product = { id: string; name: string; brand?: string; category?: string; default_unit: string; image_url?: string; barcodes: { barcode: string }[] }
export type Batch = { id: string; product_id: string; location_id: string; quantity: string; unit: string; best_before?: string; version: number; product: Product }
export type Location = { id: string; name: string }
export type MovementResult = { movement: { id: string }; batch: Batch; replayed: boolean }

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
  reverse: (movementId: string, version: number) => request<MovementResult>(`/movements/${movementId}/reverse`, { method: 'POST', body: JSON.stringify({ expected_version: version, idempotency_key: crypto.randomUUID() }) })
}
