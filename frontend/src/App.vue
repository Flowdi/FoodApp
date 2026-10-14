<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { BrowserMultiFormatReader } from '@zxing/browser'
import { api, type Batch, type Household, type InventoryDetail, type Location, type Member, type Movement, type MovementResult, type Notification, type OfflineConflict, type Product, type QueuedResult, type Receipt, type ReceiptConfig, type ReceiptLine, type RecipeRecommendation, type ShoppingItem, type VoiceAction } from './api'
import { t } from './i18n'

type View = 'stock' | 'shopping' | 'voice' | 'receipt' | 'recipes' | 'history' | 'inventory' | 'more'
type IngredientDraft = { product_id: string; quantity: number; unit: string }
type ScanMode = 'purchase' | 'consume' | 'discard' | 'inventory'

const appName = __APP_NAME__
const loggedIn = ref(api.authenticated())
const email = ref('demo@example.com'), password = ref('demo-password')
const query = new URLSearchParams(window.location.search)
const requestedMode = window.location.pathname.replace(/\/+$/, '') === '/voice' ? 'voice' : query.get('mode')
const initialView: View = requestedMode === 'shopping' || requestedMode === 'voice' || requestedMode === 'receipt' || requestedMode === 'stock' ? requestedMode : 'stock'
const explicitVoiceLaunch = requestedMode === 'voice'
const mobileDevice = window.matchMedia('(max-width: 767px)').matches
const standaloneDisplay = window.matchMedia('(display-mode: standalone)').matches || Boolean((navigator as Navigator & { standalone?: boolean }).standalone)
const resetToken = ref(query.get('reset_token') || '')
const inviteToken = ref(query.get('invite') || '')
const resetPassword = ref(''), resetComplete = ref(false), invitationLink = ref('')
const registering = ref(false), displayName = ref(''), householdName = ref('')
const batches = ref<Batch[]>([]), products = ref<Product[]>([]), locations = ref<Location[]>([])
const movements = ref<Movement[]>([]), shopping = ref<ShoppingItem[]>([])
const recipeRecommendations = ref<RecipeRecommendation[]>([]), recipeTags = ref(''), excludedRecipeTags = ref(''), recipeServings = ref<number | undefined>()
const notifications = ref<Notification[]>([])
const receipts = ref<Receipt[]>([]), activeReceipt = ref<Receipt | null>(null), receiptConfig = ref<ReceiptConfig | null>(null)
const receiptFiles = ref<File[]>([]), receiptPreviews = ref<string[]>([]), receiptImageUrl = ref(''), selectedReceiptLine = ref<string | null>(null), allowReceiptDuplicate = ref(false), receiptDragging = ref(false)
const household = ref<Household | null>(null), members = ref<Member[]>([]), notificationChannels = ref<string[]>([])
const activeView = ref<View>(initialView), search = ref(''), busy = ref(false), error = ref('')
const notice = ref(''), locationFilter = ref(''), categoryFilter = ref(''), expiryFilter = ref(false), shortageFilter = ref(false), sortBy = ref('expiry')
const historyType = ref(''), historyProduct = ref(''), historyUser = ref(''), historyStart = ref(''), historyEnd = ref(''), pendingOffline = ref(0), conflicts = ref<OfflineConflict[]>([]), online = ref(navigator.onLine)
const showAdd = ref(false), scanning = ref(false), inventory = ref<InventoryDetail | null>(null)
const showRecipe = ref(false), recipeName = ref(''), recipeInstructions = ref(''), recipeTagInput = ref(''), recipePortions = ref(2), recipeIngredients = ref<IngredientDraft[]>([{ product_id: '', quantity: 1, unit: 'piece' }])
const editingRecipeId = ref<string | null>(null)
const selectedProduct = ref(''), selectedLocation = ref(''), quantity = ref(1), unit = ref('piece'), bestBefore = ref('')
const productSearch = ref('')
const shoppingProductSearch = ref(''), shoppingProductId = ref(''), shoppingText = ref(''), shoppingQuantity = ref(1), shoppingUnit = ref('piece')
const shoppingUndo = ref<{ itemId: string; itemVersion: number; batchVersion: number } | null>(null)
const voiceText = ref(''), voiceActions = ref<VoiceAction[]>([]), voiceRecording = ref(false)
const voiceLevel = ref(0), voiceStatus = ref('Bereit'), voiceResult = ref('')
const voiceAutoConfirm = ref(false), voiceSpeechOutput = ref(false), voiceStartOnLaunch = ref<boolean | null>(null)
const voicePermissionIntro = ref(false), voiceLaunchFallback = ref(false)
const voiceCountdown = ref(0)
let voiceRecorder: MediaRecorder | null = null
let voiceStream: MediaStream | null = null
let voiceAudioContext: AudioContext | null = null
let voiceMeter: number | undefined
let voiceTimeout: number | undefined
let voiceAutoTimer: number | undefined
let voiceLaunchHandled = false
let receiptPollTimer: number | undefined
const swipeStarts = new Map<string, number>()
const lastMovements = ref<{ id: string; version: number }[]>([])
const shoppingProductIds = computed(() => new Set(shopping.value.filter(item => item.status === 'open').map(item => item.product_id)))
const openShopping = computed(() => shopping.value.filter(item => item.status === 'open').sort((a, b) => (a.category || 'Sonstiges').localeCompare(b.category || 'Sonstiges', 'de') || a.product_name.localeCompare(b.product_name, 'de')))
const checkedShopping = computed(() => shopping.value.filter(item => item.status === 'checked'))
const shoppingGroups = computed(() => [...new Set(openShopping.value.map(item => item.category || 'Sonstiges'))].map(category => ({ category, items: openShopping.value.filter(item => (item.category || 'Sonstiges') === category) })))
const viewTitle = computed(() => ({ stock: t('stock'), shopping: t('shopping'), voice: t('voice'), receipt: t('receipt'), recipes: t('recipes'), history: t('history'), inventory: t('inventory'), more: t('settings') }[activeView.value]))
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
const reviewReceiptLines = computed(() => activeReceipt.value?.lines.filter(line => !['ignored', 'already_booked'].includes(line.status)) || [])
const receiptHighlightStyle = computed(() => {
  const coordinates = activeReceipt.value?.lines.find(line => line.id === selectedReceiptLine.value)?.coordinates
  if (!coordinates) return null
  const values = ['x', 'y', 'width', 'height'].map(key => Number(coordinates[key]))
  if (values.some(value => !Number.isFinite(value))) return null
  const percent = (value: number) => `${value <= 1 ? value * 100 : value}%`
  return { left: percent(values[0]), top: percent(values[1]), width: percent(values[2]), height: percent(values[3]) }
})

