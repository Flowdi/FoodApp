<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { BrowserMultiFormatReader } from '@zxing/browser'
import { api, type Batch, type Household, type InventoryDetail, type Location, type Member, type Movement, type MovementResult, type Notification, type OfflineConflict, type Product, type QueuedResult, type ShoppingItem } from './api'
import { t } from './i18n'

type View = 'stock' | 'history' | 'inventory' | 'more'

const loggedIn = ref(api.authenticated())
const email = ref('demo@example.com'), password = ref('demo-password')
const query = new URLSearchParams(window.location.search)
const resetToken = ref(query.get('reset_token') || '')
const inviteToken = ref(query.get('invite') || '')
const resetPassword = ref(''), resetComplete = ref(false), invitationLink = ref('')
const registering = ref(false), displayName = ref(''), householdName = ref('')
const batches = ref<Batch[]>([]), products = ref<Product[]>([]), locations = ref<Location[]>([])
const movements = ref<Movement[]>([]), shopping = ref<ShoppingItem[]>([])
const notifications = ref<Notification[]>([])
const household = ref<Household | null>(null), members = ref<Member[]>([]), notificationChannels = ref<string[]>([])
const activeView = ref<View>('stock'), search = ref(''), busy = ref(false), error = ref('')
const notice = ref(''), locationFilter = ref(''), categoryFilter = ref(''), expiryFilter = ref(false), shortageFilter = ref(false), sortBy = ref('expiry')
const historyType = ref(''), historyProduct = ref(''), historyUser = ref(''), historyStart = ref(''), historyEnd = ref(''), pendingOffline = ref(0), conflicts = ref<OfflineConflict[]>([]), online = ref(navigator.onLine)
const showAdd = ref(false), scanning = ref(false), inventory = ref<InventoryDetail | null>(null)
const selectedProduct = ref(''), selectedLocation = ref(''), quantity = ref(1), unit = ref('piece'), bestBefore = ref('')
const lastMovements = ref<{ id: string; version: number }[]>([])
const shoppingProductIds = computed(() => new Set(shopping.value.map(item => item.product_id)))
const categories = computed(() => [...new Set(products.value.map(product => product.category).filter(Boolean) as string[])].sort())
const filtered = computed(() => batches.value.filter(batch => {
  if (!batch.product.name.toLowerCase().includes(search.value.toLowerCase())) return false
  if (locationFilter.value && batch.location_id !== locationFilter.value) return false
  if (categoryFilter.value && batch.product.category !== categoryFilter.value) return false
  if (expiryFilter.value && (!batch.best_before || new Date(batch.best_before).getTime() >= Date.now() + 259200000)) return false
  if (shortageFilter.value && !shoppingProductIds.value.has(batch.product_id)) return false
  return true
}).sort((a, b) => sortBy.value === 'name' ? a.product.name.localeCompare(b.product.name, 'de') : sortBy.value === 'quantity' ? Number(a.quantity) - Number(b.quantity) : (a.best_before || '9999').localeCompare(b.best_before || '9999')))
const filteredMovements = computed(() => movements.value.filter(item => {
  if (historyType.value && item.movement_type !== historyType.value) return false
  if (historyProduct.value && item.product_id !== historyProduct.value) return false
  if (historyUser.value && item.user_id !== historyUser.value) return false
  const timestamp = new Date(item.created_at).getTime()
  if (historyStart.value && timestamp < new Date(`${historyStart.value}T00:00:00`).getTime()) return false
  if (historyEnd.value && timestamp > new Date(`${historyEnd.value}T23:59:59`).getTime()) return false
  return true
}))
const batchMap = computed(() => new Map(batches.value.map(batch => [batch.id, batch])))
const movementNames: Record<string, string> = { purchase: 'Eingebucht', consume: 'Entnommen', discard: 'Entsorgt', adjust: 'Inventur', transfer: 'Ungelagert', reversal: 'Storniert' }

