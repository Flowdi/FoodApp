<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { BrowserMultiFormatReader } from '@zxing/browser'
import { api, type Batch, type InventoryDetail, type Location, type Movement, type Notification, type Product, type ShoppingItem } from './api'
import { t } from './i18n'

type View = 'stock' | 'history' | 'inventory' | 'more'

const loggedIn = ref(api.authenticated())
const email = ref('demo@vorrat.local'), password = ref('demo-password')
const batches = ref<Batch[]>([]), products = ref<Product[]>([]), locations = ref<Location[]>([])
const movements = ref<Movement[]>([]), shopping = ref<ShoppingItem[]>([])
const notifications = ref<Notification[]>([])
const activeView = ref<View>('stock'), search = ref(''), busy = ref(false), error = ref('')
const showAdd = ref(false), scanning = ref(false), inventory = ref<InventoryDetail | null>(null)
const selectedProduct = ref(''), selectedLocation = ref(''), quantity = ref(1), unit = ref('piece'), bestBefore = ref('')
const lastMovement = ref<{ id: string; version: number } | null>(null)
const filtered = computed(() => batches.value.filter(batch => batch.product.name.toLowerCase().includes(search.value.toLowerCase())))
const batchMap = computed(() => new Map(batches.value.map(batch => [batch.id, batch])))
const movementNames: Record<string, string> = { purchase: 'Eingebucht', consume: 'Entnommen', discard: 'Entsorgt', adjust: 'Inventur', transfer: 'Ungelagert', reversal: 'Storniert' }

async function load() {
  [batches.value, products.value, locations.value, movements.value, shopping.value, notifications.value] = await Promise.all([
    api.stock(), api.products(), api.locations(), api.movements(), api.shoppingList(), api.notifications()
  ])
}
async function login() { busy.value = true; error.value = ''; try { await api.login(email.value, password.value); loggedIn.value = true; await load() } catch(e) { error.value = String((e as Error).message) } finally { busy.value = false } }
async function add() { busy.value = true; error.value = ''; try { const result = await api.purchase({ product_id: selectedProduct.value, location_id: selectedLocation.value, quantity: quantity.value, unit: unit.value, best_before: bestBefore.value || null, idempotency_key: crypto.randomUUID(), client_info: navigator.userAgent }); remember(result.movement.id, result.batch.version); showAdd.value = false; await load() } catch(e) { error.value = (e as Error).message } finally { busy.value = false } }
function remember(id: string, version: number) { lastMovement.value = { id, version }; setTimeout(() => lastMovement.value = null, 10000) }
async function consume(batch: Batch) { const amount = Number(prompt(`Wie viel ${batch.unit} entnehmen?`, '1')); if (!amount) return; try { const result = await api.consume(batch, amount); remember(result.movement.id, result.batch.version); await load() } catch(e) { error.value = (e as Error).message; await load() } }
async function transfer(batch: Batch) { const targets = locations.value.filter(item => item.id !== batch.location_id); const choice = prompt(`Ziellagerort:\n${targets.map((item, index) => `${index + 1}: ${item.name}`).join('\n')}`, '1'); if (!choice) return; const target = targets[Number(choice) - 1]; if (!target) { error.value = 'Ungültiger Lagerort'; return } const amount = Number(prompt(`Wie viel ${batch.unit} umlagern?`, String(Number(batch.quantity)))); if (!amount) return; try { await api.transfer(batch, target.id, amount); await load() } catch(e) { error.value = (e as Error).message; await load() } }
async function undo() { if (!lastMovement.value) return; try { await api.reverse(lastMovement.value.id, lastMovement.value.version); lastMovement.value = null; await load() } catch(e) { error.value = (e as Error).message } }
async function configureMinimum(product: Product) { const value = prompt(`Mindestbestand für ${product.name} (${product.default_unit})`, '1'); if (value === null || !Number(value)) return; try { await api.setMinStock(product.id, Number(value), product.default_unit); await load() } catch(e) { error.value = (e as Error).message } }
async function editProduct(product: Product) { const name = prompt('Produktname', product.name); if (!name || name === product.name) return; try { await api.updateProduct(product.id, { name }); await load() } catch(e) { error.value = (e as Error).message } }
async function checkWarnings() { try { await api.checkNotifications(); await load() } catch(e) { error.value = (e as Error).message } }
async function readWarning(notification: Notification) { if (notification.read_at) return; try { await api.markNotificationRead(notification.id); await load() } catch(e) { error.value = (e as Error).message } }
async function startInventory() { try { inventory.value = await api.startInventory(selectedLocation.value || undefined); activeView.value = 'inventory' } catch(e) { error.value = (e as Error).message } }
async function saveCount(batchId: string, event: Event) { if (!inventory.value) return; const value = Number((event.target as HTMLInputElement).value); try { await api.recordCount(inventory.value.session.id, batchId, value); const count = inventory.value.counts.find(item => item.batch_id === batchId); if (count) count.counted_quantity = String(value) } catch(e) { error.value = (e as Error).message } }
async function confirmInventory() { if (!inventory.value || !confirm('Abweichungen jetzt als Korrekturbuchungen übernehmen?')) return; try { await api.confirmInventory(inventory.value.session.id); inventory.value = null; await load(); activeView.value = 'stock' } catch(e) { error.value = (e as Error).message } }
function logout() { api.logout(); window.location.reload() }
async function scan() { scanning.value = true; error.value = ''; await new Promise(resolve => setTimeout(resolve)); const reader = new BrowserMultiFormatReader(); try { const result = await reader.decodeOnceFromVideoDevice(undefined, 'scanner'); let product: Product; try { product = await api.barcode(result.getText()) } catch { const found = await api.lookup(result.getText()); product = await api.createProduct({ name: found.name || `Artikel ${result.getText()}`, brand: found.brand, image_url: found.image_url, default_unit: 'piece', barcodes: [result.getText()] }) } selectedProduct.value = product.id; unit.value = product.default_unit; showAdd.value = true } catch { error.value = 'Scanner konnte nicht gestartet werden. Bitte Barcode manuell suchen.' } finally { const video = document.querySelector<HTMLVideoElement>('#scanner'); if (video?.srcObject instanceof MediaStream) video.srcObject.getTracks().forEach(track => track.stop()); scanning.value = false } }
onMounted(() => { if (loggedIn.value) load().catch(e => error.value = e.message) })
</script>

