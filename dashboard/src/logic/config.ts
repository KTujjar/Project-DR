import type { ItemType } from '../types/schemas'

// Rates and thresholds, kept in one place so they can be tuned during the demo.
export const config = {
  // Planning horizon for consumable items (water, food).
  horizonDays: 1,
  // Per person per day.
  dailyRates: { water_L: 3, food_meals: 3 } as Partial<Record<ItemType, number>>,
  peoplePerMedicalKit: 50,

  // When a site has several cameras: "sum" if they cover separate areas, "max" if they overlap.
  headcountMode: 'sum' as 'sum' | 'max',

  // Worst-item coverage at or above `ok` is OK, at or above `low` is Low, otherwise Critical.
  severity: { ok: 1, low: 0.5 },
  capacityCriticalRatio: 0.9,

  // Depots keep this share of their stock back and only dispatch the rest.
  depotReserveRatio: 0.2,
  truckSpeedKmh: 40,

  staleAfterSeconds: 60,

  priority: {
    criticalWeight: 3,
    lowWeight: 1,
    needsReviewBonus: 300,
    offlineCameraBonus: 250,
  },
}

export type Config = typeof config