async function load() {
  const [stock, productList, locationList, movementList, shoppingList, notificationList, householdData, memberList, preferences] = await Promise.all([
    api.stock(), api.products(), api.locations(), api.movements(), api.shoppingList(), api.notifications(), api.household(), api.members(), api.notificationPreferences()
  ])
  batches.value = stock; products.value = productList; locations.value = locationList; movements.value = movementList; shopping.value = shoppingList; notifications.value = notificationList; household.value = householdData; members.value = memberList; notificationChannels.value = preferences.channels
}
function clearQueryToken(name: string) { const url = new URL(window.location.href); url.searchParams.delete(name); window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`) }
async function acceptPendingInvitation() { if (!inviteToken.value) return; await api.acceptInvitation(inviteToken.value); inviteToken.value = ''; clearQueryToken('invite') }
async function login() { busy.value = true; error.value = ''; try { await api.login(email.value, password.value); loggedIn.value = true; await acceptPendingInvitation(); await load(); startLive() } catch(e) { error.value = String((e as Error).message) } finally { busy.value = false } }
async function register() { busy.value = true; error.value = ''; try { await api.register(email.value, displayName.value, password.value, inviteToken.value ? null : householdName.value, inviteToken.value || null); if (inviteToken.value) { inviteToken.value = ''; clearQueryToken('invite') } loggedIn.value = true; await load(); startLive() } catch(e) { error.value = String((e as Error).message) } finally { busy.value = false } }
async function requestReset() { const address = prompt('Für welche E-Mail-Adresse soll ein Reset-Link versendet werden?', email.value); if (!address) return; try { const result = await api.requestPasswordReset(address); alert(result.message) } catch(e) { error.value = (e as Error).message } }
async function completeReset() { busy.value = true; error.value = ''; try { await api.confirmPasswordReset(resetToken.value, resetPassword.value); loggedIn.value = false; resetComplete.value = true; resetToken.value = ''; clearQueryToken('reset_token') } catch(e) { error.value = (e as Error).message } finally { busy.value = false } }
async function createInvitation() { const address = prompt('E-Mail-Adresse der eingeladenen Person (optional)', '') ?? ''; const role = prompt('Rolle: admin, member oder viewer', 'member'); if (!role) return; try { const result = await api.createInvitation(address, role); invitationLink.value = result.invitation_url } catch(e) { error.value = (e as Error).message } }
async function editHousehold() { if (!household.value) return; const name = prompt('Name des Haushalts', household.value.name); if (!name) return; const days = Number(prompt('Wie viele Tage vor dem MHD warnen?', String(household.value.expiry_warning_days))); if (!Number.isFinite(days) || days < 0) return; try { household.value = await api.updateHousehold({ name, expiry_warning_days: days }) } catch(e) { error.value = (e as Error).message } }
async function changeMemberRole(member: Member) { const role = prompt('Neue Rolle: admin, member oder viewer', member.role); if (!role || role === member.role) return; try { await api.updateMember(member.user_id, role); await load() } catch(e) { error.value = (e as Error).message } }
async function removeMember(member: Member) { if (!confirm(`${member.display_name} wirklich aus dem Haushalt entfernen?`)) return; try { await api.removeMember(member.user_id); await load() } catch(e) { error.value = (e as Error).message } }
function vapidKeyBytes(value: string) { const padding = '='.repeat((4 - value.length % 4) % 4); const raw = atob((value + padding).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from([...raw].map(character => character.charCodeAt(0))) }
async function enablePush() { if (!('serviceWorker' in navigator) || !('PushManager' in window)) throw new Error('Web Push wird von diesem Browser nicht unterstützt'); if (await Notification.requestPermission() !== 'granted') throw new Error('Benachrichtigungen wurden nicht erlaubt'); const { public_key } = await api.vapidPublicKey(); const registration = await navigator.serviceWorker.ready; const subscription = await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: vapidKeyBytes(public_key) }); await api.subscribePush(subscription.toJSON()) }
async function toggleNotificationChannel(channel: string, enabled: boolean) { try { if (channel === 'push' && enabled) await enablePush(); const channels = enabled ? [...new Set([...notificationChannels.value, channel])] : notificationChannels.value.filter(item => item !== channel); const result = await api.setNotificationPreferences(channels); notificationChannels.value = result.channels; if (channel === 'in_app' && !enabled) notifications.value = [] } catch(e) { error.value = (e as Error).message } }
function isQueued(result: unknown): result is QueuedResult { return Boolean(result && typeof result === 'object' && 'queued' in result) }
async function handleQueued() { notice.value = t('offlinePending'); await refreshOffline() }
async function add() { busy.value = true; error.value = ''; try { const result = await api.purchase({ product_id: selectedProduct.value, location_id: selectedLocation.value, quantity: quantity.value, unit: unit.value, best_before: bestBefore.value || null, idempotency_key: crypto.randomUUID(), client_info: navigator.userAgent }); if (isQueued(result)) await handleQueued(); else remember([result]); showAdd.value = false; if (online.value) await load() } catch(e) { error.value = (e as Error).message } finally { busy.value = false } }
function remember(results: MovementResult[]) { lastMovements.value = results.map(result => ({ id: result.movement.id, version: result.batch.version })); setTimeout(() => lastMovements.value = [], 10000) }
async function consume(batch: Batch) { const amount = Number(prompt(`Wie viel ${batch.unit} entnehmen? Früheste MHD-Chargen werden zuerst verwendet.`, '1')); if (!amount) return; try { const result = await api.consumeFefo(batch.product_id, batch.unit, amount, batches.value); if (isQueued(result)) await handleQueued(); else remember(result); if (online.value) await load() } catch(e) { error.value = (e as Error).message; if (online.value) await load() } }
async function discard(batch: Batch) { const amount = Number(prompt(`Wie viel ${batch.unit} entsorgen?`, '1')); if (!amount) return; try { const result = await api.discard(batch, amount); if (isQueued(result)) await handleQueued(); else remember([result]); if (online.value) await load() } catch(e) { error.value = (e as Error).message; if (online.value) await load() } }
async function transfer(batch: Batch) { const targets = locations.value.filter(item => item.id !== batch.location_id); const choice = prompt(`Ziellagerort:\n${targets.map((item, index) => `${index + 1}: ${item.name}`).join('\n')}`, '1'); if (!choice) return; const target = targets[Number(choice) - 1]; if (!target) { error.value = 'Ungültiger Lagerort'; return } const amount = Number(prompt(`Wie viel ${batch.unit} umlagern?`, String(Number(batch.quantity)))); if (!amount) return; try { const result = await api.transfer(batch, target.id, amount); if (isQueued(result)) await handleQueued(); else notice.value = 'Umlagerung gespeichert'; if (online.value) await load() } catch(e) { error.value = (e as Error).message; if (online.value) await load() } }
async function editBatch(batch: Batch) { const date = prompt('Mindesthaltbar bis (JJJJ-MM-TT, leer für kein Datum)', batch.best_before || ''); if (date === null) return; const opened = prompt('Geöffnet am (JJJJ-MM-TT, leer für kein Datum)', batch.opened_at || ''); if (opened === null) return; const newUnit = prompt('Einheit', batch.unit); if (!newUnit) return; const choices = locations.value.map((item, index) => `${index + 1}: ${item.name}`).join('\n'); const currentIndex = locations.value.findIndex(item => item.id === batch.location_id); const locationChoice = prompt(`Lagerort:\n${choices}`, String(currentIndex + 1)); if (!locationChoice) return; const location = locations.value[Number(locationChoice) - 1]; if (!location) { error.value = 'Ungültiger Lagerort'; return } try { await api.updateBatch(batch.id, { best_before: date || null, opened_at: opened || null, unit: newUnit, location_id: location.id, expected_version: batch.version }); await load() } catch(e) { error.value = (e as Error).message } }
async function undo() { if (!lastMovements.value.length) return; try { for (const movement of [...lastMovements.value].reverse()) await api.reverse(movement.id, movement.version); lastMovements.value = []; await load() } catch(e) { error.value = (e as Error).message } }
async function configureMinimum(product: Product) { const value = prompt(`Mindestbestand für ${product.name} (${product.default_unit})`, '1'); if (value === null || !Number(value)) return; try { await api.setMinStock(product.id, Number(value), product.default_unit); await load() } catch(e) { error.value = (e as Error).message } }
async function editProduct(product: Product) { const name = prompt('Produktname', product.name); if (!name) return; const brand = prompt('Marke', product.brand || ''); if (brand === null) return; const category = prompt('Kategorie', product.category || ''); if (category === null) return; const barcodes = prompt('Barcodes, durch Komma getrennt', product.barcodes.map(item => item.barcode).join(', ')); if (barcodes === null) return; const notes = prompt('Notizen', product.notes || ''); if (notes === null) return; try { await api.updateProduct(product.id, { name, brand: brand || null, category: category || null, notes: notes || null, barcodes: barcodes.split(',').map(item => item.trim()).filter(Boolean) }); await load() } catch(e) { error.value = (e as Error).message } }
async function checkWarnings() { try { await api.checkNotifications(); await load() } catch(e) { error.value = (e as Error).message } }
async function readWarning(notification: Notification) { if (notification.read_at) return; try { await api.markNotificationRead(notification.id); await load() } catch(e) { error.value = (e as Error).message } }
async function startInventory() { try { inventory.value = await api.startInventory(selectedLocation.value || undefined); activeView.value = 'inventory' } catch(e) { error.value = (e as Error).message } }
async function saveCount(batchId: string, event: Event) { if (!inventory.value) return; const value = Number((event.target as HTMLInputElement).value); try { await api.recordCount(inventory.value.session.id, batchId, value); const count = inventory.value.counts.find(item => item.batch_id === batchId); if (count) count.counted_quantity = String(value) } catch(e) { error.value = (e as Error).message } }
async function confirmInventory() { if (!inventory.value || !confirm('Abweichungen jetzt als Korrekturbuchungen übernehmen?')) return; try { await api.confirmInventory(inventory.value.session.id); inventory.value = null; await load(); activeView.value = 'stock' } catch(e) { error.value = (e as Error).message } }
async function logout() { await api.logout(); window.location.reload() }
async function selectBarcode(code: string) { let product: Product; try { product = await api.barcode(code) } catch { const found = await api.lookup(code); const name = prompt('Produktname bestätigen oder anpassen', found.name || `Artikel ${code}`); if (!name) return; product = await api.createProduct({ name, brand: found.brand, image_url: found.image_url, default_unit: 'piece', barcodes: [code] }) } selectedProduct.value = product.id; unit.value = product.default_unit; showAdd.value = true }
async function createManualProduct() { const name = prompt('Name des neuen Produkts'); if (!name) return; const brand = prompt('Marke (optional)', '') || null; const category = prompt('Kategorie (optional)', '') || null; const defaultUnit = prompt('Standardeinheit: piece, g, kg, ml, l oder package', 'piece'); if (!defaultUnit) return; try { const product = await api.createProduct({ name, brand, category, default_unit: defaultUnit, barcodes: [] }); products.value.push(product); selectedProduct.value = product.id; unit.value = product.default_unit } catch(e) { error.value = (e as Error).message } }
async function manualBarcode() { const code = prompt('EAN-8, EAN-13 oder UPC eingeben'); if (!code) return; try { await selectBarcode(code.trim()) } catch(e) { error.value = (e as Error).message } }
async function scan() { scanning.value = true; error.value = ''; await new Promise(resolve => setTimeout(resolve)); const reader = new BrowserMultiFormatReader(); try { const result = await reader.decodeOnceFromVideoDevice(undefined, 'scanner'); await selectBarcode(result.getText()) } catch { error.value = 'Scanner konnte nicht gestartet werden. Bitte Barcode manuell eingeben.' } finally { const video = document.querySelector<HTMLVideoElement>('#scanner'); if (video?.srcObject instanceof MediaStream) video.srcObject.getTracks().forEach(track => track.stop()); scanning.value = false } }
async function refreshOffline() { const state = await api.offlineState(); pendingOffline.value = state.pending; conflicts.value = state.conflicts }
async function syncOffline() { online.value = navigator.onLine; if (!online.value) return; try { const state = await api.flushOffline(); pendingOffline.value = state.pending; conflicts.value = state.conflicts; await load() } catch(e) { error.value = (e as Error).message } }
async function retryOffline(conflict: OfflineConflict) { try { const state = await api.retryOfflineConflict(conflict); pendingOffline.value = state.pending; conflicts.value = state.conflicts; await load() } catch(e) { error.value = (e as Error).message; await refreshOffline() } }
async function discardOffline(key: string) { const state = await api.discardOfflineConflict(key); pendingOffline.value = state.pending; conflicts.value = state.conflicts }
let eventsController: AbortController | null = null
function startLive() { eventsController?.abort(); eventsController = api.watchEvents(() => load().catch(() => undefined)) }
function markOffline() { online.value = false }
onMounted(async () => { window.addEventListener('online', syncOffline); window.addEventListener('offline', markOffline); await refreshOffline(); if (loggedIn.value) { try { await acceptPendingInvitation(); await syncOffline(); startLive() } catch(e) { error.value = (e as Error).message } } })
onUnmounted(() => { eventsController?.abort(); window.removeEventListener('online', syncOffline); window.removeEventListener('offline', markOffline) })
</script>

<template>
  <main v-if="resetToken" class="login-shell">
    <section class="login-card">
      <div class="brand-mark">V</div><p class="eyebrow">KONTO SCHÜTZEN</p><h1>Neues Passwort</h1><p class="muted">Vergib ein neues Passwort mit mindestens zehn Zeichen.</p>
      <form @submit.prevent="completeReset"><label>Neues Passwort<input v-model="resetPassword" type="password" minlength="10" autocomplete="new-password" required></label><p v-if="error" class="error">{{ error }}</p><button class="primary" :disabled="busy">Passwort speichern</button></form>
    </section>
  </main>

  <main v-else-if="!loggedIn" class="login-shell">
    <section class="login-card">
      <div class="brand-mark">V</div><p class="eyebrow">ZUHAUSE GUT VERSORGT</p><h1>Vorrat</h1><p class="muted">Lebensmittel gemeinsam im Blick behalten.</p>
      <p v-if="resetComplete" class="success">Das Passwort wurde geändert. Du kannst dich jetzt anmelden.</p>
      <p v-if="inviteToken" class="invite-note">Melde dich an oder erstelle ein Konto, um die Haushaltseinladung anzunehmen.</p>
      <form @submit.prevent="registering ? register() : login()"><label v-if="registering">Name<input v-model="displayName" autocomplete="name" required></label><label>E-Mail<input v-model="email" type="email" autocomplete="email" required></label><label>Passwort<input v-model="password" type="password" :autocomplete="registering ? 'new-password' : 'current-password'" :minlength="registering ? 10 : undefined" required></label><label v-if="registering && !inviteToken">Name des Haushalts<input v-model="householdName" required></label><p v-if="error" class="error">{{ error }}</p><button class="primary" :disabled="busy">{{ registering ? 'Konto erstellen' : 'Anmelden' }}</button><button type="button" class="link-button" @click="registering = !registering; error = ''">{{ registering ? 'Schon registriert? Anmelden' : 'Noch kein Konto? Registrieren' }}</button><button v-if="!registering" type="button" class="link-button" @click="requestReset">Passwort vergessen?</button></form>
    </section>
  </main>

  <main v-else class="app-shell">
    <header><div><p class="eyebrow">GUTEN APPETIT</p><h1>{{ activeView === 'stock' ? t('stock') : activeView === 'history' ? 'Verlauf' : activeView === 'inventory' ? 'Inventur' : 'Einstellungen' }}</h1></div><button class="avatar" aria-label="Abmelden" @click="logout">FH</button></header>
    <p v-if="error" class="error banner">{{ error }} <button @click="error=''">×</button></p>
    <p v-if="notice" class="success banner">{{ notice }} <button @click="notice=''">×</button></p>
    <p v-if="!online || pendingOffline" class="offline-banner">{{ online ? `${pendingOffline} Aktion(en) werden synchronisiert` : 'Offline – Aktionen werden sicher vorgemerkt' }}</p>

    <template v-if="activeView === 'stock'">
      <section class="summary"><div><strong>{{ batches.length }}</strong><span>Chargen</span></div><div><strong>{{ shopping.length }}</strong><span>nachkaufen</span></div><div><strong>{{ batches.filter(b => b.best_before && new Date(b.best_before).getTime() < Date.now()+259200000).length }}</strong><span>bald fällig</span></div></section>
      <div class="actions"><button class="scan" @click="scan">⌁ {{ t('scan') }}</button><button class="add" @click="manualBarcode">⌨ {{ t('manualBarcode') }}</button><button class="add" @click="showAdd = true">＋ {{ t('add') }}</button></div>
      <video v-show="scanning" id="scanner" class="scanner"></video>
      <label class="search">⌕<input v-model="search" :placeholder="t('search')"></label>
      <details class="filters"><summary>{{ t('filters') }}</summary><div class="filter-grid"><select v-model="locationFilter"><option value="">{{ t('allLocations') }}</option><option v-for="location in locations" :key="location.id" :value="location.id">{{ location.name }}</option></select><select v-model="categoryFilter"><option value="">{{ t('allCategories') }}</option><option v-for="category in categories" :key="category">{{ category }}</option></select><select v-model="sortBy"><option value="expiry">Nach MHD</option><option value="name">Nach Name</option><option value="quantity">Nach Menge</option></select><label><input v-model="expiryFilter" type="checkbox"> {{ t('expiringSoon') }}</label><label><input v-model="shortageFilter" type="checkbox"> {{ t('lowStock') }}</label></div></details>
      <section v-if="shopping.length" class="shopping-card"><p class="eyebrow">EINKAUFSLISTE</p><div v-for="item in shopping" :key="item.product_id"><strong>{{ item.product_name }}</strong><span>{{ Number(item.missing_quantity) }} {{ item.unit }} fehlen</span></div></section>
      <section class="list"><article v-for="batch in filtered" :key="batch.id" class="stock-card"><div class="product-icon">{{ batch.product.name.slice(0,1) }}</div><div class="product-copy"><h2>{{ batch.product.name }}</h2><p>{{ batch.product.brand || batch.product.category || 'Lebensmittel' }}</p><small>{{ locations.find(item => item.id === batch.location_id)?.name }}<template v-if="batch.best_before"> · {{ t('expires') }} {{ new Date(batch.best_before).toLocaleDateString('de-DE') }}</template></small></div><div class="amount"><strong>{{ Number(batch.quantity) }}</strong><span>{{ batch.unit }}</span><div class="batch-actions"><button @click="consume(batch)">{{ t('consume') }}</button><button @click="discard(batch)">{{ t('discard') }}</button><button @click="transfer(batch)">Umlagern</button><button @click="editBatch(batch)">Bearbeiten</button></div></div></article><div v-if="!filtered.length" class="empty"><span>◌</span><h2>{{ t('empty') }}</h2><p>Scanne einen Barcode oder buche einen Artikel manuell ein.</p></div></section>
    </template>

    <template v-else-if="activeView === 'history'">
      <div class="history-filters"><select v-model="historyType"><option value="">Alle Buchungstypen</option><option v-for="(label, value) in movementNames" :key="value" :value="value">{{ label }}</option></select><select v-model="historyProduct"><option value="">Alle Produkte</option><option v-for="product in products" :key="product.id" :value="product.id">{{ product.name }}</option></select><select v-model="historyUser"><option value="">Alle Personen</option><option v-for="member in members" :key="member.user_id" :value="member.user_id">{{ member.display_name }}</option></select><label>Von<input v-model="historyStart" type="date"></label><label>Bis<input v-model="historyEnd" type="date"></label><button class="export-button" @click="api.downloadHistory().catch(e => error=e.message)">CSV exportieren</button></div>
      <section class="timeline"><article v-for="movement in filteredMovements" :key="movement.id"><span class="timeline-dot"></span><div><strong>{{ movementNames[movement.movement_type] || movement.movement_type }}</strong><p>{{ movement.product_name || batchMap.get(movement.batch_id)?.product.name || 'Bestandsposition' }} · {{ Number(movement.quantity_delta) > 0 ? '+' : '' }}{{ Number(movement.quantity_delta) }}</p><small>{{ movement.user_name || 'Unbekannt' }} · {{ new Date(movement.created_at).toLocaleString('de-DE') }}<template v-if="movement.client_info"> · {{ movement.client_info }}</template></small></div></article></section>
    </template>

    <template v-else-if="activeView === 'inventory'">
      <section v-if="!inventory" class="empty panel"><span>✓</span><h2>Bestand zählen</h2><p>Starte eine Inventur für den ganzen Haushalt oder einen Lagerort.</p><select v-model="selectedLocation"><option value="">Ganzer Haushalt</option><option v-for="location in locations" :value="location.id">{{ location.name }}</option></select><button class="primary" @click="startInventory">Inventur starten</button></section>
      <section v-else><p class="muted inventory-intro">Trage die tatsächlich vorhandene Menge ein. Änderungen werden erst nach Bestätigung gebucht.</p><article v-for="count in inventory.counts" :key="count.batch_id" class="count-row"><div><strong>{{ batchMap.get(count.batch_id)?.product.name || 'Artikel' }}</strong><small>Soll: {{ Number(count.expected_quantity) }} {{ batchMap.get(count.batch_id)?.unit }}</small></div><input type="number" min="0" step="0.001" :value="Number(count.counted_quantity)" @change="saveCount(count.batch_id, $event)"></article><button class="primary full" @click="confirmInventory">Inventur abschließen</button></section>
    </template>

    <template v-else>
      <section class="settings-list">
        <div class="section-heading"><div><p class="eyebrow">{{ t('conflicts').toUpperCase() }}</p><h2>Offline-Synchronisation</h2></div><button v-if="online && pendingOffline" @click="syncOffline">Jetzt senden</button></div>
        <p v-if="!conflicts.length" class="muted no-warnings">Keine offenen Konflikte. {{ pendingOffline ? `${pendingOffline} Aktion(en) warten auf Verbindung.` : 'Alle Änderungen sind synchronisiert.' }}</p>
        <article v-for="conflict in conflicts" :key="conflict.key" class="conflict"><div><strong>{{ conflict.message }}</strong><small>{{ new Date(conflict.failedAt).toLocaleString('de-DE') }} · {{ conflict.url }}</small></div><div><button @click="retryOffline(conflict)">Neu prüfen</button><button @click="discardOffline(conflict.key)">Verwerfen</button></div></article>

        <div class="section-heading warnings-heading"><div><p class="eyebrow">HAUSHALT</p><h2>{{ household?.name || 'Haushalt' }}</h2></div><button @click="editHousehold">Einstellungen</button></div>
        <article v-for="member in members" :key="member.user_id"><div><strong>{{ member.display_name }}</strong><small>{{ member.email }} · {{ member.role }}</small></div><div><button v-if="member.role !== 'owner'" @click="changeMemberRole(member)">Rolle</button><button v-if="member.role !== 'owner'" @click="removeMember(member)">Entfernen</button></div></article>
        <div class="section-heading"><div><h2>Mitglieder einladen</h2></div><button @click="createInvitation">Einladung erstellen</button></div>
        <div v-if="invitationLink" class="invitation-result"><strong>Einladungslink</strong><input :value="invitationLink" readonly @focus="($event.target as HTMLInputElement).select()"><small>Der Link ist sieben Tage gültig und wird nur hier vollständig angezeigt.</small></div>

        <div class="section-heading warnings-heading"><div><p class="eyebrow">KANÄLE</p><h2>Benachrichtigungen</h2></div></div>
        <div class="channel-options"><label><input type="checkbox" :checked="notificationChannels.includes('in_app')" @change="toggleNotificationChannel('in_app', ($event.target as HTMLInputElement).checked)"> In der App</label><label><input type="checkbox" :checked="notificationChannels.includes('email')" @change="toggleNotificationChannel('email', ($event.target as HTMLInputElement).checked)"> E-Mail</label><label><input type="checkbox" :checked="notificationChannels.includes('push')" @change="toggleNotificationChannel('push', ($event.target as HTMLInputElement).checked)"> Web Push</label></div>
        <div class="section-heading warnings-heading"><div><p class="eyebrow">WARNUNGEN</p><h2>Hinweise</h2></div><button @click="checkWarnings">Jetzt prüfen</button></div>
        <article v-for="notification in notifications" :key="notification.id" :class="{unread: !notification.read_at}" @click="readWarning(notification)"><div><strong>{{ notification.kind === 'low_stock' ? 'Mindestbestand' : 'MHD' }}</strong><small>{{ notification.message }}</small></div><span>{{ notification.read_at ? '✓' : 'Neu' }}</span></article>
        <p v-if="!notifications.length" class="muted no-warnings">Keine aktuellen Warnungen.</p>
        <p class="muted products-intro">Produkte und Mindestbestände verwalten. Änderungen werden im Audit-Log gespeichert.</p>
        <article v-for="product in products" :key="product.id"><div><strong>{{ product.name }}</strong><small>{{ product.brand || product.category || product.default_unit }}</small></div><div><button @click="configureMinimum(product)">Minimum</button><button @click="editProduct(product)">Bearbeiten</button></div></article>
      </section>
    </template>

    <nav><button :class="{active:activeView==='stock'}" @click="activeView='stock'">⌂<span>Vorrat</span></button><button :class="{active:activeView==='history'}" @click="activeView='history'">≡<span>Verlauf</span></button><button :class="{active:activeView==='inventory'}" @click="activeView='inventory'">✓<span>Inventur</span></button><button :class="{active:activeView==='more'}" @click="activeView='more'">⚙<span>Mehr</span></button></nav>
    <div v-if="lastMovements.length" class="snackbar">Buchung gespeichert <button @click="undo">Rückgängig</button></div>
    <div v-if="showAdd" class="modal" @click.self="showAdd=false"><form class="sheet" @submit.prevent="add"><div class="handle"></div><h2>Artikel einbuchen</h2><label>Produkt<select v-model="selectedProduct" required><option disabled value="">Bitte wählen</option><option v-for="product in products" :value="product.id">{{ product.name }}</option></select></label><button type="button" class="ghost" @click="createManualProduct">Neues Produkt manuell anlegen</button><div class="row"><label>Menge<input v-model.number="quantity" type="number" min="0.001" step="0.001" required></label><label>Einheit<select v-model="unit"><option value="piece">Stück</option><option>g</option><option>kg</option><option>ml</option><option>l</option><option value="package">Packung</option></select></label></div><label>Lagerort<select v-model="selectedLocation" required><option disabled value="">Bitte wählen</option><option v-for="location in locations" :value="location.id">{{ location.name }}</option></select></label><label>Mindesthaltbar bis<input v-model="bestBefore" type="date"></label><button class="primary" :disabled="busy">Einbuchen</button><button type="button" class="ghost" @click="showAdd=false">Abbrechen</button></form></div>
  </main>
</template>
