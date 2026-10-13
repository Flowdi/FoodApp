import { discardConflict, flushOutbox, offlineState, queueRequest, retryConflict, type OfflineConflict } from './offline'

export type Product = { id: string; name: string; brand?: string; category?: string; default_unit: string; image_url?: string; package_quantity?: string; notes?: string; barcodes: { barcode: string }[] }
export type Batch = { id: string; product_id: string; location_id: string; quantity: string; unit: string; best_before?: string; opened_at?: string; version: number; product: Product }
export type Location = { id: string; name: string }
export type MovementResult = { movement: { id: string }; batch: Batch; replayed: boolean }
export type Movement = { id: string; batch_id: string; user_id: string; product_id?: string; product_name?: string; user_name?: string; movement_type: string; quantity_delta: string; note?: string; client_info?: string; created_at: string }
export type ShoppingItem = { product_id: string; product_name: string; current_quantity: string; minimum_quantity: string; missing_quantity: string; unit: string; source: string; recipe_id?: string }
export type RecipeIngredient = { id: string; product_id: string; product_name: string; quantity: string; unit: string }
export type Recipe = { id: string; name: string; servings: number; instructions?: string; tags: string[]; ingredients: RecipeIngredient[] }
export type MissingIngredient = { product_id: string; product_name: string; required_quantity: string; available_quantity: string; missing_quantity: string; unit: string }
export type RecipeRecommendation = { recipe: Recipe; score: number; availability_score: number; expiry_score: number; preference_score: number; missing_ingredients: MissingIngredient[]; explanation: string; ranking_source: string }
export type RecipePreferences = { preferred_tags: string[]; excluded_tags: string[] }
export type InventoryCount = { batch_id: string; expected_quantity: string; expected_version: number; counted_quantity: string }
export type InventoryDetail = { session: { id: string; location_id?: string; status: string; created_at: string }; counts: InventoryCount[] }
export type Notification = { id: string; kind: string; message: string; read_at?: string; resolved_at?: string; created_at: string }
export type Household = { id: string; name: string; timezone: string; expiry_warning_days: number }
export type Member = { user_id: string; email: string; display_name: string; role: string }
export type QueuedResult = { queued: true; key: string }

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message) }
}

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
    const detail = body.detail
    const message = typeof detail === 'string'
      ? detail
      : Array.isArray(detail)
        ? detail.map(item => item.msg).join('; ')
        : detail?.message
    throw new ApiError(message || 'Aktion fehlgeschlagen', response.status)
  }
  if (response.status === 204) return undefined as T
  return response.json()
}

async function offlineRequest<T>(path: string, body: Record<string, unknown>): Promise<T | QueuedResult> {
  try {
    return await request<T>(path, { method: 'POST', body: JSON.stringify(body) })
  } catch (caught) {
    if (navigator.onLine && !(caught instanceof TypeError)) throw caught
    const key = await queueRequest(path, body)
    return { queued: true, key }
  }
}

async function sendQueued(path: string, body: Record<string, unknown>) {
  await request(path, { method: 'POST', body: JSON.stringify(body) })
}

