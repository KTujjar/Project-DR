import { ITEM_TYPES, type InventoryRecord, type ItemType } from '../types/schemas'
import { config as defaultConfig, type Config } from './config'

export type ItemQuantities = Record<ItemType, number>

export interface ItemStatus {
  need: number
  onHand: number
  shortfall: number
  coverage: number // onHand / need; 1 when nothing is needed
}

export function emptyQuantities(): ItemQuantities {
  return { water_L: 0, food_meals: 0, medical_kits: 0, blankets: 0, cots: 0 }
}

// Need over the planning horizon for `headcount` people.
export function computeNeed(headcount: number, capacity?: number, cfg: Config = defaultConfig): ItemQuantities {
  const days = cfg.horizonDays
  return {
    water_L: Math.ceil(headcount * (cfg.dailyRates.water_L ?? 0) * days),
    food_meals: Math.ceil(headcount * (cfg.dailyRates.food_meals ?? 0) * days),
    medical_kits: Math.ceil(headcount / cfg.peoplePerMedicalKit),
    blankets: headcount,
    cots: capacity === undefined ? headcount : Math.min(headcount, capacity),
  }
}

// Most recent quantity per site and item.
export function latestStock(inventory: InventoryRecord[]): Record<string, ItemQuantities> {
  const latest = new Map<string, InventoryRecord>()
  for (const r of inventory) {
    const key = `${r.site_id}|${r.item}`
    const prev = latest.get(key)
    if (!prev || r.timestamp >= prev.timestamp) latest.set(key, r)
  }

  const stock: Record<string, ItemQuantities> = {}
  for (const r of latest.values()) {
    stock[r.site_id] ??= emptyQuantities()
    stock[r.site_id][r.item] = r.quantity
  }
  return stock
}

export function itemStatus(need: number, onHand: number): ItemStatus {
  return {
    need,
    onHand,
    shortfall: Math.max(0, need - onHand),
    coverage: need === 0 ? 1 : onHand / need,
  }
}

export function itemStatuses(need: ItemQuantities, onHand: ItemQuantities): Record<ItemType, ItemStatus> {
  const result = {} as Record<ItemType, ItemStatus>
  for (const item of ITEM_TYPES) result[item] = itemStatus(need[item], onHand[item])
  return result
}
