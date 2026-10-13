export const messages = {
  de: {
    stock: 'Mein Vorrat',
    add: 'Einbuchen',
    scan: 'Barcode scannen',
    manualBarcode: 'Barcode eingeben',
    empty: 'Noch nichts eingelagert',
    consume: 'Entnehmen',
    discard: 'Entsorgen',
    expires: 'MHD',
    search: 'Vorrat durchsuchen …',
    filters: 'Filter und Sortierung',
    allLocations: 'Alle Lagerorte',
    allCategories: 'Alle Kategorien',
    expiringSoon: 'Läuft bald ab',
    lowStock: 'Unter Mindestbestand',
    offlinePending: 'Offline vorgemerkt',
    conflicts: 'Synchronisationskonflikte'
    ,recipes: 'Rezepte'
  }
} as const
export const t = (key: keyof typeof messages.de) => messages.de[key]