async function streamEvents(onChange: () => void, signal: AbortSignal) {
  while (!signal.aborted) {
    try {
      const response = await fetch('/api/v1/events', {
        headers: { Authorization: `Bearer ${state.token}`, 'X-Household-ID': state.household },
        signal
      })
      if (response.status === 401 && await renewAccessToken()) continue
      if (!response.ok || !response.body) throw new Error('Live-Verbindung fehlgeschlagen')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (!signal.aborted) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const blocks = buffer.split('\n\n')
        buffer = blocks.pop() || ''
        for (const block of blocks) if (block.includes('event: changed')) onChange()
      }
    } catch {
      if (signal.aborted) return
      onChange()
      await new Promise(resolve => setTimeout(resolve, 10000))
    }
  }
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
  household: () => request<Household>('/households/current'),
  members: () => request<Member[]>('/households/members'),
  updateHousehold: (body: object) => request<Household>('/households/current', { method: 'PATCH', body: JSON.stringify(body) }),
  updateMember: (userId: string, role: string) => request<Member>(`/households/members/${userId}`, { method: 'PATCH', body: JSON.stringify({ role }) }),
  removeMember: (userId: string) => request<void>(`/households/members/${userId}`, { method: 'DELETE' }),
  products: () => request<Product[]>('/products'),
  locations: () => request<Location[]>('/locations'),
  stock: () => request<Batch[]>('/stock'),
  barcode: (code: string) => request<Product>(`/products/barcode/${code}`),
  lookup: (code: string) => request<{ found: boolean; name?: string; brand?: string; quantity?: string; image_url?: string }>(`/lookup/${code}`),
  createProduct: (body: object) => request<Product>('/products', { method: 'POST', body: JSON.stringify(body) }),
  purchase: (body: Record<string, unknown>) => offlineRequest<MovementResult>('/stock/purchase', body),
  consumeFefo: (productId: string, unit: string, quantity: number, batches: Batch[]) => offlineRequest<MovementResult[]>('/stock/consume-fefo', { product_id: productId, unit, quantity, expected_versions: Object.fromEntries(batches.filter(batch => batch.product_id === productId && batch.unit === unit).map(batch => [batch.id, batch.version])), idempotency_key: crypto.randomUUID(), client_info: navigator.userAgent }),
  discardFefo: (productId: string, unit: string, quantity: number, batches: Batch[]) => offlineRequest<MovementResult[]>('/stock/discard-fefo', { product_id: productId, unit, quantity, expected_versions: Object.fromEntries(batches.filter(batch => batch.product_id === productId && batch.unit === unit).map(batch => [batch.id, batch.version])), idempotency_key: crypto.randomUUID(), client_info: navigator.userAgent }),
  consume: (batch: Batch, quantity: number, idempotency_key = crypto.randomUUID()) => offlineRequest<MovementResult>(`/stock/${batch.id}/consume`, { quantity, expected_version: batch.version, idempotency_key, client_info: navigator.userAgent }),
  discard: (batch: Batch, quantity: number, idempotency_key = crypto.randomUUID()) => offlineRequest<MovementResult>(`/stock/${batch.id}/discard`, { quantity, expected_version: batch.version, idempotency_key, client_info: navigator.userAgent }),
  transfer: (batch: Batch, target_location_id: string, quantity: number) => offlineRequest<MovementResult[]>('/stock/transfer', { batch_id: batch.id, target_location_id, quantity, expected_version: batch.version, idempotency_key: crypto.randomUUID(), client_info: navigator.userAgent }),
  reverse: (movementId: string, version: number) => request<MovementResult>(`/movements/${movementId}/reverse`, { method: 'POST', body: JSON.stringify({ expected_version: version, idempotency_key: crypto.randomUUID() }) })
  ,movements: () => request<Movement[]>('/movements')
  ,shoppingList: () => request<ShoppingItem[]>('/shopping-list')
  ,recipes: () => request<Recipe[]>('/recipes')
  ,recipeRecommendations: (tags: string[] = [], servings?: number) => { const params = new URLSearchParams(); tags.forEach(tag => params.append('tags', tag)); if (servings) params.set('servings', String(servings)); const query = params.toString(); return request<RecipeRecommendation[]>(`/recipes/recommendations${query ? `?${query}` : ''}`) }
  ,recipePreferences: () => request<RecipePreferences>('/recipes/preferences')
  ,setRecipePreferences: (body: RecipePreferences) => request<RecipePreferences>('/recipes/preferences', { method: 'PUT', body: JSON.stringify(body) })
  ,createRecipe: (body: object) => request<Recipe>('/recipes', { method: 'POST', body: JSON.stringify(body) })
  ,updateRecipe: (recipeId: string, body: object) => request<Recipe>(`/recipes/${recipeId}`, { method: 'PATCH', body: JSON.stringify(body) })
  ,deleteRecipe: (recipeId: string) => request<void>(`/recipes/${recipeId}`, { method: 'DELETE' })
  ,addRecipeToShoppingList: (recipeId: string, servings?: number) => request<void>(`/recipes/${recipeId}/shopping-list${servings ? `?servings=${servings}` : ''}`, { method: 'POST' })
  ,notifications: () => request<Notification[]>('/notifications')
  ,notificationPreferences: () => request<{ channels: string[] }>('/notifications/preferences')
  ,setNotificationPreferences: (channels: string[]) => request<{ channels: string[] }>('/notifications/preferences', { method: 'PUT', body: JSON.stringify({ channels }) })
  ,vapidPublicKey: () => request<{ public_key: string }>('/notifications/vapid-public-key')
  ,subscribePush: (body: PushSubscriptionJSON) => request<void>('/notifications/push-subscriptions', { method: 'POST', body: JSON.stringify({ endpoint: body.endpoint, p256dh: body.keys?.p256dh, auth: body.keys?.auth }) })
  ,checkNotifications: () => request<{ created: number }>('/notifications/check', { method: 'POST' })
  ,markNotificationRead: (id: string) => request<Notification>(`/notifications/${id}/read`, { method: 'POST' })
  ,setMinStock: (productId: string, minimum_quantity: number, unit: string) => request(`/products/${productId}/min-stock`, { method: 'PUT', body: JSON.stringify({ minimum_quantity, unit, active: true }) })
  ,updateProduct: (productId: string, body: object) => request<Product>(`/products/${productId}`, { method: 'PATCH', body: JSON.stringify(body) })
  ,updateBatch: (batchId: string, body: object) => request<Batch>(`/stock/${batchId}`, { method: 'PATCH', body: JSON.stringify(body) })
  ,startInventory: (location_id?: string) => request<InventoryDetail>('/inventory-sessions', { method: 'POST', body: JSON.stringify({ location_id: location_id || null }) })
  ,recordCount: (sessionId: string, batch_id: string, counted_quantity: number) => request<InventoryCount>(`/inventory-sessions/${sessionId}/counts`, { method: 'PUT', body: JSON.stringify({ batch_id, counted_quantity }) })
  ,confirmInventory: (sessionId: string) => request<MovementResult[]>(`/inventory-sessions/${sessionId}/confirm`, { method: 'POST', body: JSON.stringify({ idempotency_key: crypto.randomUUID() }) })
  ,async downloadHistory() {
    const response = await fetch('/api/v1/movements/export.csv', { headers: { Authorization: `Bearer ${state.token}`, 'X-Household-ID': state.household } })
    if (!response.ok) throw new Error('CSV-Export fehlgeschlagen')
    const url = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'vorrat-buchungen.csv'; anchor.click(); URL.revokeObjectURL(url)
  },
  async flushOffline() { await flushOutbox(sendQueued); return offlineState() },
  offlineState,
  async discardOfflineConflict(key: string) { await discardConflict(key); return offlineState() },
  async retryOfflineConflict(conflict: OfflineConflict) {
    const body = { ...conflict.body }
    const current = await request<Batch[]>('/stock')
    const batchId = String(body.batch_id || conflict.url.split('/')[2] || '')
    const batch = current.find(item => item.id === batchId)
    if ('expected_version' in body && batch) body.expected_version = batch.version
    if ('expected_versions' in body && body.product_id) {
      body.expected_versions = Object.fromEntries(current.filter(item => item.product_id === body.product_id && item.unit === body.unit).map(item => [item.id, item.version]))
    }
    await retryConflict(conflict, body, sendQueued)
    return offlineState()
  },
  watchEvents(onChange: () => void) { const controller = new AbortController(); void streamEvents(onChange, controller.signal); return controller }
}

export type { OfflineConflict }
