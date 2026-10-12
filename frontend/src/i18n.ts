export const messages = {
  de: { stock: 'Mein Vorrat', add: 'Einbuchen', scan: 'Barcode scannen', empty: 'Noch nichts eingelagert', consume: 'Entnehmen', expires: 'MHD', search: 'Vorrat durchsuchen …' }
} as const
export const t = (key: keyof typeof messages.de) => messages.de[key]
