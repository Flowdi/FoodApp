import { openDB } from 'idb'

const db = openDB('vorrat-offline', 1, { upgrade(database) { database.createObjectStore('outbox', { keyPath: 'key' }) } })

export async function queueMovement(url: string, body: Record<string, unknown>) {
  const key = String(body.idempotency_key || crypto.randomUUID())
  await (await db).put('outbox', { key, url, body: { ...body, idempotency_key: key }, createdAt: Date.now() })
}

export async function flushOutbox(sender: (url: string, body: Record<string, unknown>) => Promise<void>) {
  const database = await db
  for (const item of await database.getAll('outbox')) {
    try { await sender(item.url, item.body); await database.delete('outbox', item.key) }
    catch (error) { if (navigator.onLine) throw error; break }
  }
}