async function load() {
  const [stock, productList, locationList, movementList, shoppingList, notificationList, householdData, memberList, preferences, recommendations, recipePreferences, voicePreferences] = await Promise.all([
    api.stock(), api.products(), api.locations(), api.movements(), api.shoppingList(), api.notifications(), api.household(), api.members(), api.notificationPreferences(), api.recipeRecommendations([], recipeServings.value), api.recipePreferences(), api.voicePreferences()
  ])
  batches.value = stock; products.value = productList; locations.value = locationList; movements.value = movementList; shopping.value = shoppingList; notifications.value = notificationList; household.value = householdData; members.value = memberList; notificationChannels.value = preferences.channels; recipeRecommendations.value = recommendations; recipeTags.value = recipePreferences.preferred_tags.join(', '); excludedRecipeTags.value = recipePreferences.excluded_tags.join(', '); voiceAutoConfirm.value = voicePreferences.auto_confirm_shopping; voiceSpeechOutput.value = voicePreferences.speech_output; voiceStartOnLaunch.value = voicePreferences.start_listening_on_launch ?? null
  await refreshReceipts()
}
async function refreshRecipes() { try { recipeRecommendations.value = await api.recipeRecommendations([], recipeServings.value) } catch(e) { error.value = (e as Error).message } }
async function saveRecipePreferences() { try { await api.setRecipePreferences({ preferred_tags: recipeTags.value.split(',').map(tag => tag.trim()).filter(Boolean), excluded_tags: excludedRecipeTags.value.split(',').map(tag => tag.trim()).filter(Boolean) }); await refreshRecipes() } catch(e) { error.value = (e as Error).message } }
function addIngredientDraft() { recipeIngredients.value.push({ product_id: '', quantity: 1, unit: 'piece' }) }
function selectIngredientProduct(ingredient: IngredientDraft) { const product = products.value.find(item => item.id === ingredient.product_id); if (product) ingredient.unit = product.default_unit }
function resetRecipeForm() { editingRecipeId.value = null; recipeName.value = ''; recipeInstructions.value = ''; recipeTagInput.value = ''; recipePortions.value = 2; recipeIngredients.value = [{ product_id: '', quantity: 1, unit: 'piece' }] }
function openNewRecipe() { resetRecipeForm(); showRecipe.value = true }
function editRecipe(recommendation: RecipeRecommendation) { const recipe = recommendation.recipe; editingRecipeId.value = recipe.id; recipeName.value = recipe.name; recipeInstructions.value = recipe.instructions || ''; recipeTagInput.value = recipe.tags.join(', '); recipePortions.value = recipe.servings; recipeIngredients.value = recipe.ingredients.map(item => ({ product_id: item.product_id, quantity: Number(item.quantity), unit: item.unit })); showRecipe.value = true }
async function createRecipe() { busy.value = true; error.value = ''; try { const body = { name: recipeName.value, servings: recipePortions.value, instructions: recipeInstructions.value || null, tags: recipeTagInput.value.split(',').map(tag => tag.trim()).filter(Boolean), ingredients: recipeIngredients.value }; if (editingRecipeId.value) await api.updateRecipe(editingRecipeId.value, body); else await api.createRecipe(body); showRecipe.value = false; resetRecipeForm(); await load(); notice.value = 'Rezept gespeichert' } catch(e) { error.value = (e as Error).message } finally { busy.value = false } }
async function addRecipeMissing(recommendation: RecipeRecommendation) { try { await api.addRecipeToShoppingList(recommendation.recipe.id, recipeServings.value); shopping.value = await api.shoppingList(); notice.value = 'Fehlende Zutaten wurden zur Einkaufsliste hinzugefügt' } catch(e) { error.value = (e as Error).message } }
async function removeRecipe(recommendation: RecipeRecommendation) { if (!confirm(`„${recommendation.recipe.name}“ wirklich löschen?`)) return; try { await api.deleteRecipe(recommendation.recipe.id); await refreshRecipes() } catch(e) { error.value = (e as Error).message } }
function clearQueryToken(name: string) { const url = new URL(window.location.href); url.searchParams.delete(name); window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`) }
async function acceptPendingInvitation() { if (!inviteToken.value) return; await api.acceptInvitation(inviteToken.value); inviteToken.value = ''; clearQueryToken('invite') }
async function login() { busy.value = true; error.value = ''; try { await api.login(email.value, password.value); loggedIn.value = true; await acceptPendingInvitation(); await load(); startLive(); await prepareVoiceLaunch() } catch(e) { error.value = String((e as Error).message) } finally { busy.value = false } }
async function register() { busy.value = true; error.value = ''; try { await api.register(email.value, displayName.value, password.value, inviteToken.value ? null : householdName.value, inviteToken.value || null); if (inviteToken.value) { inviteToken.value = ''; clearQueryToken('invite') } loggedIn.value = true; await load(); startLive(); await prepareVoiceLaunch() } catch(e) { error.value = String((e as Error).message) } finally { busy.value = false } }
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
async function discard(batch: Batch) { const amount = Number(prompt(`Wie viel ${batch.unit} entsorgen? Früheste MHD-Chargen werden zuerst verwendet.`, '1')); if (!amount) return; try { const result = await api.discardFefo(batch.product_id, batch.unit, amount, batches.value); if (isQueued(result)) await handleQueued(); else remember(result); if (online.value) await load() } catch(e) { error.value = (e as Error).message; if (online.value) await load() } }
async function transfer(batch: Batch) { const targets = locations.value.filter(item => item.id !== batch.location_id); const choice = prompt(`Ziellagerort:\n${targets.map((item, index) => `${index + 1}: ${item.name}`).join('\n')}`, '1'); if (!choice) return; const target = targets[Number(choice) - 1]; if (!target) { error.value = 'Ungültiger Lagerort'; return } const amount = Number(prompt(`Wie viel ${batch.unit} umlagern?`, String(Number(batch.quantity)))); if (!amount) return; try { const result = await api.transfer(batch, target.id, amount); if (isQueued(result)) await handleQueued(); else notice.value = 'Umlagerung gespeichert'; if (online.value) await load() } catch(e) { error.value = (e as Error).message; if (online.value) await load() } }
async function editBatch(batch: Batch) { const date = prompt('Mindesthaltbar bis (JJJJ-MM-TT, leer für kein Datum)', batch.best_before || ''); if (date === null) return; const opened = prompt('Geöffnet am (JJJJ-MM-TT, leer für kein Datum)', batch.opened_at || ''); if (opened === null) return; const newUnit = prompt('Einheit', batch.unit); if (!newUnit) return; const choices = locations.value.map((item, index) => `${index + 1}: ${item.name}`).join('\n'); const currentIndex = locations.value.findIndex(item => item.id === batch.location_id); const locationChoice = prompt(`Lagerort:\n${choices}`, String(currentIndex + 1)); if (!locationChoice) return; const location = locations.value[Number(locationChoice) - 1]; if (!location) { error.value = 'Ungültiger Lagerort'; return } try { await api.updateBatch(batch.id, { best_before: date || null, opened_at: opened || null, unit: newUnit, location_id: location.id, expected_version: batch.version }); await load() } catch(e) { error.value = (e as Error).message } }
async function undo() { if (!lastMovements.value.length) return; try { for (const movement of [...lastMovements.value].reverse()) await api.reverse(movement.id, movement.version); lastMovements.value = []; await load() } catch(e) { error.value = (e as Error).message } }
async function configureMinimum(product: Product) { const value = prompt(`Mindestbestand für ${product.name} (${product.default_unit})`, '1'); if (value === null || !Number(value)) return; try { await api.setMinStock(product.id, Number(value), product.default_unit); await load() } catch(e) { error.value = (e as Error).message } }
async function editProduct(product: Product) { const name = prompt('Produktname', product.name); if (!name) return; const brand = prompt('Marke', product.brand || ''); if (brand === null) return; const category = prompt('Kategorie', product.category || ''); if (category === null) return; const packageQuantity = prompt('Packungsgröße (optional)', product.package_quantity || ''); if (packageQuantity === null) return; const defaultUnit = prompt('Standardeinheit: piece, g, kg, ml, l oder package', product.default_unit); if (!defaultUnit) return; const locationChoice = prompt(`Standard-Lagerort (leer = automatisch):\n${locations.value.map((item, index) => `${index + 1}: ${item.name}`).join('\n')}`, product.default_location_id ? String(locations.value.findIndex(item => item.id === product.default_location_id) + 1) : ''); if (locationChoice === null) return; const defaultLocationId = locationChoice ? locations.value[Number(locationChoice) - 1]?.id : null; if (locationChoice && !defaultLocationId) { error.value = 'Ungültiger Lagerort'; return } const barcodes = prompt('Barcodes, durch Komma getrennt', product.barcodes.map(item => item.barcode).join(', ')); if (barcodes === null) return; const notes = prompt('Notizen', product.notes || ''); if (notes === null) return; try { await api.updateProduct(product.id, { name, brand: brand || null, category: category || null, package_quantity: packageQuantity || null, default_unit: defaultUnit, default_location_id: defaultLocationId, notes: notes || null, barcodes: barcodes.split(',').map(item => item.trim()).filter(Boolean) }); await load() } catch(e) { error.value = (e as Error).message } }
async function checkWarnings() { try { await api.checkNotifications(); await load() } catch(e) { error.value = (e as Error).message } }
async function readWarning(notification: Notification) { if (notification.read_at) return; try { await api.markNotificationRead(notification.id); await load() } catch(e) { error.value = (e as Error).message } }
async function startInventory() { try { inventory.value = await api.startInventory(selectedLocation.value || undefined); activeView.value = 'inventory' } catch(e) { error.value = (e as Error).message } }
async function saveCount(batchId: string, event: Event) { if (!inventory.value) return; const value = Number((event.target as HTMLInputElement).value); try { await api.recordCount(inventory.value.session.id, batchId, value); const count = inventory.value.counts.find(item => item.batch_id === batchId); if (count) count.counted_quantity = String(value) } catch(e) { error.value = (e as Error).message } }
async function confirmInventory() { if (!inventory.value || !confirm('Abweichungen jetzt als Korrekturbuchungen übernehmen?')) return; try { await api.confirmInventory(inventory.value.session.id); inventory.value = null; await load(); activeView.value = 'stock' } catch(e) { error.value = (e as Error).message } }
async function logout() { await api.logout(); window.location.reload() }
function productLabel(product: Product) { return `${product.name}${product.brand ? ` · ${product.brand}` : ''}` }
function selectProductFromSearch() { const product = products.value.find(item => productLabel(item) === productSearch.value); selectedProduct.value = product?.id || ''; if (product) unit.value = product.default_unit }
function selectShoppingProduct() { const product = products.value.find(item => productLabel(item) === shoppingProductSearch.value); shoppingProductId.value = product?.id || ''; if (product) shoppingUnit.value = product.default_unit }
async function addShoppingItem() { if (!online.value) { error.value = 'Neue Einkaufslisteneinträge benötigen derzeit eine Verbindung.'; return } const freeText = shoppingProductId.value ? null : (shoppingText.value.trim() || shoppingProductSearch.value.trim()); if (!shoppingProductId.value && !freeText) return; try { await api.createShoppingItem({ product_id: shoppingProductId.value || null, free_text: freeText || null, quantity: shoppingQuantity.value, unit: shoppingUnit.value, source: 'manual', idempotency_key: crypto.randomUUID() }); shoppingProductSearch.value = ''; shoppingProductId.value = ''; shoppingText.value = ''; shoppingQuantity.value = 1; shoppingUnit.value = 'piece'; await load() } catch(e) { error.value = (e as Error).message } }
async function checkShoppingItem(item: ShoppingItem) { if (!online.value) { error.value = 'Abhaken und Einbuchen benötigen eine Verbindung.'; return } let productId = item.product_id; if (!productId) { const choice = prompt(`Produkt für „${item.product_name}“ auswählen:\n${products.value.map((product, index) => `${index + 1}: ${product.name}`).join('\n')}\nLeer lassen = ohne Einbuchen abhaken`); if (choice) productId = products.value[Number(choice) - 1]?.id } try { const book = household.value?.shopping_check_mode === 'instant' && Boolean(productId); const result = await api.checkShoppingItem(item, book, productId); if (result.movement) { shoppingUndo.value = { itemId: result.item.id, itemVersion: result.item.version, batchVersion: result.movement.batch.version }; setTimeout(() => shoppingUndo.value = null, 10000) } await load() } catch(e) { error.value = (e as Error).message; await load() } }
async function undoShopping() { const value = shoppingUndo.value; if (!value) return; try { await api.undoShoppingItem(value.itemId, value.itemVersion, value.batchVersion); shoppingUndo.value = null; await load() } catch(e) { error.value = (e as Error).message } }
async function finishShoppingTrip() { const pending = checkedShopping.value.filter(item => !item.linked_movement_id && item.product_id); if (!pending.length) return; const lines: { item: ShoppingItem; location_id?: string; best_before?: string }[] = []; for (const item of pending) { const product = products.value.find(value => value.id === item.product_id); const suggested = product?.default_location_id ? locations.value.findIndex(value => value.id === product.default_location_id) + 1 : (selectedLocation.value ? locations.value.findIndex(value => value.id === selectedLocation.value) + 1 : 1); const choice = prompt(`${item.product_name}: Lagerort\n${locations.value.map((value, index) => `${index + 1}: ${value.name}`).join('\n')}`, String(Math.max(suggested, 1))); if (!choice) return; const locationId = locations.value[Number(choice) - 1]?.id; if (!locationId) { error.value = 'Ungültiger Lagerort'; return } const bestBefore = prompt(`${item.product_name}: MHD (JJJJ-MM-TT, optional)`, ''); if (bestBefore === null) return; lines.push({ item, location_id: locationId, best_before: bestBefore || undefined }) } try { const results = await api.finishShoppingTrip(lines); remember(results.flatMap(result => result.movement ? [result.movement] : [])); await load() } catch(e) { error.value = (e as Error).message } }
async function removeShoppingItem(item: ShoppingItem) { try { await api.removeShoppingItem(item); await load() } catch(e) { error.value = (e as Error).message } }
async function clearCheckedShopping() { try { await api.clearCheckedShopping(); await load() } catch(e) { error.value = (e as Error).message } }
async function shareShopping() { try { const text = await api.shoppingText(); if (navigator.share) await navigator.share({ title: 'Einkaufsliste', text }); else { await navigator.clipboard.writeText(text); notice.value = 'Einkaufsliste wurde kopiert' } } catch(e) { error.value = (e as Error).message } }
function startSwipe(item: ShoppingItem, event: TouchEvent) { swipeStarts.set(item.id, event.touches[0]?.clientX || 0) }
function endSwipe(item: ShoppingItem, event: TouchEvent) { const start = swipeStarts.get(item.id); swipeStarts.delete(item.id); if (start === undefined) return; const distance = (event.changedTouches[0]?.clientX || start) - start; if (distance > 80) checkShoppingItem(item); else if (distance < -80) removeShoppingItem(item) }
async function selectBarcode(code: string, mode: ScanMode = 'purchase') { let product: Product; try { product = await api.barcode(code) } catch { if (mode !== 'purchase') throw new Error('Barcode ist noch keinem Produkt zugeordnet'); const found = await api.lookup(code); const details = [found.brand, found.quantity].filter(Boolean).join(' · '); const name = prompt(`Produktname bestätigen oder anpassen${details ? `\n${details}` : ''}`, found.name || `Artikel ${code}`); if (!name) return; product = await api.createProduct({ name, brand: found.brand, package_quantity: found.quantity, image_url: found.image_url, default_unit: 'piece', barcodes: [code] }) }
  if (mode === 'purchase') { selectedProduct.value = product.id; productSearch.value = productLabel(product); unit.value = product.default_unit; showAdd.value = true; return }
  const matching = batches.value.filter(batch => batch.product_id === product.id).sort((a, b) => (a.best_before || '9999').localeCompare(b.best_before || '9999'))
  if (!matching.length) throw new Error('Für dieses Produkt ist kein Bestand vorhanden')
  if (mode === 'consume') { await consume(matching[0]); return }
  if (mode === 'discard') { await discard(matching[0]); return }
  if (!inventory.value) throw new Error('Bitte zuerst eine Inventur starten')
  const counted = inventory.value.counts.filter(count => matching.some(batch => batch.id === count.batch_id))
  if (!counted.length) throw new Error('Dieses Produkt gehört nicht zur laufenden Inventur')
  let selected = counted[0]
  if (counted.length > 1) { const choice = prompt(`Charge wählen:\n${counted.map((count, index) => `${index + 1}: ${batchMap.value.get(count.batch_id)?.best_before || 'ohne MHD'}`).join('\n')}`, '1'); if (!choice) return; selected = counted[Number(choice) - 1]; if (!selected) throw new Error('Ungültige Charge') }
  const actual = prompt(`Ist-Menge für ${product.name}`, String(Number(selected.counted_quantity))); if (actual === null || !Number.isFinite(Number(actual)) || Number(actual) < 0) return; await api.recordCount(inventory.value.session.id, selected.batch_id, Number(actual)); selected.counted_quantity = String(Number(actual)); notice.value = 'Inventurwert gespeichert'
}
async function createManualProduct() { const name = prompt('Name des neuen Produkts'); if (!name) return; const brand = prompt('Marke (optional)', '') || null; const category = prompt('Kategorie (optional)', '') || null; const defaultUnit = prompt('Standardeinheit: piece, g, kg, ml, l oder package', 'piece'); if (!defaultUnit) return; try { const product = await api.createProduct({ name, brand, category, default_unit: defaultUnit, barcodes: [] }); products.value.push(product); selectedProduct.value = product.id; productSearch.value = productLabel(product); unit.value = product.default_unit } catch(e) { error.value = (e as Error).message } }
async function manualBarcode() { const code = prompt('EAN-8, EAN-13 oder UPC eingeben'); if (!code) return; try { await selectBarcode(code.trim()) } catch(e) { error.value = (e as Error).message } }
async function scan(mode: ScanMode = 'purchase') { scanning.value = true; error.value = ''; await new Promise(resolve => setTimeout(resolve)); const reader = new BrowserMultiFormatReader(); try { const result = await reader.decodeOnceFromVideoDevice(undefined, 'scanner'); await selectBarcode(result.getText(), mode) } catch(e) { error.value = (e as Error).message || 'Scanner konnte nicht gestartet werden. Bitte Barcode manuell eingeben.' } finally { const video = document.querySelector<HTMLVideoElement>('#scanner'); if (video?.srcObject instanceof MediaStream) video.srcObject.getTracks().forEach(track => track.stop()); scanning.value = false } }
async function refreshOffline() { const state = await api.offlineState(); pendingOffline.value = state.pending; conflicts.value = state.conflicts }
async function syncOffline() { online.value = navigator.onLine; if (!online.value) return; try { const state = await api.flushOffline(); pendingOffline.value = state.pending; conflicts.value = state.conflicts; await load() } catch(e) { error.value = (e as Error).message } }
async function retryOffline(conflict: OfflineConflict) { try { const state = await api.retryOfflineConflict(conflict); pendingOffline.value = state.pending; conflicts.value = state.conflicts; await load() } catch(e) { error.value = (e as Error).message; await refreshOffline() } }
async function discardOffline(key: string) { const state = await api.discardOfflineConflict(key); pendingOffline.value = state.pending; conflicts.value = state.conflicts }
let eventsController: AbortController | null = null
function startLive() { eventsController?.abort(); eventsController = api.watchEvents(() => load().catch(() => undefined)) }
function markOffline() { online.value = false }
function keyboardShortcuts(event: KeyboardEvent) { const editing = event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement; if (event.ctrlKey && event.key.toLowerCase() === 'z') { event.preventDefault(); if (shoppingUndo.value) undoShopping(); else undo(); return } if (editing) return; if (event.key === '/') { event.preventDefault(); activeView.value = 'stock'; setTimeout(() => document.querySelector<HTMLInputElement>('#stock-search')?.focus()) } else if (event.key.toLowerCase() === 'n') { activeView.value = 'shopping'; setTimeout(() => document.querySelector<HTMLInputElement>('#shopping-product')?.focus()) } else if (event.key.toLowerCase() === 'm') activeView.value = 'voice' }
function clearVoiceTimers() { if (voiceMeter) window.clearInterval(voiceMeter); if (voiceTimeout) window.clearTimeout(voiceTimeout); if (voiceAutoTimer) window.clearInterval(voiceAutoTimer); voiceMeter = undefined; voiceTimeout = undefined; voiceAutoTimer = undefined }
function stopVoice() { if (voiceRecorder?.state === 'recording') voiceRecorder.stop(); voiceStream?.getTracks().forEach(track => track.stop()); voiceStream = null; if (voiceAudioContext) void voiceAudioContext.close(); voiceAudioContext = null; voiceRecording.value = false; voiceLevel.value = 0; clearVoiceTimers() }
async function interpretVoice() { if (!voiceText.value.trim()) return; busy.value = true; error.value = ''; voiceResult.value = ''; try { const draft = await api.interpretVoice(voiceText.value.trim()); voiceActions.value = draft.actions; voiceStatus.value = draft.parser === 'rules' ? 'Lokal erkannt' : 'Mit KI erkannt'; scheduleVoiceAutoConfirm() } catch(e) { error.value = (e as Error).message; voiceStatus.value = 'Nicht erkannt' } finally { busy.value = false } }
async function startVoice(startup = false): Promise<boolean> {
  error.value = ''; voiceResult.value = ''; voiceActions.value = []
  voicePermissionIntro.value = false
  if (!navigator.mediaDevices?.getUserMedia || !('MediaRecorder' in window)) { error.value = 'Dieser Browser unterstützt keine Audioaufnahme. Nutze die Texteingabe.'; voiceLaunchFallback.value = startup; return false }
  try {
    voiceStream = await navigator.mediaDevices.getUserMedia({ audio: true })
    voiceLaunchFallback.value = false
    const chunks: Blob[] = []
    voiceRecorder = new MediaRecorder(voiceStream)
    voiceRecorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data) }
    voiceRecorder.onstop = async () => { voiceStatus.value = 'Wird erkannt …'; try { const result = await api.transcribeVoice(new Blob(chunks, { type: voiceRecorder?.mimeType || 'audio/webm' })); voiceText.value = result.text; await interpretVoice() } catch(e) { error.value = `${(e as Error).message}. Du kannst den Text unten eingeben oder die Browser-Erkennung nutzen.`; voiceStatus.value = 'Transkription fehlgeschlagen' } }
    voiceAudioContext = new AudioContext(); const analyser = voiceAudioContext.createAnalyser(), source = voiceAudioContext.createMediaStreamSource(voiceStream), data = new Uint8Array(analyser.fftSize)
    source.connect(analyser); let heardSpeech = false, lastSound = Date.now()
    voiceMeter = window.setInterval(() => { analyser.getByteTimeDomainData(data); const rms = Math.sqrt(data.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) / data.length); voiceLevel.value = Math.min(1, rms * 8); if (rms > 0.035) { heardSpeech = true; lastSound = Date.now() } else if (heardSpeech && Date.now() - lastSound > 1500) stopVoice() }, 100)
    voiceTimeout = window.setTimeout(stopVoice, 15000); voiceRecorder.start(); voiceRecording.value = true; voiceStatus.value = 'Ich höre zu …'
    return true
  } catch(e) { voiceStream?.getTracks().forEach(track => track.stop()); voiceStream = null; if (voiceAudioContext) void voiceAudioContext.close(); voiceAudioContext = null; error.value = 'Mikrofonzugriff wurde nicht erlaubt. Nutze die Texteingabe oder Browser-Erkennung.'; voiceStatus.value = 'Mikrofon nicht verfügbar'; voiceLaunchFallback.value = startup; return false }
}
function browserSpeech() { const SpeechRecognition = (window as unknown as { SpeechRecognition?: new () => { lang: string; interimResults: boolean; onresult: (event: { results: { 0: { transcript: string } }[] }) => void; onerror: () => void; start: () => void } }).SpeechRecognition || (window as unknown as { webkitSpeechRecognition?: new () => { lang: string; interimResults: boolean; onresult: (event: { results: { 0: { transcript: string } }[] }) => void; onerror: () => void; start: () => void } }).webkitSpeechRecognition; if (!SpeechRecognition) { error.value = 'Die Browser-Spracherkennung ist hier nicht verfügbar.'; return } const recognition = new SpeechRecognition(); recognition.lang = 'de-DE'; recognition.interimResults = false; recognition.onresult = event => { voiceText.value = event.results[0][0].transcript; void interpretVoice() }; recognition.onerror = () => { error.value = 'Die Browser-Spracherkennung ist fehlgeschlagen.' }; recognition.start(); voiceStatus.value = 'Browser hört zu …' }
async function saveVoicePreferences() { try { const saved = await api.setVoicePreferences({ auto_confirm_shopping: voiceAutoConfirm.value, speech_output: voiceSpeechOutput.value, start_listening_on_launch: voiceStartOnLaunch.value }); voiceAutoConfirm.value = saved.auto_confirm_shopping; voiceSpeechOutput.value = saved.speech_output; voiceStartOnLaunch.value = saved.start_listening_on_launch ?? null; scheduleVoiceAutoConfirm() } catch(e) { error.value = (e as Error).message } }
function setVoiceAutoConfirm(value: boolean) { voiceAutoConfirm.value = value; void saveVoicePreferences() }
function setVoiceSpeechOutput(value: boolean) { voiceSpeechOutput.value = value; void saveVoicePreferences() }
function setVoiceStartOnLaunch(value: boolean) { voiceStartOnLaunch.value = value; void saveVoicePreferences() }
async function beginVoiceAfterExplanation() { localStorage.setItem('voice_permission_explained', 'true'); voicePermissionIntro.value = false; await startVoice(true) }
async function prepareVoiceLaunch() {
  if (voiceLaunchHandled) return
  voiceLaunchHandled = true
  const shouldListen = voiceStartOnLaunch.value ?? mobileDevice
  if (!shouldListen || (!explicitVoiceLaunch && !standaloneDisplay)) return
  activeView.value = 'voice'
  let permission: PermissionState | undefined
  try { permission = (await navigator.permissions?.query({ name: 'microphone' as PermissionName })).state } catch { permission = undefined }
  if (permission !== 'granted' && localStorage.getItem('voice_permission_explained') !== 'true') { voicePermissionIntro.value = true; return }
  await startVoice(true)
}
function scheduleVoiceAutoConfirm() { if (voiceAutoTimer) window.clearInterval(voiceAutoTimer); const action = voiceActions.value[0]; if (!voiceAutoConfirm.value || voiceActions.value.length !== 1 || action?.intent !== 'add_to_shopping' || action.confidence < .9) { voiceCountdown.value = 0; return } voiceCountdown.value = 3; voiceAutoTimer = window.setInterval(() => { voiceCountdown.value -= 1; if (voiceCountdown.value <= 0) { if (voiceAutoTimer) window.clearInterval(voiceAutoTimer); void confirmVoiceAction(action) } }, 1000) }
function chooseVoiceProduct(action: VoiceAction, productId: string) { const product = products.value.find(item => item.id === productId); action.product_id = productId || undefined; if (product) { action.product_name = product.name; action.unit ||= product.default_unit } }
async function confirmVoiceAction(action: VoiceAction) { if (voiceAutoTimer) window.clearInterval(voiceAutoTimer); voiceCountdown.value = 0; busy.value = true; error.value = ''; try { const result = await api.executeVoice(action, selectedLocation.value || locations.value[0]?.id); voiceResult.value = result.message; voiceActions.value = voiceActions.value.filter(item => item !== action); if (result.result_type !== 'query') await load(); if (voiceSpeechOutput.value && result.result_type === 'query' && 'speechSynthesis' in window) window.speechSynthesis.speak(new SpeechSynthesisUtterance(result.message)) } catch(e) { error.value = (e as Error).message } finally { busy.value = false } }
function discardVoiceAction(action: VoiceAction) { voiceActions.value = voiceActions.value.filter(item => item !== action); scheduleVoiceAutoConfirm() }
function clearReceiptUrls() { receiptPreviews.value.forEach(URL.revokeObjectURL); receiptPreviews.value = []; if (receiptImageUrl.value) URL.revokeObjectURL(receiptImageUrl.value); receiptImageUrl.value = '' }
async function resizeReceiptImage(file: File): Promise<File> {
  if (!['image/jpeg', 'image/png'].includes(file.type)) return file
  const bitmap = await createImageBitmap(file)
  if (Math.max(bitmap.width, bitmap.height) <= 2000) { bitmap.close(); return file }
  const scale = 2000 / Math.max(bitmap.width, bitmap.height)
  const canvas = document.createElement('canvas'); canvas.width = Math.round(bitmap.width * scale); canvas.height = Math.round(bitmap.height * scale)
  canvas.getContext('2d')?.drawImage(bitmap, 0, 0, canvas.width, canvas.height); bitmap.close()
  const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error('Bild konnte nicht verkleinert werden')), 'image/jpeg', .86))
  return new File([blob], file.name.replace(/\.[^.]+$/, '.jpg'), { type: 'image/jpeg', lastModified: file.lastModified })
}
async function chooseReceiptFiles(files: FileList | File[]) {
  error.value = ''; const chosen = Array.from(files).slice(0, 10)
  try {
    const prepared = await Promise.all(chosen.map(resizeReceiptImage)); const combined = [...receiptFiles.value, ...prepared].slice(0, 10); receiptPreviews.value.forEach(URL.revokeObjectURL); receiptFiles.value = combined
    receiptPreviews.value = combined.map(file => file.type.startsWith('image/') ? URL.createObjectURL(file) : '')
  } catch(e) { error.value = (e as Error).message }
}
function removeReceiptFile(index: number) { URL.revokeObjectURL(receiptPreviews.value[index]); receiptFiles.value.splice(index, 1); receiptPreviews.value.splice(index, 1) }
function dropReceipt(event: DragEvent) { receiptDragging.value = false; if (event.dataTransfer?.files.length) void chooseReceiptFiles(event.dataTransfer.files) }
async function refreshReceipts() {
  try {
    const [items, config] = await Promise.all([api.receipts(), api.receiptConfig()]); receipts.value = items; receiptConfig.value = config
    if (activeReceipt.value) { const current = items.find(item => item.id === activeReceipt.value?.id); if (current) activeReceipt.value = current }
  } catch(e) { if (activeView.value === 'receipt') error.value = (e as Error).message }
}
function scheduleReceiptPoll(receipt: Receipt) {
  if (receiptPollTimer) window.clearTimeout(receiptPollTimer)
  if (receipt.status !== 'processing') return
  receiptPollTimer = window.setTimeout(async () => { try { await openReceipt(receipt.id, false) } catch { /* next manual refresh reports the error */ } }, 1200)
}
async function loadReceiptImage(receipt: Receipt) {
  if (receiptImageUrl.value) URL.revokeObjectURL(receiptImageUrl.value); receiptImageUrl.value = ''
  if (!receipt.image_count) return
  try { receiptImageUrl.value = URL.createObjectURL(await api.receiptImage(receipt.id)) } catch { /* retained metadata remains usable */ }
}
async function openReceipt(receiptId: string, loadImage = true) {
  const receipt = await api.receipt(receiptId); activeReceipt.value = receipt; allowReceiptDuplicate.value = false
  receipts.value = [receipt, ...receipts.value.filter(item => item.id !== receipt.id)]
  if (loadImage || (!receiptImageUrl.value && receipt.image_count)) await loadReceiptImage(receipt)
  scheduleReceiptPoll(receipt)
}
async function uploadReceipt() {
  if (!online.value || !receiptFiles.value.length) return
  busy.value = true; error.value = ''
  try { const receipt = await api.uploadReceipt(receiptFiles.value); receiptFiles.value = []; clearReceiptUrls(); activeReceipt.value = receipt; receipts.value.unshift(receipt); scheduleReceiptPoll(receipt); notice.value = 'Bon wird verarbeitet' }
  catch(e) { error.value = (e as Error).message } finally { busy.value = false }
}
async function retryReceipt() { if (!activeReceipt.value) return; activeReceipt.value = await api.retryReceipt(activeReceipt.value.id); scheduleReceiptPoll(activeReceipt.value) }
async function saveReceiptLine(line: ReceiptLine, changes: Record<string, unknown>) {
  if (!activeReceipt.value) return
  try { activeReceipt.value = await api.updateReceiptLine(activeReceipt.value.id, line.id, { expected_version: line.version, ...changes }) }
  catch(e) { error.value = (e as Error).message; await openReceipt(activeReceipt.value.id, false) }
}
function selectReceiptProduct(line: ReceiptLine, productId: string) { const product = products.value.find(item => item.id === productId); line.product_id = productId || undefined; if (product) { line.product_name = product.name; line.unit = product.default_unit; line.location_id ||= product.default_location_id } void saveReceiptLine(line, { product_id: productId || null }) }
async function createReceiptProduct(line: ReceiptLine) { const name = prompt('Name des neuen Produkts', line.raw_text); if (!name) return; const defaultUnit = prompt('Standardeinheit: piece, g, kg, ml, l oder package', line.unit || 'piece'); if (!defaultUnit) return; try { const product = await api.createProduct({ name, default_unit: defaultUnit, barcodes: [] }); products.value.push(product); line.product_id = product.id; line.product_name = product.name; line.unit = product.default_unit; line.location_id = product.default_location_id; await saveReceiptLine(line, { product_id: product.id, unit: product.default_unit, location_id: product.default_location_id || null }) } catch(e) { error.value = (e as Error).message } }
function setReceiptDate(line: ReceiptLine, days: number) { const date = new Date(); date.setDate(date.getDate() + days); line.best_before = date.toISOString().slice(0, 10); void saveReceiptLine(line, { best_before: line.best_before }) }
async function confirmReceipt() {
  const receipt = activeReceipt.value; if (!receipt) return
  const lines = reviewReceiptLines.value
  if (!lines.length || lines.some(line => !line.product_id)) { error.value = 'Bitte alle einzubuchenden Positionen einem Produkt zuordnen.'; return }
  busy.value = true; error.value = ''
  try {
    activeReceipt.value = await api.confirmReceipt(receipt.id, { allow_duplicate: allowReceiptDuplicate.value, lines: lines.map(line => ({ line_id: line.id, expected_version: line.version, product_id: line.product_id, quantity: Number(line.quantity), unit: line.unit, location_id: line.location_id || null, best_before: line.best_before || null, idempotency_key: crypto.randomUUID() })) })
    await load(); notice.value = 'Bon wurde vollständig eingebucht'
  } catch(e) { error.value = (e as Error).message } finally { busy.value = false }
}
async function reverseReceipt() { const receipt = activeReceipt.value; if (!receipt || !confirm('Alle Buchungen dieses Bons wirklich stornieren?')) return; try { activeReceipt.value = await api.reverseReceipt(receipt.id); await load(); notice.value = 'Bon wurde storniert' } catch(e) { error.value = (e as Error).message } }
function receiptStatus(receipt: Receipt) { return ({ processing: 'Wird erkannt', review: 'Zu prüfen', failed: 'Fehlgeschlagen', confirmed: 'Eingebucht', reversed: 'Storniert' } as Record<string, string>)[receipt.status] || receipt.status }
onMounted(async () => { window.addEventListener('online', syncOffline); window.addEventListener('offline', markOffline); window.addEventListener('keydown', keyboardShortcuts); await refreshOffline(); if (loggedIn.value) { try { await acceptPendingInvitation(); await syncOffline(); startLive(); await prepareVoiceLaunch() } catch(e) { error.value = (e as Error).message } } })
onUnmounted(() => { stopVoice(); clearReceiptUrls(); if (receiptPollTimer) window.clearTimeout(receiptPollTimer); eventsController?.abort(); window.removeEventListener('online', syncOffline); window.removeEventListener('offline', markOffline); window.removeEventListener('keydown', keyboardShortcuts) })
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
    <header><div><p class="eyebrow">GUTEN APPETIT</p><h1>{{ viewTitle }}</h1></div><button class="avatar" :aria-label="t('logout')" @click="logout">FH</button></header>
    <p v-if="error" class="error banner">{{ error }} <button @click="error=''">×</button></p>
    <p v-if="notice" class="success banner">{{ notice }} <button @click="notice=''">×</button></p>
    <p v-if="!online || pendingOffline" class="offline-banner">{{ online ? `${pendingOffline} Aktion(en) werden synchronisiert` : 'Offline – Aktionen werden sicher vorgemerkt' }}</p>

    <section v-if="voicePermissionIntro" class="voice-launch-overlay" role="dialog" aria-modal="true" aria-labelledby="voice-permission-title">
      <div class="voice-launch-card">
        <span class="voice-launch-icon" aria-hidden="true">●</span>
        <p class="eyebrow">SPRACHSTART</p>
        <h2 id="voice-permission-title">Mikrofon für den Sprachstart</h2>
        <p>Damit {{ appName }} nach dem Öffnen zuhören kann, benötigt die App einmalig Zugriff auf dein Mikrofon.</p>
        <p class="voice-privacy">Während der Aufnahme ist der Mikrofonstatus sichtbar. Die Aufnahme endet bei Stille oder spätestens nach 15 Sekunden; danach wird das Mikrofon sofort freigegeben.</p>
        <button class="primary voice-launch-action" @click="beginVoiceAfterExplanation">Mikrofon erlauben und sprechen</button>
        <button class="ghost" @click="voicePermissionIntro=false">Jetzt nicht</button>
      </div>
    </section>

    <section v-if="voiceLaunchFallback" class="voice-launch-overlay" role="dialog" aria-modal="true" aria-labelledby="voice-fallback-title">
      <div class="voice-launch-card voice-fallback-card">
        <span class="voice-launch-icon" aria-hidden="true">●</span>
        <h2 id="voice-fallback-title">Sprachstart bereit</h2>
        <p>Der Browser braucht eine Berührung, bevor das Mikrofon starten darf.</p>
        <button class="primary voice-launch-action" @click="startVoice(true)">Tippen zum Sprechen</button>
        <button class="ghost" @click="voiceLaunchFallback=false">Texteingabe verwenden</button>
      </div>
    </section>

    <template v-if="activeView === 'stock'">
      <section class="summary"><div><strong>{{ batches.length }}</strong><span>Chargen</span></div><div><strong>{{ shopping.length }}</strong><span>nachkaufen</span></div><div><strong>{{ batches.filter(b => b.best_before && new Date(b.best_before).getTime() < Date.now()+259200000).length }}</strong><span>bald fällig</span></div></section>
      <div class="actions"><button class="scan" @click="scan('purchase')">⌁ {{ t('scan') }}</button><button class="add" @click="manualBarcode">⌨ {{ t('manualBarcode') }}</button><button class="add" @click="showAdd = true">＋ {{ t('add') }}</button></div>
      <div class="scan-actions"><button @click="scan('consume')">⌁ {{ t('consumeScan') }}</button><button @click="scan('discard')">⌁ {{ t('discardScan') }}</button></div>
      <video v-show="scanning" id="scanner" class="scanner"></video>
      <label class="search">⌕<input id="stock-search" v-model="search" :placeholder="t('search')"></label>
      <details class="filters"><summary>{{ t('filters') }}</summary><div class="filter-grid"><select v-model="locationFilter"><option value="">{{ t('allLocations') }}</option><option v-for="location in locations" :key="location.id" :value="location.id">{{ location.name }}</option></select><select v-model="categoryFilter"><option value="">{{ t('allCategories') }}</option><option v-for="category in categories" :key="category">{{ category }}</option></select><select v-model="sortBy"><option value="expiry">Nach MHD</option><option value="name">Nach Name</option><option value="quantity">Nach Menge</option></select><label><input v-model="expiryFilter" type="checkbox"> {{ t('expiringSoon') }}</label><label><input v-model="shortageFilter" type="checkbox"> {{ t('lowStock') }}</label></div></details>
      <section v-if="openShopping.length" class="shopping-card"><p class="eyebrow">EINKAUFSLISTE</p><div v-for="item in openShopping.slice(0, 4)" :key="item.id"><strong>{{ item.product_name }}</strong><span>{{ Number(item.quantity) }} {{ item.unit }}<template v-if="item.source === 'recipe'"> · Rezept</template></span></div><button @click="activeView='shopping'">Liste öffnen</button></section>
      <section class="list"><article v-for="batch in filtered" :key="batch.id" class="stock-card"><div class="product-icon"><img v-if="batch.product.image_url" :src="batch.product.image_url" :alt="batch.product.name"><template v-else>{{ batch.product.name.slice(0,1) }}</template></div><div class="product-copy"><h2>{{ batch.product.name }}</h2><p>{{ [batch.product.brand, batch.product.package_quantity, batch.product.category].filter(Boolean).join(' · ') || t('food') }}</p><small>{{ locations.find(item => item.id === batch.location_id)?.name }}<template v-if="batch.best_before"> · {{ t('expires') }} {{ new Date(batch.best_before).toLocaleDateString('de-DE') }}</template></small></div><div class="amount"><strong>{{ Number(batch.quantity) }}</strong><span>{{ batch.unit }}</span><div class="batch-actions"><button @click="consume(batch)">{{ t('consume') }}</button><button @click="discard(batch)">{{ t('discard') }}</button><button @click="transfer(batch)">{{ t('transfer') }}</button><button @click="editBatch(batch)">{{ t('edit') }}</button></div></div></article><div v-if="!filtered.length" class="empty"><span>◌</span><h2>{{ t('empty') }}</h2><p>Scanne einen Barcode oder buche einen Artikel manuell ein.</p></div></section>
    </template>

    <template v-else-if="activeView === 'shopping'">
      <section class="shopping-workspace">
        <div class="shopping-list-panel">
          <div class="shopping-toolbar"><p>{{ openShopping.length }} offen · {{ checkedShopping.length }} abgehakt</p><div><button @click="shareShopping">Teilen</button><button v-if="checkedShopping.length" @click="clearCheckedShopping">Abgehakte entfernen</button></div></div>
          <p v-if="!online" class="offline-banner">Offline – die Liste bleibt sichtbar; Änderungen sind nach dem Verbinden wieder möglich.</p>
          <section v-for="group in shoppingGroups" :key="group.category" class="shopping-group"><h2>{{ group.category }}</h2><article v-for="item in group.items" :key="item.id" class="shopping-item" tabindex="0" @touchstart.passive="startSwipe(item, $event)" @touchend.passive="endSwipe(item, $event)"><button class="shopping-check" :aria-label="`${item.product_name} abhaken`" @click="checkShoppingItem(item)">✓</button><div><strong>{{ item.product_name }}</strong><small>{{ Number(item.quantity) }} {{ item.unit }}<template v-if="item.note"> · {{ item.note }}</template></small><span>{{ item.source === 'min_stock' ? 'Mindestbestand' : item.source === 'recipe' ? 'Rezept' : 'Manuell' }}</span></div><button class="shopping-remove" :aria-label="`${item.product_name} entfernen`" @click="removeShoppingItem(item)">×</button></article></section>
          <div v-if="!openShopping.length" class="empty panel"><span>✓</span><h2>Alles besorgt</h2><p>Füge rechts oder über „N“ einen neuen Eintrag hinzu.</p></div>
          <details v-if="checkedShopping.length" class="checked-shopping" open><summary>Abgehakt ({{ checkedShopping.length }})</summary><article v-for="item in checkedShopping" :key="item.id" class="shopping-item checked"><span class="shopping-check">✓</span><div><strong>{{ item.product_name }}</strong><small>{{ item.checked_by_name ? `von ${item.checked_by_name}` : 'Im Wagen' }}</small></div><button class="shopping-remove" @click="removeShoppingItem(item)">×</button></article></details>
          <button v-if="household?.shopping_check_mode === 'finish_trip' && checkedShopping.some(item => !item.linked_movement_id && item.product_id)" class="primary full finish-trip" @click="finishShoppingTrip">Einkauf abschließen</button>
        </div>
        <aside class="shopping-add-panel"><p class="eyebrow">NEUER EINTRAG</p><form @submit.prevent="addShoppingItem"><label>Produkt oder Freitext<input id="shopping-product" v-model="shoppingProductSearch" list="shopping-product-suggestions" placeholder="z. B. Milch" required @input="selectShoppingProduct"><datalist id="shopping-product-suggestions"><option v-for="product in products" :key="product.id" :value="productLabel(product)"></option></datalist></label><div class="row"><label>Menge<input v-model.number="shoppingQuantity" type="number" min="0.001" step="0.001" required></label><label>Einheit<select v-model="shoppingUnit"><option value="piece">Stück</option><option>g</option><option>kg</option><option>ml</option><option>l</option><option value="package">Packung</option></select></label></div><button class="primary" :disabled="!online">Hinzufügen</button></form><p class="muted shortcut-help">Tastatur: N neuer Eintrag · M Mikrofon · / Suche · Strg+Z rückgängig</p></aside>
      </section>
    </template>

    <template v-else-if="activeView === 'voice'">
      <section class="voice-workspace">
        <div class="voice-capture panel">
          <p class="eyebrow">SPRACHEINGABE</p><h2>Was soll ich eintragen?</h2><p class="muted">Zum Beispiel: „Setze zwei Packungen Nudeln auf die Einkaufsliste.“</p>
          <button class="voice-record" :class="{ recording: voiceRecording }" :aria-pressed="voiceRecording" :aria-label="voiceRecording ? 'Aufnahme beenden' : 'Sprachaufnahme starten'" @click="voiceRecording ? stopVoice() : startVoice()"><span>●</span>{{ voiceRecording ? 'Aufnahme beenden' : 'Sprechen' }}</button>
          <div class="voice-level" role="meter" aria-label="Mikrofonpegel" :aria-valuenow="Math.round(voiceLevel * 100)"><span :style="{ width: `${Math.max(4, voiceLevel * 100)}%` }"></span></div><p class="voice-status" aria-live="polite">{{ voiceStatus }}<template v-if="voiceRecording"> · Mikrofon aktiv · stoppt nach 1,5 s Stille, spätestens nach 15 s</template></p>
          <button class="ghost voice-browser" @click="browserSpeech">Browser-Spracherkennung verwenden</button>
          <form class="voice-text" @submit.prevent="interpretVoice"><label>Erkannter oder eingegebener Text<textarea v-model="voiceText" rows="3" placeholder="Befehl eingeben …"></textarea></label><button class="primary" :disabled="busy || !voiceText.trim()">Befehl prüfen</button></form>
          <label class="voice-option"><input type="checkbox" :checked="voiceAutoConfirm" @change="setVoiceAutoConfirm(($event.target as HTMLInputElement).checked)"> Sichere Einkaufslisten-Einträge nach 3 Sekunden automatisch bestätigen</label>
          <label class="voice-option"><input type="checkbox" :checked="voiceSpeechOutput" @change="setVoiceSpeechOutput(($event.target as HTMLInputElement).checked)"> Antworten auf Bestandsfragen vorlesen</label>
          <label class="voice-option"><input type="checkbox" :checked="voiceStartOnLaunch ?? mobileDevice" @change="setVoiceStartOnLaunch(($event.target as HTMLInputElement).checked)"> Beim App-Start sofort zuhören</label>
          <p class="voice-default-note">Standard: auf Mobilgeräten an, auf PCs aus. Deine Auswahl wird im Benutzerkonto gespeichert.</p>
        </div>
        <div class="voice-results">
          <p v-if="voiceResult" class="success" aria-live="polite">✓ {{ voiceResult }}</p>
          <article v-for="action in voiceActions" :key="`${action.intent}-${action.product_name}`" class="voice-action">
            <div class="voice-action-head"><span>{{ Math.round(action.confidence * 100) }}% sicher</span><strong>{{ { add_to_stock:'Zum Vorrat hinzufügen', consume:'Verbrauchen', discard:'Entsorgen', add_to_shopping:'Auf die Einkaufsliste', remove_from_shopping:'Von der Einkaufsliste entfernen', check_shopping:'Auf der Einkaufsliste abhaken', query_stock:'Bestand abfragen', unknown:'Unklar' }[action.intent] }}</strong></div>
            <label>Produkt<select :value="action.product_id || ''" @change="chooseVoiceProduct(action, ($event.target as HTMLSelectElement).value)"><option value="">{{ action.product_name }} (Freitext)</option><option v-for="product in products" :key="product.id" :value="product.id">{{ product.name }}</option></select></label>
            <div v-if="!['remove_from_shopping','check_shopping','query_stock'].includes(action.intent)" class="row"><label>Menge<input v-model="action.quantity" type="number" min="0.001" step="0.001" placeholder="gesamter Bestand"></label><label>Einheit<select v-model="action.unit"><option value="piece">Stück</option><option value="pack">Packung</option><option>g</option><option>kg</option><option>ml</option><option>l</option></select></label></div>
            <p v-if="!action.product_id && !['add_to_shopping','remove_from_shopping'].includes(action.intent)" class="voice-warning">Bitte ein vorhandenes Produkt auswählen.</p>
            <p v-if="voiceCountdown" class="voice-countdown">Wird in {{ voiceCountdown }} s bestätigt …</p>
            <div class="voice-action-buttons"><button @click="discardVoiceAction(action)">Verwerfen</button><button class="primary" :disabled="busy || (!action.product_id && action.intent !== 'add_to_shopping')" @click="confirmVoiceAction(action)">Bestätigen</button></div>
          </article>
          <div v-if="!voiceActions.length && !voiceResult" class="voice-help"><h3>Unterstützte Befehle</h3><p>Vorrat hinzufügen, verbrauchen oder entsorgen · Einkaufslisten-Einträge anlegen, abhaken oder entfernen · Bestand abfragen</p></div>
        </div>
      </section>
    </template>

    <template v-else-if="activeView === 'receipt'">
      <section class="receipt-workspace">
        <div class="receipt-main">
          <section v-if="!activeReceipt" class="receipt-upload panel" :class="{ dragging: receiptDragging }" @dragenter.prevent="receiptDragging=true" @dragover.prevent @dragleave.prevent="receiptDragging=false" @drop.prevent="dropReceipt">
            <span class="receipt-upload-icon" aria-hidden="true">▣</span><h2>{{ t('receiptUpload') }}</h2>
            <p>Bon flach hinlegen, ganz ins Bild nehmen und auf gutes Licht achten. Lange Bons kannst du in mehreren Abschnitten fotografieren.</p>
            <div class="receipt-picker-actions"><label class="receipt-file-button">Foto aufnehmen<input class="receipt-camera-picker" type="file" accept="image/*" capture="environment" multiple @change="chooseReceiptFiles(($event.target as HTMLInputElement).files || [])"></label><label class="receipt-file-button secondary">Dateien auswählen<input class="receipt-file-picker" type="file" accept="image/jpeg,image/png,image/heic,image/heif,application/pdf" multiple @change="chooseReceiptFiles(($event.target as HTMLInputElement).files || [])"></label></div>
            <p class="receipt-drop-hint">Am PC kannst du Dateien auch hierher ziehen.</p>
            <div v-if="receiptFiles.length" class="receipt-previews"><div v-for="(file, index) in receiptFiles" :key="`${file.name}-${index}`"><img v-if="receiptPreviews[index]" :src="receiptPreviews[index]" alt="Ausgewählte Bonseite"><span v-else>PDF</span><small>{{ file.name }}</small><button type="button" :aria-label="`${file.name} entfernen`" @click="removeReceiptFile(index)">×</button></div></div>
            <button class="primary full" :disabled="busy || !online || !receiptFiles.length" @click="uploadReceipt">{{ busy ? 'Wird hochgeladen …' : `${receiptFiles.length || ''} Bondatei${receiptFiles.length === 1 ? '' : 'en'} analysieren` }}</button>
            <p v-if="!online" class="receipt-warning">Für die Bonerkennung ist eine Internetverbindung erforderlich.</p>
            <p v-if="receiptConfig" class="receipt-privacy">Datenschutz: {{ receiptConfig.cloud_processing === 'images' ? 'Bonbilder werden an den konfigurierten Cloud-Anbieter übertragen.' : receiptConfig.cloud_processing === 'text' ? 'Die Bilderkennung läuft lokal; nur erkannter Text wird an den Cloud-Anbieter übertragen.' : 'Bilder und Text werden lokal verarbeitet.' }} Bilder werden {{ receiptConfig.image_retention_days === 0 ? 'direkt nach dem Einbuchen gelöscht' : `nach ${receiptConfig.image_retention_days} Tagen gelöscht` }}.</p>
          </section>

          <section v-else class="receipt-detail">
            <button class="receipt-back" @click="activeReceipt=null; selectedReceiptLine=null">← Neuer oder anderer Bon</button>
            <div class="receipt-heading panel"><div><p class="eyebrow">{{ receiptStatus(activeReceipt).toUpperCase() }}</p><h2>{{ activeReceipt.merchant || 'Kassenbon' }}</h2><p>{{ activeReceipt.purchased_at ? new Date(activeReceipt.purchased_at).toLocaleString('de-DE') : new Date(activeReceipt.created_at).toLocaleString('de-DE') }} · {{ activeReceipt.total ? `${Number(activeReceipt.total).toFixed(2)} €` : 'Summe offen' }}</p></div><span>{{ activeReceipt.image_count }} Seite{{ activeReceipt.image_count === 1 ? '' : 'n' }}</span></div>
            <div v-if="activeReceipt.status === 'processing'" class="receipt-processing panel" aria-live="polite"><strong>Bon wird erkannt … {{ activeReceipt.progress }} %</strong><progress :value="activeReceipt.progress" max="100"></progress><p>Du kannst die Seite verlassen; die Verarbeitung läuft im Hintergrund weiter.</p></div>
            <div v-else-if="activeReceipt.status === 'failed'" class="receipt-failed panel"><strong>Erkennung fehlgeschlagen</strong><p>{{ activeReceipt.processing_error }}</p><button class="primary" @click="retryReceipt">Erneut versuchen</button></div>
            <template v-else>
              <p v-if="activeReceipt.duplicate_message" class="receipt-duplicate">⚠ {{ activeReceipt.duplicate_message }}</p>
              <p v-if="activeReceipt.sum_difference && Number(activeReceipt.sum_difference) > .02" class="receipt-warning">Die Positionssumme weicht um {{ Number(activeReceipt.sum_difference).toFixed(2) }} € von der Bonsumme ab.</p>
              <div class="receipt-review-layout">
                <div v-if="receiptImageUrl" class="receipt-image-panel"><div class="receipt-image-canvas"><img :src="receiptImageUrl" alt="Hochgeladener Kassenbon"><span v-if="receiptHighlightStyle" class="receipt-coordinate" :style="receiptHighlightStyle" aria-hidden="true"></span></div></div>
                <div class="receipt-lines">
                  <article v-for="line in activeReceipt.lines" :key="line.id" class="receipt-line" :class="[`status-${line.status}`, { selected: selectedReceiptLine === line.id }]" @click="selectedReceiptLine=line.id">
                    <div class="receipt-line-title"><span>{{ line.status === 'mapped' || line.status === 'booked' ? '✓' : line.status === 'ignored' || line.status === 'already_booked' ? '–' : '!' }}</span><div><strong>{{ line.raw_text }}</strong><small>{{ Math.round(Number(line.confidence) * 100) }} % sicher<template v-if="line.status === 'already_booked'"> · bereits über Einkaufsliste gebucht</template></small></div><b v-if="line.total_price">{{ Number(line.total_price).toFixed(2) }} €</b></div>
                    <div v-if="activeReceipt.status === 'review'" class="receipt-line-fields">
                      <label>Produkt<select :value="line.product_id || ''" :disabled="line.status === 'already_booked'" @change="selectReceiptProduct(line, ($event.target as HTMLSelectElement).value)"><option value="">Bitte zuordnen</option><option v-for="product in products" :key="product.id" :value="product.id">{{ product.name }}</option></select></label>
                      <button v-if="!line.product_id" type="button" class="receipt-new-product" @click.stop="createReceiptProduct(line)">＋ Neues Produkt anlegen</button>
                      <div class="row"><label>Menge<input v-model="line.quantity" type="number" min="0.001" step="0.001" @change="saveReceiptLine(line, { quantity: Number(line.quantity) })"></label><label>Einheit<select v-model="line.unit" @change="saveReceiptLine(line, { unit: line.unit })"><option value="piece">Stück</option><option value="package">Packung</option><option>g</option><option>kg</option><option>ml</option><option>l</option></select></label></div>
                      <label>Lagerort<select v-model="line.location_id" @change="saveReceiptLine(line, { location_id: line.location_id || null })"><option value="">Standard</option><option v-for="location in locations" :key="location.id" :value="location.id">{{ location.name }}</option></select></label>
                      <label>MHD<input v-model="line.best_before" type="date" @change="saveReceiptLine(line, { best_before: line.best_before || null })"></label>
                      <div class="receipt-date-shortcuts"><button type="button" @click.stop="setReceiptDate(line, 3)">+3 Tage</button><button type="button" @click.stop="setReceiptDate(line, 7)">+7 Tage</button><button type="button" @click.stop="setReceiptDate(line, 30)">+30 Tage</button></div>
                      <label class="receipt-ignore"><input type="checkbox" :checked="line.status === 'ignored'" @change="saveReceiptLine(line, { ignored: ($event.target as HTMLInputElement).checked })"> Nicht einbuchen</label>
                    </div>
                  </article>
                </div>
              </div>
              <div v-if="activeReceipt.status === 'review'" class="receipt-confirm panel"><label v-if="activeReceipt.duplicate_of_id"><input v-model="allowReceiptDuplicate" type="checkbox"> Ich habe die Dublette geprüft und möchte trotzdem einbuchen.</label><button class="primary full" :disabled="busy || !reviewReceiptLines.length || reviewReceiptLines.some(line => !line.product_id) || (!!activeReceipt.duplicate_of_id && !allowReceiptDuplicate)" @click="confirmReceipt">{{ reviewReceiptLines.length }} Positionen einbuchen</button></div>
              <button v-if="activeReceipt.status === 'confirmed'" class="danger receipt-reverse" @click="reverseReceipt">Gesamten Bon stornieren</button>
              <p v-if="activeReceipt.status === 'reversed'" class="receipt-reversed">Dieser Bon wurde vollständig storniert.</p>
            </template>
          </section>
        </div>
        <aside class="receipt-history"><div class="section-heading"><div><p class="eyebrow">VERLAUF</p><h2>Letzte Bons</h2></div><button @click="activeReceipt=null">＋ Neu</button></div><button v-for="receipt in receipts" :key="receipt.id" :class="{ active: activeReceipt?.id === receipt.id }" @click="openReceipt(receipt.id)"><span><strong>{{ receipt.merchant || 'Kassenbon' }}</strong><small>{{ new Date(receipt.created_at).toLocaleDateString('de-DE') }}</small></span><em>{{ receiptStatus(receipt) }}</em></button><p v-if="!receipts.length" class="muted">Noch keine Bons hochgeladen.</p></aside>
      </section>
    </template>

    <template v-else-if="activeView === 'recipes'">
      <section class="recipe-hero"><div><p class="eyebrow">AUS DEINEM VORRAT</p><h2>Was passt heute?</h2><p>Rezepte werden nach verfügbaren Zutaten, nahendem MHD und deinen Vorlieben sortiert.</p></div><button class="primary" @click="openNewRecipe">＋ Rezept</button></section>
      <div class="recipe-filters"><label>Lieblings-Tags<input v-model="recipeTags" placeholder="z. B. vegetarisch, schnell" @change="saveRecipePreferences"></label><label>Ausgeschlossene Tags<input v-model="excludedRecipeTags" placeholder="z. B. scharf" @change="saveRecipePreferences"></label><label>Portionen<input v-model.number="recipeServings" type="number" min="1" max="100" placeholder="Original" @change="refreshRecipes"></label></div>
      <section class="recipe-list"><article v-for="recommendation in recipeRecommendations" :key="recommendation.recipe.id" class="recipe-card"><div class="recipe-score"><strong>{{ Math.round(recommendation.score * 100) }}%</strong><span>Passung</span></div><div class="recipe-copy"><div class="recipe-title"><div><h2>{{ recommendation.recipe.name }}</h2><small>{{ recommendation.recipe.servings }} Portionen · {{ recommendation.recipe.tags.join(' · ') || 'Ohne Tags' }}</small><span v-if="recommendation.ranking_source !== 'deterministic'" class="ai-badge">KI · {{ recommendation.ranking_source }}</span></div><div class="recipe-title-actions"><button class="icon-button" aria-label="Rezept bearbeiten" @click="editRecipe(recommendation)">✎</button><button class="icon-button" aria-label="Rezept löschen" @click="removeRecipe(recommendation)">×</button></div></div><p>{{ recommendation.explanation }}</p><ul><li v-for="ingredient in recommendation.recipe.ingredients" :key="ingredient.id">{{ Number(ingredient.quantity) }} {{ ingredient.unit }} {{ ingredient.product_name }}</li></ul><details v-if="recommendation.recipe.instructions"><summary>Zubereitung</summary><p class="instructions">{{ recommendation.recipe.instructions }}</p></details><div v-if="recommendation.missing_ingredients.length" class="recipe-missing"><strong>Fehlt noch</strong><span v-for="item in recommendation.missing_ingredients" :key="item.product_id">{{ Number(item.missing_quantity) }} {{ item.unit }} {{ item.product_name }}</span><button @click="addRecipeMissing(recommendation)">Zur Einkaufsliste</button></div><p v-else class="recipe-ready">✓ Alle Zutaten vorhanden</p></div></article><div v-if="!recipeRecommendations.length" class="empty panel"><span>♨</span><h2>Noch keine passenden Rezepte</h2><p>Lege ein Rezept an oder prüfe deine ausgeschlossenen Tags.</p><button class="primary" @click="openNewRecipe">Rezept anlegen</button></div></section>
    </template>

    <template v-else-if="activeView === 'history'">
      <div class="history-filters"><select v-model="historyType"><option value="">Alle Buchungstypen</option><option v-for="(label, value) in movementNames" :key="value" :value="value">{{ label }}</option></select><select v-model="historyProduct"><option value="">Alle Produkte</option><option v-for="product in products" :key="product.id" :value="product.id">{{ product.name }}</option></select><select v-model="historyUser"><option value="">Alle Personen</option><option v-for="member in members" :key="member.user_id" :value="member.user_id">{{ member.display_name }}</option></select><label>Von<input v-model="historyStart" type="date"></label><label>Bis<input v-model="historyEnd" type="date"></label><button class="export-button" @click="api.downloadHistory().catch(e => error=e.message)">CSV exportieren</button></div>
      <section class="timeline"><article v-for="movement in filteredMovements" :key="movement.id"><span class="timeline-dot"></span><div><strong>{{ movementNames[movement.movement_type] || movement.movement_type }}</strong><p>{{ movement.product_name || batchMap.get(movement.batch_id)?.product.name || 'Bestandsposition' }} · {{ Number(movement.quantity_delta) > 0 ? '+' : '' }}{{ Number(movement.quantity_delta) }}</p><small>{{ movement.user_name || 'Unbekannt' }} · {{ new Date(movement.created_at).toLocaleString('de-DE') }}<template v-if="movement.client_info"> · {{ movement.client_info }}</template></small></div></article></section>
    </template>

    <template v-else-if="activeView === 'inventory'">
      <section v-if="!inventory" class="empty panel"><span>✓</span><h2>Bestand zählen</h2><p>Starte eine Inventur für den ganzen Haushalt oder einen Lagerort.</p><select v-model="selectedLocation"><option value="">Ganzer Haushalt</option><option v-for="location in locations" :value="location.id">{{ location.name }}</option></select><button class="primary" @click="startInventory">Inventur starten</button></section>
      <section v-else><p class="muted inventory-intro">Trage die tatsächlich vorhandene Menge ein oder scanne den Artikel. Änderungen werden erst nach Bestätigung gebucht.</p><button class="primary full inventory-scan" @click="scan('inventory')">⌁ {{ t('inventoryScan') }}</button><video v-show="scanning" id="scanner" class="scanner"></video><article v-for="count in inventory.counts" :key="count.batch_id" class="count-row"><div><strong>{{ batchMap.get(count.batch_id)?.product.name || 'Artikel' }}</strong><small>Soll: {{ Number(count.expected_quantity) }} {{ batchMap.get(count.batch_id)?.unit }}</small></div><input type="number" min="0" step="0.001" :value="Number(count.counted_quantity)" @change="saveCount(count.batch_id, $event)"></article><button class="primary full" @click="confirmInventory">Inventur abschließen</button></section>
    </template>

    <template v-else-if="activeView === 'more'">
      <section class="settings-list">
        <div class="more-links"><button @click="activeView='recipes'">Rezepte</button><button @click="activeView='history'">Verlauf</button><button @click="activeView='inventory'">Inventur</button></div>
        <div class="section-heading"><div><p class="eyebrow">{{ t('conflicts').toUpperCase() }}</p><h2>Offline-Synchronisation</h2></div><button v-if="online && pendingOffline" @click="syncOffline">Jetzt senden</button></div>
        <p v-if="!conflicts.length" class="muted no-warnings">Keine offenen Konflikte. {{ pendingOffline ? `${pendingOffline} Aktion(en) warten auf Verbindung.` : 'Alle Änderungen sind synchronisiert.' }}</p>
        <article v-for="conflict in conflicts" :key="conflict.key" class="conflict"><div><strong>{{ conflict.message }}</strong><small>{{ new Date(conflict.failedAt).toLocaleString('de-DE') }} · {{ conflict.url }}</small></div><div><button @click="retryOffline(conflict)">Neu prüfen</button><button @click="discardOffline(conflict.key)">Verwerfen</button></div></article>

        <div class="section-heading warnings-heading"><div><p class="eyebrow">HAUSHALT</p><h2>{{ household?.name || 'Haushalt' }}</h2></div><button @click="editHousehold">Einstellungen</button></div>
        <label class="check-mode">Beim Abhaken<select :value="household?.shopping_check_mode" @change="api.updateHousehold({ shopping_check_mode: ($event.target as HTMLSelectElement).value }).then(value => household=value).catch(e => error=e.message)"><option value="instant">Sofort einbuchen</option><option value="finish_trip">Erst beim Einkaufsabschluss</option></select></label>
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

    <nav><button :class="{active:activeView==='stock'}" @click="activeView='stock'">⌂<span>{{ t('stock') }}</span></button><button :class="{active:activeView==='shopping'}" @click="activeView='shopping'">☷<span>{{ t('shopping') }}</span></button><button class="voice-nav" :class="{active:activeView==='voice'}" @click="activeView='voice'">●<span>{{ t('voice') }}</span></button><button :class="{active:activeView==='receipt'}" @click="activeView='receipt'">▣<span>{{ t('receipt') }}</span></button><button :class="{active:activeView==='more'}" @click="activeView='more'">⚙<span>{{ t('more') }}</span></button></nav>
    <div v-if="shoppingUndo" class="snackbar">Einkauf eingebucht <button @click="undoShopping">{{ t('undo') }}</button></div>
    <div v-if="lastMovements.length" class="snackbar">{{ t('saved') }} <button @click="undo">{{ t('undo') }}</button></div>
    <div v-if="showAdd" class="modal" @click.self="showAdd=false"><form class="sheet" @submit.prevent="add"><div class="handle"></div><h2>{{ t('addItem') }}</h2><label>{{ t('product') }}<input v-model="productSearch" list="product-suggestions" placeholder="Produkt suchen …" required @input="selectProductFromSearch"><datalist id="product-suggestions"><option v-for="product in products" :key="product.id" :value="productLabel(product)"></option></datalist></label><p v-if="productSearch && !selectedProduct" class="error">{{ t('selectExistingProduct') }}</p><button type="button" class="ghost" @click="createManualProduct">{{ t('newProduct') }}</button><div class="row"><label>{{ t('quantity') }}<input v-model.number="quantity" type="number" min="0.001" step="0.001" required></label><label>{{ t('unit') }}<select v-model="unit"><option value="piece">Stück</option><option>g</option><option>kg</option><option>ml</option><option>l</option><option value="package">Packung</option></select></label></div><label>{{ t('location') }}<select v-model="selectedLocation" required><option disabled value="">{{ t('choose') }}</option><option v-for="location in locations" :value="location.id">{{ location.name }}</option></select></label><label>{{ t('bestBefore') }}<input v-model="bestBefore" type="date"></label><button class="primary" :disabled="busy || !selectedProduct">{{ t('add') }}</button><button type="button" class="ghost" @click="showAdd=false">{{ t('cancel') }}</button></form></div>
    <div v-if="showRecipe" class="modal" @click.self="showRecipe=false"><form class="sheet recipe-sheet" @submit.prevent="createRecipe"><div class="handle"></div><h2>{{ editingRecipeId ? 'Rezept bearbeiten' : 'Neues Rezept' }}</h2><div class="row"><label>Name<input v-model="recipeName" required></label><label>Portionen<input v-model.number="recipePortions" type="number" min="1" max="100" required></label></div><label>Tags, durch Komma getrennt<input v-model="recipeTagInput" placeholder="vegetarisch, schnell"></label><div class="ingredient-editor"><strong>Zutaten</strong><div v-for="(ingredient, index) in recipeIngredients" :key="index" class="ingredient-row"><select v-model="ingredient.product_id" required @change="selectIngredientProduct(ingredient)"><option disabled value="">Produkt wählen</option><option v-for="product in products" :key="product.id" :value="product.id">{{ product.name }}</option></select><input v-model.number="ingredient.quantity" type="number" min="0.001" step="0.001" required><select v-model="ingredient.unit"><option value="piece">Stück</option><option>g</option><option>kg</option><option>ml</option><option>l</option><option value="package">Packung</option></select><button v-if="recipeIngredients.length > 1" type="button" aria-label="Zutat entfernen" @click="recipeIngredients.splice(index, 1)">×</button></div><button type="button" class="ghost" @click="addIngredientDraft">＋ Weitere Zutat</button></div><label>Zubereitung<textarea v-model="recipeInstructions" rows="5"></textarea></label><button class="primary" :disabled="busy">{{ editingRecipeId ? 'Änderungen speichern' : 'Rezept speichern' }}</button><button type="button" class="ghost" @click="showRecipe=false">Abbrechen</button></form></div>
  </main>
</template>
