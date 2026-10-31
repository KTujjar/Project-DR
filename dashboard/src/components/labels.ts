import type { ItemType } from '../types/schemas'

export const ITEM_LABEL: Record<ItemType, string> = {
  water_L: 'Water (L)',
  food_meals: 'Meals',
  medical_kits: 'Med kits',
  blankets: 'Blankets',
  cots: 'Cots',
}

export function formatItems(items: Partial<Record<ItemType, number>>): string {
  return (Object.entries(items) as [ItemType, number][])
    .map(([item, qty]) => `${qty.toLocaleString()} ${ITEM_LABEL[item]}`)
    .join(', ')
}

export function timeAgo(iso: string, now = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (seconds < 60) return `${seconds}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  return `${Math.floor(seconds / 3600)}h ago`
}

