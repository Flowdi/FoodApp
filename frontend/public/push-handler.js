self.addEventListener('push', event => {
  const data = event.data ? event.data.json() : { title: 'Vorrat', body: 'Neue Warnung' }
  event.waitUntil(self.registration.showNotification(data.title || 'Vorrat', {
    body: data.body,
    icon: '/icon.svg',
    badge: '/icon.svg',
    data: { url: '/' }
  }))
})

self.addEventListener('notificationclick', event => {
  event.notification.close()
  event.waitUntil(self.clients.openWindow(event.notification.data?.url || '/'))
})