<template>
  <main v-if="!loggedIn" class="login-shell">
    <section class="login-card">
      <div class="brand-mark">V</div><p class="eyebrow">ZUHAUSE GUT VERSORGT</p><h1>Vorrat</h1><p class="muted">Lebensmittel gemeinsam im Blick behalten.</p>
      <form @submit.prevent="login"><label>E-Mail<input v-model="email" type="email" autocomplete="email" required></label><label>Passwort<input v-model="password" type="password" autocomplete="current-password" required></label><p v-if="error" class="error">{{ error }}</p><button class="primary" :disabled="busy">Anmelden</button></form>
    </section>
  </main>

  <main v-else class="app-shell">
    <header><div><p class="eyebrow">GUTEN APPETIT</p><h1>{{ activeView === 'stock' ? t('stock') : activeView === 'history' ? 'Verlauf' : activeView === 'inventory' ? 'Inventur' : 'Einstellungen' }}</h1></div><button class="avatar" aria-label="Abmelden" @click="logout">FH</button></header>
    <p v-if="error" class="error banner">{{ error }} <button @click="error=''">×</button></p>

    <template v-if="activeView === 'stock'">
      <section class="summary"><div><strong>{{ batches.length }}</strong><span>Chargen</span></div><div><strong>{{ shopping.length }}</strong><span>nachkaufen</span></div><div><strong>{{ batches.filter(b => b.best_before && new Date(b.best_before).getTime() < Date.now()+259200000).length }}</strong><span>bald fällig</span></div></section>
      <div class="actions"><button class="scan" @click="scan">⌁ {{ t('scan') }}</button><button class="add" @click="showAdd = true">＋ {{ t('add') }}</button></div>
      <video v-show="scanning" id="scanner" class="scanner"></video>
      <label class="search">⌕<input v-model="search" :placeholder="t('search')"></label>
      <section v-if="shopping.length" class="shopping-card"><p class="eyebrow">EINKAUFSLISTE</p><div v-for="item in shopping" :key="item.product_id"><strong>{{ item.product_name }}</strong><span>{{ Number(item.missing_quantity) }} {{ item.unit }} fehlen</span></div></section>
      <section class="list"><article v-for="batch in filtered" :key="batch.id" class="stock-card"><div class="product-icon">{{ batch.product.name.slice(0,1) }}</div><div class="product-copy"><h2>{{ batch.product.name }}</h2><p>{{ batch.product.brand || batch.product.category || 'Lebensmittel' }}</p><small v-if="batch.best_before">{{ t('expires') }} {{ new Date(batch.best_before).toLocaleDateString('de-DE') }}</small></div><div class="amount"><strong>{{ Number(batch.quantity) }}</strong><span>{{ batch.unit }}</span><div class="batch-actions"><button @click="consume(batch)">{{ t('consume') }}</button><button @click="transfer(batch)">Umlagern</button></div></div></article><div v-if="!filtered.length" class="empty"><span>◌</span><h2>{{ t('empty') }}</h2><p>Scanne einen Barcode oder buche einen Artikel manuell ein.</p></div></section>
    </template>

    <template v-else-if="activeView === 'history'">
      <button class="export-button" @click="api.downloadHistory().catch(e => error=e.message)">CSV exportieren</button>
      <section class="timeline"><article v-for="movement in movements" :key="movement.id"><span class="timeline-dot"></span><div><strong>{{ movementNames[movement.movement_type] || movement.movement_type }}</strong><p>{{ batchMap.get(movement.batch_id)?.product.name || 'Bestandsposition' }} · {{ Number(movement.quantity_delta) > 0 ? '+' : '' }}{{ Number(movement.quantity_delta) }}</p><small>{{ new Date(movement.created_at).toLocaleString('de-DE') }}</small></div></article></section>
    </template>

    <template v-else-if="activeView === 'inventory'">
      <section v-if="!inventory" class="empty panel"><span>✓</span><h2>Bestand zählen</h2><p>Starte eine Inventur für den ganzen Haushalt oder einen Lagerort.</p><select v-model="selectedLocation"><option value="">Ganzer Haushalt</option><option v-for="location in locations" :value="location.id">{{ location.name }}</option></select><button class="primary" @click="startInventory">Inventur starten</button></section>
      <section v-else><p class="muted inventory-intro">Trage die tatsächlich vorhandene Menge ein. Änderungen werden erst nach Bestätigung gebucht.</p><article v-for="count in inventory.counts" :key="count.batch_id" class="count-row"><div><strong>{{ batchMap.get(count.batch_id)?.product.name || 'Artikel' }}</strong><small>Soll: {{ Number(count.expected_quantity) }} {{ batchMap.get(count.batch_id)?.unit }}</small></div><input type="number" min="0" step="0.001" :value="Number(count.counted_quantity)" @change="saveCount(count.batch_id, $event)"></article><button class="primary full" @click="confirmInventory">Inventur abschließen</button></section>
    </template>

    <template v-else>
      <section class="settings-list"><div class="section-heading"><div><p class="eyebrow">WARNUNGEN</p><h2>Hinweise</h2></div><button @click="checkWarnings">Jetzt prüfen</button></div><article v-for="notification in notifications" :key="notification.id" :class="{unread: !notification.read_at}" @click="readWarning(notification)"><div><strong>{{ notification.kind === 'low_stock' ? 'Mindestbestand' : 'MHD' }}</strong><small>{{ notification.message }}</small></div><span>{{ notification.read_at ? '✓' : 'Neu' }}</span></article><p v-if="!notifications.length" class="muted no-warnings">Keine aktuellen Warnungen.</p><p class="muted products-intro">Produkte und Mindestbestände verwalten. Änderungen werden im Audit-Log gespeichert.</p><article v-for="product in products" :key="product.id"><div><strong>{{ product.name }}</strong><small>{{ product.brand || product.category || product.default_unit }}</small></div><div><button @click="configureMinimum(product)">Minimum</button><button @click="editProduct(product)">Bearbeiten</button></div></article></section>
    </template>

    <nav><button :class="{active:activeView==='stock'}" @click="activeView='stock'">⌂<span>Vorrat</span></button><button :class="{active:activeView==='history'}" @click="activeView='history'">≡<span>Verlauf</span></button><button :class="{active:activeView==='inventory'}" @click="activeView='inventory'">✓<span>Inventur</span></button><button :class="{active:activeView==='more'}" @click="activeView='more'">⚙<span>Mehr</span></button></nav>
    <div v-if="lastMovement" class="snackbar">Buchung gespeichert <button @click="undo">Rückgängig</button></div>
    <div v-if="showAdd" class="modal" @click.self="showAdd=false"><form class="sheet" @submit.prevent="add"><div class="handle"></div><h2>Artikel einbuchen</h2><label>Produkt<select v-model="selectedProduct" required><option disabled value="">Bitte wählen</option><option v-for="product in products" :value="product.id">{{ product.name }}</option></select></label><div class="row"><label>Menge<input v-model.number="quantity" type="number" min="0.001" step="0.001" required></label><label>Einheit<select v-model="unit"><option value="piece">Stück</option><option>g</option><option>kg</option><option>ml</option><option>l</option><option value="package">Packung</option></select></label></div><label>Lagerort<select v-model="selectedLocation" required><option disabled value="">Bitte wählen</option><option v-for="location in locations" :value="location.id">{{ location.name }}</option></select></label><label>Mindesthaltbar bis<input v-model="bestBefore" type="date"></label><button class="primary" :disabled="busy">Einbuchen</button><button type="button" class="ghost" @click="showAdd=false">Abbrechen</button></form></div>
  </main>
</template>
