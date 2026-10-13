import { openDB } from 'idb'

export type OfflineRequest = {
  key: string
  url: string
  body: Record<string, unknown>
  createdAt: number
}

export type OfflineConflict = OfflineRequest & {
  message: string
  failedAt: number
}

type RequestError = Error & { status?: number }

const db = openDB('vorrat-offline', 2, {
  upgrade(database) {
    if (!database.objectStoreNames.contains('outbox')) {
      database.createObjectStore('outbox', { keyPath: 'key' })
    }
    if (!database.objectStoreNames.contains('conflicts')) {
      database.createObjectStore('conflicts', { keyPath: 'key' })
    }
  }
})

export async function queueRequest(url: string, body: Record<string, unknown>) {
  const key = String(body.idempotency_key || crypto.randomUUID())
  await (await db).put('outbox', {
    key,
    url,
    body: { ...body, idempotency_key: key },
    createdAt: Date.now()
  })
  return key
}

export async function flushOutbox(
  sender: (url: string, body: Record<string, unknown>) => Promise<void>
) {
  const database = await db
  for (const item of await database.getAll('outbox') as OfflineRequest[]) {
    try {
      await sender(item.url, item.body)
      await database.delete('outbox', item.key)
    } catch (caught) {
      const error = caught as RequestError
      if (!navigator.onLine || error.status === undefined) break
      await database.put('conflicts', {
        ...item,
        message: error.message,
        failedAt: Date.now()
      })
      await database.delete('outbox', item.key)
    }
  }
}

export async function offlineState() {
  const database = await db
  return {
    pending: await database.count('outbox'),
    conflicts: await database.getAll('conflicts') as OfflineConflict[]
  }
}

export async function discardConflict(key: string) {
  await (await db).delete('conflicts', key)
}

export async function retryConflict(
  conflict: OfflineConflict,
  body: Record<string, unknown>,
  sender: (url: string, body: Record<string, unknown>) => Promise<void>
) {
  await sender(conflict.url, body)
  await (await db).delete('conflicts', conflict.key)
}
