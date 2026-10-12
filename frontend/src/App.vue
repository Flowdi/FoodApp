<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { BrowserMultiFormatReader } from '@zxing/browser'
import { api, type Batch, type Location, type Product } from './api'
import { t } from './i18n'

const loggedIn = ref(api.authenticated())
const email = ref('demo@vorrat.local'), password = ref('demo-password')
const batches = ref<Batch[]>([]), products = ref<Product[]>([]), locations = ref<Location[]>([])
const search = ref(''), busy = ref(false), error = ref(''), showAdd = ref(false), scanning = ref(false)
const selectedProduct = ref(''), selectedLocation = ref(''), quantity = ref(1), unit = ref('piece'), bestBefore = ref('')
const lastMovement = ref<{ id: string; version: number } | null>(null)
const filtered = computed(() => batches.value.filter(b => b.product.name.toLowerCase().includes(search.value.toLowerCase())))

async function load() { [batches.value, products.value, locations.value] = await Promise.all([api.stock(), api.products(), api.locations()]) }
async function login() { busy.value = true; error.value = ''; try { await api.login(email.value, password.value); loggedIn.value = true; await load() } catch(e) { error.value = String((e as Error).message) } finally { busy.value = false } }
async function add() { busy.value = true; error.value = ''; try { const result = await api.purchase({ product_id: selectedProduct.value, location_id: selectedLocation.value, quantity: quantity.value, unit: unit.value, best_before: bestBefore.value || null, idempotency_key: crypto.randomUUID(), client_info: navigator.userAgent }); lastMovement.value = { id: result.movement.id, version: result.batch.version }; showAdd.value = false; await load(); setTimeout(() => lastMovement.value = null, 10000) } catch(e) { error.value = (e as Error).message } finally { busy.value = false } }
async function consume(batch: Batch) { const amount = Number(prompt(`Wie viel ${batch.unit} entnehmen?`, '1')); if (!amount) return; try { const result = await api.consume(batch, amount); lastMovement.value = { id: result.movement.id, version: result.batch.version }; await load(); setTimeout(() => lastMovement.value = null, 10000) } catch(e) { error.value = (e as Error).message; await load() } }
async function undo() { if (!lastMovement.value) return; try { await api.reverse(lastMovement.value.id, lastMovement.value.version); lastMovement.value = null; await load() } catch(e) { error.value = (e as Error).message } }
function logout() { api.logout(); window.location.reload() }
async function scan() { scanning.value = true; error.value = ''; await new Promise(r => setTimeout(r)); const reader = new BrowserMultiFormatReader(); try { const result = await reader.decodeOnceFromVideoDevice(undefined, 'scanner'); let product: Product; try { product = await api.barcode(result.getText()) } catch { const found = await api.lookup(result.getText()); product = await api.createProduct({ name: found.name || `Artikel ${result.getText()}`, brand: found.brand, image_url: found.image_url, default_unit: 'piece', barcodes: [result.getText()] }) } selectedProduct.value = product.id; unit.value = product.default_unit; showAdd.value = true } catch(e) { error.value = 'Scanner konnte nicht gestartet werden. Bitte Barcode manuell suchen.' } finally { const video = document.querySelector<HTMLVideoElement>('#scanner'); if (video?.srcObject instanceof MediaStream) video.srcObject.getTracks().forEach(track => track.stop()); scanning.value = false } }
onMounted(() => { if (loggedIn.value) load().catch(e => error.value = e.message) })
</script>

<template>
  <main v-if="!loggedIn" class="login-shell">
    <section class="login-card"><div class="brand-mark">V</div><p class="eyebrow">ZUHAUSE GUT VERSORGT</p><h1>Vorrat</h1><p class="muted">Lebensmittel gemeinsam im Blick behalten.</p>
      <form @submit.prevent="login"><label>E-Mail<input v-model="email" type="email" autocomplete="email" required></label><label>Passwort<input v-model="password" type="password" autocomplete="current-password" required></label><p v-if="error" class="error">{{ error }}</p><button class="primary" :disabled="busy">Anmelden</button></form>
    </section>
  </main>
  <main v-else class="app-shell">
    <header><div><p class="eyebrow">GUTEN APPETIT</p><h1>{{ t('stock') }}</h1></div><button class="avatar" aria-label="Abmelden" @click="logout">FH</button></header>
    <section class="summary"><div><strong>{{ batches.length }}</strong><span>Chargen</span></div><div><strong>{{ products.length }}</strong><span>Produkte</span></div><div><strong>{{ batches.filter(b => b.best_before && new Date(b.best_before).getTime() < Date.now()+259200000).length }}</strong><span>bald fällig</span></div></section>
    <div class="actions"><button class="scan" @click="scan">⌁ {{ t('scan') }}</button><button class="add" @click="showAdd = true">＋ {{ t('add') }}</button></div>
    <video v-show="scanning" id="scanner" class="scanner"></video>
    <label class="search">⌕<input v-model="search" :placeholder="t('search')"></label>
    <p v-if="error" class="error banner">{{ error }} <button @click="error=''">×</button></p>
    <section class="list"><article v-for="batch in filtered" :key="batch.id" class="stock-card"><div class="product-icon">{{ batch.product.name.slice(0,1) }}</div><div class="product-copy"><h2>{{ batch.product.name }}</h2><p>{{ batch.product.brand || batch.product.category || 'Lebensmittel' }}</p><small v-if="batch.best_before">{{ t('expires') }} {{ new Date(batch.best_before).toLocaleDateString('de-DE') }}</small></div><div class="amount"><strong>{{ Number(batch.quantity) }}</strong><span>{{ batch.unit }}</span><button @click="consume(batch)">{{ t('consume') }}</button></div></article><div v-if="!filtered.length" class="empty"><span>◌</span><h2>{{ t('empty') }}</h2><p>Scanne einen Barcode oder buche einen Artikel manuell ein.</p></div></section>
    <nav><button class="active">⌂<span>Vorrat</span></button><button>≡<span>Verlauf</span></button><button>✓<span>Inventur</span></button><button>⚙<span>Mehr</span></button></nav>
    <div v-if="lastMovement" class="snackbar">Buchung gespeichert <button @click="undo">Rückgängig</button></div>
    <div v-if="showAdd" class="modal" @click.self="showAdd=false"><form class="sheet" @submit.prevent="add"><div class="handle"></div><h2>Artikel einbuchen</h2><label>Produkt<select v-model="selectedProduct" required><option disabled value="">Bitte wählen</option><option v-for="p in products" :value="p.id">{{ p.name }}</option></select></label><div class="row"><label>Menge<input v-model.number="quantity" type="number" min="0.001" step="0.001" required></label><label>Einheit<select v-model="unit"><option value="piece">Stück</option><option>g</option><option>kg</option><option>ml</option><option>l</option><option value="package">Packung</option></select></label></div><label>Lagerort<select v-model="selectedLocation" required><option disabled value="">Bitte wählen</option><option v-for="l in locations" :value="l.id">{{ l.name }}</option></select></label><label>Mindesthaltbar bis<input v-model="bestBefore" type="date"></label><button class="primary" :disabled="busy">Einbuchen</button><button type="button" class="ghost" @click="showAdd=false">Abbrechen</button></form></div>
  </main>
</template>
